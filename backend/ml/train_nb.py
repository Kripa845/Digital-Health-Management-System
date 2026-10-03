"""Train the Bernoulli Naive Bayes symptom → illness model (offline; not part of any request).

Run from backend/:   python -m ml.train_nb

Writes:
  ml/nb_model.joblib          (model, symptom_columns)            — loaded once by the server
  ml/test_set.joblib          (X_test, y_test, symptom_columns)   — used by ml/evaluate.py
  ml/confusion_matrix.png     confusion matrix heatmap (deduplicated model)
  ml/TRAINING_RESULTS.md      metrics with and without deduplication, and why they differ
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import joblib
import matplotlib
matplotlib.use('Agg')                      # no window; write the PNG only
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import BernoulliNB

ML_DIR = Path(__file__).resolve().parent
DATA = ML_DIR / 'data' / 'dataset.csv'
MODEL_PATH = ML_DIR / 'nb_model.joblib'
TEST_SET_PATH = ML_DIR / 'test_set.joblib'
CONFUSION_PNG = ML_DIR / 'confusion_matrix.png'
RESULTS_PATH = ML_DIR / 'TRAINING_RESULTS.md'

PROJECT_DATA = ML_DIR.parent / 'apps' / 'recommendations' / 'data'
TEST_SIZE = 0.2
RANDOM_STATE = 42


def clean_symptom(name) -> str:
    """'  skin_rash' → 'skin rash'; 'spotting_ urination' → 'spotting urination'."""
    return ' '.join(str(name).strip().replace('_', ' ').split())


def load_one_hot() -> tuple[pd.DataFrame, pd.Series, int]:
    """One 0/1 column per symptom; returns (X, y, exact text duplicates in the raw file)."""
    raw = pd.read_csv(DATA)
    exact_duplicates = int(raw.duplicated().sum())
    symptom_cols = [c for c in raw.columns if c.lower().startswith('symptom')]
    diseases = raw['Disease'].astype(str).str.strip()
    rows = [
        {clean_symptom(v): 1 for v in raw.loc[i, symptom_cols] if pd.notna(v) and str(v).strip()}
        for i in raw.index
    ]
    X = pd.DataFrame(rows).fillna(0).astype(np.int8)
    X = X[sorted(X.columns)]
    return X, diseases.rename('Disease'), exact_duplicates


def split(X, y, label: str):
    try:
        return train_test_split(X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y)
    except ValueError as exc:
        # A class with a single row cannot be stratified.
        print(f'[{label}] Stratified split failed ({exc}); falling back to a random split.')
        return train_test_split(X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE)


def fit_and_score(X, y, label: str):
    X_train, X_test, y_train, y_test = split(X, y, label)
    model = BernoulliNB(alpha=1.0)
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred, average='macro', zero_division=0)
    overlap = len(pd.merge(
        pd.concat([X_test, y_test], axis=1).drop_duplicates(),
        pd.concat([X_train, y_train], axis=1).drop_duplicates(), how='inner'))
    return model, X_train, X_test, y_train, y_test, y_pred, acc, f1, overlap


def project_vocabulary() -> tuple[set, set]:
    with open(PROJECT_DATA / 'symptom_severity.csv', encoding='utf-8') as fh:
        severity = {clean_symptom(r['Symptom']).lower() for r in csv.DictReader(fh) if r.get('Symptom')}
    with open(PROJECT_DATA / 'symptom_department_map.json', encoding='utf-8') as fh:
        rules = json.load(fh)['department_rules']
    keywords = {clean_symptom(k).lower() for kws in rules.values() for k in kws}
    return severity, keywords


def save_confusion_png(y_test, y_pred, labels):
    cm = confusion_matrix(y_test, y_pred, labels=labels)
    fig, ax = plt.subplots(figsize=(18, 16))
    im = ax.imshow(cm, cmap='Blues')
    ax.set_xticks(range(len(labels)), labels=labels, rotation=90, fontsize=7)
    ax.set_yticks(range(len(labels)), labels=labels, fontsize=7)
    ax.set_xlabel('Predicted illness')
    ax.set_ylabel('True illness')
    ax.set_title('Bernoulli Naive Bayes — confusion matrix (held-out test set, deduplicated data)')
    for i in range(len(labels)):
        for j in range(len(labels)):
            if cm[i, j]:
                ax.text(j, i, cm[i, j], ha='center', va='center', fontsize=6,
                        color='white' if cm[i, j] > cm.max() / 2 else 'black')
    fig.colorbar(im, ax=ax, fraction=0.03)
    fig.tight_layout()
    fig.savefig(CONFUSION_PNG, dpi=120)
    plt.close(fig)


def main():
    X_all, y_all, exact_duplicates = load_one_hot()
    print(f'Loaded {len(X_all)} rows, {y_all.nunique()} diseases, {X_all.shape[1]} distinct symptoms.')
    print(f'Exact duplicate rows in the raw file: {exact_duplicates}')

    # Deduplicate BEFORE splitting: same disease and same set of symptoms = same example.
    combined = pd.concat([X_all, y_all], axis=1)
    deduped = combined.drop_duplicates().reset_index(drop=True)
    removed = len(combined) - len(deduped)
    print(f'Duplicate rows removed (same disease + same symptom set): {removed} '
          f'({len(combined)} -> {len(deduped)} rows)')
    X, y = deduped.drop(columns='Disease'), deduped['Disease']
    per_class = y.value_counts()
    print(f'Rows per disease after deduplication: min {per_class.min()}, max {per_class.max()}')

    # Main model: deduplicated data.
    model, X_train, X_test, y_train, y_test, y_pred, acc, f1, _ = fit_and_score(X, y, 'deduplicated')
    print(f'\n=== Deduplicated data: {len(X_train)} train / {len(X_test)} test rows ===')
    print(f'Accuracy: {acc:.4f}')
    print(f'Macro F1: {f1:.4f}')
    report = classification_report(y_test, y_pred, zero_division=0)
    print(report)

    # Comparison: the same procedure on the raw (duplicated) data.
    _, Xr_train, Xr_test, *_rest = fit_and_score(X_all, y_all, 'raw')
    raw_acc, raw_f1, raw_overlap = _rest[-3], _rest[-2], _rest[-1]
    print(f'=== Without deduplication: {len(Xr_train)} train / {len(Xr_test)} test rows ===')
    print(f'Accuracy: {raw_acc:.4f}   Macro F1: {raw_f1:.4f}')
    print(f'Test rows that also appear in the training set: {raw_overlap} distinct patterns '
          f'(of {len(Xr_test.drop_duplicates())} distinct test patterns)')

    labels = sorted(y.unique())
    save_confusion_png(y_test, y_pred, labels)
    joblib.dump((model, list(X.columns)), MODEL_PATH)
    joblib.dump((X_test, y_test, list(X.columns)), TEST_SET_PATH)
    print(f'\nSaved model -> {MODEL_PATH.name}, test set -> {TEST_SET_PATH.name}, heatmap -> {CONFUSION_PNG.name}')

    # Vocabulary comparison with the project's own symptom lists.
    model_vocab = {c.lower() for c in X.columns}
    severity, keywords = project_vocabulary()
    only_model = sorted(model_vocab - severity)
    only_severity = sorted(severity - model_vocab)
    in_keywords = sorted(model_vocab & keywords)
    print(f'\nVocabulary: model {len(model_vocab)} symptoms | severity table {len(severity)} | '
          f'keyword file {len(keywords)}')
    print(f'  In the model but not in the severity table ({len(only_model)}): {only_model}')
    print(f'  In the severity table but not in the model ({len(only_severity)}): {only_severity}')
    print(f'  Model symptoms that are also department keywords: {len(in_keywords)} of {len(model_vocab)}')

    RESULTS_PATH.write_text(f"""# Naive Bayes training results

