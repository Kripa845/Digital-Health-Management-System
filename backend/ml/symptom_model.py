
 
"""Symptom text → red flags → likely illnesses → department, with a Random Forest.
 
Pipeline (predict):
    analyse(text)  → symptoms mentioned (exact / synonym / base form / spelling), negated ones
                     left out; unsure spellings become "Did you mean ...?" suggestions
    red flags      → status "emergency"; the model is NOT called (ml/red_flags.py: rules on the
                     recognised symptoms AND on phrases in the text, so an unrecognised
                     "my throat is closing" still stops the check)
    confirm        → unconfirmed suggestions: status "needs_confirmation", the model is NOT called
    Random Forest  → likely illnesses from a 0/1 symptom vector (symptoms not mentioned = 0),
                     calibrated and corrected to DDXPlus prevalence, summed into a likely
                     department (illnesses under DEPT_MIN_ILLNESS_PROBABILITY not counted)
    not sure       → "not enough information": General Medicine as the first point of contact,
                     plus one information-gain follow-up question (ml/questioning.py, using
                     the symptom-rate table saved with the model)
The caller (apps/recommendations/smart_views.py) then ranks doctors with AHP-weighted TOPSIS.
 
Symptoms and illnesses come from ml/data/symptom_schema.json (DDXPlus, synthetic data;
see ml/schema.py). The trained model (ml/symptom_model.joblib, made by `python -m ml.train_model`)
is loaded ONCE at server startup. load() raises SchemaError — and the server does not
start — when the model, the synonyms, the red-flag rules or the department map do not
agree with the schema. A model file that is missing or cannot be read does not stop the
server: the cause is logged (unavailable_reason()), loading is retried with backoff, and
predict() returns status "model_unavailable" (the endpoint answers 503).
 
Statuses returned by predict():
    ok                 every field below
    emergency          a red-flag rule matched (red_flags, department "Emergency Medicine")
    needs_confirmation some words were only close to a symptom ("feverr" → fever?): the
                       ``suggestions`` must be confirmed (send {symptom: true} in ``answers``)
                       or dismissed (send the term in ``dismissed``) first
    not_enough_info    fewer than MIN_SYMPTOMS recognised (non-negated) symptoms
    low_confidence     ``reason`` says why:
                       unseen_combination     fewer than MIN_SUPPORT training rows have all the
                                              symptoms together (the forest is guessing outside its data)
                       too_many_unrecognized  at least as many unrecognised terms as symptoms
                       no_clear_illness       best illness below MIN_ILLNESS_PROBABILITY
                       no_clear_department    best department below MIN_DEPARTMENT_PROBABILITY, or
                                              ahead of the runner-up by less than MIN_DEPARTMENT_MARGIN
                       serious_illness        the best illness has DDXPlus severity <= SERIOUS_SEVERITY
                                              (anaphylaxis, Ebola, STEMI...) but no red flag matched:
                                              common symptoms are not shown as a serious diagnosis
    model_unavailable  the model file is missing or could not be loaded
not_enough_info and low_confidence say "not enough information" and suggest General Medicine
(``department``, ``message``, ``safety_net``), and may carry a follow-up ``question``.

The thresholds can be overridden with environment variables (useful for sweeping
them with ``python -m ml.evaluate`` without editing this file):
    SMART_MIN_SYMPTOMS          default 3
    SMART_MIN_DEPT_PROB         default 0.40
    SMART_MIN_DEPT_MARGIN       default 0.15
    SMART_MIN_ILLNESS_PROB      default 0.30
    SMART_MIN_SUPPORT           default 1
    SMART_DEPT_MIN_ILLNESS_PROB default 0.05
    SMART_SERIOUS_SEVERITY      default 1 (0 turns the serious-illness check off)

The forest's probabilities are calibrated with the temperature and multiplied by the class
prior saved with the model (DDXPlus prevalence / weighted training share, see
ml/train_model.py), then renormalised.
 
Symptoms are shown to users by their schema label ("fever"), never by DDXPlus code.
The output is a suggestion, never a diagnosis.
"""
from __future__ import annotations
 
import logging
import os
import time
from pathlib import Path
 
import joblib
import numpy as np
import pandas as pd
 
