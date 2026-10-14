"""Diagnostics for the symptom model: data, features and predictions (read-only).

Run from backend/:
    python -m ml.diagnose counts                         rows per illness: DDXPlus patients vs training rows,
                                                         symptoms per row, duplicate patterns
    python -m ml.diagnose contain fever nausea dizziness illnesses whose training rows have these symptoms
                                                         (each one, and all together)
    python -m ml.diagnose importance [N]                 the forest's N most important symptoms (default 20)
    python -m ml.diagnose predict "fever, cough and sore throat" ["..."]
                                                         the full pipeline, plus the forest's raw probabilities
                                                         before the prevalence correction
    python -m ml.diagnose match "rashes, swelling, itchy, redness" ["..."]
                                                         how each word was matched: exact / synonym / lemma /
                                                         fuzzy (score, phrase it resembled) / suggestion /
                                                         unrecognised, plus phrase red flags
    python -m ml.diagnose balance                        class balance: training rows, class weight, weighted
                                                         share, DDXPlus prevalence and the prior factor per illness
    python -m ml.diagnose calibration                    reliability table on the TEST split (short descriptions
                                                         built from test patients): stated confidence vs how often
                                                         the top illness is right, raw vs calibrated
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from ml import symptom_model
from ml.schema import get as get_schema
from ml.train_model import PREVALENCE_PATH, TARGET, TRAIN_PATH


def _training() -> tuple[pd.DataFrame, pd.Series]:
    data = pd.read_csv(TRAIN_PATH)
    return data.drop(columns=[TARGET]), data[TARGET]


def _codes(labels: list[str]) -> list[str]:
    by_label = {label: name for name, label in get_schema().labels().items()}
    unknown = [label for label in labels if label not in by_label]
    if unknown:
        raise SystemExit(f'Not symptom labels: {unknown}. Labels are in ml/data/symptom_schema.json.')
    return [by_label[label] for label in labels]


def counts() -> None:
    import json
    X, y = _training()
    table = pd.DataFrame({'train_rows': y.value_counts()})
    table['train_%'] = (100 * table.train_rows / len(y)).round(2)
    try:
        with open(PREVALENCE_PATH, encoding='utf-8') as fh:
            raw = pd.Series(json.load(fh)['counts'])
        table['patients_%'] = (100 * raw / raw.sum()).round(2)
        table['inflation'] = (table['train_%'] / table['patients_%']).round(2)
    except OSError:
        print(f'({PREVALENCE_PATH.name} missing: rerun ml.ddxplus_adapter for the prevalence columns)')
    table['symptoms_per_row'] = X.sum(axis=1).groupby(y).mean().round(1)
    table['duplicate_rows'] = table.index.map(lambda c: int(X[y == c].duplicated().sum()))
    print(f'{len(y)} training rows, {y.nunique()} illnesses, {X.shape[1]} columns; '
          f'symptoms per row: mean {X.sum(axis=1).mean():.1f}')
    print('inflation = share of training rows / share of DDXPlus patients (>1: over-represented)\n')
    print(table.sort_values('train_rows', ascending=False).to_string())


def contain(labels: list[str]) -> None:
    X, y = _training()
    codes = _codes(labels)
    sizes = y.value_counts()
    for label, code in zip(labels, codes):
        with_it = y[X[code] == 1].value_counts()
        share = (with_it / sizes[with_it.index]).round(2)
        print(f'\n{label} ({code}): {int(X[code].sum())} rows, {len(with_it)} illnesses')
        print(pd.DataFrame({'rows': with_it, 'share_of_illness': share}).head(10).to_string())
    together = X[codes].all(axis=1)
    print(f'\nALL of {labels}: {int(together.sum())} rows')
    if together.any():
        print(y[together].value_counts().head(10).to_string())


def importance(n: int = 20) -> None:
    symptom_model.load()
    model, columns = symptom_model._model, symptom_model._columns
    labels = get_schema().labels()
    ranked = pd.Series(model.feature_importances_, index=[labels.get(c, c) for c in columns])
    print(ranked.sort_values(ascending=False).head(n).round(4).to_string())


def predict(texts: list[str]) -> None:
    symptom_model.load()
    model, columns = symptom_model._model, symptom_model._columns
    for text in texts:
        analysis = symptom_model.analyse(text)
        expanded = symptom_model.expand(set(analysis.present)) - set(analysis.negated)
        r = symptom_model.predict(text)
        print(f'\n"{text}"')
        print(f'  symptoms {r["symptoms"]}  negated {r["negated"]}  unrecognised {r["unrecognized"]}')
        print(f'  training rows with all of them: {symptom_model.support(expanded)}')
        if analysis.present:
            raw = symptom_model._probabilities(model, columns, expanded)
            top = np.argsort(-raw)[:3]
            print('  forest, before prevalence:', ', '.join(f'{model.classes_[i]} {raw[i]:.2f}' for i in top))
            final = symptom_model._probabilities(model, columns, expanded, symptom_model._prior,
                                                 symptom_model._temperature)
            top = np.argsort(-final)[:3]
            print('  calibrated, with prevalence:', ', '.join(f'{model.classes_[i]} {final[i]:.2f}' for i in top))
        print(f'  status {r["status"]}' + (f' ({r["reason"]})' if r.get('reason') else ''))
        if r['status'] == 'ok':
            print('  illnesses:', ', '.join(f'{i["name"]} {i["probability"]:.2f}' for i in r['illnesses']))
            print(f'  department: {r["department"]} {r["dept_probability"]:.2f}  {r["departments"]}')
        if r.get('question'):
            print(f'  follow-up question: {r["question"]["text"]}')


def match(texts: list[str]) -> None:
    from ml import red_flags
    symptom_model.load()
    for text in texts:
        a = symptom_model.analyse(text)
        print(f'\n"{text}"')
        for m in a.matches:
            how = m.method + (f' {m.score:.1f}% like "{m.phrase}"' if m.method == 'fuzzy' else '')
            print(f'  {m.term!r:24} -> {symptom_model._label(m.symptom):24} {how}' + ('  NEGATED' if m.negated else ''))
        for s in a.suggestions:
            print(f'  {s.term!r:24} -> {symptom_model._label(s.symptom) + "?":24} suggestion {s.score:.1f}% '
                  f'like "{s.phrase}" (asked, not sent to the model)')
        for u in a.unrecognized:
            print(f'  {u!r:24} -> unrecognised (not sent to the model)')
        flags = red_flags.check_text(text)
        if flags:
            print('  phrase red flags:', [f.id for f in flags])


def balance() -> None:
    from ml.train_model import prevalence
    symptom_model.load()
    import joblib
    artifact = joblib.load(symptom_model.MODEL_PATH)
    _, y = _training()
    classes = artifact['classes']
    weights = artifact.get('class_weight') or {}
    rates = prevalence(classes) or {}
    table = pd.DataFrame({'rows': y.value_counts().reindex(classes).fillna(0).astype(int)}, index=classes)
    table['class_weight'] = [round(weights.get(c, 1.0), 2) for c in classes]
    mass = table['rows'] * table['class_weight']
    table['weighted_%'] = (100 * mass / mass.sum()).round(2)
    table['patients_%'] = [round(100 * rates.get(c, float('nan')), 2) for c in classes]
    table['prior_x'] = np.round(artifact['prior'], 2)
    table['severity'] = [artifact.get('severity', {}).get(c) for c in classes]
    counts = table['rows']
    print(f'{counts.sum()} rows, {len(classes)} illnesses; rows per illness min {counts.min()}, median '
          f'{int(counts.median())}, max {counts.max()} (imbalance x{counts.max() / max(counts.min(), 1):.0f})')
    print('A balanced set would give every illness about the same rows. prior_x = patients_% / weighted share; '
          'within [1/20, 20] means no factor was clipped.\n')
    print(table.sort_values('rows', ascending=False).to_string())


def calibration(n: int = 3000) -> None:
    from ml.evaluate import TEST_PATH
    from ml.train_model import apply_calibration, expected_calibration_error, partial_rows
    symptom_model.load()
    model, columns = symptom_model._model, symptom_model._columns
    test = pd.read_csv(TEST_PATH)
    test = test[test[TARGET].isin(model.classes_)].sample(n=min(n, len(test)), random_state=42)
    X, y = partial_rows(test[columns].reset_index(drop=True), test[TARGET].reset_index(drop=True), get_schema(),
                        symptom_model._implied, symptom_model._gated, per_row=1)
    index = {c: i for i, c in enumerate(model.classes_)}
    y_index = y.map(index).to_numpy()
    raw = model.predict_proba(X)
    weights = np.ones(len(y_index))
    print(f'{len(y_index)} short descriptions from {len(test)} TEST patients, temperature {symptom_model._temperature:.2f}')
    for name, q in (('forest only', raw),
                    ('+ prevalence', apply_calibration(raw, symptom_model._prior)),
                    ('+ prevalence + temperature', apply_calibration(raw, symptom_model._prior, symptom_model._temperature))):
        top, right = q.max(axis=1), q.argmax(axis=1) == y_index
        print(f'\n{name}: accuracy {right.mean():.3f}, ECE {expected_calibration_error(q, y_index, weights):.3f}')
        print('  stated confidence   rows   top illness right')
        for lo in np.arange(0, 1, 0.1):
            mask = (top >= lo) & (top < lo + 0.1 + (lo >= 0.9))
            if mask.any():
                print(f'  {lo:.1f}-{lo + 0.1:.1f}          {mask.sum():6d}   {right[mask].mean():.2f}')


def main(argv: list[str]) -> None:
    commands = {'counts', 'contain', 'importance', 'predict', 'match', 'balance', 'calibration'}
    if not argv or argv[0] not in commands:
        raise SystemExit(__doc__)
    command, args = argv[0], argv[1:]
    if command == 'match':
        return match(args)
    if command == 'balance':
        return balance()
    if command == 'calibration':
        return calibration()
    if command == 'counts':
        counts()
    elif command == 'contain':
        contain(args)
    elif command == 'importance':
        importance(int(args[0]) if args else 20)
    else:
        predict(args)


if __name__ == '__main__':
    main(sys.argv[1:])