Generated by `python -m ml.train_nb`. Model: `BernoulliNB(alpha=1.0)`, 80/20 split,
`random_state={RANDOM_STATE}`, stratified by disease.

## Data

| | Rows |
| --- | --- |
| Raw file | {len(combined)} |
| Exact duplicate rows in the raw file | {exact_duplicates} |
| Removed as duplicates (same disease + same symptom set) | {removed} |
| Unique rows used | {len(deduped)} ({y.nunique()} diseases, {per_class.min()}–{per_class.max()} rows each) |
| Distinct symptoms (0/1 columns) | {X.shape[1]} |

## Accuracy with and without deduplication

| Data | Train / test rows | Accuracy | Macro F1 |
| --- | --- | --- | --- |
| Deduplicated (used by the app) | {len(X_train)} / {len(X_test)} | {acc:.4f} | {f1:.4f} |
| Not deduplicated | {len(Xr_train)} / {len(Xr_test)} | {raw_acc:.4f} | {raw_f1:.4f} |

**Why they differ.** {removed} of the {len(combined)} rows are repeats of the same disease with the same
symptoms. Without deduplication, a random split puts copies of the same row on both sides: of the
{len(Xr_test.drop_duplicates())} distinct symptom patterns in that test set, {raw_overlap} also occur in its
training set, so the model is largely tested on examples it has already seen and the score measures
memory rather than generalisation. Deduplicating first means every test row is a symptom combination
the model has never seen, which is the honest figure. Even so, this Kaggle dataset is very clean and
synthetic-looking (each disease has a small fixed symptom list), so both numbers are far higher than
real-world performance would be.

## Classification report (deduplicated, held-out test set)

```
{report}```

Confusion matrix: `ml/confusion_matrix.png`.

## Symptom vocabulary vs the project's lists

- Model: {len(model_vocab)} symptoms; project severity table: {len(severity)}; keyword file: {len(keywords)}.
- In the model but not in the severity table ({len(only_model)}): {', '.join(only_model) or 'none'}
- In the severity table but not in the model ({len(only_severity)}): {', '.join(only_severity) or 'none'}
- Model symptoms that are also department keywords: {len(in_keywords)} of {len(model_vocab)}
""", encoding='utf-8')
    print(f'Wrote {RESULTS_PATH.name}')


if __name__ == '__main__':
    main()
