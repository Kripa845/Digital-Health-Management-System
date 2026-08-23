from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ExtractedField:
    field_name: str
    patient_field: str
    extracted_value: str
    unit: str = ''
    reference_range: str = ''
    confidence: str = 'medium'
    raw_match: str = ''


# ── Field aliases for flexible matching ───────────────────────────────────────

FIELD_ALIASES: dict[str, list[str]] = {
    'blood_pressure': [
        'blood pressure', 'b.p.', 'blood pres',
        'systolic', 'diastolic',
    ],
    'heart_rate': [
        'heart rate', 'pulse', 'pulse rate',
    ],
    'spo2': [
        'spo2', 'sp o2', 'oxygen saturation', 'o2 saturation',
    ],
    'blood_sugar_fasting': [
        'fasting blood sugar', 'fasting glucose', 'fbs', 'fbg',
        'blood sugar fasting', 'glucose fasting',
        'blood sugar (fasting)',
    ],
    'blood_sugar_random': [
        'random blood sugar', 'random glucose', 'rbs', 'rbg',
        'blood sugar random', 'glucose random',
        'blood sugar (random)', 'post prandial', 'pp blood sugar',
    ],
    'hemoglobin': [
        'hemoglobin', 'haemoglobin', 'hb', 'hgb',
    ],
    'cholesterol_total': [
        'total cholesterol', 'cholesterol total', 'total chol', 'chol total',
    ],
    'cholesterol_hdl': [
        'hdl cholesterol', 'hdl', 'high density lipoprotein',
    ],
    'cholesterol_ldl': [
        'ldl cholesterol', 'ldl', 'low density lipoprotein',
    ],
    'triglycerides': [
        'triglycerides', 'tg', 'trig',
    ],
    'height': [
        'height', 'ht',
    ],
    'weight': [
        'weight', 'wt', 'body weight',
    ],
    'blood_group': [
        'blood group', 'blood type', 'group', 'type',
    ],
    'temperature': [
        'temperature', 'temp', 'body temperature',
    ],
    'hematocrit': [
        'hematocrit', 'hct', 'hcv', 'packed cell volume',
    ],
    'wbc_count': [
        'wbc', 'white blood cell', 'white blood count', 'leukocyte',
    ],
    'rbc_count': [
        'rbc', 'red blood cell', 'red blood count', 'erythrocyte',
    ],
    'platelet_count': [
        'platelet', 'plt', 'thrombocyte',
    ],
    'esr': [
        'esr', 'erythrocyte sedimentation rate', 'sed rate',
    ],
    'hba1c': [
        'hba1c', 'hb a1c', 'a1c', 'glycated hemoglobin',
    ],
    'serum_creatinine': [
        'creatinine', 'serum creatinine',
    ],
    'blood_urea': [
        'urea', 'blood urea', 'blood urea nitrogen', 'bun',
    ],
    'uric_acid': [
        'uric acid', 'urate',
    ],
    'ssgpt_alt': [
        'sgpt', 'alt', 'alanine aminotransferase', 'alanine transaminase',
    ],
    'ssgot_ast': [
        'sgot', 'ast', 'aspartate aminotransferase', 'aspartate transaminase',
    ],
    'bilirubin_total': [
        'bilirubin', 'total bilirubin',
    ],
    'tsh': [
        'tsh', 'thyroid stimulating hormone',
    ],
    't3': [
        't3', 'triiodothyronine',
    ],
    't4': [
        't4', 'thyroxine',
    ],
    'sodium': [
        'sodium', 'na+', 'serum sodium',
    ],
    'potassium': [
        'potassium', 'k+', 'serum potassium',
    ],
}


# ── Original field definitions ────────────────────────────────────────────────

