"""Loads config/lab_tests.json: test aliases, units, conversions and plausible ranges.

Edit the JSON, not this file, to add a test, a spelling or a unit.
"""
from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / 'config' / 'lab_tests.json'


@lru_cache(maxsize=1)
def load() -> dict:
    with open(CONFIG_PATH, encoding='utf-8') as fh:
        return json.load(fh)


def tests() -> dict[str, dict]:
    return load()['tests']


def _decimal(factor) -> Decimal:
    """1, "0.1" or "1/88.42" → Decimal."""
    text = str(factor)
    if '/' in text:
        num, den = text.split('/', 1)
        return Decimal(num) / Decimal(den)
    return Decimal(text)


def canonical_units() -> dict[str, str]:
    return {k: t['unit'] for k, t in tests().items() if t.get('unit')}


def unit_factors() -> dict[str, dict[str, Decimal]]:
    return {k: {u: _decimal(f) for u, f in t['units'].items()} for k, t in tests().items() if 'units' in t}


def plausible_ranges() -> dict[str, tuple[float, float]]:
    return {k: (float(t['plausible'][0]), float(t['plausible'][1])) for k, t in tests().items() if 'plausible' in t}


def display_names() -> dict[str, str]:
    return {k: t['display'] for k, t in tests().items() if t.get('display')}


def unit_aliases() -> dict[str, str]:
    return dict(load()['unit_aliases'])


def header_synonyms() -> dict[str, list[str]]:
    return load()['headers']


def ignore_tokens() -> frozenset[str]:
    return frozenset(load()['ignore_tokens'])


def ignore_qualifiers() -> frozenset[str]:
    return frozenset(load()['ignore_qualifiers'])
