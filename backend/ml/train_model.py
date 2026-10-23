
from __future__ import annotations

import json
import random
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from ml.disease_dept import check_classes
from ml.schema import SchemaError, get as get_schema

ML_DIR = Path(__file__).resolve().parent
TRAIN_PATH = ML_DIR / 'data' / 'train' / 'ddxplus_binary.csv'
PREVALENCE_PATH = TRAIN_PATH.parent / 'prevalence.json'   # written by ml/ddxplus_adapter.py
CONDITIONS_PATH = ML_DIR / 'data' / 'ddxplus' / 'release_conditions.json'   # DDXPlus severity (optional)
MODEL_PATH = ML_DIR / 'symptom_model.joblib'
TARGET = 'prognosis'
RANDOM_STATE = 42
N_ESTIMATORS = 50
MIN_SAMPLES_LEAF = 3    # no leaf holds a single memorised row (smoother, less over-confident probabilities)
PARTIAL_PER_ROW = 6     # partial copies of each training row (see partial_rows())
PARTIAL_MAX = 5         # at most this many typed symptoms kept in a partial copy
PRIOR_CAP = 20          # class_prior() factors are kept within [1/20, 20]
WEIGHT_CAP = 20         # class_weights() are kept within [1/20, 20] (laryngospasm has 1 row: x300 uncapped)
CALIBRATION_SHARE = 0.2  # patients held out to fit the temperature (illnesses with >= 5 rows)
PROBABILITY_FLOOR = 1e-4  # added before the temperature so a 0 from the forest stays finite
IMPLIED_MIN = 0.99      # a follow-up present with at least 99% of its parent's rows is filled in with it
PAIN = 'E_53'           # "pain somewhere": the DDXPlus gate question for every pain detail
GATED_MIN = 0.98        # "pain" is filled in for symptoms that come with it in at least 98% of rows
GATED_MIN_ROWS = 30


def make_model(class_weight: dict[str, float] | None = None):
    from sklearn.ensemble import RandomForestClassifier
    # class_weight evens out the training rows; on its own it would push the forest towards
    # rare illnesses (Ebola, Chagas), so class_prior() always puts the prevalence back.
    return RandomForestClassifier(n_estimators=N_ESTIMATORS, min_samples_leaf=MIN_SAMPLES_LEAF,
                                  class_weight=class_weight, random_state=RANDOM_STATE, n_jobs=-1)


def class_weights(y: pd.Series, cap: float = WEIGHT_CAP) -> dict[str, float]:
    """sklearn's "balanced" weights (n_rows / (n_classes x rows of the class)), kept within [1/cap, cap]."""
    counts = y.value_counts()
    balanced = len(y) / (len(counts) * counts)
    return {str(c): float(np.clip(w, 1 / cap, cap)) for c, w in balanced.items()}


def apply_calibration(p: np.ndarray, prior: np.ndarray | None, temperature: float = 1.0) -> np.ndarray:
    """Forest probabilities (rows x classes, or one row) → calibrated, prevalence-corrected
    probabilities: p^(1/T) x prior, renormalised. T > 1 softens over-confident probabilities."""
    p = np.asarray(p, dtype=float)
    if temperature != 1.0:
        p = (p + PROBABILITY_FLOOR) ** (1.0 / temperature)
    if prior is not None:
        p = p * prior
    total = p.sum(axis=-1, keepdims=True)
    return np.divide(p, total, out=np.zeros_like(p), where=total > 0)


def _log_loss(q: np.ndarray, y_index: np.ndarray, weights: np.ndarray) -> float:
    picked = np.clip(q[np.arange(len(y_index)), y_index], 1e-12, 1.0)
    return float(-(weights * np.log(picked)).sum() / weights.sum())


def expected_calibration_error(q: np.ndarray, y_index: np.ndarray, weights: np.ndarray, bins: int = 10) -> float:
    """Weighted gap between the top probability and how often the top illness is right, over 10 bins."""
    top = q.max(axis=1)
    right = (q.argmax(axis=1) == y_index).astype(float)
    edges = np.minimum((top * bins).astype(int), bins - 1)
    ece = 0.0
    for b in range(bins):
        mask = edges == b
        if mask.any():
            w = weights[mask]
            ece += w.sum() * abs(np.average(top[mask], weights=w) - np.average(right[mask], weights=w))
    return float(ece / weights.sum())