from ml import questioning, red_flags
from ml.disease_dept import check_classes, department_for
from ml.schema import SchemaError, get as get_schema
from ml.symptom_terms import (
    DEFAULT_FUZZY_THRESHOLD, SUGGEST_THRESHOLD, SYNONYMS_PATH, SymptomVocabulary, TermAnalysis, load_synonyms,
)
 
logger = logging.getLogger(__name__)
 
MODEL_PATH = Path(__file__).resolve().parent / 'symptom_model.joblib'
DISCLAIMER = 'Suggestion only, not a medical diagnosis.'
MIN_SYMPTOMS = int(os.environ.get('SMART_MIN_SYMPTOMS', 3))
MIN_DEPARTMENT_PROBABILITY = float(os.environ.get('SMART_MIN_DEPT_PROB', 0.40))
MIN_DEPARTMENT_MARGIN = float(os.environ.get('SMART_MIN_DEPT_MARGIN', 0.15))
MIN_ILLNESS_PROBABILITY = float(os.environ.get('SMART_MIN_ILLNESS_PROB', 0.30))
MIN_SUPPORT = int(os.environ.get('SMART_MIN_SUPPORT', 1))
DEPT_MIN_ILLNESS_PROBABILITY = float(os.environ.get('SMART_DEPT_MIN_ILLNESS_PROB', 0.05))
SERIOUS_SEVERITY = int(os.environ.get('SMART_SERIOUS_SEVERITY', 1))
TOP_ILLNESSES = 3
FALLBACK_DEPARTMENT = 'General Medicine'
NOT_ENOUGH_INFO_MESSAGE = ('Not enough information to suggest a specific area of care. A General Medicine '
                           'doctor is the right first point of contact.')
SERIOUS_MESSAGE = ('These symptoms are common to several conditions, including some that need prompt care. '
                   'Please see a General Medicine doctor soon so they can examine you.')
SAFETY_NET = ('Get emergency help straight away if you have difficulty breathing, swelling of the throat, '
              'tongue or lips, chest pain, or you faint.')

_model = None            # RandomForestClassifier, set by load()
_columns: list[str] = []  # symptom names in training column order (= schema columns)
_rates = None            # P(symptom | illness), (classes, _rate_columns): for follow-up questions
_rate_columns: list[str] = []
_prior = None            # per class: prevalence / training share (None = no correction)
_temperature = 1.0       # probability calibration fitted by ml/train_model.py (1.0 = none)
_severity: dict[str, int] = {}   # illness → DDXPlus severity (1 = most severe); {} = not checked
_row_bits = None         # training rows, np.packbits per row: for support()
_implied: dict[str, str] = {}   # follow-up symptom → its parent, when it is always present with it
_gated: dict[str, str] = {}     # symptom → "pain", when the training rows with it nearly always say pain
_vocabulary: SymptomVocabulary | None = None   # labels + synonyms, built by load()
_loaded = False
_references_checked = False
_load_error: str | None = None   # why the last load failed (see unavailable_reason())
_retry_at: float | None = None   # time.monotonic() after which a failed load is tried again
_retry_delay = 0.0
 
 
def _setting(name: str, default):
    """A Django setting when Django is configured (the server), else the default (scripts)."""
    try:
        from django.conf import settings
        return getattr(settings, name, default) if settings.configured else default
    except Exception:
        return default
 
 
def _synonyms() -> dict[str, str]:
    try:
        return load_synonyms(Path(_setting('SMART_CHECK_SYNONYMS_PATH', SYNONYMS_PATH)))
    except (OSError, ValueError) as exc:
        logger.warning('Symptom synonyms not loaded (%s); only exact and fuzzy matching are used.',
                       type(exc).__name__)
        return {}
 
 
def build_vocabulary(columns, synonyms: dict[str, str] | None = None, labels: dict[str, str] | None = None,
                     strict: bool = False) -> SymptomVocabulary:
    vocab = SymptomVocabulary(columns, _synonyms() if synonyms is None else synonyms,
                              _setting('SMART_CHECK_FUZZY_THRESHOLD', DEFAULT_FUZZY_THRESHOLD), labels,
                              _setting('SMART_CHECK_SUGGEST_THRESHOLD', SUGGEST_THRESHOLD))
    if vocab.invalid_synonyms and strict:
        raise SchemaError(f'Synonyms whose target is not in the symptom schema: {vocab.invalid_synonyms[:10]}')
    return vocab
 
 
