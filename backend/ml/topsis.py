"""TOPSIS: rank options by closeness to the ideal best and distance from the ideal worst.

Used to rank the doctors of the predicted department. Each row is a doctor,
each column a criterion:

    free hours this week   benefit (more is better)
    current caseload       cost    (less is better)
    years of experience    benefit — only if the Doctor model stores it

The project's Doctor model has no experience field, so the doctor ranking uses
the first two criteria and renormalises their weights (0.4 / 0.4 → 0.5 / 0.5).
"""
from __future__ import annotations

import numpy as np

# Default criterion weights (free hours, caseload, experience). Review these.
DEFAULT_WEIGHTS = {'free_hours': 0.4, 'caseload': 0.4, 'experience': 0.2}
BENEFIT = {'free_hours': True, 'caseload': False, 'experience': True}


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