def fit_temperature(p: np.ndarray, y_index: np.ndarray, prior: np.ndarray | None,
                    weights: np.ndarray | None = None) -> tuple[float, dict]:
    """The temperature that minimises the (weighted) log-loss of apply_calibration() on held-out rows."""
    weights = np.ones(len(y_index)) if weights is None else weights
    grid = np.exp(np.linspace(np.log(0.25), np.log(8.0), 61))
    losses = [_log_loss(apply_calibration(p, prior, t), y_index, weights) for t in grid]
    best = float(grid[int(np.argmin(losses))])
    before, after = apply_calibration(p, prior, 1.0), apply_calibration(p, prior, best)
    scores = {'log_loss_before': _log_loss(before, y_index, weights), 'log_loss_after': min(losses),
              'ece_before': expected_calibration_error(before, y_index, weights),
              'ece_after': expected_calibration_error(after, y_index, weights), 'fitted_temperature': best}
    # Kept only when it improves BOTH scores: a lower log-loss bought with a worse ECE (sharper,
    # over-confident mid-range probabilities) is not better calibration.
    if not (scores['log_loss_after'] < scores['log_loss_before'] and scores['ece_after'] < scores['ece_before']):
        best = 1.0
        scores['log_loss_after'], scores['ece_after'] = scores['log_loss_before'], scores['ece_before']
    return best, scores


def severity(path: Path = CONDITIONS_PATH) -> dict[str, int]:
    """DDXPlus severity per illness (1 = most severe), {} when the file is not available."""
    try:
        with open(path, encoding='utf-8') as fh:
            return {c['cond-name-eng']: int(c['severity']) for c in json.load(fh).values()}
    except OSError:
        return {}


def implied_followups(X: pd.DataFrame, schema) -> dict[str, str]:
    """Follow-up questions (e.g. pain intensity) that are present whenever their parent (pain) is."""
    implied = {}
    for s in schema.symptoms:
        if s.parent and s.parent in X and X[s.parent].sum():
            if X.loc[X[s.parent] == 1, s.name].mean() >= IMPLIED_MIN:
                implied[s.name] = s.parent
    return implied


def pain_gated(X: pd.DataFrame, schema) -> dict[str, str]:
    """Yes/no symptoms that come with "pain" in nearly every row (sore throat → pain)."""
    if PAIN not in X:
        return {}
    gated = {}
    for s in schema.symptoms:
        if s.name == PAIN or s.data_type != 'B' or s.antecedent or s.name not in X:
            continue
        rows = X[s.name] == 1
        if rows.sum() >= GATED_MIN_ROWS and X.loc[rows, PAIN].mean() >= GATED_MIN:
            gated[s.name] = PAIN
    return gated


def symptom_rates(X: pd.DataFrame, y: pd.Series, classes: list[str], symptoms: list[str]) -> np.ndarray:
    """P(symptom present | illness) = (rows with it + 1) / (rows of the illness + 2)."""
    rates = np.empty((len(classes), len(symptoms)))
    for i, illness in enumerate(classes):
        rows = X.loc[y == illness, symptoms]
        rates[i] = (rows.sum().to_numpy() + 1) / (len(rows) + 2)
    return rates


def typed_symptoms(schema) -> tuple[list[str], set[str]]:
    """(symptoms a user can type: yes/no, not history; the pain-region columns)."""
    from ml.ddxplus_adapter import PAIN_LOCATION
    typed = [s.name for s in schema.symptoms if s.data_type == 'B' and not s.antecedent]
    regions = {s.name for s in schema.symptoms if s.parent == PAIN_LOCATION}
    return typed, regions