_FIELD_DEFS: list[tuple[str, str, list[str]]] = [
    ('Height', 'height', [
        r'height\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>cm|m)?',
        r'ht\.?\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>cm|m)?',
    ]),
    ('Weight', 'weight', [
        r'weight\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d{1,2})?)\s*(?P<unit>kg|lbs?)?',
        r'wt\.?\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d{1,2})?)\s*(?P<unit>kg|lbs?)?',
        r'body\s+weight\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d{1,2})?)\s*(?P<unit>kg|lbs?)?',
    ]),
    ('BMI', '', [
        r'b\.?m\.?i\.?\s*[:\-=]?\s*(?P<val>\d{1,2}(?:\.\d{1,2})?)',
        r'body\s+mass\s+index\s*[:\-=]?\s*(?P<val>\d{1,2}(?:\.\d{1,2})?)',
    ]),
    ('Blood Pressure', 'blood_pressure', [
        r'b(?:lood\s+)?p(?:ressure)?\s*[:\-=]?\s*(?P<val>\d{2,3}\s*/\s*\d{2,3})\s*(?P<unit>mm\s*hg)?',
        r'systolic\s*[:\-=]?\s*(?P<sys>\d{2,3}).*?diastolic\s*[:\-=]?\s*(?P<dia>\d{2,3})',
    ]),
    ('Pulse / Heart Rate', 'heart_rate', [
        r'(?:pulse|heart\s+rate)\s*[:\-=]?\s*(?P<val>\d{2,3})\s*(?P<unit>bpm|/\s*min)?',
        r'\bhr\b\s*[:\-=]?\s*(?P<val>\d{2,3})\s*(?P<unit>bpm|/\s*min)?',
    ]),
    ('SpO2', 'spo2', [
        r'(?:spo2|sp\.?\s*o2|oxygen\s+saturation)\s*[:\-=]?\s*(?P<val>\d{2,3})\s*(?P<unit>%)?',
    ]),
    ('Temperature', 'temperature', [
        r'(?:temperature|temp)\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d)?)\s*(?P<unit>°?[CF])',
    ]),
    ('Hemoglobin', 'hemoglobin', [
        r'h(?:ae?moglobin)\s*(?:\([^)]*\))?\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d{1,2})?)\s*(?P<unit>g\s*/\s*d[lL]|g%)?(?:\s*\((?P<ref>[^)]+)\))?',
        r'\bhb\b\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d{1,2})?)\s*(?P<unit>g\s*/\s*d[lL]|g%)?',
    ]),
    ('Hematocrit', 'hematocrit', [
        r'h(?:ae?matocrit|ct|cv)\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d{1,2})?)\s*(?P<unit>%)?(?:\s*\((?P<ref>[^)]+)\))?',
    ]),
    ('WBC Count', 'wbc_count', [
        r'(?:wbc|white\s+blood\s+(?:cell|count)|leukocytes?)\s*[:\-=]?\s*(?P<val>\d{1,6}(?:\.\d{1,2})?)\s*(?P<unit>cells?/[mμ][lL]|×\s*10\^?\d+/[μu][lL]|k/[μu][lL])?',
    ]),
    ('RBC Count', 'rbc_count', [
        r'(?:rbc|red\s+blood\s+(?:cell|count)|erythrocytes?)\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d{1,2})?)\s*(?P<unit>mil?\/[μu][lL]|×\s*10\^?\d+/[μu][lL]|m/[μu][lL])?',
    ]),
    ('Platelet Count', 'platelet_count', [
        r'(?:platelet(?:s)?(?:\s+count)?|plt)\s*[:\-=]?\s*(?P<val>\d{1,6}(?:\.\d{1,2})?)\s*(?P<unit>×\s*10\^?\d+/[μu][lL]|k/[μu][lL]|/[μu][lL])?',
    ]),
    ('ESR', 'esr', [
        r'(?:esr|erythrocyte\s+sedimentation\s+rate)\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d)?)\s*(?P<unit>mm/hr?|mm/h)?',
    ]),
    ('Blood Sugar (Fasting)', 'blood_sugar_fasting', [
        r'(?:fasting\s+(?:blood\s+)?(?:glucose|sugar)|fbg|fbs)\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|mmol\s*/\s*[lL])?',
        r'blood\s+sugar\s*\(\s*fasting\s*\)\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|mmol\s*/\s*[lL])?',
        r'(?:blood\s+sugar|glucose)\s+fasting\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|mmol\s*/\s*[lL])?',
        r'blood\s+sugar\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL])?\s*\(?\s*fasting',
    ]),
    ('Blood Sugar (Random)', 'blood_sugar_random', [
        r'(?:random\s+(?:blood\s+)?(?:glucose|sugar)|rbg|rbs)\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|mmol\s*/\s*[lL])?',
        r'blood\s+sugar\s*\(\s*random\s*\)\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|mmol\s*/\s*[lL])?',
        r'(?:blood\s+sugar|glucose)\s+(?:random|pp|post\s*prandial)\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|mmol\s*/\s*[lL])?',
        r'blood\s+sugar\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL])?\s*\(?\s*random',
    ]),
    ('HbA1c', 'hba1c', [
        r'(?:hba1c|hb\s*a1c|glycated\s+hemoglobin|a1c)\s*[:\-=]?\s*(?P<val>\d{1,2}(?:\.\d{1,2})?)\s*(?P<unit>%)?',
    ]),
    ('Total Cholesterol', 'cholesterol_total', [
        r'(?:total\s+cholesterol|cholesterol[\s,]+total)\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|mmol\s*/\s*[lL])?',
        r'(?<!hdl\s)(?<!ldl\s)\bcholesterol\b(?!\s*(?:hdl|ldl|total|level))\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|mmol\s*/\s*[lL])?',
    ]),
    ('HDL Cholesterol', 'cholesterol_hdl', [
        r'hdl[\s\-]?(?:cholesterol|c)?\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|mmol\s*/\s*[lL])?',
        r'high[\s\-]density\s+lipoprotein\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL])?',
    ]),
    ('LDL Cholesterol', 'cholesterol_ldl', [
        r'ldl[\s\-]?(?:cholesterol|c)?\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|mmol\s*/\s*[lL])?',
        r'low[\s\-]density\s+lipoprotein\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL])?',
    ]),
    ('Triglycerides', 'triglycerides', [
        r'(?:triglycerides?|tg)\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|mmol\s*/\s*[lL])?',
    ]),
    ('Serum Creatinine', 'serum_creatinine', [
        r'(?:serum\s+)?creatinine\s*[:\-=]?\s*(?P<val>\d{1,2}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|μmol\s*/\s*[lL])?',
    ]),
    ('Blood Urea', 'blood_urea', [
        r'(?:blood\s+)?urea(?:\s+nitrogen)?\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|mmol\s*/\s*[lL])?',
    ]),
    ('Uric Acid', 'uric_acid', [
        r'uric\s+acid\s*[:\-=]?\s*(?P<val>\d{1,2}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL]|μmol\s*/\s*[lL])?',
    ]),
    ('SGPT / ALT', 'ssgpt_alt', [
        r'(?:sgpt|alt|alanine\s+(?:amino)?transf(?:erase)?)\s*[:\-=]?\s*(?P<val>\d{1,4}(?:\.\d{1,2})?)\s*(?P<unit>u\s*/\s*[lL]|iu\s*/\s*[lL])?',
    ]),
    ('SGOT / AST', 'ssgot_ast', [
        r'(?:sgot|ast|aspartate\s+(?:amino)?transf(?:erase)?)\s*[:\-=]?\s*(?P<val>\d{1,4}(?:\.\d{1,2})?)\s*(?P<unit>u\s*/\s*[lL]|iu\s*/\s*[lL])?',
    ]),
    ('Bilirubin (Total)', 'bilirubin_total', [
        r'(?:total\s+bilirubin|bilirubin\s+total|bilirubin\b)\s*[:\-=]?\s*(?P<val>\d{1,2}(?:\.\d{1,2})?)\s*(?P<unit>mg\s*/\s*d[lL])?',
    ]),
    ('TSH', 'tsh', [
        r'(?:tsh|thyroid\s+stimulating\s+hormone)\s*[:\-=]?\s*(?P<val>\d{1,4}(?:\.\d{1,4})?)\s*(?P<unit>m(?:iu|u)\s*/\s*[lL]|[μu]iu\s*/\s*m[lL])?',
    ]),
    ('T3', 't3', [
        r'\bT3\b\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d{1,2})?)\s*(?P<unit>ng\s*/\s*d[lL]|pmol\s*/\s*[lL])?',
    ]),
    ('T4', 't4', [
        r'\bT4\b\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d{1,2})?)\s*(?P<unit>[μu]g\s*/\s*d[lL]|pmol\s*/\s*[lL])?',
    ]),
    ('Sodium', 'sodium', [
        r'(?:sodium|na\+?)\s*[:\-=]?\s*(?P<val>\d{2,3}(?:\.\d{1,2})?)\s*(?P<unit>m(?:mol|eq)\s*/\s*[lL])?',
    ]),
    ('Potassium', 'potassium', [
        r'(?:potassium|k\+?)\s*[:\-=]?\s*(?P<val>\d{1,2}(?:\.\d{1,2})?)\s*(?P<unit>m(?:mol|eq)\s*/\s*[lL])?',
    ]),
    ('Blood Group', 'blood_group', [
        r'blood\s+(?:group|type)\s*[:\-=]?\s*(?P<val>[ABO]{1,2}[+-]?(?:\s+(?:positive|negative))?)',
        r'(?:group|type)\s*[:\-=]?\s*(?P<val>[ABO]{1,2}[+-])',
        r'\b(?P<val>(?:A|B|AB|O)\s*[+\-](?:ve)?)\b',
    ]),
]

