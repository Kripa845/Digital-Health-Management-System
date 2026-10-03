"""Tests for ml/negation.py.

Run:  python -m ml.test_negation      (prints "X of Y passed")
  or: python -m pytest ml/test_negation.py
"""
from ml.negation import extract_symptoms

SYMPTOMS = [
    'fever', 'cough', 'headache', 'chest pain', 'dizziness', 'skin_rash', 'vomiting', 'nausea',
    'fatigue', 'joint pain', 'stomach pain', 'high fever', 'itching', 'back pain', 'breathlessness',
]

# (text, expected present symptoms)
CASES = [
    # Required cases
    ('no fever but headache and cough', ['cough', 'headache']),
    ('fever and cough', ['cough', 'fever']),
    ('I have no chest pain', []),
    ('without fever, cough present', ['cough']),
    ('not feeling dizziness. fever', ['fever']),
    ('no fever, no cough, headache', ['headache']),
    # Multi-word symptoms and underscores
    ('I have a skin rash and itching', ['itching', 'skin_rash']),
    ('skin_rash since yesterday', ['skin_rash']),
    ('severe chest pain and dizziness', ['chest pain', 'dizziness']),
    ('high fever with vomiting', ['fever', 'high fever', 'vomiting']),
    # Other negation words
    ('patient denies nausea, has vomiting', ['vomiting']),
    ('I never had headache', []),
    ('deny any dizziness', []),
    # Window of 4 words
    ('no history of any fever', []),                       # "no" is 4 words before
    ('no real problem today except fever', ['fever']),     # "no" is 5 words before: outside the window
    # Stoppers
    ('no fever however cough', ['cough']),
    ('not tired although fatigue sometimes', ['fatigue']),
    ('no nausea; vomiting', []),                           # ";" is not a stopper: "no" still applies
    ('no headache. back pain', ['back pain']),
    # Repeated mention: one non-negated mention is enough
    ('no fever yesterday, but fever today', ['fever']),
    # Case, punctuation, empty input
    ('FEVER! Cough? Joint-pain', ['cough', 'fever', 'joint pain']),
    ('', []),
    ('feeling fine', []),
    ('stomach pain without breathlessness', ['stomach pain']),
]


def run() -> tuple[int, int, list[str]]:
    failures = []
    for text, expected in CASES:
        got = extract_symptoms(text, SYMPTOMS)
        if got != sorted(expected):
            failures.append(f'  FAIL {text!r}: expected {sorted(expected)}, got {got}')
    return len(CASES) - len(failures), len(CASES), failures


def test_negation_cases():
    passed, total, failures = run()
    assert not failures, '\n' + '\n'.join(failures)


if __name__ == '__main__':
    passed, total, failures = run()
    for line in failures:
        print(line)
    print(f'{passed} of {total} passed')
    raise SystemExit(0 if passed == total else 1)
