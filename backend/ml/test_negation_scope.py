"""Negation scope on the real vocabulary (schema labels + ml/data/symptom_synonyms.json).

Run:  python -m pytest ml/test_negation_scope.py

Results are compared by label ("repeated vomiting"), not by DDXPlus code.
"""
import numpy as np
import pytest

from ml.negation import NEGATION, _words, find_symptoms, normalize_negations
from ml.schema import get as get_schema
from ml.symptom_terms import SYNONYMS_PATH, SymptomVocabulary, load_synonyms

USER_EXAMPLE = ("i have fever but i don't have headache , i feel nausea sometimes and dizziness too "
                "but i don't have vomiting")


@pytest.fixture(scope='module')
def check():
    schema = get_schema()
    labels = schema.labels()
    vocab = SymptomVocabulary(schema.names, load_synonyms(SYNONYMS_PATH), labels=labels)

    def run(text):
        a = vocab.analyse(text)
        return {labels.get(s, s) for s in a.present}, {labels.get(s, s) for s in a.negated}
    return run


@pytest.mark.parametrize('text, present, absent', [
    ("i have fever but i don't have headache", {'fever'}, {'headache'}),
    ('no fever but cough and sore throat', {'cough', 'sore throat'}, {'fever'}),
    ('without headache', set(), {'headache'}),
    ('i do not have vomiting', set(), {'repeated vomiting'}),
    ('no fever, cough or rash', set(), {'fever', 'cough', 'skin lesions'}),
    ('never had nausea but dizziness', {'dizziness'}, {'nausea'}),
    (USER_EXAMPLE, {'fever', 'nausea', 'dizziness'}, {'headache', 'repeated vomiting'}),
    # Contractions, with and without the apostrophe
    ("i dont have fever", set(), {'fever'}),
    ("she doesn’t have a cough", set(), {'cough'}),
    ("i didn't get any headache, just nausea", {'nausea'}, {'headache'}),
    ("i haven't really felt dizziness", set(), {'dizziness'}),
    # Clause boundaries
    ("no headache. fever", {'fever'}, {'headache'}),
    ("i don't have headache, i have cough", {'cough'}, {'headache'}),
    ("no headache and have nausea", {'nausea'}, {'headache'}),
    ("no fever, no cough, nausea", {'nausea'}, {'fever', 'cough'}),               # per-item cues
    # Scope length: the symptom must be within 4 content tokens of the cue
    ("no history of any fever", set(), {'fever'}),
    ("no problem at all last week except fever", {'fever'}, set()),
    # Cues inside a symptom phrase are not cues
    ("cant breathe and fever", {'shortness of breath', 'fever'}, set()),
    # Multi-word symptoms, longest match
    ("no sore throat but cough", {'cough'}, {'sore throat'}),
    # Explicit negation wins over another mention
    ("fever today, no fever yesterday", set(), {'fever'}),
])
def test_scope(check, text, present, absent):
    got_present, got_absent = check(text)
    assert (got_present, got_absent) == (present, absent)
    assert not got_present & got_absent


def test_contractions_normalised_to_one_token():
    words = _words("I don't, dont, doesn't, didn't, haven't, can't, cannot, never, no, without")
    cues = [w for w in normalize_negations(words) if w not in {',', 'i'}]
    assert cues == [NEGATION] * 10


def test_find_symptoms_maps_synonyms_after_negation():
    present, absent = find_symptoms('i do not have vomiting but nausea', ['repeated vomiting', 'nausea'],
                                     {'vomiting': 'repeated vomiting'})
    assert (present, absent) == ({'nausea'}, {'repeated vomiting'})


def test_absent_symptoms_never_reach_the_model():
    from ml.symptom_model import predict

    class Spy:
        classes_ = ['A', 'B']

        def predict_proba(self, x):
            self.x = x
            return np.array([[0.5, 0.5]])

    columns = ['fever', 'headache', 'nausea', 'dizziness', 'vomiting']
    spy = Spy()
    r = predict(USER_EXAMPLE, model=spy, columns=columns)
    assert r['symptoms'] == ['dizziness', 'fever', 'nausea']
    assert set(r['negated']) == {'headache', 'vomiting'}
    row = spy.x.iloc[0]
    assert row['headache'] == 0 and row['vomiting'] == 0
    assert row['fever'] == row['nausea'] == row['dizziness'] == 1
