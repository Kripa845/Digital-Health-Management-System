"""Which values read from a report need the user's confirmation before they are saved.

Every value carries:
    ocr_confidence    Tesseract's confidence (0–100) for the word(s) the value was read
                      from; 100 for a PDF's own text; the page average when the word
                      cannot be located; None for values read by the AI fallback
    reference_range   the range printed beside the value on the report, with its unit
                      ("13.0–17.0 g/dL", "< 200 mg/dL"), when there is one

A value needs confirmation (``needs_confirmation``) when any of these hold:
    low_confidence     its word confidence is below LAB_VALUE_MIN_CONFIDENCE
    far_outside_range  it is more than LAB_FAR_OUTSIDE_FACTOR times above the printed
                       upper limit (or that many times below the lower limit)
    decimal_point      it was read without a decimal point and only makes sense with one
                       (cholesterol "1302" → 130.2); the suggestion is shown, never saved
                       silently

Values read from a report's table (services/table_reader.py) can carry more reasons:
    decimal_point      also used when a scan's reading was auto-corrected (41 → 4.1)
    conflict           two rows of the report were read as the same test
    readings_differ    two OCR readings of the result cell disagreed
    range_misread      the printed range was read but cannot be right for the test
    loose_match        found by searching the free text, not read from a table row

These are all "possibly misread" reasons. Being outside the range printed on the report
is a clinical finding, not a misread: it is reported separately (``reference_flag``) and
on its own never asks for confirmation.

Unconfirmed values are never saved (services/dashboard.apply_report). The thresholds are
in config/settings.py and NEED REVIEW: they are starting points, not validated figures.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from apps.lab_reports.extractor import _UNIT_AFTER_VALUE
from apps.lab_reports.units import normalise_unit

LOW_CONFIDENCE = 'low_confidence'
FAR_OUTSIDE_RANGE = 'far_outside_range'
DECIMAL_POINT = 'decimal_point'
CONFLICT = 'conflict'
READINGS_DIFFER = 'readings_differ'
RANGE_MISREAD = 'range_misread'
LOOSE_MATCH = 'loose_match'
# Reasons decided when the report is read (not recomputed from the stored row), so a
# re-planned preview (services/dashboard.replan_preview) must carry them over.
READ_TIME_REASONS = (DECIMAL_POINT, CONFLICT, READINGS_DIFFER, RANGE_MISREAD, LOOSE_MATCH)

DEFAULTS = {
    'LAB_VALUE_MIN_CONFIDENCE': 80.0,   # 0–100
    'LAB_FAR_OUTSIDE_FACTOR': 3.0,      # × the printed limit
}


def _cfg(name: str) -> float:
    try:
        from django.conf import settings
        if settings.configured:
            return float(getattr(settings, name, DEFAULTS[name]))
    except Exception:
        pass
    return DEFAULTS[name]


# ── Printed reference ranges ─────────────────────────────────────────────────

_NUM = r'\d+(?:\.\d+)?'
# What may sit between the value (or its unit) and the range: separators and an H/L
# flag. OCR text normalisation turns a lone "L" before a number into "1", so a lone 1
# is accepted as the flag too.
_BEFORE_RANGE = r'^[\s:|*()\[\],]*(?:(?:high|low|abnormal|[hl1])(?![\w.])[\s|*()\[\],]*)?'
_RANGE_FORMS = (
    re.compile(rf'(?P<low>{_NUM})\s*(?:-|–|—|to)\s*(?P<high>{_NUM})', re.IGNORECASE),
    re.compile(rf'(?:<\s*=?|≤|up\s*to|less\s*than|below)\s*(?P<high>{_NUM})', re.IGNORECASE),
    re.compile(rf'(?:>\s*=?|≥|more\s*than|above)\s*(?P<low>{_NUM})', re.IGNORECASE),
)


@dataclass
class ReferenceRange:
    low: float | None
    high: float | None
    unit: str = ''

    @property
    def text(self) -> str:
        if self.low is not None and self.high is not None:
            body = f'{_n(self.low)}–{_n(self.high)}'
        elif self.high is not None:
            body = f'< {_n(self.high)}'
        else:
            body = f'> {_n(self.low)}'
        return f'{body} {self.unit}'.strip()


def _n(x: float) -> str:
    return f'{x:g}'


def _unit_at(text: str) -> tuple[str, int]:
    m = _UNIT_AFTER_VALUE.match(text or '')
    return (re.sub(r'\s+', '', m.group('unit')), m.end()) if m else ('', 0)


def _range_at(text: str) -> tuple[ReferenceRange | None, int]:
    """A range at the start of ``text`` (after separators / an H-L flag), and where it ends."""
    lead = re.match(_BEFORE_RANGE, text, re.IGNORECASE)
    start = lead.end() if lead else 0
    for form in _RANGE_FORMS:
        m = form.match(text, start)
        if not m:
            continue
        groups = m.groupdict()
        low = float(groups['low']) if groups.get('low') else None
        high = float(groups['high']) if groups.get('high') else None
        if low is not None and high is not None and low >= high:
            return None, 0
        return ReferenceRange(low, high), m.end()
    return None, 0


def details_after_value(after: str) -> tuple[str, ReferenceRange | None]:
    """The unit and printed reference range on the text that follows a value:
    "g/dL 13.0 - 17.0", "H 13.0-17.0 g/dL", "mg/dL (< 200)"."""
    unit, used = _unit_at(after)
    rest = after[used:]
    ref, end = _range_at(rest)
    if ref is not None:
        ref.unit, _ = _unit_at(rest[end:].lstrip(' )]'))
        if not ref.unit:
            ref.unit = unit
        if not unit:
            unit = ref.unit
    return unit, ref


def parse_reference_range(text: str) -> ReferenceRange | None:
    """Read a stored range text back ("13.0–17.0 g/dL", "< 200 mg/dL", "70 - 110")."""
    ref, end = _range_at((text or '').strip())
    if ref is not None:
        ref.unit, _ = _unit_at((text or '').strip()[end:])
    return ref


def _same_unit(a: str, b: str) -> bool:
    return not a or not b or normalise_unit(a) == normalise_unit(b)


LOW, NORMAL, HIGH = 'low', 'normal', 'high'


def reference_flag(value: str, reference_range: str) -> str | None:
    """Clinical flag against the range printed on the report's own row: 'low', 'normal',
    'high', or None when there is no range or the value is not a plain number."""
    ref = parse_reference_range(reference_range)
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if ref is None:
        return None
    if ref.low is not None and n < ref.low:
        return LOW
    if ref.high is not None and n > ref.high:
        return HIGH
    return NORMAL


# ── Per-value OCR confidence ─────────────────────────────────────────────────

_MISREAD = str.maketrans({'O': '0', 'o': '0', 'l': '1', 'I': '1', '|': '1', ',': '.'})


def _numbers(word: str) -> list[str]:
    if any(ch.isdigit() for ch in word):
        word = word.translate(_MISREAD)
    return re.findall(_NUM, word)


def _label_key(label: str) -> str:
    m = re.search(r'[A-Za-z]{3,}', label or '')
    return m.group(0).lower() if m else ''


def value_confidence(words: list[list[tuple[str, float]]], value: str, label: str) -> float | None:
    """Confidence of the word(s) a value was read from.

    The value is looked for after its label on the label's line, then on the line just
    below (a value printed under its label), and otherwise on the only line containing
    it. For "120/80" both numbers must be found; the lower confidence is used.
    """
    parts = re.findall(_NUM, value or '')
    if not parts or not words:
        return None
    key = _label_key(label)

    def find(line, start=0):
        confs = []
        position = start
        for part in parts:
            for i in range(position, len(line)):
                if part in _numbers(line[i][0]):
                    confs.append(float(line[i][1]))
                    position = i + 1
                    break
            else:
                return None
        return min(confs)

    if key:
        for idx, line in enumerate(words):
            at = next((i for i, (w, _c) in enumerate(line) if key in w.lower()), None)
            if at is None:
                continue
            found = find(line, at + 1)
            if found is None and idx + 1 < len(words):
                found = find(words[idx + 1])
            if found is not None:
                return found
    hits = [c for c in (find(line) for line in words) if c is not None]
    return hits[0] if len(hits) == 1 else None


def attach_confidences(values, ocr) -> None:
    """Set ``ocr_confidence`` on each extracted value from the OCR result."""
    for x in values:
        if ocr.source == 'text_layer':
            x.ocr_confidence = 100.0
        elif ocr.source in ('ocr', 'mixed'):
            found = value_confidence(ocr.words, x.extracted_value, x.raw_match or x.field_name)
            x.ocr_confidence = found if found is not None else ocr.confidence
        else:
            x.ocr_confidence = None


# ── The checks ───────────────────────────────────────────────────────────────

def reasons_for(raw_value: str, unit: str, confidence: float | None, reference_range: str,
                suggested: str = '') -> list[dict]:
    """[{code, message}] explaining why a value needs confirmation (empty when it does not)."""
    reasons = []
    minimum = _cfg('LAB_VALUE_MIN_CONFIDENCE')
    if confidence is not None and confidence < minimum:
        reasons.append({'code': LOW_CONFIDENCE,
                        'message': f'Read with low confidence ({round(confidence)}%). Check it against the scan.'})
    if suggested:
        reasons.append({'code': DECIMAL_POINT,
                        'message': f'Read as {raw_value}, which is not plausible; {suggested} is suggested '
                                   '(a decimal point may have been missed). Check it against the scan.'})
    ref = parse_reference_range(reference_range)
    factor = _cfg('LAB_FAR_OUTSIDE_FACTOR')
    if ref and not suggested and _same_unit(ref.unit, unit):
        try:
            n = float(raw_value)
        except (TypeError, ValueError):
            n = None
        if n is not None and ((ref.high and n > ref.high * factor) or (ref.low and n < ref.low / factor)):
            reasons.append({'code': FAR_OUTSIDE_RANGE,
                            'message': f'Far outside the range printed on the report ({ref.text}). '
                                       'Check it against the scan.'})
    return reasons
