"""Optional fallback: read the main dashboard values from the page images with Claude.

Used only when LAB_LLM_FALLBACK is True and an ANTHROPIC_API_KEY is set, and
only after the PDF text and OCR found no usable value. Page images (patient
data) leave the server when it runs, which is why it is off by default.

The reply is untrusted: it must be a JSON object with exactly the expected keys
and plain numbers, or it is ignored. Values still go through the same unit
conversion, range checks, identity gate and user confirmation as any other
value. Nothing read from the report is logged.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
from dataclasses import dataclass, field

from django.conf import settings
from PIL import Image

from apps.lab_reports.extractor import ExtractedField, display_name

logger = logging.getLogger(__name__)

MAX_PAGES = 5
MAX_IMAGE_SIDE = 2000          # px; larger pages are scaled down before sending

PROMPT = """You are reading a medical laboratory report (the page images above).

Return ONLY a JSON object, with no other text, in exactly this shape:
{"hemoglobin": {"value": "...", "unit": "..."} or null,
 "total_cholesterol": {"value": "...", "unit": "..."} or null,
 "blood_sugar": {"value": "...", "unit": "..."} or null,
 "patient_id": "..." or null}

Rules:
- hemoglobin: haemoglobin / Hb / HGB result (not HbA1c).
- total_cholesterol: total cholesterol result (not HDL or LDL).
- blood_sugar: random (non-fasting) blood sugar / glucose result. If the report only
  shows a fasting or post-prandial sugar, use null.
- patient_id: the patient ID printed on the report (for example PAT-79028232), or null.
- Copy each number exactly as printed, and its unit exactly as printed ("" if none).
- Use the patient's result, never a reference range or limit.
- If a value is absent or you cannot read it with certainty, use null. Never guess."""

# Reply key → patient field.
FIELDS = {
    'hemoglobin': 'hemoglobin',
    'total_cholesterol': 'cholesterol_total',
    'blood_sugar': 'blood_sugar_random',
}
_NUMBER = re.compile(r'^\d{1,4}(?:\.\d{1,3})?$')
_UNIT = re.compile(r'^[A-Za-z%/µμ0-9 .]{0,15}$')
_PATIENT_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 \-]{1,31}$')


@dataclass
class LlmReading:
    values: list[ExtractedField] = field(default_factory=list)
    patient_id: str | None = None


def enabled() -> bool:
    return bool(settings.LAB_LLM_FALLBACK and settings.ANTHROPIC_API_KEY)


def read_values(page_images: list[bytes]) -> LlmReading | None:
    """Ask Claude for the values; None when disabled, on any error, or on a malformed reply."""
    if not enabled() or not page_images:
        return None
    try:
        reply = _ask([_prepare(img) for img in page_images[:MAX_PAGES]])
    except Exception as exc:   # network, API or image errors: fall through to "nothing found"
        logger.warning('Lab report AI fallback failed (%s).', type(exc).__name__)
        return None
    reading = parse_reply(reply)
    if reading is None:
        logger.warning('Lab report AI fallback returned an invalid reply; it was ignored.')
    return reading


def _prepare(raw: bytes) -> bytes:
    """Re-encode as PNG, scaled down if large (also drops any photo metadata)."""
    with Image.open(io.BytesIO(raw)) as img:
        img = img.convert('L')
        img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        out = io.BytesIO()
        img.save(out, format='PNG', optimize=True)
        return out.getvalue()


def _ask(images: list[bytes]) -> str:
    import anthropic   # imported here so the app runs without the package when the fallback is off

    client = anthropic.Anthropic(
        api_key=settings.ANTHROPIC_API_KEY, timeout=settings.LAB_LLM_TIMEOUT, max_retries=1,
    )
    content = [
        {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png',
                                     'data': base64.b64encode(img).decode('ascii')}}
        for img in images
    ]
    content.append({'type': 'text', 'text': PROMPT})
    message = client.messages.create(
        model=settings.LAB_LLM_MODEL,
        max_tokens=400,
        messages=[{'role': 'user', 'content': content}],
    )
    return ''.join(block.text for block in message.content if getattr(block, 'type', '') == 'text')


def parse_reply(reply: str) -> LlmReading | None:
    """Validate the model's reply; None if it is not exactly the expected JSON."""
    text = (reply or '').strip()
    fenced = re.fullmatch(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or set(data) != {*FIELDS, 'patient_id'}:
        return None

    reading = LlmReading()
    for key, patient_field in FIELDS.items():
        item = data[key]
        if item is None:
            continue
        if not isinstance(item, dict) or set(item) - {'value', 'unit'}:
            return None
        value, unit = item.get('value'), item.get('unit') or ''
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int, float)) or not isinstance(unit, str):
            return None
        value = str(value).strip()
        if not _NUMBER.match(value) or not _UNIT.match(unit.strip()):
            return None
        reading.values.append(ExtractedField(
            field_name=display_name(patient_field), patient_field=patient_field,
            extracted_value=value, unit=unit.strip(), confidence='high', raw_match='',
        ))

    pid = data['patient_id']
    if pid is not None:
        if not isinstance(pid, str) or not _PATIENT_ID.match(pid.strip()):
            return None
        reading.patient_id = pid.strip()
    return reading
