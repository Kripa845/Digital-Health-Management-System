"""Symptom text → likely illnesses → department, with Bernoulli Naive Bayes.

The trained model (ml/nb_model.joblib, made by `python -m ml.train_nb`) is loaded
ONCE: the recommendations app calls load() at server startup, and predict()
only reuses it. predict() never trains or reads files per request.

Statuses returned by predict():
    ok                every field below
    not_enough_info   fewer than MIN_SYMPTOMS recognised (non-negated) symptoms
    low_confidence    best department below MIN_DEPARTMENT_PROBABILITY
    model_unavailable the model file is missing or could not be loaded
For any status other than "ok" the caller falls back to the keyword scorer.

The output is a suggestion, never a diagnosis.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ml.disease_dept import department_for
from ml.negation import extract_symptoms

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).resolve().parent / 'nb_model.joblib'
DISCLAIMER = 'Suggestion only, not a medical diagnosis.'
MIN_SYMPTOMS = 2
MIN_DEPARTMENT_PROBABILITY = 0.40
TOP_ILLNESSES = 3

_model = None            # BernoulliNB, set by load()
_columns: list[str] = []  # symptom names in training column order
_loaded = False


def load(path: Path = MODEL_PATH) -> bool:
    """Load the model into memory (once). Returns True when a model is available."""
    global _model, _columns, _loaded
    if _loaded:
        return _model is not None
    _loaded = True
    try:
        import joblib
        _model, _columns = joblib.load(path)
        _columns = list(_columns)
        logger.info('Symptom model loaded: %d illnesses, %d symptoms.', len(_model.classes_), len(_columns))
    except Exception as exc:   # missing file, version mismatch...: the keyword scorer is used instead
        _model, _columns = None, []
        logger.warning('Symptom model not available (%s); the keyword scorer will be used.', type(exc).__name__)
    return _model is not None


def symptom_columns() -> list[str]:
    load()
    return list(_columns)


def department_probabilities(classes, probabilities) -> dict[str, float]:
    """Sum the probability of every illness mapped to the same department."""
    totals: dict[str, float] = {}
    for illness, p in zip(classes, probabilities):
        dept = department_for(illness)
        totals[dept] = totals.get(dept, 0.0) + float(p)
    return totals


def predict(text: str, model=None, columns: list[str] | None = None) -> dict:
    """Likely illnesses and department for a free-text symptom description."""
    if model is None:
        if not load():
            return {'status': 'model_unavailable', 'symptoms': []}
        model, columns = _model, _columns

    # 1. Symptoms mentioned and not negated.
    present = extract_symptoms(text, columns)
    # 2. Too little to go on.
    if len(present) < MIN_SYMPTOMS:
        return {'status': 'not_enough_info', 'symptoms': present}

    # 3. 0/1 vector in training column order (with the training column names).
    index = {name: i for i, name in enumerate(columns)}
    x = np.zeros((1, len(columns)), dtype=np.int8)
    for name in present:
        x[0, index[name]] = 1
    probabilities = model.predict_proba(pd.DataFrame(x, columns=columns))[0]

    # 4. Top illnesses.
    order = np.argsort(-probabilities, kind='stable')[:TOP_ILLNESSES]
    illnesses = [{'name': str(model.classes_[i]), 'probability': round(float(probabilities[i]), 4)} for i in order]

    # 5. Department probability = sum over its illnesses.
    departments = department_probabilities(model.classes_, probabilities)
    department = max(departments, key=departments.get)
    dept_probability = departments[department]

    # 6. Not confident enough.
    if dept_probability < MIN_DEPARTMENT_PROBABILITY:
        return {'status': 'low_confidence', 'symptoms': present}

    # 7. Result.
    return {
        'status': 'ok',
        'symptoms': present,
        'illnesses': illnesses,
        'department': department,
        'dept_probability': round(dept_probability, 4),
    }