def check_artifact(artifact: dict, schema=None) -> None:
    """Raise SchemaError when the saved model's symptoms or illnesses differ from the schema."""
    schema = schema or get_schema()
    missing = {'model', 'symptoms', 'classes', 'symptom_rates', 'rate_columns'} - set(artifact)
    if missing:
        raise SchemaError(f'The model file lacks {sorted(missing)}; retrain with python -m ml.train_model.')
    model = artifact['model']
    if type(model).__name__ != 'RandomForestClassifier':
        raise SchemaError(f'The model file holds a {type(model).__name__}, not a Random Forest; '
                          'retrain with python -m ml.train_model.')
    if list(artifact['symptoms']) != list(schema.columns):
        raise SchemaError('The model was trained on a different symptom list than symptom_schema.json; '
                          'retrain with python -m ml.train_model.')
    if list(artifact['classes']) != list(model.classes_) or not set(artifact['classes']) <= set(schema.classes):
        raise SchemaError('The model illnesses differ from symptom_schema.json; retrain with python -m ml.train_model.')
    if list(artifact['rate_columns']) != schema.names or \
            np.shape(artifact['symptom_rates']) != (len(artifact['classes']), len(schema.names)):
        raise SchemaError('The symptom-rate table does not match symptom_schema.json; '
                          'retrain with python -m ml.train_model.')
 
 
def check_references(schema=None) -> None:
    """Every symptom named by another module exists in the schema (run at startup)."""
    schema = schema or get_schema()
    schema.require(red_flags.symptoms_named(), 'ml/red_flags.py')
    build_vocabulary(schema.names, labels=schema.labels(), strict=True)
 
 
def _unavailable_hint(exc: Exception, path: Path) -> str:
    """Why the model file could not be loaded, and what to do about it."""
    if isinstance(exc, FileNotFoundError):
        return (f'{path} does not exist. Train it with "python -m ml.train_model" (needs '
                'ml/data/train/ddxplus_binary.csv) and deploy the file with the server.')
    if isinstance(exc, ImportError):
        return ('scikit-learn or joblib could not be imported: not installed, or a compiled library '
                f'was blocked (e.g. by Windows Application Control). {exc}')
    return (f'{path} could not be read ({type(exc).__name__}: {exc}). It may be corrupt or saved with '
            'another scikit-learn version; retrain with "python -m ml.train_model".')
 
 
def unavailable_reason() -> str | None:
    """Why the model is not loaded (for logs and admins, not shown to patients), or None."""
    return _load_error
 
 
def load(path: Path = MODEL_PATH) -> bool:
    """Load the model into memory (once). Returns True when a model is available.
 
    Raises SchemaError when the model or any module disagrees with the symptom schema
    (on the first attempt, at startup). When the file cannot be loaded, the error is logged
    and loading is tried again on a later call, waiting SMART_CHECK_MODEL_RETRY_SECONDS and
    doubling up to SMART_CHECK_MODEL_RETRY_MAX_SECONDS, so a model deployed after startup is
    picked up without a restart.
    """
    global _model, _columns, _implied, _gated, _rates, _rate_columns, _prior, _row_bits, _vocabulary, _loaded
    global _load_error, _retry_at, _retry_delay, _references_checked, _temperature, _severity
    if _loaded:
        return True
    first_attempt = _retry_at is None
    if not first_attempt and time.monotonic() < _retry_at:
        return False
    schema = get_schema()
    if not _references_checked:
        check_references(schema)
        _references_checked = True
    try:
        import joblib
        artifact = joblib.load(path)
        check_artifact(artifact, schema)
        check_classes(artifact['classes'])
    except Exception as exc:   # the keyword scorer is used instead until a later attempt succeeds
        if isinstance(exc, SchemaError) and first_attempt:
            raise
        base = float(_setting('SMART_CHECK_MODEL_RETRY_SECONDS', 30))
        cap = float(_setting('SMART_CHECK_MODEL_RETRY_MAX_SECONDS', 600))
        _retry_delay = base if first_attempt else min(_retry_delay * 2, cap)
        _retry_at = time.monotonic() + _retry_delay
        _model, _columns, _vocabulary = None, [], None
        _load_error = _unavailable_hint(exc, Path(path))
        logger.error('Symptom model not available: %s The keyword scorer is used; retrying in %.0f s.',
                     _load_error, _retry_delay, exc_info=not isinstance(exc, FileNotFoundError))
        return False
    _model, _columns = artifact['model'], list(artifact['symptoms'])
    _implied = dict(artifact.get('implied', {}))
    _gated = dict(artifact.get('gated', {}))
    _rates, _rate_columns = np.asarray(artifact['symptom_rates']), list(artifact['rate_columns'])
    _prior = np.asarray(artifact['prior']) if artifact.get('prior') is not None else None
    _temperature = float(artifact.get('temperature', 1.0))
    _severity = dict(artifact.get('severity', {}))
    _row_bits = artifact.get('row_bits')
    _vocabulary = build_vocabulary(_columns, labels=schema.labels())
    _loaded, _load_error = True, None
    logger.info('Symptom model loaded (Random Forest): %d illnesses, %d symptoms.',
                len(_model.classes_), len(_columns))
    return True
 
 
