"""Regression tests for the symptom-matching and prediction fixes (wrong spelling matches,
illogical predictions for common symptoms, unsafe handling of unclear input).

Run:  python -m pytest ml/test_symptom_fixes.py -v
(the trained-model checks need ml/symptom_model.joblib: python -m ml.train_model)
"""
import numpy as np
import pytest

from ml import red_flags, symptom_model
from ml.symptom_terms import SymptomVocabulary, word_forms
from ml.train_model import apply_calibration, class_weights, expected_calibration_error, fit_temperature

import pandas as pd


@pytest.fixture(scope='module', autouse=True)
def model():
    if not symptom_model.load():
        pytest.skip('run python -m ml.train_model first')


def matched(text):
    a = symptom_model.analyse(text)
    return {m.term: (symptom_model._label(m.symptom), m.method) for m in a.matches}, a


# ── Problem 1: matching order and strict spelling ────────────────────────────

def test_reported_skin_input_is_matched_to_skin_symptoms():
    terms, a = matched('rashes, swelling, itchy, redness')
    assert terms == {
        'rashes': ('skin lesions', 'lemma'),        # plural → "rash" (synonym)
        'swelling': ('swelling', 'exact'),
        'itchy': ('itchy rash', 'synonym'),          # was fuzzy "itch" 89%
        'redness': ('skin lesions', 'synonym'),      # was fuzzy "tiredness" 87.5% → fatigue
    }
    assert 'fatigue' not in {label for label, _ in terms.values()}
    assert a.unrecognized == [] and a.suggestions == []


@pytest.mark.parametrize('text, label', [
    ('skin rashes', 'skin lesions'), ('itchiness', 'itchy rash'), ('hives', 'itchy rash'),
    ('red skin', 'skin lesions'), ('headaches', 'headache'), ('swollen ankles', 'swelling'),
])
def test_word_forms_and_synonyms(text, label):
    terms, _ = matched(text)
    assert [lab for lab, _ in terms.values()] == [label]


def test_word_forms():
    assert word_forms('rashes')[0] == 'rash' and word_forms('allergies')[0] == 'allergy'
    assert word_forms('itchiness') == ['itchy'] and word_forms('feet') == ['foot']
    assert word_forms('rash') == [] and word_forms('illness') == ['ill']


def test_order_exact_then_synonym_then_lemma_then_fuzzy():
    v = SymptomVocabulary(['rash', 'cough'], {'itch': 'rash'}, labels={})
    a = v.analyse('rash, itch, rashes, coughh, cogh')
    assert [(m.term, m.method) for m in a.matches] == [('rash', 'exact'), ('itch', 'synonym'), ('rashes', 'lemma')]
    assert [(s.term, s.method) for s in a.suggestions] == [('coughh', 'suggestion')]   # 91%: ask
    assert a.unrecognized == ['cogh']                                                   # under 5 letters


def test_strict_fuzzy_threshold():
    v = SymptomVocabulary(['headache', 'fatigue'], {'tiredness': 'fatigue'}, labels={})
    assert [(m.term, m.method) for m in v.analyse('hedache').matches] == [('hedache', 'fuzzy')]   # 93.3
    a = v.analyse('redness')                                       # 87.5 to "tiredness": never auto-matched
    assert a.matches == [] and [s.term for s in a.suggestions] == ['redness']


def test_low_confidence_match_is_not_sent_to_the_model():
    r = symptom_model.predict('feverr, cough, sore throat')
    assert r['status'] == 'needs_confirmation' and 'illnesses' not in r
    assert r['symptoms'] == ['cough', 'sore throat']
    assert r['suggestions'] == [{'term': 'feverr', 'symptom': 'E_91', 'label': 'fever', 'score': 90.9}]


def test_confirmed_and_dismissed_suggestions():
    assert 'fever' in symptom_model.predict('feverr, cough, sore throat', answers={'E_91': True})['symptoms']
    r = symptom_model.predict('feverr, cough, sore throat', dismissed=['feverr'])
    assert r['status'] != 'needs_confirmation' and 'fever' not in r['symptoms']


def test_negated_typo_is_not_suggested():
    a = symptom_model.analyse('no feverr, cough')
    assert a.suggestions == [] and 'feverr' in a.unrecognized


