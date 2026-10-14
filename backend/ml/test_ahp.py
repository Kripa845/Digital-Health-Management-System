"""Tests for ml/ahp.py.

Run:  python -m ml.test_ahp      or     python -m pytest ml/test_ahp.py
"""
import numpy as np

from ml.ahp import CRITERIA, ahp_weights, equal_matrix, validate_criteria_weights

# Saaty's textbook example: A is moderately more important than B, strongly more than C.
KNOWN = [[1, 3, 5], [1 / 3, 1, 3], [1 / 5, 1 / 3, 1]]
# A > B, B > C but C > A, each at 9: as inconsistent as comparisons get.
CIRCULAR = [[1, 9, 1 / 9], [1 / 9, 1, 9], [9, 1 / 9, 1]]


def _raises(matrix) -> bool:
    try:
        ahp_weights(matrix)
    except ValueError:
        return True
    return False


def cases():
    w, cr = ahp_weights(equal_matrix())
    yield 'all-equal 5x5 matrix gives equal weights of 0.2', np.allclose(w, 0.2)
    yield 'all-equal matrix has CR 0', abs(cr) < 1e-9
    w, cr = ahp_weights(KNOWN)
    yield 'known example weights ≈ [0.637, 0.258, 0.105]', np.allclose(w, [0.637, 0.258, 0.105], atol=0.002)
    yield 'known example CR ≈ 0.033', abs(cr - 0.033) < 0.002
    yield 'weights add up to 1', np.isclose(w.sum(), 1.0)
    p = np.array([5, 3, 1, 2, 4], dtype=float)
    w, cr = ahp_weights(p[:, None] / p[None, :])
    yield 'a perfectly consistent matrix recovers its priorities', np.allclose(w, p / p.sum()) and cr < 1e-9
    yield 'a 2x2 matrix has CR 0', ahp_weights([[1, 4], [1 / 4, 1]])[1] == 0
    yield 'an inconsistent matrix raises (CR >= 0.10)', _raises(CIRCULAR)
    yield 'a non-square matrix raises', _raises([[1, 2, 3], [1 / 2, 1, 2]])
    yield 'a zero or negative entry raises', _raises([[1, 0], [0, 1]]) and _raises([[1, -2], [-0.5, 1]])
    yield 'a non-reciprocal matrix raises', _raises([[1, 3], [3, 1]])
    yield 'the identity matrix (zeros off the diagonal) raises', _raises(np.eye(3))
    yield 'text entries raise', _raises([[1, 'a'], ['b', 1]])
    yield 'more than 7 criteria raise (no RI value)', _raises(equal_matrix(8))
    yield 'one criterion gets the whole weight', ahp_weights([[1]])[0].tolist() == [1.0]

    # Weight validation for the five doctor-ranking criteria.
    good = dict.fromkeys(CRITERIA, 0.2)
    yield 'valid criterion weights accepted', validate_criteria_weights(good) == good
    for bad, label in (({**good, 'match': 0.5}, 'sum not 1'),
                       ({**good, 'match': -0.2, 'caseload': 0.6}, 'negative'),
                       ({'free_hours': 0.5, 'caseload': 0.3, 'experience': 0.2}, 'missing criteria'),
                       ({**good, 'rating': 0.0}, 'unknown criterion'),
                       ({}, 'empty')):
        try:
            validate_criteria_weights(bad)
            yield f'invalid weights rejected ({label})', False
        except ValueError:
            yield f'invalid weights rejected ({label})', True


def run():
    results = list(cases())
    return results, sum(ok for _, ok in results)


def test_ahp_cases():
    results, _ = run()
    failed = [name for name, ok in results if not ok]
    assert not failed, failed


if __name__ == '__main__':
    w, cr = ahp_weights(KNOWN)
    print('Known example weights:', np.round(w, 3).tolist(), f'CR {cr:.3f}')
    results, passed = run()
    for name, ok in results:
        print(('  ok   ' if ok else '  FAIL ') + name.replace('≈', '~'))
    print(f'{passed} of {len(results)} passed')
    raise SystemExit(0 if passed == len(results) else 1)