def symptom_columns() -> list[str]:
    load()
    return list(_columns)
 
 
def department_probabilities(classes, probabilities, min_probability: float = 0.0) -> dict[str, float]:
    """Sum the probability of every illness mapped to the same department, counting only
    illnesses with at least ``min_probability``.

    Without the floor a department with many illnesses wins on their long tail: ten 3%
    illnesses add up to 30% although none of them is likely. predict() passes
    DEPT_MIN_ILLNESS_PROBABILITY. Departments with no counted illness are left out.
    """
    totals: dict[str, float] = {}
    for illness, p in zip(classes, probabilities):
        if p < min_probability or p <= 0:
            continue
        dept = department_for(illness)
        totals[dept] = totals.get(dept, 0.0) + float(p)
    return totals
 
 
def analyse(text: str, columns: list[str] | None = None) -> TermAnalysis:
    """Which symptoms the text mentions (exact, synonym or fuzzy), which are negated, and
    which words were not recognised."""
    if columns is None:
        load()
        vocab = _vocabulary
    else:
        vocab = build_vocabulary(columns, labels=_labels(columns))
    return vocab.analyse(text) if vocab else TermAnalysis()
 
 
def _labels(columns) -> dict[str, str]:
    """Schema labels for the columns that have one (hand-made test models use plain names)."""
    try:
        labels = get_schema().labels()
    except SchemaError:
        return {}
    return {c: labels[c] for c in columns if c in labels}
 
 
def _label(name: str) -> str:
    return _labels([name]).get(name, name)
 
 
def expand(present, implied: dict[str, str] | None = None, gated: dict[str, str] | None = None) -> set[str]:
    """Fill in what the DDXPlus questionnaire would have recorded with the symptoms mentioned:
    their parent questions, up the chain ("headache" → pain location → pain); "pain" for
    symptoms that always come with it ("sore throat"); and the follow-ups always present with
    a parent ("pain" → pain intensity)."""
    implied = _implied if implied is None else implied
    gated = _gated if gated is None else gated
    out = set(present)
    out |= {gated[s] for s in present if s in gated}
    try:
        schema = get_schema()
        todo = list(out)
        while todo:
            s = todo.pop()
            parent = schema.symptom(s).parent if s in schema.names else None
            if parent and parent not in out:
                out.add(parent)
                todo.append(parent)
    except SchemaError:
        pass
    out |= {child for child, parent in implied.items() if parent in out}
    return out


def _askable(columns) -> list[str]:
    """Yes/no symptoms that can be asked as a question (not multi-choice details, not history).
    Pain regions ("Do you have a headache?") are yes/no and can be asked."""
    try:
        schema = get_schema()
    except SchemaError:
        return list(columns)
    return [s.name for s in schema.symptoms
            if s.name in columns and s.data_type == 'B' and not s.antecedent]


def _question(belief, rates, rate_columns, columns, known, answers) -> dict | None:
    if len(answers) >= questioning.MAX_QUESTIONS or belief is None:
        return None
    name = questioning.next_question(belief, rates, rate_columns, known, _askable(columns))
    if name is None:
        return None
    try:
        text = get_schema().question(name)
    except (SchemaError, KeyError):
        text = f'Do you have {_label(name)}?'
    return {'symptom': name, 'label': _label(name), 'text': text}
 
 
