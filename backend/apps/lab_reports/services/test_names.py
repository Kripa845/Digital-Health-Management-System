"""Map a test name printed on a report to a test key, by exact alias only.

The whole printed name is normalised and looked up in the alias map of
config/lab_tests.json; it is never matched as a substring or fuzzily, so
"Bilirubin Direct" can never be read as total bilirubin. A name that does not
match is unknown (None): it is logged and shown for review, never guessed.

Tried in order (the first hit wins):
    1. the full name                      "SGPT (ALT)"            → "sgpt alt"
    2. without method/sample words        "S. Creatinine (Jaffe)" → "creatinine"
    3. without brackets, only when every bracket is a method/sample word or the
       same test's own alias              "Haemoglobin (Hb)"      → "haemoglobin"
                                          "Bilirubin (Direct)"    → step 1 already
    4. names joined by "/", when every part is the same test
                                          "PCV/ Haematocrit"      → "haematocrit"
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache

from apps.lab_reports import lab_config

logger = logging.getLogger(__name__)


def normalise_name(text: str) -> str:
    """Lower case; footnote marks and punctuation (other than + and brackets) become spaces."""
    s = (text or '').lower().replace('µ', 'u').replace('μ', 'u')
    s = re.sub(r'[^a-z0-9+()]+', ' ', s)
    s = re.sub(r'\(\s*', ' (', s)
    s = re.sub(r'\s*\)', ') ', s)
    s = re.sub(r'\s+by\s+.*$', '', s)          # "Urea by Urease method" → "urea"
    return re.sub(r'\s+', ' ', s).strip()


def _flat(text: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'[()]', ' ', text)).strip()


@lru_cache(maxsize=1)
def alias_map() -> dict[str, str]:
    """normalised alias → test key. An alias listed under two tests is a config error."""
    mapping: dict[str, str] = {}
    for key, test in lab_config.tests().items():
        for alias in test.get('aliases', []):
            norm = _flat(normalise_name(alias))
            if mapping.get(norm, key) != key:
                raise ValueError(f'Alias "{alias}" is listed for both {mapping[norm]} and {key}.')
            mapping[norm] = key
    return mapping


def _without_ignorable(text: str) -> str:
    ignore = lab_config.ignore_tokens()
    return ' '.join(w for w in text.split() if w not in ignore)


def _ignorable(qualifier: str) -> bool:
    q = _flat(qualifier)
    return not q or q in lab_config.ignore_qualifiers() or all(w in lab_config.ignore_tokens() for w in q.split())


def _lookup(text: str) -> str | None:
    aliases = alias_map()
    return aliases.get(text) or aliases.get(_without_ignorable(text))


def match_test(printed_name: str) -> str | None:
    """The test key for a printed test name, or None when it is not a known test.

    A name made of synonyms joined by "/" ("Packed Cell Volume/ Haematocrit") matches
    only when every part is an alias of the same test."""
    key = _match_one(printed_name)
    if key or '/' not in (printed_name or ''):
        return key
    parts = [p for p in printed_name.split('/') if p.strip()]
    keys = {_match_one(p) for p in parts}
    return keys.pop() if len(parts) > 1 and len(keys) == 1 and None not in keys else None


def _match_one(printed_name: str) -> str | None:
    norm = normalise_name(printed_name)
    if not norm or not re.search(r'[a-z]', norm):
        return None
    key = _lookup(_flat(norm))
    if key:
        return key
    qualifiers = re.findall(r'\(([^)]*)\)', norm)
    if not qualifiers:
        return None
    base_key = _lookup(_flat(re.sub(r'\([^)]*\)', ' ', norm)))
    if base_key and all(_ignorable(q) or _lookup(_flat(q)) == base_key for q in qualifiers):
        return base_key
    return None
