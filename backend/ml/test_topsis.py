"""Tests for ml/topsis.py.

Run:  python -m ml.test_topsis      or     python -m pytest ml/test_topsis.py
"""
import numpy as np

from ml.topsis import DEFAULT_WEIGHTS, criteria_weights, topsis

EXAMPLE = [[10, 20, 5], [6, 8, 10], [12, 25, 15]]       # doctors A, B, C
EXAMPLE_WEIGHTS = [0.4, 0.4, 0.2]
EXAMPLE_BENEFIT = [True, False, True]                  # free hours, caseload (cost), experience


def _ranking(scores, names='ABC'):
    return ''.join(names[i] for i in np.argsort(-np.asarray(scores), kind='stable'))


def cases():
    scores = topsis(EXAMPLE, EXAMPLE_WEIGHTS, EXAMPLE_BENEFIT)
    yield 'worked example scores ≈ [0.378, 0.582, 0.465]', np.allclose(scores, [0.378, 0.582, 0.465], atol=0.001)
    yield 'worked example ranking is B, C, A', _ranking(scores) == 'BCA'
    yield 'scores are between 0 and 1', bool(((scores >= 0) & (scores <= 1)).all())
    yield 'a single option scores 1.0', topsis([[3, 4, 5]], EXAMPLE_WEIGHTS, EXAMPLE_BENEFIT).tolist() == [1.0]
    yield 'no options gives an empty result', topsis(np.zeros((0, 3)), EXAMPLE_WEIGHTS, EXAMPLE_BENEFIT).size == 0
    yield 'a column of zeros does not divide by zero', np.isfinite(
        topsis([[10, 0, 5], [6, 0, 10]], EXAMPLE_WEIGHTS, EXAMPLE_BENEFIT)).all()
    same = topsis([[5, 5, 5], [5, 5, 5]], EXAMPLE_WEIGHTS, EXAMPLE_BENEFIT)
    yield 'identical options get identical scores (no division by zero)', np.isfinite(same).all() and same[0] == same[1]
    best_on_all = topsis([[20, 1, 30], [10, 9, 5], [5, 20, 1]], EXAMPLE_WEIGHTS, EXAMPLE_BENEFIT)
    yield 'an option best on every criterion scores 1, worst on every criterion scores 0', \
        np.isclose(best_on_all[0], 1) and np.isclose(best_on_all[2], 0)
    two = topsis([[10, 20], [6, 8], [12, 25]], criteria_weights(['free_hours', 'caseload']), [True, False])
    yield 'two criteria (no experience field) still rank', len(two) == 3 and np.isfinite(two).all()
    yield 'weights renormalise 0.4/0.4 → 0.5/0.5', np.allclose(criteria_weights(['free_hours', 'caseload']), [0.5, 0.5])
    yield 'default weights are 0.4 / 0.4 / 0.2', DEFAULT_WEIGHTS == {'free_hours': 0.4, 'caseload': 0.4, 'experience': 0.2}
    try:
        topsis([[1, 2]], [0.5], [True])
        yield 'mismatched weights raise ValueError', False
    except ValueError:
        yield 'mismatched weights raise ValueError', True


def run():
    results = list(cases())
    return results, sum(ok for _, ok in results)


def test_topsis_cases():
    results, _ = run()
    failed = [name for name, ok in results if not ok]
    assert not failed, failed


if __name__ == '__main__':
    scores = topsis(EXAMPLE, EXAMPLE_WEIGHTS, EXAMPLE_BENEFIT)
    print('Worked example scores (A, B, C):', np.round(scores, 4).tolist(), '-> ranking', ', '.join(_ranking(scores)))
    results, passed = run()
    for name, ok in results:
        print(('  ok   ' if ok else '  FAIL ') + name.replace('≈', '~').replace('→', '->'))
    print(f'{passed} of {len(results)} passed')
    raise SystemExit(0 if passed == len(results) else 1)
