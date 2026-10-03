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
        'haemoglobin', 'hemoglobin', 'hb', 'hgb',
        # Common OCR misreads (i/l/1 and o/0 confused)
        'haemoglobln', 'hemoglobln', 'haemoglob1n', 'hemoglob1n',
        'haemog1obin', 'hemog1obin', 'haemogl0bin', 'hemogl0bin',
    ],
    'cholesterol_total': [
        'total cholesterol', 'cholesterol total', 'total chol', 'chol total',
        't. chol', 't.chol', 't chol', 't. cholesterol', 's. cholesterol', 'serum cholesterol',
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
    'temperature': [
        'temperature', 'temp', 'body temperature',
    ],
    'hematocrit': [
        'haematocrit', 'hematocrit', 'hct', 'hcv', 'packed cell volume',
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
        # OCR reads the "1" as I, l or |, and may split the word ("HbAIC", "HbAlC", "HbA1 C").
        'hbaic', 'hbalc', 'hba|c', 'hb aic', 'hb alc', 'hba1 c', 'hb a1 c',
        'glycated haemoglobin', 'glycosylated hemoglobin', 'glycosylated haemoglobin',
        'haemoglobin a1c', 'hemoglobin a1c',
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


# Names shown to users where the field key would read wrongly (British spelling,
# as printed on Nepali lab reports).
_DISPLAY_NAMES: dict[str, str] = {
    'hemoglobin': 'Haemoglobin',
    'hematocrit': 'Haematocrit',
    'hba1c': 'HbA1C',
    'spo2': 'SpO2',
    'ssgpt_alt': 'SGPT / ALT',
    'ssgot_ast': 'SGOT / AST',
    'tsh': 'TSH',
    't3': 'T3',
    't4': 'T4',
    'esr': 'ESR',
    'wbc_count': 'WBC Count',
    'rbc_count': 'RBC Count',
    'cholesterol_hdl': 'HDL Cholesterol',
    'cholesterol_ldl': 'LDL Cholesterol',
    'cholesterol_total': 'Total Cholesterol',
    'blood_sugar_fasting': 'Blood Sugar (Fasting)',
    'blood_sugar_random': 'Blood Sugar (Random)',
}


def display_name(field: str) -> str:
    return _DISPLAY_NAMES.get(field, field.replace('_', ' ').title())


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
    ('Haemoglobin', 'hemoglobin', [
        # Haemoglobin / Hemoglobin, tolerating OCR misreads such as "Haemoglobln" or "Hemog1obin".
        r'h(?:a?e)mog[l1i][o0]b[il1]n\s*(?:\([^)]*\))?\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d{1,2})?)\s*(?P<unit>g\s*/\s*d[lL]|g%)?(?:\s*\((?P<ref>[^)]+)\))?',
        r'\bhb\b\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d{1,2})?)\s*(?P<unit>g\s*/\s*d[lL]|g%)?',
    ]),
    ('Haematocrit', 'hematocrit', [
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
    ('HbA1C', 'hba1c', [
        r'(?:h\s*b\s*a\s*[1il|]\s*c|glyc(?:at|osyl)ated\s+ha?emoglobin|ha?emoglobin\s+a[1il|]c|(?<![a-z])a1c)'
        r'(?:\s*\([^)\n]*\))?\s*[:\-=]?\s*(?P<val>\d{1,2}(?:\.\d{1,2})?)\s*(?P<unit>%)?',
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
        # Only an explicit "Blood group/type:" label is trusted; a bare "A+"
        # elsewhere in a report (grades, footnotes) must never set the group.
        r'blood\s+(?:group|type)\s*[:\-=]?\s*(?P<val>(?:AB|A|B|O)\s*(?:[+\-](?:ve)?|\s+(?:positive|negative)))',
    ]),
]

# Every pattern starts at a word boundary, so "ast" never matches inside "past"
# and "alt" never matches inside "salt".
_COMPILED: list[tuple[str, str, list[re.Pattern]]] = [
    (label, pat_field, [re.compile(rf'(?<![a-z0-9])(?:{p})', re.IGNORECASE | re.MULTILINE) for p in patterns])
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
    # A lone O or l before a number is usually a misread 0 or 1. Letters that are
    # part of a unit ("mmol/L 3.9-5.5", "g/L 120") are left alone.
    text = re.sub(r'(?<![\w/])O(?![\w/])(?=\s*\d)', '0', text, flags=re.IGNORECASE)
    text = re.sub(r'(?<![\w/])l(?![\w/])(?=\s*\d)', '1', text, flags=re.IGNORECASE)
    # A decimal comma ("13,13 g/dl") is a decimal point; "1,234" (thousands) is left alone.
    text = re.sub(r'(?<![\d,.])(\d{1,3}),(\d{1,2})(?![\d,])', r'\1.\2', text)
    return text.strip()


def _normalise_blood_group(raw: str) -> str | None:
    s = re.sub(r'\s+', ' ', raw.strip()).lower()
    if s in _BG_MAP:
        return _BG_MAP[s]
    compact = s.replace(' ', '')                      # "O +ve" → "o+ve"
    if compact in _BG_MAP:
        return _BG_MAP[compact]
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


# Physiologically plausible bounds. A value outside them is treated as an OCR
# misread and is never written to the patient record.
_PLAUSIBLE_RANGES: dict[str, tuple[float, float]] = {
    'height': (30, 250),
    'weight': (1, 300),
    'hemoglobin': (3, 25),
    'blood_sugar_fasting': (20, 600),
    'blood_sugar_random': (20, 800),
    'cholesterol_total': (50, 500),
    'cholesterol_hdl': (10, 1000),
    'cholesterol_ldl': (10, 1000),
    'triglycerides': (10, 1000),
    'heart_rate': (30, 220),
    'spo2': (50, 100),
    'temperature': (30, 110),
    'hba1c': (3, 20),
    'serum_creatinine': (0.1, 20),
    'blood_urea': (1, 300),
    'uric_acid': (0.5, 20),
    'ssgpt_alt': (1, 999),
    'ssgot_ast': (1, 999),
    'bilirubin_total': (0.1, 50),
    'tsh': (0.001, 150),
    't3': (0.1, 999),
    't4': (0.1, 99),
    'sodium': (100, 180),
    'potassium': (1.5, 10),
    'wbc_count': (0.1, 9999),
    'rbc_count': (0.5, 15),
    'platelet_count': (1, 9999),
    'hematocrit': (5, 75),
    'esr': (0, 200),
}


def validate_numeric_result(value: str, field: str) -> bool:
    if not _is_valid_number(value):
        return False
    if field == 'blood_pressure':
        return validate_blood_pressure(value)
    try:
        n = float(value.strip())
    except ValueError:
        return False
    bounds = _PLAUSIBLE_RANGES.get(field)
    if bounds is None:
        return True
    low, high = bounds
    return low <= n <= high


# ── Nearby-line search ────────────────────────────────────────────────────────

# The value must follow its label: a few non-digit characters (":", "(Hb)",
# table spacing) and then the number. Taking the first number anywhere on the
# line would read "SGPT: 34  SGOT: 28" as SGOT = 34.
_BP_AFTER_LABEL = re.compile(r'^[^\d\n]{0,30}?(\d{2,3}\s*/\s*\d{2,3})')
# A number stuck to a letter ("a4l") is an OCR misread, not a result.
_NUM_AFTER_LABEL = re.compile(r'^[^\d\n]{0,30}?(?<![A-Za-z])(\d{1,6}(?:\.\d{1,3})?)(?!\s*[-–—]\s*\d)')


# A unit printed right after the value (longest spellings first).
_UNIT_AFTER_VALUE = re.compile(
    r'^\s*(?P<unit>mmol\s*/\s*mol|mmol\s*/\s*l|[µμu]mol\s*/\s*l|mg\s*/\s*dl|mg\s*%|'
    r'gm?s?\s*/\s*dl|gm?\s*/\s*l|gm?\s*%|m?eq\s*/\s*l|[µμu]?iu\s*/\s*ml|m?iu\s*/\s*l|'
    r'u\s*/\s*l|ng\s*/\s*dl|[µμu]g\s*/\s*dl|mm\s*/?\s*hg|mm\s*/\s*h(?:r|our)?|bpm|/\s*min|'
    r'%|kgs?|lbs?|cm|in(?:ches)?|m|°?\s*[cf])(?![a-z])',
    re.IGNORECASE,
)


def _unit_after(text: str) -> str:
    m = _UNIT_AFTER_VALUE.match(text or '')
    return re.sub(r'\s+', '', m.group('unit')) if m else ''


# Lines that mention haemoglobin but are not the haemoglobin result: HbA1c
# ("Glycated Haemoglobin", "Haemoglobin A1c", OCR "HbAIC") and the red cell
# indices ("Mean Cell Haemoglobin", MCH, MCHC).
_NOT_HAEMOGLOBIN_LINE = re.compile(
    r'h\s*b\s*a\s*[1il|]\s*c|a[1il|]c\b|glyc|mean\s+cell|corpuscular|\bmchc?\b', re.IGNORECASE)


def _on_excluded_line(text: str, m: re.Match, field: str) -> bool:
    """Whether a haemoglobin match sits on an HbA1c or red-cell-index line."""
    if field != 'hemoglobin':
        return False
    start = text.rfind('\n', 0, m.start()) + 1
    end = text.find('\n', m.end())
    return bool(_NOT_HAEMOGLOBIN_LINE.search(text[start:end if end != -1 else len(text)]))


def _first_match(pattern: re.Pattern, text: str, field: str) -> Optional[re.Match]:
    return next((m for m in pattern.finditer(text) if not _on_excluded_line(text, m, field)), None)


def _value_after_alias(field: str, line: str) -> tuple[bool, Optional[str], str]:
    """Return (alias found, value that follows the alias on the same line, its unit)."""
    if field == 'hemoglobin' and _NOT_HAEMOGLOBIN_LINE.search(line):
        return False, None, ''
    found = False
    for rx in _ALIAS_RES.get(field, []):
        for m in rx.finditer(line):
            found = True
            rest = line[m.end():]
            pattern = _BP_AFTER_LABEL if field == 'blood_pressure' else _NUM_AFTER_LABEL
            v = pattern.search(rest)
            if v:
                return True, re.sub(r'\s*/\s*', '/', v.group(1)), _unit_after(rest[v.end():])
    return found, None, ''


def _search_following_lines(lines: list[str], idx: int, field: str, max_lookahead: int = 2) -> tuple[Optional[str], str]:
    """Look for a value (and its unit) printed on its own line just below the label."""
    for offset in range(1, max_lookahead + 1):
        if idx + offset >= len(lines):
            break
        candidate = lines[idx + offset].strip()
        if not candidate or _is_reference_range_line(candidate):
            continue
        # Only a line that starts with the value counts; a line that starts with
        # another label belongs to a different test.
        pattern = r'^(\d{2,3}\s*/\s*\d{2,3})' if field == 'blood_pressure' else r'^(\d{1,6}(?:\.\d{1,3})?)\b'
        m = re.match(pattern, candidate)
        if m:
            unit = _unit_after(candidate[m.end():])
            if not unit and offset + idx + 1 < len(lines):
                unit = _unit_after(lines[idx + offset + 1])   # "118/76" then "mmHg" below
            return re.sub(r'\s*/\s*', '/', m.group(1)), unit
        return None, ''
    return None, ''


# ── Flexible patterns for the main dashboard tests ────────────────────────────
# Used when the stricter patterns above find nothing: the label, then up to 40
# characters without digits on the same line (":", "(Hb)", a method name, table
# spacing), then the number. Fasting / post-prandial sugar and HbA1c are excluded.

_CORE_GAP = r'[^\d\n]{0,40}?'
_CORE_NUMBER = r'(?<![A-Za-z])(?P<val>\d{1,4}(?:\.\d{1,3})?)(?!\s*[-–—]\s*\d)(?!\.?\d)'
_CORE_LABELS: dict[str, str] = {
    'hemoglobin': r'(?<!glycated )(?<!glycosylated )(?<!cell )\b(?:ha?emoglobin|hgb|hb)\b(?![ \t]*a[1il|]c)(?![ \t]*conc)',
    'cholesterol_total': r'\b(?:total[ \t]+cholesterol|cholesterol[ \t]*,?[ \t]*total|t\.?[ \t]*chol(?:esterol)?)\b',
    'blood_sugar_random': (
        r'\b(?:random[ \t]+(?:blood[ \t]+)?(?:sugar|glucose)|rbs|glucose[ \t]*[-–(,]?[ \t]*random'
        r'|blood[ \t]+sugar(?![^\d\n]{0,15}?(?:fasting|\bf\b|\bpp\b|post)))\b'
    ),
}
_CORE_RES: dict[str, re.Pattern] = {
    field: re.compile(label + _CORE_GAP + _CORE_NUMBER, re.IGNORECASE) for field, label in _CORE_LABELS.items()
}


def _core_fallback(normalized: str, field: str) -> ExtractedField | None:
    for m in _CORE_RES[field].finditer(normalized):
        if _on_excluded_line(normalized, m, field):
            continue
        value = m.group('val')
        return ExtractedField(
            field_name=display_name(field),
            patient_field=field,
            extracted_value=value,
            unit=_unit_after(normalized[m.end():].split('\n', 1)[0]),
            confidence='high' if validate_numeric_result(value, field) else 'low',
            raw_match=m.group(0),
        )
    return None


# ── Core extraction ───────────────────────────────────────────────────────────

def _try_sys_dia(ocr_text: str) -> str | None:
    for pattern in (_SYS_DIA_RE, _SYS_DIA_RE2):
        m = pattern.search(ocr_text)
        if m:
            return f"{m.group('sys')}/{m.group('dia')}"
    return None


_ALIAS_RES: dict[str, list[re.Pattern]] = {
    field: [re.compile(rf'(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])', re.IGNORECASE) for alias in aliases]
    for field, aliases in FIELD_ALIASES.items()
}


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

    # 1. Try alias-based extraction first: the value after the label, or on the line below it
    for internal_field in FIELD_ALIASES:
        if internal_field in seen_patient_fields:
            continue
        for i, line in enumerate(lines):
            alias_found, val_on_same_line, unit = _value_after_alias(internal_field, line)
            if alias_found:
                if val_on_same_line:
                    confidence = 'high' if validate_numeric_result(val_on_same_line, internal_field) else 'low'
                    _add(ExtractedField(
                        field_name=display_name(internal_field),
                        patient_field=internal_field,
                        extracted_value=val_on_same_line,
                        unit=unit,
                        confidence=confidence,
                        raw_match=line,
                    ))
                    break
                # Then try the lines directly below the label
                nearby, unit = _search_following_lines(lines, i, internal_field)
                if nearby:
                    confidence = 'high' if validate_numeric_result(nearby, internal_field) else 'low'
                    _add(ExtractedField(
                        field_name=display_name(internal_field),
                        patient_field=internal_field,
                        extracted_value=nearby,
                        unit=unit,
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
            m = _first_match(pattern, normalized, patient_field)
            if not m:
                continue

            if label == 'Blood Pressure' and 'sys' in pattern.groupindex:
                sys_v = m.group('sys')
                dia_v = m.group('dia')
                if sys_v and dia_v:
                    raw_val = f"{sys_v}/{dia_v}"
                    unit = ''
                    reference_range = ''
                    confidence = 'high' if validate_blood_pressure(raw_val) else 'low'
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
            if patient_field and patient_field != 'blood_group' and not validate_numeric_result(raw_val, patient_field):
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

    # 3. Flexible label patterns for the main tests the passes above missed
    for core_field in _CORE_RES:
        if core_field not in seen_patient_fields:
            found = _core_fallback(normalized, core_field)
            if found:
                _add(found)

    # 4. Blood pressure sys/dia fallback
    if 'blood_pressure' not in seen_patient_fields:
        bp_val = _try_sys_dia(normalized)
        if bp_val:
            confidence = 'high' if validate_blood_pressure(bp_val) else 'low'
            _add(ExtractedField(
                field_name='Blood Pressure',
                patient_field='blood_pressure',
                extracted_value=bp_val,
                unit='mmHg',
                confidence=confidence,
            ))

    logger.info('Medical extractor found %d field(s) in OCR text.', len(results))
    return results