# ── Problem 2: confidence gate, prevalence, department score ─────────────────

@pytest.mark.parametrize('text, reason', [
    ('fever, nausea, dizziness', 'unseen_combination'),
    ('rash, swelling, itching', 'serious_illness'),          # was Anaphylaxis 80%, Emergency Medicine
    ('rashes, swelling, itchy, redness', 'serious_illness'),
    ('fever, cough, sore throat, kxcd, plmq, wert', 'too_many_unrecognized'),
])
def test_unsure_results_say_not_enough_information_and_general_medicine(text, reason):
    r = symptom_model.predict(text)
    assert (r['status'], r['reason']) == ('low_confidence', reason)
    assert r['department'] == 'General Medicine' and 'illnesses' not in r
    assert r['message'] and r['safety_net']


def test_common_cold_symptoms_give_a_common_illness():
    r = symptom_model.predict('fever, cough, sore throat')
    assert r['status'] == 'ok' and r['illnesses'][0]['name'] == 'URTI'
    assert not {'Ebola', 'Chagas'} & {i['name'] for i in r['illnesses']}


def test_department_ignores_the_long_tail():
    classes = ['Atrial fibrillation', 'PSVT', 'Stable angina', 'Myocarditis', 'URTI']
    p = [0.03, 0.03, 0.03, 0.03, 0.30]
    assert symptom_model.department_probabilities(classes, p) == pytest.approx(
        {'Cardiology': 0.12, 'General Medicine': 0.30})
    assert symptom_model.department_probabilities(classes, p, 0.05) == pytest.approx({'General Medicine': 0.30})


def test_class_weights_are_balanced_and_capped():
    y = pd.Series(['a'] * 1000 + ['b'] * 10 + ['c'])
    w = class_weights(y, cap=20)
    assert w['a'] < 1 < w['b'] and w['c'] == 20


def test_calibration_helpers():
    p = np.array([[0.9, 0.1], [0.6, 0.4]])
    assert np.allclose(apply_calibration(p, np.array([1.0, 3.0])), [[0.75, 0.25], [1 / 3, 2 / 3]])
    softer = apply_calibration(p, None, 2.0)
    assert softer[0, 0] < 0.9                                   # T > 1 softens
    # A model that says 90% but is right half the time: the fitted temperature softens it.
    q = np.tile([[0.9, 0.1]], (100, 1))
    y = np.array([0, 1] * 50)
    t, scores = fit_temperature(q, y, None)
    assert t > 1 and scores['ece_after'] < scores['ece_before']
    assert expected_calibration_error(np.array([[1.0, 0.0]]), np.array([0]), np.ones(1)) == 0


def test_saved_model_has_weights_prior_calibration_and_severity():
    assert symptom_model._prior is not None and symptom_model._prior.max() < 20   # no factor clipped
    assert symptom_model._temperature > 0
    assert symptom_model._severity.get('Anaphylaxis') == 1


# ── Problem 3: red flags override the model ──────────────────────────────────

@pytest.mark.parametrize('text, flag', [
    ('rash and my throat is closing', 'throat_swelling'),
    ('swollen tongue and itching', 'throat_swelling'),
    ("I can't breathe", 'severe_breathing_difficulty'),
    ('lips turning blue', 'severe_breathing_difficulty'),
    ('I keep fainting', 'fainting'),
    ('crushing chest pain', 'severe_chest_pain'),
    ('chest pain and shortness of breath', 'chest_pain_with_warning_signs'),
    ('chest pain and sweating', 'chest_pain_with_warning_signs'),
    ('swelling and wheezing', 'swelling_with_breathing_problem'),
])
def test_red_flags(text, flag):
    r = symptom_model.predict(text)
    assert r['status'] == 'emergency' and flag in [f['id'] for f in r['red_flags']]


@pytest.mark.parametrize('text', ['no throat swelling', "I don't faint", 'never fainted'])
def test_negated_phrase_red_flags_do_not_fire(text):
    assert red_flags.check_text(text) == []


def test_red_flag_wins_over_a_pending_suggestion():
    assert symptom_model.predict('feverr and I cannot breathe')['status'] == 'emergency'


def test_chest_pain_alone_is_not_a_red_flag():
    assert symptom_model.predict('heartburn and chest pain')['status'] != 'emergency'
