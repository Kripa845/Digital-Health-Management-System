from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.lab_reports.extractor import ExtractedField, validate_numeric_result, validate_blood_pressure
from apps.lab_reports.models import LabReport, LabReportField
from apps.lab_reports.units import convert

logger = logging.getLogger(__name__)


# Fields an OCR result may write into the patient record. Blood group is
# deliberately absent: it is shown on the public emergency profile, so a misread
# is dangerous. A detected blood group is reported for review, never applied.
_UPDATABLE_PATIENT_FIELDS: frozenset[str] = frozenset({
    'height',
    'weight',
    'blood_pressure',
    'hemoglobin',
    'blood_sugar_fasting',
    'blood_sugar_random',
    'cholesterol_total',
    'cholesterol_hdl',
    'cholesterol_ldl',
    'triglycerides',
    'heart_rate',
    'spo2',
    'temperature',
    'hba1c',
    'serum_creatinine',
    'blood_urea',
    'uric_acid',
    'ssgpt_alt',
    'ssgot_ast',
    'bilirubin_total',
    'tsh',
    't3',
    't4',
    'sodium',
    'potassium',
    'wbc_count',
    'rbc_count',
    'platelet_count',
    'hematocrit',
    'esr',
})

_REVIEW_ONLY_PATIENT_FIELDS: frozenset[str] = frozenset({'blood_group'})

_DECIMAL_PATIENT_FIELDS: frozenset[str] = _UPDATABLE_PATIENT_FIELDS - {'blood_pressure', 'heart_rate'}


@dataclass
class FieldResult:
    field_name: str
    patient_field: str
    extracted_value: str
    previous_value: str
    unit: str
    reference_range: str
    change_status: str   # 'INSERTED' | 'UPDATED' | 'UNCHANGED' | 'SKIPPED'


@dataclass
class ProcessingResult:
    detected_fields: list[FieldResult] = field(default_factory=list)
    updated_fields: list[FieldResult] = field(default_factory=list)
    unchanged_fields: list[FieldResult] = field(default_factory=list)
    needs_review_fields: list[FieldResult] = field(default_factory=list)

    @property
    def detected_count(self) -> int:
        return len(self.detected_fields)

    @property
    def updated_count(self) -> int:
        return len(self.updated_fields)

    @property
    def unchanged_count(self) -> int:
        return len(self.unchanged_fields)

    @property
    def needs_review_count(self) -> int:
        return len(self.needs_review_fields)

    def add(self, row: LabReportField):
        fr = FieldResult(
            field_name=row.field_name, patient_field=row.patient_field,
            extracted_value=row.extracted_value, previous_value=row.previous_value,
            unit=row.unit, reference_range=row.reference_range, change_status=row.change_status,
        )
        self.detected_fields.append(fr)
        if row.change_status == LabReportField.ChangeStatus.SKIPPED:
            self.needs_review_fields.append(fr)
        elif row.change_status in (LabReportField.ChangeStatus.UNCHANGED, LabReportField.ChangeStatus.HISTORY):
            self.unchanged_fields.append(fr)
        else:
            self.updated_fields.append(fr)


DASHBOARD_FIELDS = _UPDATABLE_PATIENT_FIELDS | _REVIEW_ONLY_PATIENT_FIELDS

def build_preview(lab_report: LabReport, extracted_fields: list[ExtractedField]) -> ProcessingResult:
    """Kept for existing callers; the logic lives in services/dashboard.py."""
    from apps.lab_reports.services.dashboard import build_preview as _build_preview
    return _build_preview(lab_report, extracted_fields)


def apply_report(lab_report: LabReport, confirmed_by=None) -> ProcessingResult:
    """Kept for existing callers; the logic lives in services/dashboard.py."""
    from apps.lab_reports.services.dashboard import apply_report as _apply_report
    return _apply_report(lab_report, user=confirmed_by).result


def run_cdsa(lab_report: LabReport, extracted_fields: list[ExtractedField]) -> ProcessingResult:
    """Preview and confirm in one step (used by tests and maintenance code)."""
    build_preview(lab_report, extracted_fields)
    if lab_report.status != LabReport.Status.PENDING_CONFIRMATION:
        lab_report.status = LabReport.Status.PENDING_CONFIRMATION
        lab_report.save(update_fields=['status'])
    return apply_report(lab_report)


def _to_display(raw) -> str:
    if raw is None:
        return ''
    return str(raw).strip()


def _normalise(value: str, patient_field: str) -> str:
    v = (value or '').strip()
    if not v:
        return ''
    if patient_field == 'blood_group':
        return v.upper()
    if patient_field == 'blood_pressure':
        return re.sub(r'\s*/\s*', '/', v)
    if patient_field in _DECIMAL_PATIENT_FIELDS or patient_field == 'heart_rate':
        try:
            return str(Decimal(v).normalize())
        except (InvalidOperation, ValueError):
            return v
    return v


def _parse_for_field(patient, patient_field: str, raw_value: str):
    """Return the value to store, or None when it is invalid for the field."""
    v = (raw_value or '').strip()
    if not validate_numeric_result(v, patient_field):
        return None

    if patient_field == 'blood_pressure':
        if not validate_blood_pressure(v):
            return None
        normalised = re.sub(r'\s*/\s*', '/', v)
        max_length = patient._meta.get_field('blood_pressure').max_length
        return normalised if len(normalised) <= max_length else None

    if patient_field == 'heart_rate':
        try:
            return int(Decimal(v))
        except (InvalidOperation, ValueError):
            return None

    if patient_field in _DECIMAL_PATIENT_FIELDS:
        try:
            number = Decimal(v)
        except (InvalidOperation, ValueError):
            return None
        return _fit_decimal(patient, patient_field, number)

    return None


def _fit_decimal(patient, patient_field: str, number: Decimal) -> Decimal | None:
    """Round to the column's decimal places; reject values that would overflow it."""
    model_field = patient._meta.get_field(patient_field)
    quantum = Decimal(1).scaleb(-model_field.decimal_places)
    try:
        rounded = number.quantize(quantum)
    except InvalidOperation:
        return None
    integer_digits = len(rounded.as_tuple().digits) - model_field.decimal_places
    if integer_digits > model_field.max_digits - model_field.decimal_places:
        return None
    return rounded