def partial_rows(X: pd.DataFrame, y: pd.Series, schema, implied: dict[str, str], gated: dict[str, str],
                 per_row: int = PARTIAL_PER_ROW, seed: int = RANDOM_STATE) -> tuple[pd.DataFrame, pd.Series]:
    """Copies of each row keeping 1..PARTIAL_MAX of its typed symptoms, everything else 0,
    then expanded as predict() expands what a user types (parents, "pain", implied follow-ups)."""
    from ml.symptom_model import expand
    typed, regions = typed_symptoms(schema)
    typed = [s for s in typed if s in X]
    index = {c: i for i, c in enumerate(X.columns)}
    rng = random.Random(seed)
    present = X[typed].to_numpy()
    names = np.array(typed)
    rows, labels = [], []
    for i, label in enumerate(y):
        have = list(names[present[i] == 1])
        if set(have) & regions:                 # people type "headache", not "pain"
            have = [s for s in have if s != PAIN]
        if not have:
            continue
        for _ in range(per_row):
            row = np.zeros(len(index), dtype=np.int8)
            chosen = rng.sample(have, rng.randint(1, min(PARTIAL_MAX, len(have))))
            for s in expand(chosen, implied, gated):
                if s in index:
                    row[index[s]] = 1
            rows.append(row)
            labels.append(label)
    return pd.DataFrame(np.array(rows), columns=X.columns), pd.Series(labels, name=y.name)


def prevalence(classes: list[str], path: Path = PREVALENCE_PATH) -> dict[str, float] | None:
    """DDXPlus patients per illness as a share of all patients (None when the file is missing)."""
    try:
        with open(path, encoding='utf-8') as fh:
            counts = json.load(fh)['counts']
    except OSError:
        return None
    total = sum(counts.get(c, 0) for c in classes)
    return {c: counts.get(c, 0) / total for c in classes}


def weighted_share(y: pd.Series, weights: dict[str, float] | None = None) -> pd.Series:
    """Each illness's share of the fitted rows, counting every row with its class weight."""
    mass = y.value_counts() * (pd.Series(weights) if weights else 1.0)
    mass = mass.dropna()
    return mass / mass.sum()


def class_prior(y: pd.Series, classes: list[str], path: Path = PREVALENCE_PATH,
                weights: dict[str, float] | None = None) -> np.ndarray:
    
    try:
        with open(path, encoding='utf-8') as fh:
            counts = json.load(fh)['counts']
    except OSError:
        return np.ones(len(classes))
    share = weighted_share(y, weights)
    total = sum(counts.get(c, 0) for c in classes)
    ratio = np.array([(counts[c] / total) / share[c] if counts.get(c) else 1.0 for c in classes])
    # An illness with a handful of training rows (localized edema: 2) has noisy forest
    # probabilities; an x200 factor would amplify the noise.
    return np.clip(ratio, 1 / PRIOR_CAP, PRIOR_CAP)


def train(path: Path = TRAIN_PATH) -> dict:
    schema = get_schema()
    data = pd.read_csv(path)
    columns = list(schema.columns)
    if list(data.columns) != columns + [TARGET]:
        raise SchemaError(f'{path} does not follow symptom_schema.json column order; rerun ml.ddxplus_adapter.')
    X, y = data[columns], data[TARGET]
    implied, gated = implied_followups(X, schema), pain_gated(X, schema)

    # 1. Calibration: fit on most patients, fit the temperature on the others' partial rows
    #    (short descriptions, like a user's). Partial rows of one patient stay on one side.
    temperature, calibration = calibrate(X, y, schema, implied, gated)

    # 2. The model itself, on every patient.
    X_fit, y_fit = fitting_rows(X, y, schema, implied, gated)
    weights = class_weights(y_fit)
    model = make_model(weights).fit(X_fit, y_fit)
    classes = [str(c) for c in model.classes_]
    check_classes(classes)
    return {'model': model, 'symptoms': columns, 'classes': classes,
            'implied': implied, 'gated': gated,
            'symptom_rates': symptom_rates(X, y, classes, schema.names), 'rate_columns': schema.names,
            'prior': class_prior(y_fit, classes, weights=weights), 'class_weight': weights,
            'temperature': temperature, 'calibration': calibration, 'severity': severity(),
            'row_bits': np.packbits(X.to_numpy(dtype=bool), axis=1),
            'train_rows': len(data), 'partial_rows': len(X_fit) - len(X)}


