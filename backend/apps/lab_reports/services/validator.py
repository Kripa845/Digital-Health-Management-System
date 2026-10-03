"""Unit conversion, plausibility ranges and flags for extracted or edited values.

A value outside its range is flagged ("out_of_range"): it is shown to the user
and saved only if they explicitly accept it on confirm. For the three main
dashboard tests (STRICT_RANGE_TESTS) an out-of-range value is dropped instead
("invalid"): it is shown as not saved and cannot be accepted. A value in a unit we do
not recognise ("unknown_unit") or that is not a number ("invalid") is never
saved unless the user types a corrected value.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from apps.lab_reports.extractor import _PLAUSIBLE_RANGES, validate_blood_pressure
from apps.lab_reports.units import CANONICAL_UNITS, convert

OUT_OF_RANGE = 'out_of_range'
UNKNOWN_UNIT = 'unknown_unit'
INVALID = 'invalid'
BLOOD_GROUP_CONFLICT = 'blood_group_conflict'
TOO_LARGE = 'too_large'

VALID_BLOOD_GROUPS = ('A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-')

# Haemoglobin 3–25 g/dL, total cholesterol 50–500 mg/dL, random sugar 20–800 mg/dL:
# a value outside these is taken as a misread and never saved.
STRICT_RANGE_TESTS = ('hemoglobin', 'cholesterol_total', 'blood_sugar_random')


@dataclass
class Checked:
    value: str | None          # in the dashboard's unit
    unit: str
    converted: bool = False
    flag: str = ''
    message: str = ''


def range_text(field: str) -> str:
    bounds = _PLAUSIBLE_RANGES.get(field)
    if not bounds:
        return ''
    low, high = bounds
    return f'{_plain(low)}–{_plain(high)} {CANONICAL_UNITS.get(field, "")}'.strip()


def _plain(n) -> str:
    return format(Decimal(str(n)).normalize(), 'f')


def _in_range(field: str, value: str) -> bool:
    bounds = _PLAUSIBLE_RANGES.get(field)
    if not bounds:
        return True
    try:
        n = float(value)
    except ValueError:
        return False
    return bounds[0] <= n <= bounds[1]


def check_value(field: str, raw_value: str, raw_unit: str = '') -> Checked:
    """Validate a value as printed on the report (converting its unit)."""
    if field == 'blood_pressure':
        v = re.sub(r'\s*/\s*', '/', (raw_value or '').strip())
        if validate_blood_pressure(v):
            return Checked(v, 'mmHg')
        return Checked(v or None, 'mmHg', flag=OUT_OF_RANGE,
                       message='Outside the expected range for blood pressure; it may have been misread.')

    conversion = convert(field, raw_value, raw_unit)
    if conversion.value is None:
        flag = UNKNOWN_UNIT if 'unit' in conversion.error else INVALID
        return Checked(None, conversion.unit, flag=flag, message=conversion.error)
    if not _in_range(field, conversion.value):
        if field in STRICT_RANGE_TESTS:
            return Checked(conversion.value, conversion.unit, conversion.converted, INVALID,
                           f'Outside the expected range ({range_text(field)}), so it was treated as a misread '
                           'and not saved.')
        return Checked(conversion.value, conversion.unit, conversion.converted, OUT_OF_RANGE,
                       f'Outside the expected range ({range_text(field)}), so it may have been misread.')
    return Checked(conversion.value, conversion.unit, conversion.converted)


def is_usable(field: str, raw_value: str, raw_unit: str = '') -> bool:
    """Whether an extracted value could be saved (possibly after the user accepts a flag)."""
    if field == 'blood_group':
        return normalise_blood_group(raw_value) is not None
    return check_value(field, raw_value, raw_unit).flag in ('', OUT_OF_RANGE)


def check_edited_value(field: str, text: str) -> Checked:
    """Validate a value the user typed on the confirm screen (already in the dashboard unit)."""
    raw = (text or '').strip()
    if field == 'blood_pressure':
        return check_value(field, raw)
    try:
        number = Decimal(raw)
    except (InvalidOperation, ValueError):
        return Checked(None, CANONICAL_UNITS.get(field, ''), flag=INVALID, message='Enter a number.')
    value = format(number.normalize(), 'f')
    unit = CANONICAL_UNITS.get(field, '')
    if not _in_range(field, value):
        return Checked(value, unit, flag=INVALID if field in STRICT_RANGE_TESTS else OUT_OF_RANGE,
                       message=f'Outside the expected range ({range_text(field)}).')
    return Checked(value, unit)


def normalise_blood_group(raw: str | None) -> str | None:
    s = re.sub(r'\s+', '', (raw or '').upper()).replace('VE', '')
    s = s.replace('POSITIVE', '+').replace('NEGATIVE', '-')
    return s if s in VALID_BLOOD_GROUPS else None


def to_db_value(patient, field: str, value: str):
    """Convert to the patient column's type; None when it would not fit the column."""
    if field == 'blood_pressure':
        max_length = patient._meta.get_field('blood_pressure').max_length
        return value if value and len(value) <= max_length else None
    if field == 'heart_rate':
        try:
            n = int(Decimal(value))
        except (InvalidOperation, ValueError):
            return None
        return n if 0 < n < 1000 else None
    model_field = patient._meta.get_field(field)
    try:
        rounded = Decimal(value).quantize(Decimal(1).scaleb(-model_field.decimal_places))
    except (InvalidOperation, ValueError):
        return None
    integer_digits = len(rounded.as_tuple().digits) - model_field.decimal_places
    if integer_digits > model_field.max_digits - model_field.decimal_places:
        return None
    return rounded
