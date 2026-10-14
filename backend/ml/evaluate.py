"""Evaluate the smart symptom check on the DDXPlus TEST split and write ml/RESULTS.md.

Run from backend/:   python -m ml.evaluate      (after ml.ddxplus_adapter for both splits and ml.train_model)

1. The model on ml/data/test/ddxplus_binary.csv (never on training rows): accuracy,
   top-3 accuracy, macro F1 and department accuracy, also on test rows whose exact
   symptom pattern does not occur in the training split.
2. The whole text pipeline on short descriptions written from test rows (3 symptoms
   each, as a user would type them): statuses, department accuracy, and the old keyword
   scorer for comparison.
3. Negation unit-test pass rate.  4. TOPSIS weight sensitivity (unchanged worked example).
DDXPlus is SYNTHETIC: these figures say how well the model fits the generator, not real patients.
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
from sklearn.metrics import accuracy_score, f1_score  # noqa: E402

from apps.recommendations.views import match_department  # noqa: E402  (old keyword scorer)
from ml import symptom_model, test_negation  # noqa: E402
from ml.disease_dept import UNCERTAIN, department_for  # noqa: E402
from ml.schema import get as get_schema  # noqa: E402
from ml.sensitivity import BENEFIT as SENS_BENEFIT, MATRIX as SENS_MATRIX, WEIGHT_SETS  # noqa: E402
from ml.topsis import topsis  # noqa: E402
from ml.ddxplus_adapter import PAIN_LOCATION  # noqa: E402
from ml.train_model import N_ESTIMATORS, PAIN, TARGET, TRAIN_PATH  # noqa: E402

ML_DIR = Path(__file__).resolve().parent
RESULTS = ML_DIR / 'RESULTS.md'
TEST_PATH = ML_DIR / 'data' / 'test' / 'ddxplus_binary.csv'
N_TEXT_CASES = 300
SYMPTOMS_PER_TEXT = 3
SEED = 42


def as_text(symptoms: list[str]) -> str:
    """['fever', 'cough', 'sore throat'] → 'fever, cough and sore throat'."""
    if len(symptoms) == 1:
        return symptoms[0]
    return ', '.join(symptoms[:-1]) + ' and ' + symptoms[-1]


def model_metrics(model, X, y) -> dict:
    proba = model.predict_proba(X)
    order = np.argsort(-proba, axis=1)
    classes = model.classes_
    pred = classes[order[:, 0]]
    top3 = np.array([y.iloc[i] in classes[order[i, :3]] for i in range(len(y))])
    dept_true = y.map(department_for).to_numpy()
    dept_pred = np.array([department_for(p) for p in pred])
    return {'rows': len(y), 'accuracy': accuracy_score(y, pred), 'top3': top3.mean(),
            'macro_f1': f1_score(y, pred, average='macro', zero_division=0),
            'dept_accuracy': (dept_true == dept_pred).mean(), 'pred': pred}


def text_cases(test: pd.DataFrame, schema) -> list[dict]:
    """Short descriptions from random test rows: 3 of the row's yes/no symptoms, by label."""
    # Yes/no symptoms, including pain regions ("headache"); bare "pain" is left out when the row
    # has a region, since people type "headache", not "pain and headache".
    askable = [s.name for s in schema.symptoms if s.data_type == 'B' and not s.antecedent]
    regions = [s.name for s in schema.symptoms if s.parent == PAIN_LOCATION]

    def typed(i):
        present = [c for c in askable if test.iloc[i][c] == 1]
        return [c for c in present if c != PAIN] if set(present) & set(regions) else present

    rng = random.Random(SEED)
    rows = [i for i in range(len(test)) if len(typed(i)) >= SYMPTOMS_PER_TEXT]
    cases = []
    for i in rng.sample(rows, min(N_TEXT_CASES, len(rows))):
        present = typed(i)
        chosen = rng.sample(present, SYMPTOMS_PER_TEXT)
        illness = test.iloc[i][TARGET]
        cases.append({'text': as_text([schema.label(c) for c in chosen]), 'illness': illness,
                      'correct': department_for(illness)})
    for c in cases:
        r = symptom_model.predict(c['text'])
        c['status'] = r['status']
        c['new'] = r.get('department') if r['status'] in ('ok', 'emergency') else None
        c['top3'] = c['illness'] in [i['name'] for i in r.get('illnesses', [])]
        c['old'] = match_department(c['text'])
        c['shipped'] = c['new'] or c['old']                     # non-ok → keyword fallback
    return cases


def table(rows, header):
    lines = ['| ' + ' | '.join(header) + ' |', '| ' + ' | '.join('---' for _ in header) + ' |']
    lines += ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in rows]
    return '\n'.join(lines)


def spread(counts: pd.Series) -> str:
    return f'{counts.min()} / {int(counts.median())} / {counts.max()}'


