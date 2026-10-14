"""Tests for ml/symptom_model.py and ml/questioning.py, including information gain worked by hand.

Run:  python -m ml.test_symptom_model     or     python -m pytest ml/test_symptom_model.py
(the trained-model checks need ml/symptom_model.joblib: python -m ml.train_model)
"""
import math

import numpy as np

from ml import symptom_model
from ml.questioning import MAX_QUESTIONS, information_gain, next_question
from ml.symptom_model import (
    DISCLAIMER, _probabilities, department_probabilities, load, predict, support, symptom_columns,
)

# ── Information gain by hand ─────────────────────────────────────────────────
# Two illnesses, equally likely. "fever" splits them (90% vs 10%); "cough" does not (50% vs 50%).
BELIEF = np.array([0.5, 0.5])
RATES = np.array([[0.9, 0.5],     # illness A: P(fever), P(cough)
                  [0.1, 0.5]])    # illness B


def hand_gain_fever() -> float:
    """H(before) = 1 bit. P(yes) = 0.5; after yes the belief is (0.9, 0.1), after no (0.1, 0.9)."""
    h_after = -(0.9 * math.log2(0.9) + 0.1 * math.log2(0.1))     # 0.469 bits either way
    return 1.0 - h_after                                          # 0.531 bits


class FixedModel:
    """A stand-in for the forest: fixed probabilities, so the pipeline is tested without training."""

    def __init__(self, classes, probabilities):
        self.classes_ = np.array(classes)
        self._p = np.array([probabilities])
        self.inputs = []

    def predict_proba(self, x):
        self.inputs.append(x)
        return self._p


def cases():
    gains = information_gain(BELIEF, RATES)
    yield 'hand: asking about fever gains 0.531 bits', math.isclose(gains[0], hand_gain_fever(), abs_tol=1e-9)
    yield 'hand: asking about cough gains nothing', math.isclose(gains[1], 0.0, abs_tol=1e-9)
    yield 'next_question picks fever', next_question(BELIEF, RATES, ['fever', 'cough'], set(), ['fever', 'cough']) == 'fever'
    yield 'next_question skips symptoms already known', next_question(
        BELIEF, RATES, ['fever', 'cough'], {'fever'}, ['fever', 'cough']) is None      # cough gains nothing
    yield 'no symptom table -> no question', next_question(BELIEF, None, [], set(), ['fever']) is None

    # predict() with a fixed model: negation, the 0/1 vector it builds, illnesses ordered by probability.
    # The illnesses are not in the department map, so all fall back to General Medicine.
    columns = ['fever', 'cough', 'headache']
    model = FixedModel(['Flu', 'Migraine', 'Cold'], [0.7172, 0.0004, 0.2824])
    min_symptoms, symptom_model.MIN_SYMPTOMS = symptom_model.MIN_SYMPTOMS, 2   # this toy schema has 3 symptoms
    try:
        r = predict('fever and cough, no headache', model=model, columns=columns)
    finally:
        symptom_model.MIN_SYMPTOMS = min_symptoms
    yield 'predict(): negation drops headache, finds fever and cough', r['symptoms'] == ['cough', 'fever']
    yield 'predict(): the forest gets fever=1, cough=1, headache=0', (
        model.inputs[-1].iloc[0].tolist() == [1, 1, 0] and list(model.inputs[-1].columns) == columns)
    yield 'predict(): top illness Flu 71.7%', r['illnesses'][0] == {'name': 'Flu', 'probability': 0.7172}
    yield 'predict(): illnesses ordered Flu, Cold, Migraine', [i['name'] for i in r['illnesses']] == ['Flu', 'Cold', 'Migraine']

    # Department probability is the SUM over the department's illnesses.
    dept = department_probabilities(['GERD', 'Pneumonia', 'Bronchitis'], [0.3, 0.3, 0.4])
    yield 'department = sum of its illnesses (Pulmonology 0.7 beats Gastroenterology 0.3)', (
        math.isclose(dept['Pulmonology'], 0.7) and math.isclose(dept['Gastroenterology'], 0.3))

    # Class prior: (0.5, 0.5) x (1, 3) renormalised = (0.25, 0.75).
    p = _probabilities(FixedModel(['A', 'B'], [0.5, 0.5]), ['fever'], {'fever'}, np.array([1.0, 3.0]))
    yield 'prior: probabilities x prior, renormalised', np.allclose(p, [0.25, 0.75])

    # Support: training rows (fever, nausea, dizziness) = (1,1,0), (1,0,0), (0,1,1).
    rows = np.packbits(np.array([[1, 1, 0], [1, 0, 0], [0, 1, 1]], dtype=bool), axis=1)
    cols = ['fever', 'nausea', 'dizziness']
    yield 'support: fever alone is in 2 rows', support({'fever'}, cols, rows) == 2
    yield 'support: fever + nausea is in 1 row', support({'fever', 'nausea'}, cols, rows) == 1
    yield 'support: fever + nausea + dizziness is in no row', support(set(cols), cols, rows) == 0

    # The trained model (DDXPlus, synthetic).
    if not load():
        yield 'trained model available (run python -m ml.train_model)', False
        return
    for text, department in SAMPLE_SENTENCES:
        r = predict(text)
        yield f'"{text}" -> ok, {department}', (r['status'], r.get('department')) == ('ok', department)
    for text, expected in UNSURE_SENTENCES:
        r = predict(text)
        yield f'"{text}" -> low_confidence ({expected})', (r['status'], r.get('reason')) == ('low_confidence', expected)
    r = predict('heartburn, worse after eating and worse lying down')
    yield 'reflux symptoms -> GERD first', r['illnesses'][0]['name'] == 'GERD'
    yield 'ok result has 3 illnesses and a probability', len(r['illnesses']) == 3 and 0.4 <= r['dept_probability'] <= 1
    yield 'symptoms are shown by label, not DDXPlus code', r['symptoms'] == [
        'heartburn', 'worse after eating', 'worse lying down']
    r = predict('I only have a cough')
    yield 'one symptom only -> not_enough_info', r['status'] == 'not_enough_info'
    yield 'not_enough_info asks an information-gain question', (
        r['question'] is not None and r['question']['symptom'] in symptom_columns()
        and r['question']['text'].endswith('?'))
    r2 = predict('I only have a cough', answers={r['question']['symptom']: True})
    yield 'a "yes" answer counts as a symptom', r['question']['label'] in r2['symptoms']
    yield 'negated symptoms do not count -> not_enough_info', predict('no cough, no fever, no sore throat')['status'] == 'not_enough_info'
    empty = predict('')
    yield 'empty text -> not_enough_info, no question', (
        empty['status'], empty['symptoms'], empty['unrecognized'], empty['question']) == ('not_enough_info', [], [], None)
    many = predict('I only have a cough', answers={f'E_{n}': False for n in (91, 97, 77, 66, 214)})
    yield f'no question after {MAX_QUESTIONS} answers', many['question'] is None
    yield 'disclaimer text', DISCLAIMER == 'Suggestion only, not a medical diagnosis.'


