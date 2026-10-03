"""Identity gate: decide whether a report may be applied to a patient.

IDs are compared on their digits only; every letter is ignored. PAT-79028232,
"PAT 7902 8232", "Patient ID: 79028232" and "Name: Hari Tamang (79028232)" all
match the patient PAT-79028232. An ID with fewer than MIN_ID_DIGITS digits is
compared on its whole code instead, since so few digits match too easily.

Outcomes
    pass    the patient ID number on the report equals the patient's,
            and nothing else contradicts it → preview for confirmation
    review  no comparable ID, an ID that only matches after OCR look-alike
            correction (O/0, I/1, S/5...), or a name / date of birth / age
            that disagrees → NEEDS_REVIEW by an admin, never auto-accepted
    reject  a different ID printed with the PAT prefix → nothing is stored
            (a different bare number may be the lab's own ID: review instead)

Messages never reveal anything read from the report (another person's name,
ID or data). IDs are masked before they are logged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from rapidfuzz import fuzz

from apps.lab_reports.identity import (
    find_name_in_text, name_tokens, names_match,
)
from apps.lab_reports.services.extractor import ExtractedReport, id_code, normalize_id

PASS, REVIEW, REJECT = 'pass', 'review', 'reject'

NAME_THRESHOLD = 85          # rapidfuzz score below which the name counts as different
LOW_OCR_CONFIDENCE = 50      # mean Tesseract confidence below which a person must check

_CONFUSABLE = str.maketrans({'O': '0', 'I': '1', 'L': '1', 'S': '5', 'Z': '2'})

REASON_MESSAGES = {
    'patient_id_missing': 'The report does not show a Mero Care Card patient ID.',
    'patient_id_unclear': 'The patient ID on the report could not be read with certainty.',
    'name_mismatch': "The name on the report does not match the patient's name.",
    'dob_mismatch': "The date of birth on the report does not match the patient's.",
    # No longer produced (age is not compared); kept so older reports still show their reason.
    'age_mismatch': "The age on the report does not match the patient's age.",
    'low_ocr_confidence': 'The scan is hard to read, so the values need checking.',
}
MISMATCH_MESSAGE = 'Patient ID does not match this account.'


@dataclass
class GateResult:
    outcome: str
    reasons: list[str] = field(default_factory=list)

    @property
    def messages(self) -> list[str]:
        return [REASON_MESSAGES[r] for r in self.reasons]


def mask_id(value: str | None) -> str:
    """PAT9C0E059C → PAT-9C****9C (never log or store a full ID read from a report)."""
    v = normalize_id(value or '')
    if v.startswith('PAT') and len(v) > 7:
        code = v[3:]
        return f'PAT-{code[:2]}{"*" * (len(code) - 4)}{code[-2:]}'
    if v.startswith('PAT'):
        return 'PAT-' + '*' * (len(v) - 3)
    if len(v) <= 4:
        return '*' * len(v)
    return f'{v[:2]}{"*" * (len(v) - 4)}{v[-2:]}'


MIN_ID_DIGITS = 4


def id_key(code: str) -> str:
    """What two IDs are compared on: the digits, or the whole code when it has
    fewer than MIN_ID_DIGITS digits."""
    digits = re.sub(r'\D', '', code or '')
    return digits if len(digits) >= MIN_ID_DIGITS else (code or '').upper()


def _fold(code: str) -> str:
    """Undo OCR look-alikes (O→0, I/L→1, S→5, Z→2) before taking the digits."""
    return code.upper().translate(_CONFUSABLE)


def _name_score(report: ExtractedReport, patient) -> int | None:
    """100 for a match, else rapidfuzz similarity; None when the report shows no name."""
    first, middle, last = patient.first_name, patient.middle_name or '', patient.last_name
    if report.name:
        if names_match(report.name, first, last, middle):
            return 100
        full = ' '.join(name_tokens(f'{first} {middle} {last}'))
        return int(fuzz.token_set_ratio(' '.join(name_tokens(report.name)), full))
    if report.identity and find_name_in_text(report.identity.lines, first, last, middle):
        return 100
    return None


def verify(report: ExtractedReport, patient, ocr_confidence: float | None = None,
           today: date | None = None) -> GateResult:
    own = id_key(id_code(patient.patient_id))
    cards = [id_code(i) for i in report.card_ids]          # printed with the PAT prefix
    labelled = [id_code(i) for i in report.other_ids]      # "Patient ID: 79028232", "Name: … (79028232)"
    seen = cards + labelled
    reasons: list[str] = []

    if own in {id_key(i) for i in seen}:
        pass
    elif own in {id_key(_fold(i)) for i in seen}:
        reasons.append('patient_id_unclear')
    elif cards:
        return GateResult(REJECT)
    else:
        reasons.append('patient_id_missing')

    score = _name_score(report, patient)
    if score is not None and score < NAME_THRESHOLD:
        reasons.append('name_mismatch')

    if report.dob is not None and report.dob != patient.dob:
        reasons.append('dob_mismatch')

    if ocr_confidence is not None and ocr_confidence < LOW_OCR_CONFIDENCE:
        reasons.append('low_ocr_confidence')

    return GateResult(REVIEW if reasons else PASS, reasons)