def _terms(analysis: TermAnalysis, suggestions: list | None = None) -> dict:
    suggestions = analysis.suggestions if suggestions is None else suggestions
    return {
        'matched': [{**m.as_dict(), 'symptom': _label(m.symptom)} for m in analysis.matches
                    if m.symptom in set(analysis.present)],
        'negated': [_label(s) for s in analysis.negated],
        'unrecognized': analysis.unrecognized,
        # "Did you mean ...?": symptom is the name to send back in answers, label is shown.
        'suggestions': [{'term': s.term, 'symptom': s.symptom, 'label': _label(s.symptom),
                         'score': round(s.score, 1)} for s in suggestions],
    }


def _pending(analysis: TermAnalysis, answers: dict[str, bool], dismissed) -> list:
    """Suggestions the user has neither confirmed/answered nor dismissed."""
    dismissed = {' '.join(str(d).lower().split()) for d in dismissed}
    return [s for s in analysis.suggestions if s.symptom not in answers and s.term not in dismissed]


def _probabilities(model, columns, present, prior=None, temperature: float = 1.0) -> np.ndarray:
    """The forest's illness probabilities for a 0/1 vector in training column order,
    calibrated with the temperature, times the class prior (prevalence / weighted training
    share) and renormalised (ml/train_model.py apply_calibration())."""
    from ml.train_model import apply_calibration
    x = pd.DataFrame(np.zeros((1, len(columns)), dtype=np.int8), columns=columns)
    known = sorted(s for s in present if s in columns)
    if known:
        x.loc[0, known] = 1
    p = model.predict_proba(x)[0]
    if prior is None and temperature == 1.0:
        return p
    return apply_calibration(p, prior, temperature)


def support(present, columns=None, row_bits=None) -> int | None:
    """How many training rows have ALL these symptoms (None when the model has no row table).

    0 means no simulated patient ever had this combination: the forest's answer is then an
    extrapolation (e.g. fever + nausea + dizziness: dizziness only occurs with anemia, atrial
    fibrillation and PSVT, none of which has fever with nausea)."""
    columns = _columns if columns is None else columns
    row_bits = _row_bits if row_bits is None else row_bits
    if row_bits is None:
        return None
    wanted = np.zeros(len(columns), dtype=bool)
    wanted[[i for i, c in enumerate(columns) if c in set(present)]] = True
    mask = np.packbits(wanted)
    return int(((row_bits & mask) == mask).all(axis=1).sum())
 
 
def department_margin(departments: dict[str, float]) -> float:
    """Gap between the most and second most likely department (the top one alone if only one)."""
    ranked = sorted(departments.values(), reverse=True)
    if not ranked:
        return 0.0
    return ranked[0] - (ranked[1] if len(ranked) > 1 else 0.0)
 
 
def _unsure(status: str, reason: str | None, shown, question, terms, serious: bool = False) -> dict:
    """not_enough_info / low_confidence: "not enough information", General Medicine first."""
    out = {'status': status, 'symptoms': shown, 'question': question,
           'department': FALLBACK_DEPARTMENT,
           'message': SERIOUS_MESSAGE if serious else NOT_ENOUGH_INFO_MESSAGE,
           'safety_net': SAFETY_NET, **terms}
    if reason:
        out['reason'] = reason
    return out


