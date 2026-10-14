"""Rule-based negation detection for symptom text.

find_symptoms("i have fever but i don't have headache", ["fever", "headache"])
    -> ({"fever"}, {"headache"})                       (present, absent)

How it works:
1. Tokenise: lower-case, underscores become spaces, apostrophes inside a word are
   dropped ("don't" -> "dont", "can’t" -> "cant"), and , ; . ! ? become separate
   tokens. Other punctuation is treated as a space.
2. Symptom phrases are found on these raw tokens, longest phrase first, so "chest pain"
   wins over "pain". Synonym mapping happens only afterwards, when the match is stored
   (ml/symptom_terms.py), so a negated "vomiting" is still found as "vomiting".
3. Negation cues are normalised to one token, NEGATION ("not"): no, not, without,
   never, none, nor, neither, deny/denies/denied, cannot, and every n't contraction
   with or without the apostrophe (don't, dont, doesn't, didn't, haven't, can't...).
   "do not" is simply the filler "do" followed by "not". A cue that is part of a
   symptom phrase ("no appetite", "cant breathe") is not a cue.
4. A cue opens a scope that runs left to right:
   - filler words (have, had, any, a, the, feel, feeling, got, much, really...) are free;
   - every other word uses one of WINDOW content tokens: the symptom must be one of the
     first WINDOW content tokens after the cue, or the scope closes;
   - "but", "however", "although", "though", "except", ". ! ?" and a new subject
     ("i", "he", "she"...) close it;
   - after the first negated symptom the scope only continues as a list: through ",",
     ";", "and", "or", "nor" and articles straight into the next symptom
     ("no fever, cough or rash" -> all three absent). Any other word closes it, so in
     "i don't have headache, i feel nausea" nausea stays present;
   - when every item has its own cue ("no fever, no cough, headache") the list is
     per item: only "or" / "nor" carry the negation on, so headache stays present.
5. Each symptom is present or absent. A symptom both negated and not negated somewhere
   in the text counts as absent: the explicit negation wins.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

NEGATION = 'not'   # the single token every cue is normalised to

_CONTRACTED = {
    'dont', 'doesnt', 'didnt', 'havent', 'hasnt', 'hadnt', 'isnt', 'arent', 'wasnt', 'werent',
    'cant', 'cannot', 'couldnt', 'wont', 'wouldnt', 'shouldnt', 'aint', 'neednt', 'mustnt',
}
NEGATIONS = {'no', 'not', 'without', 'never', 'none', 'nor', 'neither', 'deny', 'denies', 'denied'} \
    | _CONTRACTED
SUBJECTS = {'i', 'im', 'he', 'she', 'we', 'they', 'you'}             # start a new clause
STOPPERS = {'but', 'however', 'although', 'though', 'except', 'apart', '.', '!', '?'} | SUBJECTS
LIST_LINKS = {',', ';', 'and', 'or', 'nor', '/'}
# Free inside a scope. Articles may also sit between list items ("no fever or any cough");
# verbs may not, they start a new predicate ("no headache and have nausea").
ARTICLES = {'a', 'an', 'the', 'any', 'some', 'much', 'really', 'very', 'real', 'other'}
VERBS = {'have', 'has', 'had', 'having', 'do', 'does', 'did', 'feel', 'feels', 'feeling', 'felt',
         'got', 'get', 'getting', 'experience', 'experienced', 'experiencing', 'notice', 'noticed',
         'been', 'be', 'am', 'is', 'are', 'was', 'were', 'suffer', 'suffered', 'suffering'}
FILLERS = ARTICLES | VERBS
WINDOW = 4

_APOSTROPHE = re.compile(r"(?<=\w)['’](?=\w)")


def _words(text: str) -> list[str]:
    text = (text or '').lower().replace('_', ' ')
    text = _APOSTROPHE.sub('', text)                    # "don't" -> "dont", "can’t" -> "cant"
    text = re.sub(r'([,;.!?/])', r' \1 ', text)          # keep , ; . ! ? / as their own tokens
    text = re.sub(r"[^\w\s,;.!?/]", ' ', text)           # other punctuation ("-", "(") -> space
    return text.split()


def normalize_negations(words: list[str]) -> list[str]:
    """Every negation cue (no, never, don't, dont, can't...) becomes NEGATION."""
    return [NEGATION if w in NEGATIONS else w for w in words]


@dataclass
class _Scope:
    used: int = 0              # content tokens since the cue
    listing: bool = False      # a symptom has been negated: only list continuation from here
    per_item: bool = False     # "no X, no Y, Z": each item carries its own cue


def negated_spans(words: list[str], spans) -> list[bool]:
    """For each (start, end) symptom span in ``words`` (sorted, not overlapping), whether
    it is negated. Tokens inside a span are never cues."""
    tokens = normalize_negations(words)
    starts = {start: (k, end) for k, (start, end) in enumerate(spans)}
    flags = [False] * len(starts)
    scope: _Scope | None = None
    i = 0
    while i < len(tokens):
        if i in starts:
            k, end = starts[i]
            flags[k] = scope is not None
            if scope:
                scope.listing = True
            i = max(end, i + 1)
            continue
        tok = tokens[i]
        i += 1
        if tok == NEGATION:
            scope = _Scope(per_item=scope is not None and scope.listing)
        elif scope is None:
            continue
        elif tok in STOPPERS:
            scope = None
        elif tok in LIST_LINKS:
            if scope.listing and scope.per_item and tok not in ('or', 'nor'):
                scope = None
        elif tok in ARTICLES or (tok in VERBS and not scope.listing):
            continue
        elif scope.listing:
            scope = None                    # a non-symptom word ends the list
        else:
            scope.used += 1
            if scope.used >= WINDOW:
                scope = None
    return flags


def longest_matches(words: list[str], phrases) -> list[tuple[int, int, tuple[str, ...]]]:
    """(start, end, phrase) for each phrase found in ``words``, left to right, longest first."""
    phrases = set(phrases)
    longest = max((len(p) for p in phrases), default=0)
    out, i = [], 0
    while i < len(words):
        for n in range(min(longest, len(words) - i), 0, -1):
            phrase = tuple(words[i:i + n])
            if phrase in phrases:
                out.append((i, i + n, phrase))
                i += n
                break
        else:
            i += 1
    return out


def find_symptoms(text: str, symptoms, synonyms: dict[str, str] | None = None) -> tuple[set[str], set[str]]:
    """(present, absent) symptoms from ``symptoms`` mentioned in ``text``.

    ``symptoms`` may use underscores ("skin_rash"); the names are returned as given.
    ``synonyms`` maps an extra phrase to one of the symptoms ({"vomiting": "repeated vomiting"});
    the mapping is applied only after negation has been decided on the words as written.
    A symptom that is negated anywhere is absent, never present.
    """
    words = _words(text)
    phrases: dict[tuple[str, ...], str] = {}
    for symptom in symptoms:
        if _words(symptom):
            phrases[tuple(_words(symptom))] = symptom
    for phrase, symptom in (synonyms or {}).items():
        if _words(phrase):
            phrases.setdefault(tuple(_words(phrase)), symptom)
    matches = longest_matches(words, phrases)
    flags = negated_spans(words, [(s, e) for s, e, _ in matches])
    absent = {phrases[p] for (_, _, p), neg in zip(matches, flags) if neg}
    present = {phrases[p] for (_, _, p), neg in zip(matches, flags) if not neg} - absent
    return present, absent


def extract_symptoms(text: str, symptoms) -> list[str]:
    """The symptoms from ``symptoms`` mentioned in ``text`` and not negated, sorted."""
    return sorted(find_symptoms(text, symptoms)[0])