def fitting_rows(X: pd.DataFrame, y: pd.Series, schema, implied, gated) -> tuple[pd.DataFrame, pd.Series]:
    """The full rows plus their partial copies: what the forest is fitted on."""
    X_partial, y_partial = partial_rows(X, y, schema, implied, gated)
    return pd.concat([X, X_partial], ignore_index=True), pd.concat([y, y_partial], ignore_index=True)


def held_out(y: pd.Series, share: float = CALIBRATION_SHARE, seed: int = RANDOM_STATE) -> np.ndarray:
    
    rng = np.random.default_rng(seed)
    mask = np.zeros(len(y), dtype=bool)
    for _, rows in y.groupby(y).groups.items():
        rows = np.asarray(rows)
        if len(rows) >= 5:
            mask[rng.choice(rows, int(round(share * len(rows))), replace=False)] = True
    return mask


def calibrate(X: pd.DataFrame, y: pd.Series, schema, implied, gated) -> tuple[float, dict]:
   
    out = held_out(y)
    X_fit, y_fit = fitting_rows(X[~out].reset_index(drop=True), y[~out].reset_index(drop=True),
                                schema, implied, gated)
    X_val, y_val = partial_rows(X[out].reset_index(drop=True), y[out].reset_index(drop=True),
                                schema, implied, gated, per_row=2)
    weights = class_weights(y_fit)
    model = make_model(weights).fit(X_fit, y_fit)
    classes = [str(c) for c in model.classes_]
    prior = class_prior(y_fit, classes, weights=weights)
    known = y_val.isin(classes).to_numpy()
    X_val, y_val = X_val[known], y_val[known]
    index = {c: i for i, c in enumerate(classes)}
    y_index = y_val.map(index).to_numpy()
    # Rows weighted so the score reflects DDXPlus patients, not the held-out mix.
    rates = prevalence(classes)
    share = y_val.value_counts(normalize=True)
    row_weights = (y_val.map(lambda c: rates[c] / share[c]).to_numpy() if rates else np.ones(len(y_val)))
    temperature, scores = fit_temperature(model.predict_proba(X_val), y_index, prior, row_weights)
    return temperature, {**scores, 'held_out_patients': int(out.sum()), 'held_out_rows': len(y_val)}


def main():
    artifact = train()
    joblib.dump(artifact, MODEL_PATH, compress=3)
    counts = pd.read_csv(TRAIN_PATH, usecols=[TARGET])[TARGET].value_counts()
    print(f'Trained Random Forest ({N_ESTIMATORS} trees) on {artifact["train_rows"]} rows '
          f'+ {artifact["partial_rows"]} partial rows, '
          f'{len(artifact["classes"])} illnesses ({counts.min()}–{counts.max()} rows each), '
          f'{len(artifact["symptoms"])} columns.')
    print(f'Follow-ups filled in with their parent: {artifact["implied"]}')
    print(f'Symptoms that fill in "pain": {sorted(artifact["gated"])}')
    w = artifact['class_weight']
    print(f'Class weights: x{min(w.values()):.2f} ({min(w, key=w.get)}) to x{max(w.values()):.1f} ({max(w, key=w.get)})')
    c = artifact['calibration']
    print(f'Calibration on {c["held_out_rows"]} held-out rows ({c["held_out_patients"]} patients): '
          f'temperature {artifact["temperature"]:.2f} (fitted {c["fitted_temperature"]:.2f}); log-loss {c["log_loss_before"]:.3f} -> {c["log_loss_after"]:.3f}, '
          f'ECE {c["ece_before"]:.3f} -> {c["ece_after"]:.3f}')
    if not artifact['severity']:
        print(f'{CONDITIONS_PATH} not found: no severity, so the serious-illness check is off.')
    if PREVALENCE_PATH.exists():
        prior = dict(zip(artifact['classes'], artifact['prior']))
        low, high = min(prior, key=prior.get), max(prior, key=prior.get)
        print(f'Prevalence correction: x{prior[low]:.2f} ({low}) to x{prior[high]:.1f} ({high})')
    else:
        print(f'{PREVALENCE_PATH} not found: no prevalence correction (rerun ml.ddxplus_adapter).')
    print(f'Saved {MODEL_PATH.name}. Evaluate with: python -m ml.evaluate')


if __name__ == '__main__':
    main()
