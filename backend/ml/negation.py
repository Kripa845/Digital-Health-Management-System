"""Rule-based negation detection for symptom text.

extract_symptoms("no fever but headache and cough", symptoms) -> ["cough", "headache"]

How it works:
1. The text is lowercased, underscores become spaces, and commas, semicolons
   and full stops become separate words. Other punctuation is treated as a space.
2. Each symptom (possibly several words, e.g. "chest pain") is matched as a
   sequence of words.
3. For every match at word index i, up to 4 words before it are checked, nearest
   first. A STOPPER (but, however, ..., "," or ".") ends the search: the symptom
   is not negated. A NEGATION word (no, not, without, ...) negates it.
4. A symptom counts as present if at least one of its mentions is not negated.
"""
from __future__ import annotations

import re

NEGATIONS = {'no', 'not', 'without', 'never', 'denies', 'deny'}
STOPPERS = {'but', 'however', 'although', 'though', '.', ','}
WINDOW = 4


def _words(text: str) -> list[str]:
    text = (text or '').lower().replace('_', ' ')
    text = re.sub(r'([,;.])', r' \1 ', text)          # keep , ; . as their own words
    text = re.sub(r"[^\w\s,;.]", ' ', text)            # other punctuation ("!", "?", "-") → space
    return text.split()


def _is_negated(words: list[str], i: int) -> bool:
    for j in range(i - 1, max(i - WINDOW, 0) - 1, -1):
        if words[j] in STOPPERS:
            return False
        if words[j] in NEGATIONS:
            return True
    return False


def extract_symptoms(text: str, symptoms) -> list[str]:
    """The symptoms from ``symptoms`` mentioned in ``text`` and not negated, sorted.

    ``symptoms`` may use underscores ("skin_rash"); the names are returned as given.
    """
    words = _words(text)
    present = set()
    for symptom in symptoms:
        target = _words(symptom)
        n = len(target)
        if not n:
            continue
        for i in range(len(words) - n + 1):
            if words[i:i + n] == target and not _is_negated(words, i):
                present.add(symptom)
                break
    return sorted(present)
