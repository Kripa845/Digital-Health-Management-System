"""
Medical Information Extractor
------------------------------
Parses raw OCR text and identifies standard clinical parameters.

Design goals:
  - Works with diverse lab report layouts (header/value pairs, tables, free text).
  - Returns a list of ExtractedField dataclass instances.
  - Every regex is documented so it is easy to extend.
  - No external ML dependencies; pure Python regex + heuristics.

patient_field mapping (Patient model attribute → stored / updated by CDSA):
  height              → Patient.height
  weight              → Patient.weight
  blood_pressure      → Patient.blood_pressure
  blood_sugar_fasting → Patient.blood_sugar_fasting
  blood_sugar_random  → Patient.blood_sugar_random
  hemoglobin          → Patient.hemoglobin
  cholesterol_total   → Patient.cholesterol_total
  cholesterol_hdl     → Patient.cholesterol_hdl
  cholesterol_ldl     → Patient.cholesterol_ldl
  triglycerides       → Patient.triglycerides
  blood_group         → Patient.blood_group
  ''                  → display-only, not written to Patient
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ExtractedField:
    """A single medical parameter found in the OCR text."""
    field_name: str           # Human-readable label, e.g. "Hemoglobin"
    patient_field: str        # Django Patient model attribute, or '' if display-only
    extracted_value: str      # Raw extracted value string
    unit: str = ''            # Unit string, e.g. "g/dL"
    reference_range: str = '' # Reference range string, e.g. "12.0–17.5"


# ---------------------------------------------------------------------------
# Field definitions
# ---------------------------------------------------------------------------
# Each tuple: (human_label, patient_model_field, [regex_patterns])
#
# Pattern conventions:
#   (?P<val>...)  captures the value
#   (?P<unit>...) captures the unit
#   (?P<ref>...)  captures the reference range
#   All patterns compiled IGNORECASE | MULTILINE.

_FIELD_DEFS: list[tuple[str, str, list[str]]] = [

    # ── Height ───────────────────────────────────────────────────────────────
    ('Height', 'height', [
        r'height\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>cm|m)?',
        r'ht\.?\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>cm|m)?',
    ]),

    # ── Weight ───────────────────────────────────────────────────────────────
    ('Weight', 'weight', [
        r'weight\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d{1,2})?)\s*(?P<unit>kg|lbs?)?',
        r'wt\.?\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d{1,2})?)\s*(?P<unit>kg|lbs?)?',
        r'body\s+weight\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d{1,2})?)\s*(?P<unit>kg|lbs?)?',
    ]),

    # ── BMI (display-only — derived from height/weight, not stored directly) ─
    ('BMI', '', [
        r'b\.?m\.?i\.?\s*[:\-=]?\s*(?P<val>\d{1,2}(?:\.\d{1,2})?)',
        r'body\s+mass\s+index\s*[:\-=]?\s*(?P<val>\d{1,2}(?:\.\d{1,2})?)',
    ]),

    # ── Blood Pressure → Patient.blood_pressure ───────────────────────────────
    # Covers:
    #   "Blood Pressure: 120/80 mmHg"           (inline slash format)
    #   "BP 130/85"                              (abbreviated)
    #   "Blood Pressure (Systolic) 118 ... (Diastolic) 76"  (table with two rows)
    #   "Systolic: 120  Diastolic: 80"           (labelled pair)
    ('Blood Pressure', 'blood_pressure', [
        # Inline slash format — most common
        r'b(?:lood\s+)?p(?:ressure)?\s*[:\-=]?\s*(?P<val>\d{2,3}\s*/\s*\d{2,3})\s*(?P<unit>mm\s*hg)?',
        # Systolic/diastolic on same or nearby lines (DOTALL handled in fallback)
        r'systolic\s*[:\-=]?\s*(?P<sys>\d{2,3}).*?diastolic\s*[:\-=]?\s*(?P<dia>\d{2,3})',
    ]),

    # ── Pulse / Heart Rate (display-only) ─────────────────────────────────────
    ('Pulse / Heart Rate', '', [
        r'(?:pulse|heart\s+rate|hr)\s*[:\-=]?\s*(?P<val>\d{2,3})\s*(?P<unit>bpm|/\s*min)?',
    ]),

    # ── Temperature (display-only) ────────────────────────────────────────────
    ('Temperature', '', [
        r'(?:temperature|temp)\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d)?)\s*(?P<unit>°?[CF])',
    ]),

    # ── Hemoglobin → Patient.hemoglobin ──────────────────────────────────────
    # Covers:
    #   "Hemoglobin: 14.2 g/dL"
    #   "Hemoglobin (Hb) 14.6 g/dL"     (table format, no colon)
    #   "Hb: 13.5"
    ('Hemoglobin', 'hemoglobin', [
        r'h(?:ae?moglobin)\s*(?:\([^)]*\))?\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d{1,2})?)\s*(?P<unit>g\s*/\s*d[lL]|g%)?(?:\s*\((?P<ref>[^)]+)\))?',
        r'\bhb\b\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d{1,2})?)\s*(?P<unit>g\s*/\s*d[lL]|g%)?',
    ]),

    # ── Hematocrit (display-only) ─────────────────────────────────────────────
    ('Hematocrit', '', [
        r'h(?:ae?matocrit|ct|cv)\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d{1,2})?)\s*(?P<unit>%)?(?:\s*\((?P<ref>[^)]+)\))?',
    ]),

    # ── WBC Count (display-only) ──────────────────────────────────────────────
    ('WBC Count', '', [
        r'(?:wbc|white\s+blood\s+(?:cell|count)|leukocytes?)\s*[:\-=]?\s*(?P<val>\d{1,6}(?:\.\d{1,2})?)\s*(?P<unit>cells?/[mμ][lL]|×\s*10\^?\d+/[μu][lL]|k/[μu][lL])?',
    ]),

    # ── RBC Count (display-only) ──────────────────────────────────────────────
    ('RBC Count', '', [
        r'(?:rbc|red\s+blood\s+(?:cell|count)|erythrocytes?)\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d{1,2})?)\s*(?P<unit>mil?\/[μu][lL]|×\s*10\^?\d+/[μu][lL]|m/[μu][lL])?',
    ]),

    # ── Platelet Count (display-only) ─────────────────────────────────────────
    ('Platelet Count', '', [
        r'(?:platelet(?:s)?(?:\s+count)?|plt)\s*[:\-=]?\s*(?P<val>\d{1,6}(?:\.\d{1,2})?)\s*(?P<unit>×\s*10\^?\d+/[μu][lL]|k/[μu][lL]|/[μu][lL])?',
    ]),

    # ── ESR (display-only) ───────────────────────────────────────────────────
    ('ESR', '', [
        r'(?:esr|erythrocyte\s+sedimentation\s+rate)\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d)?)\s*(?P<unit>mm/hr?|mm/h)?',
    ]),

    # ── Blood Sugar (Fasting) → Patient.blood_sugar_fasting ──────────────────
    # Covers:
    #   "Fasting Blood Sugar: 92 mg/dL"
    #   "Blood Sugar (Fasting) 92 mg/dL"    (table format, qualifier in parens)
    #   "FBS 95"  /  "FBG 95"
    ('Blood Sugar (Fasting)', 'blood_sugar_fasting', [
        r'(?:fasting\s+(?:blood\s+)?(?:glucose|sugar)|fbg|fbs)\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|mmol\s*/\s*[lL])?',
        r'blood\s+sugar\s*\(\s*fasting\s*\)\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|mmol\s*/\s*[lL])?',
        r'(?:blood\s+sugar|glucose)\s+fasting\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|mmol\s*/\s*[lL])?',
        r'blood\s+sugar\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL])?\s*\(?\s*fasting',
    ]),

    # ── Blood Sugar (Random) → Patient.blood_sugar_random ────────────────────
    # Covers:
    #   "Random Blood Sugar: 145 mg/dL"
    #   "Blood Sugar (Random) 145 mg/dL"    (table format, qualifier in parens)
    #   "RBS 140"  /  "RBG 140"
    ('Blood Sugar (Random)', 'blood_sugar_random', [
        r'(?:random\s+(?:blood\s+)?(?:glucose|sugar)|rbg|rbs)\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|mmol\s*/\s*[lL])?',
        r'blood\s+sugar\s*\(\s*random\s*\)\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|mmol\s*/\s*[lL])?',
        r'(?:blood\s+sugar|glucose)\s+(?:random|pp|post\s*prandial)\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|mmol\s*/\s*[lL])?',
        r'blood\s+sugar\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL])?\s*\(?\s*random',
    ]),

    # ── HbA1c (display-only) ─────────────────────────────────────────────────
    ('HbA1c', '', [
        r'(?:hba1c|hb\s*a1c|glycated\s+hemoglobin|a1c)\s*[:\-=]?\s*(?P<val>\d{1,2}(?:\.\d{1,2})?)\s*(?P<unit>%)?',
    ]),

    # ── Total Cholesterol → Patient.cholesterol_total ────────────────────────
    ('Total Cholesterol', 'cholesterol_total', [
        r'(?:total\s+cholesterol|cholesterol[\s,]+total)\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|mmol\s*/\s*[lL])?',
        r'(?<!hdl\s)(?<!ldl\s)\bcholesterol\b(?!\s*(?:hdl|ldl|total|level))\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|mmol\s*/\s*[lL])?',
    ]),

    # ── HDL Cholesterol → Patient.cholesterol_hdl ────────────────────────────
    ('HDL Cholesterol', 'cholesterol_hdl', [
        r'hdl[\s\-]?(?:cholesterol|c)?\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|mmol\s*/\s*[lL])?',
        r'high[\s\-]density\s+lipoprotein\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL])?',
    ]),

    # ── LDL Cholesterol → Patient.cholesterol_ldl ────────────────────────────
    ('LDL Cholesterol', 'cholesterol_ldl', [
        r'ldl[\s\-]?(?:cholesterol|c)?\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|mmol\s*/\s*[lL])?',
        r'low[\s\-]density\s+lipoprotein\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL])?',
    ]),

    # ── Triglycerides → Patient.triglycerides ────────────────────────────────
    ('Triglycerides', 'triglycerides', [
        r'(?:triglycerides?|tg)\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|mmol\s*/\s*[lL])?',
    ]),

    # ── Renal / Liver / Thyroid (display-only) ────────────────────────────────
    ('Serum Creatinine', '', [
        r'(?:serum\s+)?creatinine\s*[:\-=]?\s*(?P<val>\d{1,2}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|μmol\s*/\s*[lL])?',
    ]),
    ('Blood Urea', '', [
        r'(?:blood\s+)?urea(?:\s+nitrogen)?\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|mmol\s*/\s*[lL])?',
    ]),
    ('Uric Acid', '', [
        r'uric\s+acid\s*[:\-=]?\s*(?P<val>\d{1,2}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|μmol\s*/\s*[lL])?',
    ]),
    ('SGPT / ALT', '', [
        r'(?:sgpt|alt|alanine\s+(?:amino)?transf(?:erase)?)\s*[:\-=]?\s*(?P<val>\d{1,4}(?:\.\d{1,2})?)\s*(?P<unit>u\s*/\s*[lL]|iu\s*/\s*[lL])?',
    ]),
    ('SGOT / AST', '', [
        r'(?:sgot|ast|aspartate\s+(?:amino)?transf(?:erase)?)\s*[:\-=]?\s*(?P<val>\d{1,4}(?:\.\d{1,2})?)\s*(?P<unit>u\s*/\s*[lL]|iu\s*/\s*[lL])?',
    ]),
    ('Bilirubin (Total)', '', [
        r'(?:total\s+bilirubin|bilirubin\s+total|bilirubin\b)\s*[:\-=]?\s*(?P<val>\d{1,2}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL])?',
    ]),
    ('TSH', '', [
        r'(?:tsh|thyroid\s+stimulating\s+hormone)\s*[:\-=]?\s*(?P<val>\d{1,4}(?:\.\d{1,4})?)\s*(?P<unit>m(?:iu|u)\s*/\s*[lL]|[μu]iu\s*/\s*m[lL])?',
    ]),
    ('T3', '', [
        r'\bT3\b\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d{1,2})?)\s*(?P<unit>ng\s*/\s*d[lL]|pmol\s*/\s*[lL])?',
    ]),
    ('T4', '', [
        r'\bT4\b\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d{1,2})?)\s*(?P<unit>[μu]g\s*/\s*d[lL]|pmol\s*/\s*[lL])?',
    ]),

    # ── Electrolytes (display-only) ───────────────────────────────────────────
    ('Sodium', '', [
        r'(?:sodium|na\+?)\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>m(?:mol|eq)\s*/\s*[lL])?',
    ]),
    ('Potassium', '', [
        r'(?:potassium|k\+?)\s*[:\-=]?\s*(?P<val>\d{1,2}(?:\.\d{1,2})?)\s*(?P<unit>m(?:mol|eq)\s*/\s*[lL])?',
    ]),

    # ── Blood Group → Patient.blood_group ────────────────────────────────────
    ('Blood Group', 'blood_group', [
        r'blood\s+(?:group|type)\s*[:\-=]?\s*(?P<val>[ABO]{1,2}[+-]?(?:\s+(?:positive|negative))?)',
        r'(?:group|type)\s*[:\-=]?\s*(?P<val>[ABO]{1,2}[+-])',
        r'\b(?P<val>(?:A|B|AB|O)\s*[+\-](?:ve)?)\b',
    ]),
]

# Pre-compile all patterns once at module load time
_COMPILED: list[tuple[str, str, list[re.Pattern]]] = [
    (label, pat_field, [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in patterns])
    for label, pat_field, patterns in _FIELD_DEFS
]


# ---------------------------------------------------------------------------
# Blood-group normaliser
# ---------------------------------------------------------------------------

_BG_MAP = {
    'a positive': 'A+', 'a negative': 'A-',
    'b positive': 'B+', 'b negative': 'B-',
    'ab positive': 'AB+', 'ab negative': 'AB-',
    'o positive': 'O+', 'o negative': 'O-',
    'a+ve': 'A+', 'a-ve': 'A-',
    'b+ve': 'B+', 'b-ve': 'B-',
    'ab+ve': 'AB+', 'ab-ve': 'AB-',
    'o+ve': 'O+', 'o-ve': 'O-',
}
_VALID_BG = {'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-'}


def _normalise_blood_group(raw: str) -> str | None:
    s = re.sub(r'\s+', ' ', raw.strip()).lower()
    if s in _BG_MAP:
        return _BG_MAP[s]
    candidate = re.sub(r'\s+', '', raw.strip().upper())
    if candidate in _VALID_BG:
        return candidate
    return None


# ---------------------------------------------------------------------------
# Numeric / BP validator
# ---------------------------------------------------------------------------

def _is_valid_number(value: str) -> bool:
    """Return True if value looks like a plausible clinical measurement."""
    # Blood pressure: "120/80"
    if re.match(r'^\d{2,3}/\d{2,3}$', value.strip()):
        return True
    try:
        Decimal(value.strip())
        return True
    except (InvalidOperation, ValueError):
        return False


# ---------------------------------------------------------------------------
# Special handler: systolic/diastolic on separate lines
# ---------------------------------------------------------------------------

_SYS_DIA_RE = re.compile(
    r'blood\s+pressure\s*\(\s*systolic\s*\)\s*[:\-=]?\s*(?P<sys>\d{2,3}).*?'
    r'blood\s+pressure\s*\(\s*diastolic\s*\)\s*[:\-=]?\s*(?P<dia>\d{2,3})',
    re.IGNORECASE | re.DOTALL,
)

_SYS_DIA_RE2 = re.compile(
    r'systolic\s*[:\-=]?\s*(?P<sys>\d{2,3}).*?diastolic\s*[:\-=]?\s*(?P<dia>\d{2,3})',
    re.IGNORECASE | re.DOTALL,
)


def _try_sys_dia(ocr_text: str) -> str | None:
    """Return 'SYS/DIA' string if systolic+diastolic found on separate lines."""
    for pattern in (_SYS_DIA_RE, _SYS_DIA_RE2):
        m = pattern.search(ocr_text)
        if m:
            return f"{m.group('sys')}/{m.group('dia')}"
    return None


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------

def extract_medical_fields(ocr_text: str) -> list[ExtractedField]:
    """
    Parse *ocr_text* and return a list of ExtractedField instances, one per
    matched clinical parameter.  Duplicate field names are deduplicated;
    first match wins (top-of-page values are most reliable).
    """
    if not ocr_text or not ocr_text.strip():
        return []

    results: list[ExtractedField] = []
    seen_labels: set[str] = set()

    for label, patient_field, patterns in _COMPILED:
        if label in seen_labels:
            continue

        matched = False
        for pattern in patterns:
            m = pattern.search(ocr_text)
            if not m:
                continue

            # --- Special case: systolic / diastolic split across lines -------
            if label == 'Blood Pressure' and 'sys' in pattern.groupindex:
                sys_v = m.group('sys')
                dia_v = m.group('dia')
                if sys_v and dia_v:
                    raw_val = f"{sys_v}/{dia_v}"
                    unit = ''
                    reference_range = ''
                    matched = True
                    break

            try:
                raw_val = m.group('val').strip()
            except IndexError:
                continue

            # --- per-field post-processing -----------------------------------
            if patient_field == 'blood_group':
                normalised = _normalise_blood_group(raw_val)
                if normalised is None:
                    continue
                raw_val = normalised
            else:
                # Normalise whitespace inside "120 / 80" → "120/80"
                raw_val = re.sub(r'\s*/\s*', '/', raw_val).strip()
                if not _is_valid_number(raw_val):
                    continue

            # Unit
            unit = ''
            try:
                unit = re.sub(r'\s+', ' ', (m.group('unit') or '').strip())
            except IndexError:
                pass

            # Reference range
            reference_range = ''
            try:
                reference_range = (m.group('ref') or '').strip()
            except IndexError:
                pass

            matched = True
            break  # stop trying further patterns for this label

        if matched:
            # For 'Blood Pressure' split-line case raw_val may already be set
            results.append(ExtractedField(
                field_name=label,
                patient_field=patient_field,
                extracted_value=raw_val,
                unit=unit,
                reference_range=reference_range,
            ))
            seen_labels.add(label)

    # Fallback: try systolic/diastolic split if BP not found yet
    if 'Blood Pressure' not in seen_labels:
        bp_val = _try_sys_dia(ocr_text)
        if bp_val:
            results.append(ExtractedField(
                field_name='Blood Pressure',
                patient_field='blood_pressure',
                extracted_value=bp_val,
                unit='mmHg',
            ))
            seen_labels.add('Blood Pressure')

    logger.info('Medical extractor found %d field(s) in OCR text.', len(results))
    return results
