"""
Clinical Data Synchronization Algorithm (CDSA)
------------------------------------------------
For every extracted medical parameter:
  1. Retrieve the patient's current value from the database.
  2. If no value exists → insert the extracted value.
  3. If a value exists → compare.
     a. Identical  → do NOT update; mark UNCHANGED.
     b. Different  → replace with new value; mark UPDATED.
  4. Save the LabReport record with audit summary counts.
  5. Return a structured ProcessingResult.

Patient model fields the CDSA is allowed to write back to:
  ─ Vitals ──────────────────────────────────────────────
  height              DecimalField  cm
  weight              DecimalField  kg
  blood_pressure      CharField     e.g. "120/80"
  hemoglobin          DecimalField  g/dL
  blood_sugar_fasting DecimalField  mg/dL
  blood_sugar_random  DecimalField  mg/dL
  cholesterol_total   DecimalField  mg/dL
  cholesterol_hdl     DecimalField  mg/dL
  cholesterol_ldl     DecimalField  mg/dL
  triglycerides       DecimalField  mg/dL
  blood_group         CharField     e.g. "A+"

All other extracted fields (BMI, WBC, ESR, …) are stored as
LabReportField rows for display only and do NOT touch the Patient record.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from apps.lab_reports.extractor import ExtractedField
from apps.lab_reports.models import LabReport, LabReportField

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Field type registry
# ---------------------------------------------------------------------------

# Fields written back to the Patient model on every processed report.
# Order does not matter – processed as a set.
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
    'blood_group',
})

# Subset of the above that are stored as Decimal in the Patient model.
_DECIMAL_PATIENT_FIELDS: frozenset[str] = frozenset({
    'height',
    'weight',
    'hemoglobin',
    'blood_sugar_fasting',
    'blood_sugar_random',
    'cholesterol_total',
    'cholesterol_hdl',
    'cholesterol_ldl',
    'triglycerides',
})

# blood_pressure is CharField  → stored as plain string ("120/80")
# blood_group   is CharField   → normalised to uppercase ("A+")


# ---------------------------------------------------------------------------
# Result data-classes
# ---------------------------------------------------------------------------

@dataclass
class FieldResult:
    """Outcome for a single extracted medical parameter."""
    field_name: str
    patient_field: str
    extracted_value: str
    previous_value: str
    unit: str
    reference_range: str
    change_status: str   # 'INSERTED' | 'UPDATED' | 'UNCHANGED'


@dataclass
class ProcessingResult:
    """Overall result of running the CDSA on one lab report."""
    detected_fields: list[FieldResult] = field(default_factory=list)
    updated_fields: list[FieldResult] = field(default_factory=list)
    unchanged_fields: list[FieldResult] = field(default_factory=list)

    @property
    def detected_count(self) -> int:
        return len(self.detected_fields)

    @property
    def updated_count(self) -> int:
        return len(self.updated_fields)

    @property
    def unchanged_count(self) -> int:
        return len(self.unchanged_fields)


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

def run_cdsa(lab_report: LabReport, extracted_fields: list[ExtractedField]) -> ProcessingResult:
    """
    Apply the CDSA to *lab_report*.

    - Updates Patient dashboard fields where applicable.
    - Persists LabReportField rows (one per detected parameter).
    - Updates the LabReport summary counters.
    - Returns a ProcessingResult for the API response / UI summary.

    Idempotent: calling again on the same report clears old LabReportField
    rows and rebuilds them, then re-saves the Patient with the latest values.
    """
    patient = lab_report.patient

    # Wipe previous field rows so reprocessing is safe
    LabReportField.objects.filter(report=lab_report).delete()

    result = ProcessingResult()
    patient_dirty = False  # set True whenever we write a new value to patient
    changed_fields: list[str] = []  # track which patient fields were actually written

    for ef in extracted_fields:
        previous_value = ''
        change_status = LabReportField.ChangeStatus.UNCHANGED

        if ef.patient_field in _UPDATABLE_PATIENT_FIELDS:
            # ── field that maps to the Patient model ─────────────────────
            current_raw = getattr(patient, ef.patient_field, None)
            previous_value = _to_display(current_raw)

            new_norm     = _normalise(ef.extracted_value, ef.patient_field)
            current_norm = _normalise(previous_value,     ef.patient_field)

            if not previous_value:
                # No prior value → insert
                _apply_to_patient(patient, ef.patient_field, ef.extracted_value)
                patient_dirty = True
                changed_fields.append(ef.patient_field)
                change_status = LabReportField.ChangeStatus.INSERTED
            elif new_norm == current_norm:
                # Identical → leave unchanged
                change_status = LabReportField.ChangeStatus.UNCHANGED
            else:
                # Different → update
                _apply_to_patient(patient, ef.patient_field, ef.extracted_value)
                patient_dirty = True
                changed_fields.append(ef.patient_field)
                change_status = LabReportField.ChangeStatus.UPDATED
        else:
            # ── display-only field (BMI, WBC, ESR, etc.) ─────────────────
            change_status = LabReportField.ChangeStatus.INSERTED
            previous_value = ''

        # Persist the field row regardless of whether it touched Patient
        LabReportField.objects.create(
            report=lab_report,
            field_name=ef.field_name,
            patient_field=ef.patient_field,
            extracted_value=ef.extracted_value,
            previous_value=previous_value,
            unit=ef.unit,
            reference_range=ef.reference_range,
            change_status=change_status,
        )

        fr = FieldResult(
            field_name=ef.field_name,
            patient_field=ef.patient_field,
            extracted_value=ef.extracted_value,
            previous_value=previous_value,
            unit=ef.unit,
            reference_range=ef.reference_range,
            change_status=change_status,
        )
        result.detected_fields.append(fr)
        if change_status in (
            LabReportField.ChangeStatus.UPDATED,
            LabReportField.ChangeStatus.INSERTED,
        ):
            result.updated_fields.append(fr)
        else:
            result.unchanged_fields.append(fr)

    # ── Persist Patient — only save the fields that were actually changed ─────
    if patient_dirty and changed_fields:
        # Deduplicate in case the same field was extracted twice (shouldn't
        # happen because extractor deduplicates, but be safe).
        unique_fields = list(dict.fromkeys(changed_fields))
        try:
            patient.save(update_fields=unique_fields)
            logger.info(
                'CDSA updated patient %s: %s',
                patient.patient_id,
                unique_fields,
            )
        except Exception as exc:
            logger.error('CDSA failed to save patient %s: %s', patient.patient_id, exc)
            raise

    # ── Update LabReport summary counters ─────────────────────────────────────
    lab_report.detected_count  = result.detected_count
    lab_report.updated_count   = result.updated_count
    lab_report.unchanged_count = result.unchanged_count
    lab_report.status          = LabReport.Status.COMPLETED
    lab_report.processed_at    = timezone.now()
    lab_report.save(update_fields=[
        'detected_count', 'updated_count', 'unchanged_count',
        'status', 'processed_at',
    ])

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_display(raw) -> str:
    """Convert a model field value to a plain string for comparison / display."""
    if raw is None:
        return ''
    return str(raw).strip()


def _normalise(value: str, patient_field: str) -> str:
    """
    Canonical form for equality comparison.
    - blood_group   → uppercase, no spaces
    - blood_pressure → normalise whitespace around '/'
    - Decimal fields → compare as Decimal to avoid "60.0" ≠ "60.00"
    """
    v = value.strip()
    if not v:
        return ''

    if patient_field == 'blood_group':
        return v.upper()

    if patient_field == 'blood_pressure':
        # normalise "120 / 80" → "120/80"
        import re
        return re.sub(r'\s*/\s*', '/', v)

    if patient_field in _DECIMAL_PATIENT_FIELDS:
        try:
            return str(Decimal(v).normalize())
        except (InvalidOperation, ValueError):
            return v

    return v


def _apply_to_patient(patient, patient_field: str, raw_value: str) -> None:
    """
    Write the extracted string value onto the Patient instance.
    The instance is NOT saved here; the caller calls patient.save() once
    after all fields have been applied.
    """
    v = raw_value.strip()

    if patient_field in _DECIMAL_PATIENT_FIELDS:
        try:
            setattr(patient, patient_field, Decimal(v))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(
                f'Cannot convert "{v}" to a number for field "{patient_field}": {exc}'
            ) from exc

    elif patient_field == 'blood_group':
        setattr(patient, patient_field, v.upper())

    elif patient_field == 'blood_pressure':
        import re
        setattr(patient, patient_field, re.sub(r'\s*/\s*', '/', v))

    else:
        setattr(patient, patient_field, v)