# Everyday sentences and the department a first-contact clinician would expect.
SAMPLE_SENTENCES = [
    ('fever, cough and sore throat', 'General Medicine'),
    ('runny nose, sore throat and cough', 'General Medicine'),
    ('chest pain, fever, coloured sputum and cough', 'Pulmonology'),
    ('cough, coloured sputum, fever and shortness of breath', 'Pulmonology'),
    ('wheezing, shortness of breath and cough', 'Pulmonology'),
    ('heartburn, worse after eating and worse lying down', 'Gastroenterology'),
    ('heartburn, worse after eating and stomach pain', 'Gastroenterology'),
    ('palpitations, irregular heartbeat and dizziness', 'Cardiology'),
    ('runny nose, itchy eyes and itchy nose', 'ENT'),
    ('ear pain, fever and runny nose', 'ENT'),
    ('pale skin, fatigue and dizziness', 'General Medicine'),
    ('double vision, drooping eyelids and weakness worse with fatigue', 'Neurology'),
]

# Descriptions the model must NOT answer confidently, and why.
UNSURE_SENTENCES = [
    # No DDXPlus patient has fever + nausea + dizziness (dizziness: anemia, AFib, PSVT only).
    ("i have fever but i don't have headache, i feel nausea sometimes and dizziness too "
     "but i don't have vomiting", 'unseen_combination'),
    ('fever, nausea and dizziness', 'unseen_combination'),
]


def run():
    results = list(cases())
    return results, sum(ok for _, ok in results)


def test_symptom_model_cases():
    results, _ = run()
    failed = [name for name, ok in results if not ok]
    assert not failed, failed


if __name__ == '__main__':
    print(f'Hand: information gain of fever = {hand_gain_fever():.3f} bits')
    results, passed = run()
    for name, ok in results:
        print(('  ok   ' if ok else '  FAIL ') + name)
    print(f'{passed} of {len(results)} passed')
    raise SystemExit(0 if passed == len(results) else 1)
