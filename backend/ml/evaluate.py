"""Evaluate the smart symptom check and compare it with the old keyword scorer.

Run from backend/:   python -m ml.evaluate      (after python -m ml.train_nb)

1. Naive Bayes metrics on the held-out test set.
2. Department accuracy: old keyword scorer vs the new method, on cases written
   as text from held-out rows, plus cases with a negated misleading symptom.
3. Negation unit-test pass rate.
4. Everything is written to ml/RESULTS.md.
"""
from __future__ import annotations

import os
import random
from collections import Counter
from pathlib import Path

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score  # noqa: E402

from apps.recommendations.views import match_department, score_departments  # noqa: E402  (old keyword scorer)
from ml import symptom_model, test_negation  # noqa: E402
from ml.disease_dept import UNCERTAIN, department_for  # noqa: E402
from ml.negation import _words  # noqa: E402
from ml.sensitivity import BENEFIT as SENS_BENEFIT, MATRIX as SENS_MATRIX, WEIGHT_SETS  # noqa: E402
from ml.topsis import topsis  # noqa: E402

ML_DIR = Path(__file__).resolve().parent
RESULTS = ML_DIR / 'RESULTS.md'
TRAINING_RESULTS = ML_DIR / 'TRAINING_RESULTS.md'
N_STANDARD = 50
N_NEGATION = 12
SEED = 42


def as_text(symptoms: list[str]) -> str:
    """['fever', 'cough', 'headache'] → 'fever, cough and headache'."""
    if len(symptoms) == 1:
        return symptoms[0]
    return ', '.join(symptoms[:-1]) + ' and ' + symptoms[-1]


def mentioned_ignoring_negation(text: str, columns: list[str]) -> list[str]:
    """Every symptom mentioned, negated or not (for the 'no negation detection' comparison)."""
    words = _words(text)
    found = []
    for s in columns:
        target = _words(s)
        n = len(target)
        if any(words[i:i + n] == target for i in range(len(words) - n + 1)):
            found.append(s)
    return found


def nb_department(present: list[str], model, columns) -> str | None:
    if len(present) < symptom_model.MIN_SYMPTOMS:
        return None
    x = pd.DataFrame([[1 if c in present else 0 for c in columns]], columns=columns)
    depts = symptom_model.department_probabilities(model.classes_, model.predict_proba(x)[0])
    best = max(depts, key=depts.get)
    return best if depts[best] >= symptom_model.MIN_DEPARTMENT_PROBABILITY else None


def build_cases(X_test, y_test, columns):
    rows = sorted(
        ((y, [c for c in columns if X_test.iloc[i][c] == 1]) for i, y in enumerate(y_test)),
        key=lambda r: (r[0], r[1]))
    standard = [{'type': 'standard', 'text': as_text(sym), 'disease': y, 'correct': department_for(y)}
                for y, sym in rows[:N_STANDARD]]

    # Negation cases: two real symptoms, plus three symptoms typical of ONE illness in
    # another department, all negated ("no a, no b, no c, but x and y").
    rng = random.Random(SEED)
    by_disease = {}
    for y, sym in rows:
        by_disease.setdefault(y, set()).update(sym)
    negation = []
    for y, sym in rng.sample([r for r in rows if len(r[1]) >= 2], N_NEGATION):
        dept = department_for(y)
        own = by_disease[y]
        other = rng.choice(sorted(d for d in by_disease if department_for(d) != dept
                                  and len(by_disease[d] - own) >= 3))
        distractors = rng.sample(sorted(by_disease[other] - own), 3)
        real = rng.sample(sym, 2)
        negated = ', '.join(f'no {d}' for d in distractors)
        negation.append({'type': 'negation', 'text': f'{negated}, but {as_text(real)}',
                         'disease': y, 'correct': dept, 'distractor_disease': other})
    return standard, negation


def evaluate_cases(cases, model, columns):
    for c in cases:
        c['old'] = match_department(c['text'])
        r = symptom_model.predict(c['text'])
        c['new_status'] = r['status']
        c['new_nb'] = r.get('department')                       # None when not "ok"
        c['new_system'] = c['new_nb'] or c['old']               # as shipped: fallback to the keyword scorer
        c['no_negation'] = nb_department(mentioned_ignoring_negation(c['text'], columns), model, columns)
    return cases


