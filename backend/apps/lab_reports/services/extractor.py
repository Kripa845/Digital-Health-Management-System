"""Turn report text into structured data.

The report text is untrusted input: it is only ever matched with regular
expressions, never executed or passed to another system. Anything that is not
found is None; nothing is guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from apps.lab_reports.extractor import ExtractedField, extract_medical_fields
from apps.lab_reports.identity import ReportIdentity, extract_identity

# The values the feature reports on explicitly (always present in the
# extracted JSON, as null when missing).
CORE_TESTS = ('hemoglobin', 'cholesterol_total', 'blood_sugar_random')

# Labels a patient ID is printed after. OCR often reads the "I" of "ID" as 1, l
# or |, so "Patient 1D" counts as "Patient ID".
_ID = r'[i1l|]d'
_ID_LABEL = re.compile(
    rf'(?<![a-z])(?:patient\s*(?:{_ID}|no\.?|number)|p\.?\s*{_ID}|uh{_ID}|mrn|reg(?:istration)?\s*(?:no\.?|{_ID})|'
    rf'(?:health\s*)?card\s*(?:no\.?|{_ID})|mcc\s*(?:no\.?|{_ID}))(?![a-z])'
    r'[ \t]*[:\-–.#|=]*[ \t]*(?P<value>[A-Z0-9][A-Z0-9 \-/.]{2,24}?)(?=\s{2,}|[|,;]|\s+[A-Za-z]{3,}|$)',
    re.IGNORECASE | re.MULTILINE,
)
# An ID printed in brackets beside the patient's name: "Name: Hari Tamang (79028232)".
_NAME_BRACKET_ID = re.compile(
    r"(?<![a-z])(?:patient(?:'s)?\s*)?na(?:me|rne)(?![a-z])[ \t]*[:\-–.;|=]*"
    # The bracket may also start the next line when the name wraps:
    # "Name: KARUNA SHRESTHA" / "(SBHF31965)" (one blank line allowed between).
    r"[^\n(]{1,60}?(?:[ \t]*\n(?:[ \t]*\n)?[ \t]*)?\([ \t]*(?:(?:p\.?\s*id|uhid|id|no)\.?[ \t]*[:#\-]?[ \t]*)?"
    r"(?P<value>[A-Z0-9][A-Z0-9 \-/]{2,20}?)[ \t]*\)",
    re.IGNORECASE,
)
# Labels whose bracket holds someone else's number ("Doctor Name: Dr. Rai (NMC 1234)").
_NOT_PATIENT_NAME = re.compile(r'(?:dr\.?|doctor|ref(?:erred)?(?:\s*by)?|consultant|physician)\s*$', re.IGNORECASE)

# A Mero Care Card ID anywhere in the text: PAT + a code of 4 to 12 capital
# letters or digits containing a digit (e.g. PAT-79028232, "PAT 7902 8232"),
# tolerating a 4/A, 7/T misread in the prefix. The code must contain a digit,
# so words such as "Patient" or "Pathology" are not read as IDs.
_CARD_ANYWHERE = re.compile(
    r'(?<![A-Z0-9])P\s?[A4]\s?[T7][\s\-–—._]{0,2}'
    r'(?P<tail>(?=[A-Z]{0,3}\d)[0-9A-Z]{4}[ \-](?=[A-Z]{0,3}\d)[0-9A-Z]{4}|(?=[A-Z]{0,11}\d)[0-9A-Z]{4,12})'
    r'(?![A-Za-z0-9])',
    re.IGNORECASE,
)


@dataclass
class ExtractedReport:
    card_ids: list[str] = field(default_factory=list)   # normalised IDs in Mero Care Card format
    other_ids: list[str] = field(default_factory=list)  # other facility IDs (not comparable)
    name: str | None = None
    dob: date | None = None
    blood_group: str | None = None
    report_date: date | None = None
    report_date_source: str = ''      # 'reporting', 'collection' or '' (none found)
    values: list[ExtractedField] = field(default_factory=list)
    identity: ReportIdentity | None = field(default=None, repr=False)

    def value_of(self, test: str) -> ExtractedField | None:
        return next((v for v in self.values if v.patient_field == test), None)

    def to_json(self) -> dict:
        """What is stored with the report (no raw text). IDs are masked."""
        from apps.lab_reports.services.verifier import mask_id
        core = {}
        for test in CORE_TESTS:
            v = self.value_of(test)
            core[test] = {'value': v.extracted_value, 'unit': v.unit} if v else None
        return {
            'patient_id': mask_id(self.card_ids[0]) if self.card_ids else None,
            'name': self.name,
            'dob': self.dob.isoformat() if self.dob else None,
            'blood_group': self.blood_group,
            'report_date': self.report_date.isoformat() if self.report_date else None,
            'report_date_source': self.report_date_source,
            'tests': core,
            'other_tests': {
                v.patient_field: {'value': v.extracted_value, 'unit': v.unit}
                for v in self.values if v.patient_field not in CORE_TESTS and v.patient_field != 'blood_group'
            },
        }


def normalize_id(raw: str) -> str:
    """Uppercase, drop spaces/dashes/dots, drop "Patient ID"/"PID"/"UHID" prefixes."""
    s = re.sub(r'[\s\-–—_.:#/]', '', (raw or '').upper())
    for prefix in ('PATIENTID', 'PATIENTNO', 'PATIENTNUMBER', 'UHID', 'PID'):
        if s.startswith(prefix):
            s = s[len(prefix):]
    return s


def _card_form(normalised: str) -> str | None:
    """Return the ID as PAT + code if it has the Mero Care Card shape (PAT + 4–12 characters)."""
    m = re.fullmatch(r'P[A4][T7]([0-9A-Z]{4,12})', normalised)
    return f'PAT{m.group(1)}' if m else None


def id_code(value: str) -> str:
    """The part of a patient ID that is compared, without "PAT":
    PAT-79028232, "pat 7902 8232" and 79028232 all give 79028232."""
    norm = normalize_id(value)
    form = _card_form(norm)
    return form[3:] if form else norm


def find_patient_ids(text: str) -> tuple[list[str], list[str]]:
    """(Mero Care Card IDs, other facility IDs) found in the text, normalised."""
    card, other = [], []
    for m in _ID_LABEL.finditer(text or ''):
        norm = normalize_id(m.group('value'))
        if not norm or not any(ch.isdigit() for ch in norm):
            continue
        form = _card_form(norm)
        if form:
            card.append(form)
        else:
            other.append(norm)
    for m in _NAME_BRACKET_ID.finditer(text or ''):
        before = (text[:m.start()].rsplit('\n', 1)[-1])[-25:]
        norm = normalize_id(m.group('value'))
        if _NOT_PATIENT_NAME.search(before) or sum(ch.isdigit() for ch in norm) < 4:
            continue                                   # a doctor's number, or an age such as "(36 Y)"
        form = _card_form(norm)
        if form:
            card.append(form)
        else:
            other.append(norm)
    for m in _CARD_ANYWHERE.finditer(text or ''):
        card.append(_card_form(normalize_id('PAT' + m.group('tail'))))
    return list(dict.fromkeys(c for c in card if c)), list(dict.fromkeys(other))


def extract_report(text: str, today: date | None = None) -> ExtractedReport:
    identity = extract_identity(text, today)
    card_ids, other_ids = find_patient_ids(text)
    values = extract_medical_fields(text)
    blood = next((v.extracted_value for v in values if v.patient_field == 'blood_group'), None)
    return ExtractedReport(
        card_ids=card_ids,
        other_ids=other_ids,
        name=identity.name,
        dob=identity.dob,
        blood_group=blood,
        report_date=identity.report_date,
        report_date_source=identity.report_date_source,
        values=values,
        identity=identity,
    )