_COMPILED: list[tuple[str, str, list[re.Pattern]]] = [
    (label, pat_field, [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in patterns])
    for label, pat_field, patterns in _FIELD_DEFS
]

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

_SYS_DIA_RE = re.compile(
    r'blood\s+pressure\s*\(\s*systolic\s*\)\s*[:\-=]?\s*(?P<sys>\d{2,3}).*?'
    r'blood\s+pressure\s*\(\s*diastolic\s*\)\s*[:\-=]?\s*(?P<dia>\d{2,3})',
    re.IGNORECASE | re.DOTALL,
)
_SYS_DIA_RE2 = re.compile(
    r'systolic\s*[:\-=]?\s*(?P<sys>\d{2,3}).*?diastolic\s*[:\-=]?\s*(?P<dia>\d{2,3})',
    re.IGNORECASE | re.DOTALL,
)


# ── Normalization ─────────────────────────────────────────────────────────────

def normalize_ocr_text(text: str) -> str:
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.replace('|', ' ').replace('_', ' ')
    text = re.sub(r'\bO\b(?=\s*\d)', '0', text, flags=re.IGNORECASE)
    text = re.sub(r'\bl\b(?=\s*\d)', '1', text, flags=re.IGNORECASE)
    return text.strip()


def _normalise_blood_group(raw: str) -> str | None:
    s = re.sub(r'\s+', ' ', raw.strip()).lower()
    if s in _BG_MAP:
        return _BG_MAP[s]
    candidate = re.sub(r'\s+', '', raw.strip().upper())
    if candidate in _VALID_BG:
        return candidate
    return None