def accuracy_rows(cases):
    methods = [
        ('Old keyword scorer', 'old'),
        ('New: Naive Bayes only (non-ok counted as wrong)', 'new_nb'),
        ('New system as shipped (non-ok → keyword fallback)', 'new_system'),
        ('Naive Bayes WITHOUT negation detection', 'no_negation'),
    ]
    out = []
    for label, key in methods:
        correct = sum(c[key] == c['correct'] for c in cases)
        out.append((label, correct, len(cases), correct / len(cases) if cases else 0.0))
    return out


def table(rows, header):
    lines = ['| ' + ' | '.join(header) + ' |', '| ' + ' | '.join('---' for _ in header) + ' |']
    lines += ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in rows]
    return '\n'.join(lines)


def main():
    if not symptom_model.load():
        raise SystemExit('ml/nb_model.joblib is missing: run python -m ml.train_nb first.')
    model, columns = joblib.load(symptom_model.MODEL_PATH)
    X_test, y_test, _ = joblib.load(ML_DIR / 'test_set.joblib')

    # 1. Naive Bayes on the held-out set.
    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred, average='macro', zero_division=0)
    labels = sorted(set(y_test) | set(y_pred))
    cm = confusion_matrix(y_test, y_pred, labels=labels)
    errors = [(labels[i], labels[j], int(cm[i, j])) for i in range(len(labels)) for j in range(len(labels))
              if i != j and cm[i, j]]
    print(f'1. Naive Bayes on {len(y_test)} held-out rows: accuracy {acc:.4f}, macro F1 {f1:.4f}')
    for t, p, n in errors:
        print(f'   misclassified: {t} -> {p} ({n})')

    # 2. Department comparison.
    standard, negation = build_cases(X_test, y_test, columns)
    evaluate_cases(standard + negation, model, columns)
    print(f'\n2. Department accuracy ({len(standard)} standard + {len(negation)} negation cases)')
    sections = {}
    for name, cases in (('Standard cases', standard), ('Negation cases', negation), ('All cases', standard + negation)):
        rows = accuracy_rows(cases)
        sections[name] = rows
        print(f'   {name}:')
        for label, correct, total, a in rows:
            print(f'     {label.replace("→", "->"):55} {correct:>3}/{total:<3} {a:6.1%}')
    statuses = Counter(c['new_status'] for c in standard + negation)
    print(f'   New method statuses: {dict(statuses)}')

    # 3. Negation tests.
    neg_passed, neg_total, neg_failures = test_negation.run()
    print(f'\n3. Negation tests: {neg_passed} of {neg_total} passed')

    # TOPSIS sensitivity (for the report).
    sens_rows = []
    for label, weights in WEIGHT_SETS.items():
        scores = topsis(SENS_MATRIX, weights, SENS_BENEFIT)
        ranking = ' > '.join('ABC'[i] for i in np.argsort(-scores, kind='stable'))
        sens_rows.append((label, *(f'{s:.3f}' for s in scores), ranking))

    # 4. RESULTS.md
    every = standard + negation
    old_correct = sum(c['old'] == c['correct'] for c in every)
    old_default_hits = sum(c['old'] == c['correct'] == 'General Medicine'
                           and not score_departments(c['text'])
                           for c in every)
    neg_rows = sections['Negation cases']
    training =TRAINING_RESULTS.read_text(encoding='utf-8') if TRAINING_RESULTS.exists() else ''
    training_body = training.split('\n', 1)[1].strip() if training else '_Run python -m ml.train_nb._'
    case_rows = [(i + 1, c['type'], c['text'], c['disease'], c['correct'], c['old'],
                  c['new_nb'] or f"({c['new_status']})", c['new_system'],
                  '✓' if c['new_system'] == c['correct'] else '✗')
                 for i, c in enumerate(standard + negation)]
    RESULTS.write_text(f"""# Smart symptom check — evaluation results

Generated by `python -m ml.evaluate`. Pipeline: symptom text → rule-based negation detection →
Bernoulli Naive Bayes (41 illnesses) → department (sum of illness probabilities) → TOPSIS ranking
of doctors. **The output is a suggestion only, not a medical diagnosis.**

> **Important caveat.** The Kaggle dataset used here is very clean and synthetic-looking: 4,920 rows
> collapse to 304 unique ones, and each illness has a small, fixed set of symptoms. Accuracy on it is
> therefore unrealistically high and **does not reflect real-world performance**, where patients describe
> symptoms in their own words, mention unrelated complaints, and have illnesses outside these 41.

## 1. Naive Bayes on the held-out test set

| Metric | Value |
| --- | --- |
| Test rows (deduplicated data, 20 % stratified split) | {len(y_test)} |
| Accuracy | {acc:.4f} |
| Macro F1 | {f1:.4f} |

Misclassified test rows: {'; '.join(f'{t} → {p} ({n})' for t, p, n in errors) or 'none'}.
Confusion matrix: `ml/confusion_matrix.png`.

## 2. Department accuracy: old keyword scorer vs new method

Cases are written as text from held-out rows, e.g. "itching, skin rash and nodal skin eruptions".
Negation cases have two real symptoms and three negated symptoms typical of one illness in another
department ("no a, no b, no c, but x and y"). The correct department comes from the illness via `ml/disease_dept.py`.

### Standard cases ({len(standard)})
{table([(l, f'{c}/{t}', f'{a:.1%}') for l, c, t, a in sections['Standard cases']], ['Method', 'Correct', 'Accuracy'])}

### Negation cases ({len(negation)})
{table([(l, f'{c}/{t}', f'{a:.1%}') for l, c, t, a in sections['Negation cases']], ['Method', 'Correct', 'Accuracy'])}

### All cases ({len(standard) + len(negation)})
{table([(l, f'{c}/{t}', f'{a:.1%}') for l, c, t, a in sections['All cases']], ['Method', 'Correct', 'Accuracy'])}

New method statuses over all cases: {', '.join(f'{k} {v}' for k, v in statuses.items())}.

**Reading these numbers fairly.**
- The test texts use the dataset's own symptom names, which the Naive Bayes model knows exactly but the
  old keyword list mostly does not (only 13 of the 131 dataset symptoms are among its keywords), so the
  comparison favours the new method.
- The "correct" department is defined by the same disease → department map the new method uses. If
  that map is wrong for an illness, the new method is still scored as right. The map needs review by a
  medical professional.
- The old scorer answers General Medicine when it recognises no keyword; {old_default_hits} of its
  {old_correct} correct answers are that default landing on an illness mapped to General Medicine.
- The "without negation detection" row shows what the negation step adds: negated misleading symptoms
  are otherwise counted as present. On the negation cases it lifts Naive Bayes from
  {neg_rows[3][1]}/{neg_rows[3][2]} to {neg_rows[1][1]}/{neg_rows[1][2]}.
- The negation cases keep only two real symptoms, so several are genuinely ambiguous (for example
  "nausea and sweating" for Malaria); those failures come from too little information, not from
  negation handling.

## 3. Negation detection

{neg_passed} of {neg_total} unit tests passed ({neg_passed / neg_total:.0%}).
{chr(10).join(neg_failures)}

## 4. TOPSIS doctor ranking — weight sensitivity

Worked example (A, B, C; free hours = benefit, caseload = cost, experience = benefit).
The project's Doctor model has no experience field, so the live ranking uses free hours and caseload
with weights 0.5 / 0.5 (the default 0.4 / 0.4 renormalised).

{table(sens_rows, ['Weights (free / caseload / experience)', 'A', 'B', 'C', 'Ranking'])}

## 5. Training details

{training_body}

## 6. Items that need review

- Disease → department map (`ml/disease_dept.py`), especially: {', '.join(UNCERTAIN)}.
- TOPSIS weights (`DEFAULT_WEIGHTS` in `ml/topsis.py`) and the assumed 30 minutes per appointment
  (`APPOINTMENT_HOURS` in `apps/recommendations/smart_views.py`).
- Confidence threshold 40 % (`MIN_DEPARTMENT_PROBABILITY`) and minimum of 2 symptoms (`MIN_SYMPTOMS`)
  in `ml/symptom_model.py`.

## Appendix: every case

{table(case_rows, ['#', 'Type', 'Text', 'Illness', 'Correct dept', 'Old', 'New (NB)', 'New system', 'OK'])}
""", encoding='utf-8')
    print(f'\nWrote {RESULTS.relative_to(ML_DIR.parent)}')


if __name__ == '__main__':
    main()
