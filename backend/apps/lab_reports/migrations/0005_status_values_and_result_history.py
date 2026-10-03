"""Data migration (no schema change).

1. Rename stored status values to the names used by the API:
   AWAITING → PENDING_CONFIRMATION, COMPLETED → CONFIRMED.
2. Backfill LabResult (value history) from reports confirmed before the
   LabResult table existed, so trends include them.
"""
from decimal import Decimal, InvalidOperation

from django.db import migrations

STATUS_MAP = {'AWAITING': 'PENDING_CONFIRMATION', 'COMPLETED': 'CONFIRMED'}
APPLIED = ('INSERTED', 'UPDATED', 'UNCHANGED')
CANONICAL_UNITS = {
    'hemoglobin': 'g/dL', 'blood_sugar_fasting': 'mg/dL', 'blood_sugar_random': 'mg/dL',
    'cholesterol_total': 'mg/dL', 'cholesterol_hdl': 'mg/dL', 'cholesterol_ldl': 'mg/dL',
    'triglycerides': 'mg/dL', 'blood_pressure': 'mmHg', 'hba1c': '%',
}


def forwards(apps, schema_editor):
    LabReport = apps.get_model('lab_reports', 'LabReport')
    LabReportField = apps.get_model('lab_reports', 'LabReportField')
    LabResult = apps.get_model('lab_reports', 'LabResult')

    for old, new in STATUS_MAP.items():
        LabReport.objects.filter(status=old).update(status=new)

    for row in LabReportField.objects.filter(report__status='CONFIRMED', change_status__in=APPLIED) \
            .exclude(patient_field__in=['', 'blood_group']).select_related('report'):
        report = row.report
        if LabResult.objects.filter(report=report, test_name=row.patient_field).exists():
            continue
        value = (row.converted_value or row.extracted_value or '').strip()
        if not value:
            continue
        numeric = None
        if row.patient_field != 'blood_pressure':
            try:
                numeric = Decimal(value)
            except (InvalidOperation, ValueError):
                continue
        LabResult.objects.create(
            patient_id=report.patient_id, report=report, test_name=row.patient_field,
            value=value[:32], value_numeric=numeric,
            unit=row.converted_unit or CANONICAL_UNITS.get(row.patient_field, row.unit or '')[:20],
            report_date=report.report_date or report.uploaded_at.date(),
        )


def backwards(apps, schema_editor):
    LabReport = apps.get_model('lab_reports', 'LabReport')
    for old, new in STATUS_MAP.items():
        LabReport.objects.filter(status=new).update(status=old)


class Migration(migrations.Migration):
    dependencies = [('lab_reports', '0004_spec_review_history')]
    operations = [migrations.RunPython(forwards, backwards)]
