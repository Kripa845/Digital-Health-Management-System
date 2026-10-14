
from __future__ import annotations

import numpy as np

# Default criterion weights (free hours, caseload, experience). Review these.
DEFAULT_WEIGHTS = {'free_hours': 0.4, 'caseload': 0.4, 'experience': 0.2}
BENEFIT = {'free_hours': True, 'caseload': False, 'experience': True}
WEIGHT_TOLERANCE = 1e-6


def validate_weights(weights: dict[str, float]) -> dict[str, float]:
    """Check criterion weights: known criteria, each 0 or more, adding up to 1."""
    if not weights:
        raise ValueError('no TOPSIS weights are configured')
    unknown = set(weights) - set(BENEFIT)
    if unknown:
        raise ValueError(f'unknown TOPSIS criteria: {", ".join(sorted(unknown))}')
    try:
        values = {k: float(v) for k, v in weights.items()}
    except (TypeError, ValueError) as exc:
        raise ValueError('TOPSIS weights must be numbers') from exc
    if any(v < 0 for v in values.values()):
        raise ValueError('TOPSIS weights cannot be negative')
    total = sum(values.values())
    if abs(total - 1) > WEIGHT_TOLERANCE:
        raise ValueError(f'TOPSIS weights must add up to 1 (they add up to {total:g})')
    return values


def criteria_weights(criteria: list[str], weights: dict[str, float] | None = None) -> np.ndarray:
    """Weights for the given criteria, renormalised to sum to 1 (drops criteria not in use)."""
    weights = weights or DEFAULT_WEIGHTS
    w = np.array([weights[c] for c in criteria], dtype=float)
    total = w.sum()
    if total <= 0:
        raise ValueError('weights must add up to more than 0')
    return w / total


def topsis(matrix, weights, benefit) -> np.ndarray:
    """Score each row from 0 to 1 (higher is better).

    matrix   rows = options, columns = criteria (numbers)
    weights  one weight per column
    benefit  one bool per column: True = higher is better, False = lower is better (cost)
    """
    m = np.asarray(matrix, dtype=float)
    if m.ndim != 2:
        raise ValueError('matrix must be 2-dimensional (rows = options, columns = criteria)')
    w = np.asarray(weights, dtype=float)
    b = np.asarray(benefit, dtype=bool)
    if w.shape != (m.shape[1],) or b.shape != (m.shape[1],):
        raise ValueError('weights and benefit need one entry per column')

    # Missing data (None / NaN): use the worst value seen in that column, or 0
    # when the whole column is missing (it then cannot change the ranking).
    missing = ~np.isfinite(m)
    if missing.any():
        m = m.copy()
        for j in range(m.shape[1]):
            known = ~missing[:, j]
            if known.any():
                fill = m[known, j].min() if b[j] else m[known, j].max()
            else:
                fill = 0.0
            m[~known, j] = fill
    if m.shape[0] == 0:
        return np.array([])
    if m.shape[0] == 1:
        return np.array([1.0])

    # 1. Vector normalisation per column (a column of zeros keeps a norm of 1).
    norms = np.sqrt((m ** 2).sum(axis=0))
    norms[norms == 0] = 1.0
    # 2. Weighting.
    v = (m / norms) * w
    # 3. Ideal best and worst per column.
    best = np.where(b, v.max(axis=0), v.min(axis=0))
    worst = np.where(b, v.min(axis=0), v.max(axis=0))
    # 4. Euclidean distances.
    d_best = np.sqrt(((v - best) ** 2).sum(axis=1))
    d_worst = np.sqrt(((v - worst) ** 2).sum(axis=1))
    # 5. Closeness score (a zero denominator — all rows identical — is replaced by 1).
    denominator = d_best + d_worst
    denominator[denominator == 0] = 1.0
    return d_worst / denominator
