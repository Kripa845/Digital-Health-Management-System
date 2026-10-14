"""Information-gain follow-up questions for the smart symptom check.

When the model is unsure (not enough symptoms, or the best department below the
confidence threshold), the check asks ONE yes/no question: the symptom whose answer
is expected to reduce the uncertainty about the illness the most.

    gain(s) = H(belief) - [ P(yes) H(belief | s=yes) + P(no) H(belief | s=no) ]

    belief          the Random Forest's current illness probabilities
    P(s | illness)  how often s occurs with each illness in the training rows
                    (``symptom_rates``, saved in the model file by ml/train_model.py)
    P(yes)          = sum over illnesses of belief × P(s | illness)
    belief | s=yes  ∝ belief × P(s | illness)        (Bayes' rule; "no" uses 1 − P(s | illness))

The forest itself has no per-symptom probabilities, so this table is only used to
choose the question; the answer is sent back and the forest predicts again.
"""
from __future__ import annotations

import numpy as np

MAX_QUESTIONS = 5


def _entropy(p: np.ndarray, axis=0) -> np.ndarray:
    p = np.clip(p, 1e-300, 1.0)
    return -(p * np.log2(p)).sum(axis=axis)


def information_gain(belief: np.ndarray, rates: np.ndarray) -> np.ndarray:
    """Expected entropy reduction (bits) for each candidate.

    belief: (illnesses,) probabilities summing to 1.  rates: (illnesses, candidates) P(yes | illness).
    """
    belief = np.asarray(belief, dtype=float)
    belief = belief / belief.sum()
    p_yes = np.clip(belief @ rates, 1e-12, 1 - 1e-12)                       # (candidates,)
    after_yes = belief[:, None] * rates / p_yes
    after_no = belief[:, None] * (1 - rates) / (1 - p_yes)
    expected = p_yes * _entropy(after_yes) + (1 - p_yes) * _entropy(after_no)
    return _entropy(belief) - expected


def next_question(belief, rates: np.ndarray | None, rate_columns: list[str], known, askable) -> str | None:
    """The askable symptom with the highest information gain, or None (no table, nothing left, nothing to gain)."""
    if rates is None:
        return None
    index = {c: i for i, c in enumerate(rate_columns)}
    candidates = [c for c in askable if c in index and c not in set(known)]
    if not candidates:
        return None
    gains = information_gain(np.asarray(belief), rates[:, [index[c] for c in candidates]])
    best = int(np.argmax(gains))
    return candidates[best] if gains[best] > 1e-6 else None