# ── Validation ───────────────────────────────────────────────────────────────

_VALID_UNITS = {
    'mg/dl', 'mmol/l', 'g/dl', 'g%', '%', 'bpm', 'cm', 'm', 'kg', 'lbs', 'lb',
    'mmhg', 'mm/hg', 'cells/ul', 'k/ul', 'u/l', 'iu/l', 'ng/dl', 'pmol/l',
    'ug/dl', 'μmol/l', 'meq/l', 'mmol/l',
}


def _is_valid_number(value: str) -> bool:
    if re.match(r'^\d{2,3}/\d{2,3}$', value.strip()):
        return True
    try:
        Decimal(value.strip())
        return True
    except (InvalidOperation, ValueError):
        return False


def _is_reference_range_line(text: str) -> bool:
    text = text.strip()
    if not text:
        return False
    if re.match(r'^\d+[\s.\d]*[-–—]\s*\d+[\s.\d]*(\s+\w+)?$', text):
        return True
    if re.match(r'^\d+\s+to\s+\d+(\s+\w+)?$', text, re.IGNORECASE):
        return True
    return False


def validate_blood_pressure(value: str) -> bool:
    m = re.match(r'^(\d{2,3})\s*/\s*(\d{2,3})$', value.strip())
    if not m:
        return False
    sys, dia = int(m.group(1)), int(m.group(2))
    return 60 <= sys <= 220 and 40 <= dia <= 140


