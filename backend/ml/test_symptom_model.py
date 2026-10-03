"""Tests for ml/symptom_model.py, including Bernoulli Naive Bayes worked by hand.

Run:  python -m ml.test_symptom_model     or     python -m pytest ml/test_symptom_model.py
(needs ml/nb_model.joblib: python -m ml.train_nb)
"""
import math

import numpy as np
import pandas as pd
from sklearn.naive_bayes import BernoulliNB

from ml.symptom_model import DISCLAIMER, department_probabilities, load, predict

# ── Bernoulli Naive Bayes by hand ────────────────────────────────────────────
PRIORS = {'Flu': 0.40, 'Migraine': 0.30, 'Cold': 0.30}
LIKELIHOOD = {          # P(symptom present | illness)
    'Flu':      {'fever': 0.90, 'cough': 0.80, 'headache': 0.50},
    'Migraine': {'fever': 0.10, 'cough': 0.05, 'headache': 0.95},
    'Cold':     {'fever': 0.30, 'cough': 0.90, 'headache': 0.30},
}
PATIENT = {'fever': 1, 'cough': 1, 'headache': 0}
SYMPTOMS = ['fever', 'cough', 'headache']


def hand_scores():
    """Prior × Π P(x|d) for present symptoms × Π (1 − P(x|d)) for absent ones."""
    scores = {}
    for illness, prior in PRIORS.items():
        s = prior
        for sym in SYMPTOMS:
            p = LIKELIHOOD[illness][sym]
            s *= p if PATIENT[sym] else (1 - p)
        scores[illness] = s
    total = sum(scores.values())
    return scores, {k: v / total for k, v in scores.items()}


def sklearn_with_hand_parameters():
    """A scikit-learn BernoulliNB given exactly these priors and likelihoods."""
    classes = list(PRIORS)
    model = BernoulliNB(binarize=None)
    model.classes_ = np.array(classes)
    model.class_log_prior_ = np.log([PRIORS[c] for c in classes])
    model.feature_log_prob_ = np.log([[LIKELIHOOD[c][s] for s in SYMPTOMS] for c in classes])
    model.n_features_in_ = len(SYMPTOMS)
    model.feature_names_in_ = np.array(SYMPTOMS, dtype=object)
    return model


def cases():
    scores, posterior = hand_scores()
    yield 'hand score Flu = 0.1440', math.isclose(scores['Flu'], 0.1440, abs_tol=1e-9)
    yield 'hand score Migraine = 0.000075', math.isclose(scores['Migraine'], 0.000075, abs_tol=1e-12)
    yield 'hand score Cold = 0.0567', math.isclose(scores['Cold'], 0.0567, abs_tol=1e-9)
    yield 'normalised Flu 71.7%', round(100 * posterior['Flu'], 1) == 71.7
    yield 'normalised Cold 28.2%', round(100 * posterior['Cold'], 1) == 28.2
    yield 'normalised Migraine 0.04%', round(100 * posterior['Migraine'], 2) == 0.04

    model = sklearn_with_hand_parameters()
    proba = model.predict_proba(pd.DataFrame([[PATIENT[s] for s in SYMPTOMS]], columns=SYMPTOMS))[0]
    by_class = dict(zip(model.classes_, proba))
    yield 'scikit-learn BernoulliNB gives the same posteriors', all(
        math.isclose(by_class[c], posterior[c], rel_tol=1e-9) for c in PRIORS)

    # predict() with that model: the illnesses are not in the department map, so
    # all fall back to General Medicine and the department probability is 1.
    r = predict('fever and cough, no headache', model=model, columns=SYMPTOMS)
    yield 'predict(): negation drops headache, finds fever and cough', r['symptoms'] == ['cough', 'fever']
    yield 'predict(): top illness Flu 71.7%', r['illnesses'][0] == {'name': 'Flu', 'probability': 0.7172}
    yield 'predict(): illnesses ordered Flu, Cold, Migraine', [i['name'] for i in r['illnesses']] == ['Flu', 'Cold', 'Migraine']

    # Department probability is the SUM over the department's illnesses.
    dept = department_probabilities(['Hepatitis B', 'Hepatitis C', 'Migraine'], [0.3, 0.3, 0.4])
    yield 'department = sum of its illnesses (Gastroenterology 0.6 beats Neurology 0.4)', (
        math.isclose(dept['Gastroenterology'], 0.6) and math.isclose(dept['Neurology'], 0.4))

    # The trained model.
    if not load():
        yield 'trained model available (run python -m ml.train_nb)', False
        return
    r = predict('itching, skin rash and nodal skin eruptions')
    yield 'skin symptoms -> ok, Dermatology', r['status'] == 'ok' and r['department'] == 'Dermatology'
    yield 'ok result has 3 illnesses and a probability', len(r['illnesses']) == 3 and 0.4 <= r['dept_probability'] <= 1
    r = predict('I have chest pain, breathlessness and sweating')
    yield 'chest pain + breathlessness + sweating -> Heart attack first', r['illnesses'][0]['name'] == 'Heart attack'
    r = predict('itching and skin rash')
    yield 'one symptom only -> not_enough_info', predict('I only have itching')['status'] == 'not_enough_info'
    yield 'negated symptoms do not count -> not_enough_info', predict('no itching, no skin rash, no cough')['status'] == 'not_enough_info'
    yield 'empty text -> not_enough_info', predict('') == {'status': 'not_enough_info', 'symptoms': []}
    low = predict('headache and cough')
    yield 'vague pair -> low_confidence', low['status'] == 'low_confidence' and low['symptoms'] == ['cough', 'headache']
    yield 'disclaimer text', DISCLAIMER == 'Suggestion only, not a medical diagnosis.'


def run():
    results = list(cases())
    return results, sum(ok for _, ok in results)


def test_symptom_model_cases():
    results, _ = run()
    failed = [name for name, ok in results if not ok]
    assert not failed, failed


if __name__ == '__main__':
    scores, posterior = hand_scores()
    print('Hand scores:', {k: round(v, 6) for k, v in scores.items()})
    print('Normalised :', {k: f'{100 * v:.2f}%' for k, v in posterior.items()})
    results, passed = run()
    for name, ok in results:
        print(('  ok   ' if ok else '  FAIL ') + name.replace('->', '->'))
    print(f'{passed} of {len(results)} passed')
    raise SystemExit(0 if passed == len(results) else 1)
