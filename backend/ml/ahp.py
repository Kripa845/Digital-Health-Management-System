"""AHP: criterion weights from pairwise comparisons, with Saaty's consistency check.

Used to set the TOPSIS weights for ranking doctors. An administrator says, for
each pair of criteria, how much more important one is than the other on
Saaty's 1-9 scale (1 = equal, 3 = moderately, 5 = strongly, 7 = very strongly,
9 = extremely; 1/3 means the other one is moderately more important).

    weights  the principal eigenvector of the comparison matrix, summing to 1
    CI       (lambda_max - n) / (n - 1)
    CR       CI / RI[n]; the comparisons are accepted only when CR < 0.10

A matrix of all ones (every criterion as important as every other) gives equal
weights and CR 0.
"""
from __future__ import annotations

import numpy as np

# Criteria for ranking doctors, in this fixed order (rows/columns of the matrix).
CRITERIA = ['earliest_slot', 'free_hours', 'caseload', 'experience', 'match']
# True = higher is better (benefit), False = lower is better (cost).
BENEFIT = {'earliest_slot': False, 'free_hours': True, 'caseload': False, 'experience': True, 'match': True}
LABELS = {
    'earliest_slot': 'Hours to earliest free slot',
    'free_hours': 'Free hours this week',
    'caseload': 'Active caseload',
    'experience': 'Years of experience',
    'match': 'Specialisation match',
}

# Saaty's random consistency index for n criteria.
RI = {1: 0, 2: 0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32}
MAX_CR = 0.10
RECIPROCAL_TOLERANCE = 1e-3
WEIGHT_TOLERANCE = 1e-6


def equal_matrix(n: int = len(CRITERIA)) -> list[list[float]]:
    """Every criterion as important as every other."""
    return [[1.0] * n for _ in range(n)]


def ahp_weights(pairwise) -> tuple[np.ndarray, float]:
    """(weights summing to 1, consistency ratio) for a pairwise comparison matrix.

    Raises ValueError when the matrix is not square, has an entry that is not a
    positive number, is not reciprocal (a[i][j] * a[j][i] = 1), has a size with
    no RI value, or is too inconsistent (CR >= 0.10).
    """
    try:
        a = np.asarray(pairwise, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError('the comparisons must be numbers') from exc
    if a.ndim != 2 or a.shape[0] != a.shape[1] or a.shape[0] == 0:
        raise ValueError('the comparison matrix must be square')
    n = a.shape[0]
    if n not in RI:
        raise ValueError(f'{n} criteria are not supported (at most {max(RI)})')
    if not np.all(np.isfinite(a)) or np.any(a <= 0):
        raise ValueError('every comparison must be a positive number')
    if not np.allclose(a * a.T, 1.0, atol=RECIPROCAL_TOLERANCE):
        raise ValueError('the matrix must be reciprocal: a[i][j] x a[j][i] = 1')

    values, vectors = np.linalg.eig(a)
    k = int(np.argmax(values.real))
    lambda_max = float(values[k].real)
    w = np.abs(vectors[:, k].real)
    w = w / w.sum()

    ci = (lambda_max - n) / (n - 1) if n > 2 else 0.0
    cr = max(ci / RI[n], 0.0) if RI[n] else 0.0     # rounding can give a tiny negative CI
    if cr >= MAX_CR:
        raise ValueError(f'the comparisons are inconsistent (CR {cr:.2f}, must be below {MAX_CR:.2f}); '
                         'revise them')
    return w, cr


def validate_criteria_weights(weights: dict[str, float]) -> dict[str, float]:
    """Check doctor-ranking weights: exactly the known criteria, each 0 or more, adding up to 1."""
    if not weights:
        raise ValueError('no criterion weights are stored')
    unknown, missing = set(weights) - set(CRITERIA), set(CRITERIA) - set(weights)
    if unknown:
        raise ValueError(f'unknown criteria: {", ".join(sorted(unknown))}')
    if missing:
        raise ValueError(f'missing criteria: {", ".join(sorted(missing))}')
    try:
        values = {k: float(v) for k, v in weights.items()}
    except (TypeError, ValueError) as exc:
        raise ValueError('weights must be numbers') from exc
    if any(v < 0 for v in values.values()):
        raise ValueError('weights cannot be negative')
    total = sum(values.values())
    if abs(total - 1) > WEIGHT_TOLERANCE:
        raise ValueError(f'weights must add up to 1 (they add up to {total:g})')
    return values
