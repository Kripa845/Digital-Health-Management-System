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

# Canonical unit stored for each patient field.
CANONICAL_UNITS: dict[str, str] = {
    'height': 'cm',
    'weight': 'kg',
    'blood_pressure': 'mmHg',
    'heart_rate': 'bpm',
    'spo2': '%',
    'temperature': '°C/°F',
    'hemoglobin': 'g/dL',
    'blood_sugar_fasting': 'mg/dL',
    'blood_sugar_random': 'mg/dL',
    'hba1c': '%',
    'cholesterol_total': 'mg/dL',
    'cholesterol_hdl': 'mg/dL',
    'cholesterol_ldl': 'mg/dL',
    'triglycerides': 'mg/dL',
    'serum_creatinine': 'mg/dL',
    'blood_urea': 'mg/dL',
    'uric_acid': 'mg/dL',
    'bilirubin_total': 'mg/dL',
    'ssgpt_alt': 'U/L',
    'ssgot_ast': 'U/L',
    'tsh': 'mIU/L',
    't3': 'ng/dL',
    't4': 'µg/dL',
    'sodium': 'mEq/L',
    'potassium': 'mEq/L',
    'hematocrit': '%',
    'esr': 'mm/hr',
}

# Recognised spellings → normalised key.
_UNIT_ALIASES: dict[str, str] = {
    'mg/dl': 'mg/dl', 'mg%': 'mg/dl', 'mgs/dl': 'mg/dl',
    'mmol/l': 'mmol/l', 'mmol': 'mmol/l',
    'umol/l': 'umol/l', 'µmol/l': 'umol/l', 'μmol/l': 'umol/l', 'micromol/l': 'umol/l',
    'g/dl': 'g/dl', 'gm/dl': 'g/dl', 'gms/dl': 'g/dl', 'g%': 'g/dl', 'gm%': 'g/dl',
    'g/l': 'g/l', 'gm/l': 'g/l',
    '%': '%', 'percent': '%',
    'mmol/mol': 'mmol/mol',
    'cm': 'cm', 'm': 'm', 'in': 'in', 'inch': 'in', 'inches': 'in',
    'kg': 'kg', 'kgs': 'kg', 'lb': 'lb', 'lbs': 'lb',
    'mmhg': 'mmhg', 'mm/hg': 'mmhg',
    'bpm': 'bpm', '/min': 'bpm', 'beats/min': 'bpm',
    'u/l': 'u/l', 'iu/l': 'u/l',
    'meq/l': 'meq/l',
    'miu/l': 'miu/l', 'uiu/ml': 'miu/l', 'µiu/ml': 'miu/l', 'μiu/ml': 'miu/l', 'mu/l': 'miu/l',
    'ng/dl': 'ng/dl', 'ug/dl': 'ug/dl', 'µg/dl': 'ug/dl', 'μg/dl': 'ug/dl',
    'mm/hr': 'mm/hr', 'mm/h': 'mm/hr', 'mm/1sthr': 'mm/hr',
    'c': 'c', '°c': 'c', 'f': 'f', '°f': 'f',
}

# For each field: normalised unit → multiplier to the canonical unit.
# A unit absent here is not accepted for that field.
_FACTORS: dict[str, dict[str, Decimal]] = {
    'blood_sugar_fasting': {'mg/dl': Decimal(1), 'mmol/l': Decimal('18.016')},
    'blood_sugar_random': {'mg/dl': Decimal(1), 'mmol/l': Decimal('18.016')},
    'cholesterol_total': {'mg/dl': Decimal(1), 'mmol/l': Decimal('38.67')},
    'cholesterol_hdl': {'mg/dl': Decimal(1), 'mmol/l': Decimal('38.67')},
    'cholesterol_ldl': {'mg/dl': Decimal(1), 'mmol/l': Decimal('38.67')},
    'triglycerides': {'mg/dl': Decimal(1), 'mmol/l': Decimal('88.57')},
    'hemoglobin': {'g/dl': Decimal(1), 'g/l': Decimal('0.1'), 'mmol/l': Decimal('1.611')},
    'serum_creatinine': {'mg/dl': Decimal(1), 'umol/l': Decimal(1) / Decimal('88.42')},
    'blood_urea': {'mg/dl': Decimal(1), 'mmol/l': Decimal('6.006')},
    'uric_acid': {'mg/dl': Decimal(1), 'umol/l': Decimal(1) / Decimal('59.48')},
    'bilirubin_total': {'mg/dl': Decimal(1), 'umol/l': Decimal(1) / Decimal('17.1')},
    'height': {'cm': Decimal(1), 'm': Decimal(100), 'in': Decimal('2.54')},
    'weight': {'kg': Decimal(1), 'lb': Decimal('0.45359237')},
    'hba1c': {'%': Decimal(1)},  # mmol/mol handled separately (not linear)
    'spo2': {'%': Decimal(1)},
    'hematocrit': {'%': Decimal(1)},
    'heart_rate': {'bpm': Decimal(1)},
    'ssgpt_alt': {'u/l': Decimal(1)},
    'ssgot_ast': {'u/l': Decimal(1)},
    'sodium': {'meq/l': Decimal(1), 'mmol/l': Decimal(1)},
    'potassium': {'meq/l': Decimal(1), 'mmol/l': Decimal(1)},
    'tsh': {'miu/l': Decimal(1)},
    't3': {'ng/dl': Decimal(1)},
    't4': {'ug/dl': Decimal(1)},
    'esr': {'mm/hr': Decimal(1)},
    'temperature': {'c': Decimal(1), 'f': Decimal(1)},  # stored as read; range check covers both
}


@dataclass
class Conversion:
    value: str | None      # value in the canonical unit, or None when rejected
    unit: str              # canonical unit
    converted: bool        # True when a conversion was applied
    error: str = ''        # reason for rejection


def normalise_unit(raw: str) -> str:
    """Lower-case, strip spaces and the "x10^n" multipliers OCR leaves around units."""
    u = (raw or '').strip().lower().replace(' ', '')
    u = re.sub(r'^[×x]10\^?\d+', '', u)
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
