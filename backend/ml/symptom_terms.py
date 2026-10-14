"""Turn free text into the schema's symptoms, and say what could not be matched.

    "no fever, but sore throat, skin rashes and feverr, blorf"   (labels from ml/data/symptom_schema.json)
        matched       sore throat → E_97 (exact), skin rashes → E_129 skin lesions (lemma)
        suggestions   feverr → E_91 fever? (91: asked, not sent to the model)
        negated       fever → E_91
        unrecognized  blorf

Steps, in this order (each word is matched by the first step that finds it):
1. Normalise: lower-case, trim, spaces / hyphens / underscores treated alike
   (``normalize("Sore-Throat ") == "sore_throat"``).
2. Exact and synonym: scan the words left to right, longest phrase first, against the
   symptoms' labels (exact) and the synonym dictionary (synonym).
3. Lemma: words still unmatched are tried again in their singular / base form
   ("rashes" → "rash", "itchiness" → "itchy", "feet" → "foot").
4. Fuzzy (spelling), only for leftovers of at least MIN_FUZZY_LENGTH letters:
   - similarity >= the threshold (DEFAULT_FUZZY_THRESHOLD, 93): matched (fuzzy);
   - SUGGEST_THRESHOLD (80) up to the threshold: a "Did you mean ...?" suggestion. It is
     NOT a match and never reaches the model until the user confirms it.
   A lower threshold maps words to the wrong symptom: "redness" was 87.5% similar to
   the synonym "tiredness" and became fatigue.
5. Negation is decided once, on the words as written, for every match and suggestion found
   in steps 2–4 (ml/negation.py: "don't have headache", "no fever, cough or rash"). The
   synonym's symptom is only what gets stored, so a negated synonym is still negated.
6. Anything left that is not a filler word ("I", "have", "since"...) is returned
   as unrecognized — input is never silently dropped, and never sent to the model.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from itertools import product

from rapidfuzz import fuzz

from ml.negation import LIST_LINKS, NEGATIONS, STOPPERS, _words, longest_matches, negated_spans

SYNONYMS_PATH = Path(__file__).resolve().parent / 'data' / 'symptom_synonyms.json'
DEFAULT_FUZZY_THRESHOLD = 93  # a spelling match at or above this is used without asking
SUGGEST_THRESHOLD = 80        # from here up to the threshold: "Did you mean ...?", never used unasked
MAX_FUZZY_WINDOW = 3          # words tried together when fuzzy matching
MAX_LEMMA_WINDOW = 4          # words tried together in their base forms
MIN_FUZZY_LENGTH = 5          # characters; shorter leftovers are too ambiguous to guess ("cof", "rash")

# Base forms that the suffix rules in word_forms() do not produce.
IRREGULAR = {'feet': 'foot', 'teeth': 'tooth'}

# Words that separate phrases, and words that carry no symptom on their own.
SEPARATORS = STOPPERS | LIST_LINKS | {',', 'with', 'also', 'plus', 'then'}
FILLERS = NEGATIONS | {
    'i', 'im', 'me', 'my', 'mine', 'we', 'he', 'she', 'they', 'patient', 'have', 'has', 'had', 'having',
    'am', 'is', 'are', 'was', 'were', 'be', 'been', 'feel', 'feels', 'feeling', 'felt', 'got', 'get',
    'getting', 'a', 'an', 'the', 'some', 'any', 'very', 'really', 'quite', 'bit', 'little', 'lot', 'lots',
    'severe', 'slight', 'bad', 'terrible', 'mild', 'since', 'for', 'from', 'day', 'days', 'week', 'weeks',
    'month', 'months', 'today', 'yesterday', 'tonight', 'morning', 'evening', 'night', 'last', 'past',
    'few', 'two', 'three', 'of', 'in', 'on', 'at', 'to', 'it', 'its', 'this', 'that', 'there', 'present',
    'suffering', 'experiencing', 'complaining', 'complains', 'symptoms', 'symptom', 'sometimes', 'often',
    'too', 'also', 'still', 'now', 'again', 'like', 'kind', 'sort', 'pretty', 'so', 'such', 'all',
    'only', 'just', 'don', 'doesn', 't', 's',
}


def normalize(term: str) -> str:
    """'Sore-Throat ' → 'sore_throat'; 'runny _nose' → 'runny_nose'."""
    text = re.sub(r'[\s\-_]+', '_', (term or '').strip().lower())
    return text.strip('_')


def word_forms(word: str) -> list[str]:
    """Possible base forms of a word, most likely first (the word itself excluded).

    'rashes' → ['rash', 'rashe'], 'allergies' → ['allergy', 'allergi', 'allergie'],
    'itchiness' → ['itchy'], 'redness' → ['red'], 'feet' → ['foot']. Only the forms that are a
    phrase in the vocabulary are used, so a wrong guess ('rashe') never matches anything.
    """
    forms = [IRREGULAR[word]] if word in IRREGULAR else []
    if len(word) > 5 and word.endswith('iness'):
        forms.append(word[:-5] + 'y')                 # itchiness → itchy, dizziness → dizzy
    elif len(word) > 5 and word.endswith('ness'):
        forms.append(word[:-4])                       # redness → red, soreness → sore
    if len(word) > 3 and word.endswith('s') and not word.endswith(('ss', 'us', 'is')):
        if word.endswith('ies'):
            forms.append(word[:-3] + 'y')             # allergies → allergy
        if word.endswith('es'):
            forms.append(word[:-2])                   # rashes → rash
        forms.append(word[:-1])                       # headaches → headache, cramps → cramp
    return [f for f in dict.fromkeys(forms) if f and f != word]


def load_synonyms(path: Path = SYNONYMS_PATH) -> dict[str, str]:
    """Synonym phrase (normalised) → symptom name (normalised).

    An entry is either "phrase": "E_91" or "phrase": {"symptom": "E_91", "status": "needs review"}.
    """
    with open(path, encoding='utf-8') as fh:
        data = json.load(fh)
    return {normalize(k): normalize(v['symptom'] if isinstance(v, dict) else v)
            for k, v in data.get('synonyms', {}).items()}


@dataclass
class TermMatch:
    term: str             # as written by the user
    symptom: str          # the model's symptom column (schema name)
    method: str           # 'exact', 'synonym', 'lemma', 'fuzzy' or 'suggestion' (not a match: ask first)
    score: float | None   # rapidfuzz similarity for fuzzy matches and suggestions
    negated: bool
    span: tuple[int, int] = field(default=(0, 0), repr=False, compare=False)   # word indices
    phrase: str | None = field(default=None, compare=False)   # the vocabulary phrase a fuzzy term resembled

    def as_dict(self) -> dict:
        return {'term': self.term, 'symptom': self.symptom, 'method': self.method,
                'score': None if self.score is None else round(self.score, 1)}


@dataclass
class TermAnalysis:
    matches: list[TermMatch] = field(default_factory=list)
    unrecognized: list[str] = field(default_factory=list)
    # Low-confidence spelling matches ("feverr" → fever?): shown as "Did you mean ...?" and
    # used only once the user confirms them. Negated ones are not kept (see analyse()).
    suggestions: list[TermMatch] = field(default_factory=list)

    @property
    def present(self) -> list[str]:
        """Symptoms mentioned without negation and never negated (sorted). Only these may
        reach the model."""
        return sorted({m.symptom for m in self.matches if not m.negated} - set(self.negated))

    @property
    def negated(self) -> list[str]:
        """Symptoms negated at least once (sorted): an explicit negation wins over another
        mention of the same symptom."""
        return sorted({m.symptom for m in self.matches if m.negated})


class SymptomVocabulary:
    """The phrases that can be recognised: each symptom's label (or its name when no
    label is given) plus synonyms. Synonyms may target a symptom's name or its label."""

    def __init__(self, columns, synonyms: dict[str, str] | None = None,
                 fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD, labels: dict[str, str] | None = None,
                 suggest_threshold: float = SUGGEST_THRESHOLD):
        self.columns = list(columns)
        labels = labels or {}
        exact = {normalize(labels.get(c, c)): c for c in self.columns}
        by_key = {**exact, **{normalize(c): c for c in self.columns}}
        self.invalid_synonyms = sorted(k for k, v in (synonyms or {}).items() if v not in by_key)
        # phrase (tuple of words) → (column, method)
        self.phrases: dict[tuple[str, ...], tuple[str, str]] = {}
        for key, column in exact.items():
            self.phrases[tuple(key.split('_'))] = (column, 'exact')
        for key, target in (synonyms or {}).items():
            if target in by_key:
                self.phrases.setdefault(tuple(key.split('_')), (by_key[target], 'synonym'))
        self.longest = max((len(p) for p in self.phrases), default=1)
        self.fuzzy_threshold = float(fuzzy_threshold)
        self.suggest_threshold = min(float(suggest_threshold), self.fuzzy_threshold)
        self._fuzzy_choices = {' '.join(p): v for p, v in self.phrases.items()}

    def closest(self, text: str) -> tuple[str, float, str] | None:
        """(symptom, similarity, phrase) of the most similar phrase, or None for short text."""
        if len(text.replace(' ', '')) < MIN_FUZZY_LENGTH:
            return None
        best, best_score, best_phrase = None, 0.0, None
        for phrase, (column, _method) in self._fuzzy_choices.items():
            score = fuzz.ratio(text, phrase)
            if score > best_score:
                best, best_score, best_phrase = column, score, phrase
        return (best, best_score, best_phrase) if best is not None else None

    def fuzzy(self, text: str) -> tuple[str, float] | None:
        """Best phrase for a misspelt text, if similar enough to use without asking."""
        hit = self.closest(text)
        return (hit[0], hit[1]) if hit and hit[1] >= self.fuzzy_threshold else None

    def lemma(self, words: list[str]) -> tuple[str, str] | None:
        """(symptom, method of the phrase) when the words, some in a base form, are a phrase:
        ['skin', 'rashes'] → ('skin', 'rash') → skin lesions."""
        options = [[w, *word_forms(w)] for w in words]
        if all(len(o) == 1 for o in options):
            return None
        for candidate in product(*options):
            if candidate != tuple(words) and candidate in self.phrases:
                return self.phrases[candidate]
        return None

    def analyse(self, text: str) -> TermAnalysis:
        words = _words(text)
        result = TermAnalysis()
        covered = [False] * len(words)

        # 2. Exact names and synonyms, longest phrase first, on the words as written.
        for start, end, phrase in longest_matches(words, self.phrases):
            column, method = self.phrases[phrase]
            result.matches.append(TermMatch(' '.join(phrase), column, method, None, False, (start, end)))
            for k in range(start, end):
                covered[k] = True

        # 3, 4, 6. Leftover segments: base forms, then spelling, then unrecognized.
        for start, segment in self._leftover_segments(words, covered):
            self._fuzzy_segment(start, segment, result)

        # 5. Negation, decided once for all matches and suggestions.
        spans = sorted(m.span for m in result.matches + result.suggestions)
        negated = dict(zip(spans, negated_spans(words, spans)))
        for m in result.matches + result.suggestions:
            m.negated = negated[m.span]
        # "no feverr": asking "Did you mean fever?" would turn it into a symptom the user
        # does not have. The word is listed as unrecognized instead.
        result.unrecognized += [s.term for s in result.suggestions if s.negated]
        result.suggestions = [s for s in result.suggestions if not s.negated]
        return result

    @staticmethod
    def _leftover_segments(words, covered):
        """Runs of uncovered, non-separator words, with their start index."""
        segment, start = [], None
        for idx, word in enumerate(words):
            if covered[idx] or word in SEPARATORS:
                if segment:
                    yield start, segment
                segment, start = [], None
                continue
            if start is None:
                start = idx
            segment.append(word)
        if segment:
            yield start, segment

    def _windows(self, segment, k, longest):
        """Word windows starting at k, longest first, not ending in a filler word."""
        for n in range(min(longest, len(segment) - k), 0, -1):
            window = segment[k:k + n]
            if window[-1] not in FILLERS:
                yield n, window

    def _best_at(self, segment, k):
        """The first step that recognises words from segment[k]: (n words, TermMatch fields) or None.
        Order: base form (lemma), spelling match, "Did you mean" suggestion."""
        for n, window in self._windows(segment, k, min(self.longest, MAX_LEMMA_WINDOW)):
            hit = self.lemma(window)
            if hit:
                return n, (hit[0], 'lemma', None, None)
        suggestion = None
        for n, window in self._windows(segment, k, MAX_FUZZY_WINDOW):
            hit = self.closest(' '.join(window))
            if hit is None:
                continue
            column, score, phrase = hit
            if score >= self.fuzzy_threshold:
                return n, (column, 'fuzzy', score, phrase)
            if score >= self.suggest_threshold and (suggestion is None or score > suggestion[1][2]):
                suggestion = (n, (column, 'suggestion', score, phrase))
        return suggestion

    def _fuzzy_segment(self, start, segment, result):
        k, leftovers = 0, []
        while k < len(segment):
            if segment[k] in FILLERS or segment[k].isdigit():
                if leftovers:
                    result.unrecognized.append(' '.join(leftovers))
                    leftovers = []
                k += 1
                continue
            best = self._best_at(segment, k)
            if best is None:
                leftovers.append(segment[k])
                k += 1
                continue
            if leftovers:
                result.unrecognized.append(' '.join(leftovers))
                leftovers = []
            n, (column, method, score, phrase) = best
            match = TermMatch(' '.join(segment[k:k + n]), column, method, score, False,
                              (start + k, start + k + n), phrase)
            (result.suggestions if method == 'suggestion' else result.matches).append(match)
            k += n
        if leftovers:
            result.unrecognized.append(' '.join(leftovers))
