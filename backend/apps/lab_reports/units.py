"""Unit handling for extracted lab values.

The patient record stores each value in one canonical unit (the unit the
dashboard cards display). A value reported in another unit is converted; a
value in a unit we do not recognise for that test is rejected rather than
guessed at.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from apps.lab_reports import lab_config

# Canonical unit stored for each patient field, the recognised spellings of each
# unit, and per test: normalised unit → multiplier to the canonical unit (a unit
# absent there is not accepted for that test). All in config/lab_tests.json.
CANONICAL_UNITS: dict[str, str] = lab_config.canonical_units()
_UNIT_ALIASES: dict[str, str] = lab_config.unit_aliases()
_FACTORS: dict[str, dict[str, Decimal]] = lab_config.unit_factors()


@dataclass
class Conversion:
    value: str | None      # value in the canonical unit, or None when rejected
    unit: str              # canonical unit
    converted: bool        # True when a conversion was applied
    error: str = ''        # reason for rejection


_SUPERSCRIPT_DIGITS = str.maketrans('⁰¹²³⁴⁵⁶⁷⁸⁹', '0123456789')


def normalise_unit(raw: str) -> str:
    """Case-, space- and spelling-insensitive unit key: "10^3/uL", "x10³/µL", "*10^6/ul",
    "10*3/cu.mm" and "Mill/cumm" all reduce to an entry of the unit aliases. The power
    of ten is kept (it is part of the unit, not noise)."""
    u = (raw or '').strip().lower().replace('µ', 'u').replace('μ', 'u')
    u = re.sub(r'[⁰¹²³⁴⁵⁶⁷⁸⁹]+', lambda m: '^' + m.group(0).translate(_SUPERSCRIPT_DIGITS), u)
    u = re.sub(r'[\s.]+', '', u).replace('^^', '^')
    u = re.sub(r'^[\'"“”‘’`,]+', '', u)                             # stray OCR quote marks
    u = re.sub(r'^[*x×]', '', u)                                    # "*10^6/ul", "x10^3/ul"
    u = re.sub(r'^10[°%�\'"`~]+(?=\d{1,2}/)', '10^', u)       # OCR reads ^ as °, %, ' or an unknown glyph
    u = re.sub(r'^10(?:\^|\*\*|\*|e)(\d{1,2})(?=/)', r'10^\1', u)    # 10**3, 10*3, 10e3 → 10^3
    u = u.replace('cmm', 'cumm') if u.endswith('/cmm') else u
    return _UNIT_ALIASES.get(u, u)


def convert(patient_field: str, value: str, raw_unit: str) -> Conversion:
    canonical = CANONICAL_UNITS.get(patient_field, raw_unit or '')
    if patient_field == 'blood_pressure':
        return Conversion(value, 'mmHg', False)

    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        return Conversion(None, canonical, False, 'The value could not be read as a number.')

    unit = normalise_unit(raw_unit)
    factors = _FACTORS.get(patient_field)
    if not unit or factors is None:
        # No unit printed (common in tables): assume the canonical unit. The
        # plausibility range check that follows rejects values in another unit.
        return Conversion(_plain(number), canonical, False)

    if patient_field == 'hba1c' and unit == 'mmol/mol':
        # IFCC (mmol/mol) to NGSP (%) master equation.
        return Conversion(_plain(number / Decimal('10.929') + Decimal('2.15')), canonical, True)

    factor = factors.get(unit)
    if factor is None:
        return Conversion(None, canonical, False, f'The unit "{raw_unit}" is not recognised for this test.')
    if factor == 1:
        return Conversion(_plain(number), canonical, False)
    return Conversion(_plain(number * factor), canonical, True)


def _plain(number: Decimal) -> str:
    """Round to 2 decimal places and drop trailing zeros."""
    rounded = number.quantize(Decimal('0.01'))
    text = format(rounded.normalize(), 'f')
    return text