def main():
    if not symptom_model.load():
        raise SystemExit('ml/symptom_model.joblib is missing: run python -m ml.train_model first.')
    artifact = joblib.load(symptom_model.MODEL_PATH)
    model, columns = artifact['model'], artifact['symptoms']
    schema = get_schema()
    train = pd.read_csv(TRAIN_PATH)
    test = pd.read_csv(TEST_PATH)
    if list(test.columns) != columns + [TARGET]:
        raise SystemExit('The test split does not follow the schema: rerun ml.ddxplus_adapter with the same flags.')

    # 1. The model on the test split.
    X, y = test[columns], test[TARGET]
    full = model_metrics(model, X, y)
    seen = pd.util.hash_pandas_object(test, index=False).isin(pd.util.hash_pandas_object(train, index=False)).to_numpy()
    unseen = model_metrics(model, X[~seen], y[~seen])
    print(f'1. Random Forest on {full["rows"]} test rows: accuracy {full["accuracy"]:.4f}, '
          f'top-3 {full["top3"]:.4f}, macro F1 {full["macro_f1"]:.4f}, department {full["dept_accuracy"]:.4f}')
    print(f'   {seen.sum()} test rows also occur in the training split; on the {unseen["rows"]} unseen rows: '
          f'accuracy {unseen["accuracy"]:.4f}, top-3 {unseen["top3"]:.4f}')
    per_class = (pd.DataFrame({'y': y, 'ok': full['pred'] == y}).groupby('y')['ok'].agg(['mean', 'size'])
                 .sort_values('mean'))

    # 2. Text pipeline.
    cases = text_cases(test, schema)
    statuses = Counter(c['status'] for c in cases)
    n = len(cases)
    acc = {k: sum(c[k] == c['correct'] for c in cases) for k in ('new', 'shipped', 'old')}
    ok_cases = [c for c in cases if c['status'] == 'ok']
    ok_acc = sum(c['new'] == c['correct'] for c in ok_cases) / len(ok_cases) if ok_cases else 0.0
    ok_top3 = sum(c['top3'] for c in ok_cases) / len(ok_cases) if ok_cases else 0.0
    print(f'2. Text pipeline on {n} three-symptom descriptions: statuses {dict(statuses)}')
    print(f'   department: smart only {acc["new"]}/{n}, as shipped {acc["shipped"]}/{n}, keyword {acc["old"]}/{n}; '
          f'"ok" results {ok_acc:.1%} department, {ok_top3:.1%} illness in top 3')

    # 3. Negation tests.
    neg_passed, neg_total, _ = test_negation.run()
    print(f'3. Negation tests: {neg_passed} of {neg_total} passed')

    # 4. TOPSIS sensitivity (worked example, unchanged).
    sens_rows = []
    for label, weights in WEIGHT_SETS.items():
        scores = topsis(SENS_MATRIX, weights, SENS_BENEFIT)
        ranking = ' > '.join('ABC'[i] for i in np.argsort(-scores, kind='stable'))
        sens_rows.append((label, *(f'{s:.3f}' for s in scores), ranking))

    train_counts, test_counts = train[TARGET].value_counts(), test[TARGET].value_counts()
    worst = per_class.head(8)
    RESULTS.write_text(f"""# Smart symptom check — evaluation results

Generated by `python -m ml.evaluate`. Model: `RandomForestClassifier` ({N_ESTIMATORS} trees),
{len(columns)} symptom columns, {len(artifact['classes'])} illnesses.

> **The data is synthetic.** Symptoms and illnesses come from DDXPlus (Fansi Tchango et al.,
> NeurIPS 2022, CC-BY), a dataset of *simulated* patients generated from a medical knowledge base.
> These figures say how well the model reproduces that generator. They are **not** evidence of
> accuracy on real patients, and the tool must not be used for diagnosis.

## 1. Model on the DDXPlus test split

Evaluated on `ml/data/test/ddxplus_binary.csv` (from `release_test_patients`), never on training rows.
Each test row is a full DDXPlus questionnaire (every symptom answered yes or no).

| Rows | Accuracy | Top-3 accuracy | Macro F1 | Department accuracy |
| --- | --- | --- | --- | --- |
| All {full['rows']} test rows | {full['accuracy']:.4f} | {full['top3']:.4f} | {full['macro_f1']:.4f} | {full['dept_accuracy']:.4f} |
| {unseen['rows']} rows whose symptom pattern is not in the training split | {unseen['accuracy']:.4f} | {unseen['top3']:.4f} | {unseen['macro_f1']:.4f} | {unseen['dept_accuracy']:.4f} |

{int(seen.sum())} of the {full['rows']} test rows have exactly the same symptoms and illness as a training
row: the synthetic generator repeats patterns across splits. The second line is the fairer figure.

Department accuracy = the department of the predicted illness equals the department of the true
illness (map: `ml/data/disease_dept.json`, provisional).

Illnesses with the lowest accuracy:

{table([(name, f"{r['mean']:.2f}", int(r['size'])) for name, r in worst.iterrows()], ['Illness', 'Accuracy', 'Test rows'])}

## 2. Whole pipeline on typed descriptions

{n} descriptions written from random test rows, each naming {SYMPTOMS_PER_TEXT} of the row's symptoms by label
(e.g. "{cases[0]['text'] if cases else ''}"), run through text matching → red flags → Random Forest.
Users type a few symptoms, not a {len(columns)}-item questionnaire, so this is much harder than section 1.

Statuses: {', '.join(f'{k} {v}' for k, v in statuses.most_common())}.

| Method | Correct department | Accuracy |
| --- | --- | --- |
| Smart check only (non-ok counted as wrong; emergency = Emergency Medicine) | {acc['new']}/{n} | {acc['new'] / n:.1%} |
| As shipped (non-ok → keyword checker) | {acc['shipped']}/{n} | {acc['shipped'] / n:.1%} |
| Old keyword checker | {acc['old']}/{n} | {acc['old'] / n:.1%} |
| Smart check, "ok" results only | {sum(c['new'] == c['correct'] for c in ok_cases)}/{len(ok_cases)} | {ok_acc:.1%} |

On "ok" results the true illness is in the top three {ok_top3:.1%} of the time. Follow-up
questions (information gain) are not used here; each description is a single request.

## 3. Negation detection

{neg_passed} of {neg_total} negation unit tests pass (`ml/test_negation.py`).

## 4. TOPSIS doctor ranking — weight sensitivity

Worked example (A, B, C; free hours = benefit, caseload = cost, experience = benefit).

{table(sens_rows, ['Weights (free / caseload / experience)', 'A', 'B', 'C', 'Ranking'])}

## 5. Data

| | Training split | Test split |
| --- | --- | --- |
| Source file | `release_validate_patients` (see note) | `release_test_patients` |
| Rows after removing duplicates and capping per illness | {len(train)} | {len(test)} |
| Rows per illness (min / median / max) | {spread(train_counts)} | {spread(test_counts)} |

- Columns: the {len(columns)} DDXPlus symptoms (no history items, no demographics); categorical and
  multi-choice answers collapsed to present/absent (absent = the evidence's default value).
- **Training used the DDXPlus validation split** because `release_train_patients` was not available.
  When it is, rerun `python -m ml.ddxplus_adapter --split train` and `python -m ml.train_model`.
- Removing duplicates leaves few distinct patterns for some illnesses (as few as {train_counts.min()}),
  so the per-illness cap cannot make the classes balanced.
- Follow-up details always present with their parent question are filled in with it at
  prediction time: {', '.join(f'{c} → {p}' for c, p in artifact['implied'].items())}.
- Pain location is also split into {sum(x.parent == PAIN_LOCATION for x in get_schema().symptoms)} body-region columns (headache, chest pain,
  stomach pain...; `PAIN_REGIONS` in `ml/ddxplus_adapter.py`), so typed pain keeps its location.
- "pain" is filled in for symptoms that come with it in nearly every training row
  (DDXPlus asks it as a gate question): {', '.join(sorted(get_schema().label(c) for c in artifact.get('gated', {}) if get_schema().symptom(c).parent != PAIN_LOCATION)) or 'none'}.

## 6. Items that need review

- **Department map** (`ml/data/disease_dept.json`) is provisional, in particular:
  {'; '.join(f'{k}: {v}' for k, v in UNCERTAIN.items())}.
- **Red-flag rules** (`ml/red_flags.py`) and **symptom labels** (`ml/data/ddxplus_labels.json`).
- **Synonyms** (`ml/data/symptom_synonyms.json`): machine-drafted, every entry marked "needs review";
  Nepali and Romanised Nepali phrases still to be added.
- Confidence threshold {symptom_model.MIN_DEPARTMENT_PROBABILITY:.0%} (`MIN_DEPARTMENT_PROBABILITY`) and minimum
  of {symptom_model.MIN_SYMPTOMS} symptoms (`MIN_SYMPTOMS`) in `ml/symptom_model.py`.
- TOPSIS weights and the assumed 30 minutes per appointment.

## Appendix: the first 30 typed descriptions

{table([(i + 1, c['text'], c['illness'], c['correct'], c['status'], c['new'] or '—', c['old'], '✓' if c['shipped'] == c['correct'] else '✗')
        for i, c in enumerate(cases[:30])], ['#', 'Text', 'Illness', 'Correct dept', 'Status', 'Smart', 'Keyword', 'Shipped OK'])}
""", encoding='utf-8')
    print(f'\nWrote {RESULTS.relative_to(ML_DIR.parent)}')


if __name__ == '__main__':
    main()