def validate_numeric_result(value: str, field: str) -> bool:
    if not _is_valid_number(value):
        return False
    if field == 'blood_pressure':
        return validate_blood_pressure(value)
    try:
        n = float(value.strip())
    except ValueError:
        return False
    if field == 'height':
        return 30 <= n <= 250
    if field == 'weight':
        return 1 <= n <= 300
    if field == 'hemoglobin':
        return 2 <= n <= 25
    if field in ('blood_sugar_fasting', 'blood_sugar_random'):
        return 20 <= n <= 600
    if field in ('cholesterol_total', 'cholesterol_hdl', 'cholesterol_ldl', 'triglycerides'):
        return 10 <= n <= 1000
    return True


# ── Nearby-line search ────────────────────────────────────────────────────────

def _extract_value_from_line(line: str, field_name: str) -> Optional[str]:
    """Try to extract a numeric value from the same line as the field alias."""
    # Handle blood pressure specially - look for sys/dia pattern
    if field_name == 'blood_pressure':
        m = re.search(r'(\d{2,3}\s*/\s*\d{2,3})', line)
        if m:
            return m.group(1)
    # Look for patterns like "Label: value" or "Label = value"
    patterns = [
        rf'{field_name.replace("_", " ")}\s*[:\-=]\s*(\d{{1,3}}(?:\.\d{{1,2}})?)',
        rf'{field_name.replace("_", " ")}\s+(\d{{1,3}}(?:\.\d{{1,2}})?)',
    ]
    for pattern in patterns:
        m = re.search(pattern, line, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _search_nearby_lines(lines: list[str], idx: int, max_lookahead: int = 6) -> Optional[str]:
    for offset in range(0, max_lookahead + 1):
        if idx + offset >= len(lines):
            break
        candidate = lines[idx + offset].strip()
        if not candidate:
            continue
        if _is_reference_range_line(candidate):
            continue
        if _is_valid_number(candidate):
            return candidate
        m = re.search(r'(\d{2,3}\s*/\s*\d{2,3})', candidate)
        if m:
            return m.group(1)
        m = re.search(r'(\d{1,3}(?:\.\d{1,2})?)', candidate)
        if m:
            return m.group(1)
    return None


def _search_nearby_table(lines: list[str], idx: int, max_lookahead: int = 6) -> Optional[tuple[str, str]]:
    for offset in range(0, max_lookahead + 1):
        if idx + offset >= len(lines):
            break
        candidate = lines[idx + offset].strip()
        if not candidate:
            continue
        parts = re.split(r'\s{2,}', candidate)
        if len(parts) >= 2:
            val = parts[1].strip()
            unit = parts[2].strip() if len(parts) > 2 else ''
            if _is_valid_number(val):
                return val, unit
    return None


# ── Core extraction ───────────────────────────────────────────────────────────

def _try_sys_dia(ocr_text: str) -> str | None:
    for pattern in (_SYS_DIA_RE, _SYS_DIA_RE2):
        m = pattern.search(ocr_text)
        if m:
            return f"{m.group('sys')}/{m.group('dia')}"
    return None


def _apply_alias_match(label: str, line: str) -> bool:
    aliases = FIELD_ALIASES.get(label.lower(), [])
    if not aliases:
        return False
    line_lower = line.lower()
    return any(alias in line_lower for alias in aliases)


def extract_medical_fields(ocr_text: str) -> list[ExtractedField]:
    if not ocr_text or not ocr_text.strip():
        return []

    normalized = normalize_ocr_text(ocr_text)
    lines = normalized.split('\n')
    results: list[ExtractedField] = []
    seen_patient_fields: set[str] = set()

    def _add(field: ExtractedField):
        pf = field.patient_field
        if pf and pf in seen_patient_fields:
            return
        if pf:
            seen_patient_fields.add(pf)
        results.append(field)

    # 1. Try alias-based nearby-line extraction first
    for internal_field, aliases in FIELD_ALIASES.items():
        if internal_field in seen_patient_fields:
            continue
        for i, line in enumerate(lines):
            line_lower = line.lower()
            if any(alias in line_lower for alias in aliases):
                # First try to find value on the same line after the alias
                val_on_same_line = _extract_value_from_line(line, internal_field)
                if val_on_same_line:
                    confidence = 'high' if validate_numeric_result(val_on_same_line, internal_field) else 'medium'
                    _add(ExtractedField(
                        field_name=internal_field.replace('_', ' ').title(),
                        patient_field=internal_field,
                        extracted_value=val_on_same_line,
                        confidence=confidence,
                        raw_match=line,
                    ))
                    break
                # Then try nearby lines
                nearby = _search_nearby_lines(lines, i, max_lookahead=6)
                if nearby:
                    confidence = 'high' if validate_numeric_result(nearby, internal_field) else 'medium'
                    _add(ExtractedField(
                        field_name=internal_field.replace('_', ' ').title(),
                        patient_field=internal_field,
                        extracted_value=nearby,
                        confidence=confidence,
                        raw_match=line,
                    ))
                    break

    # 2. Try original regex definitions
    for label, patient_field, patterns in _COMPILED:
        pf = patient_field or label
        if pf in seen_patient_fields:
            continue

        matched = False
        for pattern in patterns:
            m = pattern.search(normalized)
            if not m:
                continue

            if label == 'Blood Pressure' and 'sys' in pattern.groupindex:
                sys_v = m.group('sys')
                dia_v = m.group('dia')
                if sys_v and dia_v:
                    raw_val = f"{sys_v}/{dia_v}"
                    unit = ''
                    reference_range = ''
                    confidence = 'high' if validate_blood_pressure(raw_val) else 'medium'
                    matched = True
                    _add(ExtractedField(
                        field_name=label,
                        patient_field=patient_field,
                        extracted_value=raw_val,
                        unit=unit,
                        reference_range=reference_range,
                        confidence=confidence,
                        raw_match=m.group(0),
                    ))
                break

            try:
                raw_val = m.group('val').strip()
            except IndexError:
                continue

            if patient_field == 'blood_group':
                normalised = _normalise_blood_group(raw_val)
                if normalised is None:
                    continue
                raw_val = normalised
            else:
                raw_val = re.sub(r'\s*/\s*', '/', raw_val).strip()
                if not _is_valid_number(raw_val):
                    continue

            unit = ''
            try:
                unit = re.sub(r'\s+', ' ', (m.group('unit') or '').strip())
            except IndexError:
                pass

            reference_range = ''
            try:
                reference_range = (m.group('ref') or '').strip()
            except IndexError:
                pass

            confidence = 'high'
            if patient_field and not validate_numeric_result(raw_val, patient_field):
                confidence = 'low'

            matched = True
            _add(ExtractedField(
                field_name=label,
                patient_field=patient_field,
                extracted_value=raw_val,
                unit=unit,
                reference_range=reference_range,
                confidence=confidence,
                raw_match=m.group(0),
            ))
            break

    # 3. Blood pressure sys/dia fallback
    if 'blood_pressure' not in seen_patient_fields:
        bp_val = _try_sys_dia(normalized)
        if bp_val:
            confidence = 'high' if validate_blood_pressure(bp_val) else 'medium'
            _add(ExtractedField(
                field_name='Blood Pressure',
                patient_field='blood_pressure',
                extracted_value=bp_val,
                unit='mmHg',
                confidence=confidence,
            ))

    logger.info('Medical extractor found %d field(s) in OCR text.', len(results))
    return results
