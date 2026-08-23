from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from apps.lab_reports.extractor import ExtractedField, validate_numeric_result, validate_blood_pressure
from apps.lab_reports.models import LabReport, LabReportField

logger = logging.getLogger(__name__)


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


@dataclass
class FieldResult:
    field_name: str
    patient_field: str
    extracted_value: str
    previous_value: str
    unit: str
    reference_range: str
    change_status: str   # 'INSERTED' | 'UPDATED' | 'UNCHANGED'


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


def run_cdsa(lab_report: LabReport, extracted_fields: list[ExtractedField]) -> ProcessingResult:
    patient = lab_report.patient

    LabReportField.objects.filter(report=lab_report).delete()

    result = ProcessingResult()
    patient_dirty = False
    changed_fields: list[str] = []

    for ef in extracted_fields:
        previous_value = ''
        change_status = LabReportField.ChangeStatus.UNCHANGED
        needs_review = False

        if ef.patient_field in _UPDATABLE_PATIENT_FIELDS:
            current_raw = getattr(patient, ef.patient_field, None)
            previous_value = _to_display(current_raw)
            new_norm = _normalise(ef.extracted_value, ef.patient_field)
            current_norm = _normalise(previous_value, ef.patient_field)

            if not previous_value:
                try:
                    _apply_to_patient(patient, ef.patient_field, ef.extracted_value)
                    patient_dirty = True
                    changed_fields.append(ef.patient_field)
                    change_status = LabReportField.ChangeStatus.INSERTED
                    if ef.confidence == 'low':
                        needs_review = True
                except ValueError as exc:
                    logger.warning('Applying field %s for patient %s despite validation error: %s', ef.patient_field, patient.patient_id, exc)
                    try:
                        _force_apply_to_patient(patient, ef.patient_field, ef.extracted_value)
                        patient_dirty = True
                        changed_fields.append(ef.patient_field)
                        change_status = LabReportField.ChangeStatus.INSERTED
                        needs_review = True
                    except Exception:
                        logger.warning('Skipping field %s for patient %s: %s', ef.patient_field, patient.patient_id, exc)
                        needs_review = True
                        change_status = LabReportField.ChangeStatus.UNCHANGED
            elif new_norm == current_norm:
                change_status = LabReportField.ChangeStatus.UNCHANGED
                if ef.confidence == 'low':
                    needs_review = True
            else:
                try:
                    _apply_to_patient(patient, ef.patient_field, ef.extracted_value)
                    patient_dirty = True
                    changed_fields.append(ef.patient_field)
                    change_status = LabReportField.ChangeStatus.UPDATED
                    if ef.confidence == 'low':
                        needs_review = True
                except ValueError as exc:
                    logger.warning('Applying field %s for patient %s despite validation error: %s', ef.patient_field, patient.patient_id, exc)
                    try:
                        _force_apply_to_patient(patient, ef.patient_field, ef.extracted_value)
                        patient_dirty = True
                        changed_fields.append(ef.patient_field)
                        change_status = LabReportField.ChangeStatus.UPDATED
                        needs_review = True
                    except Exception:
                        logger.warning('Skipping field %s for patient %s: %s', ef.patient_field, patient.patient_id, exc)
                        needs_review = True
                        change_status = LabReportField.ChangeStatus.UNCHANGED
        else:
            change_status = LabReportField.ChangeStatus.INSERTED
            previous_value = ''
            if ef.confidence == 'low':
                needs_review = True

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
        if needs_review:
            result.needs_review_fields.append(fr)
        elif change_status in (
            LabReportField.ChangeStatus.UPDATED,
            LabReportField.ChangeStatus.INSERTED,
        ):
            result.updated_fields.append(fr)
        else:
            result.unchanged_fields.append(fr)

    if patient_dirty and changed_fields:
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

    lab_report.detected_count = result.detected_count
    lab_report.updated_count = result.updated_count
    lab_report.unchanged_count = result.unchanged_count
    lab_report.status = LabReport.Status.COMPLETED
    lab_report.processed_at = timezone.now()
    lab_report.save(update_fields=[
        'detected_count', 'updated_count', 'unchanged_count',
        'status', 'processed_at',
    ])

    return result


def _to_display(raw) -> str:
    if raw is None:
        return ''
    return str(raw).strip()


def _normalise(value: str, patient_field: str) -> str:
    v = value.strip()
    if not v:
        return ''

    if patient_field == 'blood_group':
        return v.upper()

    if patient_field == 'blood_pressure':
        import re
        return re.sub(r'\s*/\s*', '/', v)

    if patient_field in _DECIMAL_PATIENT_FIELDS:
        try:
            return str(Decimal(v).normalize())
        except (InvalidOperation, ValueError):
            return v

    return v


def _apply_to_patient(patient, patient_field: str, raw_value: str) -> None:
    v = raw_value.strip()

    if patient_field == 'heart_rate':
        n = int(float(v))
        if not (30 <= n <= 220):
            raise ValueError(
                f'Extracted heart rate "{v}" for field "{patient_field}" failed validation.'
            )
        setattr(patient, patient_field, n)
    elif patient_field in _DECIMAL_PATIENT_FIELDS:
        if not validate_numeric_result(v, patient_field):
            raise ValueError(
                f'Extracted value "{v}" for field "{patient_field}" failed validation.'
            )
        try:
            setattr(patient, patient_field, Decimal(v))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(
                f'Cannot convert "{v}" to a number for field "{patient_field}": {exc}'
            ) from exc

    elif patient_field == 'blood_group':
        setattr(patient, patient_field, v.upper())

    elif patient_field == 'blood_pressure':
        if not validate_blood_pressure(v):
            raise ValueError(
                f'Extracted blood pressure "{v}" failed validation.'
            )
        import re
        setattr(patient, patient_field, re.sub(r'\s*/\s*', '/', v))

    else:
        setattr(patient, patient_field, v)


def _force_apply_to_patient(patient, patient_field: str, raw_value: str) -> None:
    v = raw_value.strip()

    if patient_field == 'heart_rate':
        try:
            setattr(patient, patient_field, int(float(v)))
        except (ValueError, TypeError):
            setattr(patient, patient_field, 0)
    elif patient_field in _DECIMAL_PATIENT_FIELDS:
        try:
            setattr(patient, patient_field, Decimal(v))
        except (InvalidOperation, ValueError):
            setattr(patient, patient_field, Decimal(0))

    elif patient_field == 'blood_group':
        setattr(patient, patient_field, v.upper())

    elif patient_field == 'blood_pressure':
        import re
        setattr(patient, patient_field, re.sub(r'\s*/\s*', '/', v))

    else:
        setattr(patient, patient_field, v)