def predict(text: str, answers: dict[str, bool] | None = None, model=None,
            columns: list[str] | None = None, rates=None, rate_columns: list[str] | None = None,
            dismissed=None, severity: dict[str, int] | None = None) -> dict:
    """Likely illnesses and department for a free-text symptom description.

    ``answers`` are the user's replies to earlier follow-up questions and "Did you mean ...?"
    suggestions ({symptom name: yes?}). ``dismissed`` lists suggestion terms the user said
    were not meant as that symptom. ``model`` / ``columns`` / ``rates`` / ``rate_columns`` /
    ``severity`` replace the loaded model (tests).
    Every result also carries ``matched`` (each term, the symptom it was mapped to and how:
    exact / synonym / lemma / fuzzy), ``negated``, ``unrecognized`` and ``suggestions`` so the
    user can see what was understood; nothing typed is silently dropped, and nothing
    unrecognised or unconfirmed reaches the model.
    """
    answers = dict(answers or {})
    prior = row_bits = None
    temperature = 1.0
    if model is None:
        if not load():
            return {'status': 'model_unavailable', 'symptoms': [], 'matched': [], 'negated': [],
                    'unrecognized': [], 'suggestions': []}
        model, columns, rates, rate_columns = _model, _columns, _rates, _rate_columns
        prior, row_bits, temperature = _prior, _row_bits, _temperature
        severity = _severity if severity is None else severity
        analysis = analyse(text)
    else:
        analysis = analyse(text, columns)
    severity = severity or {}

    # 1. Symptoms mentioned and not negated, plus "yes" answers; "no" answers are known absent.
    #    Suggestions count only once confirmed (a "yes" answer for their symptom).
    present = (set(analysis.present) | {s for s, yes in answers.items() if yes}) \
        - {s for s, yes in answers.items() if not yes}
    absent = (set(analysis.negated) | {s for s, yes in answers.items() if not yes}) - present
    shown = sorted(_label(s) for s in present)
    pending = _pending(analysis, answers, dismissed or [])
    terms = _terms(analysis, pending)

    # 2. Red flags, before anything else: on the recognised symptoms and on the text itself.
    #    expand() may add parents / implied follow-ups: never one the user said they don't have.
    expanded = expand(present) - absent
    flags = red_flags.check(expanded) + red_flags.check_text(text)
    if flags:
        return {'status': 'emergency', 'symptoms': shown, 'red_flags': [f.as_dict() for f in flags],
                'department': red_flags.EMERGENCY_DEPARTMENT, 'message': red_flags.EMERGENCY_MESSAGE, **terms}

    # 3. Unsure spellings: ask "Did you mean ...?" before the model sees anything.
    if pending:
        return {'status': 'needs_confirmation', 'symptoms': shown, **terms}

    # 4. Illness probabilities from the forest (symptoms not mentioned count as absent).
    probabilities = _probabilities(model, columns, expanded, prior, temperature) if present else None
    known = expanded | absent

    def question():
        return _question(probabilities, rates, rate_columns or [], columns, known, answers)

    # 5. Too little to go on: General Medicine, and the most informative question.
    if len(present) < MIN_SYMPTOMS:
        return _unsure('not_enough_info', None, shown, question(), terms)

    # 6. Top illnesses.
    order = np.argsort(-probabilities, kind='stable')[:TOP_ILLNESSES]
    illnesses = [{'name': str(model.classes_[i]), 'probability': round(float(probabilities[i]), 4)} for i in order]

    # 7. Department probability = sum over its likely illnesses (the long tail is not counted).
    departments = department_probabilities(model.classes_, probabilities, DEPT_MIN_ILLNESS_PROBABILITY)
    department = max(departments, key=departments.get) if departments else FALLBACK_DEPARTMENT
    dept_probability = departments.get(department, 0.0)

    # 8. Confidence gate: no training row with all these symptoms together, too much of the
    #    text not understood, no illness clearly ahead, the top two departments too close to
    #    call, or a serious illness from symptoms with no red flag. "Not enough information":
    #    General Medicine, and the most informative question.
    rows = support(expanded, columns, row_bits) if row_bits is not None else None
    top = illnesses[0]
    reason = None
    if rows is not None and rows < MIN_SUPPORT:
        reason = 'unseen_combination'
    elif analysis.unrecognized and len(analysis.unrecognized) >= len(analysis.present):
        reason = 'too_many_unrecognized'
    elif top['probability'] < MIN_ILLNESS_PROBABILITY:
        reason = 'no_clear_illness'
    elif dept_probability < MIN_DEPARTMENT_PROBABILITY or department_margin(departments) < MIN_DEPARTMENT_MARGIN:
        reason = 'no_clear_department'
    elif SERIOUS_SEVERITY and severity.get(top['name'], 99) <= SERIOUS_SEVERITY:
        reason = 'serious_illness'
    if reason:
        return _unsure('low_confidence', reason, shown, question(), terms, serious=reason == 'serious_illness')

    # 9. Result.
    return {
        'status': 'ok',
        'symptoms': shown,
        'illnesses': illnesses,
        'department': department,
        'dept_probability': round(dept_probability, 4),
        'departments': {d: round(p, 4) for d, p in sorted(departments.items(), key=lambda kv: -kv[1]) if round(p, 4) > 0},
        **terms,
    }
