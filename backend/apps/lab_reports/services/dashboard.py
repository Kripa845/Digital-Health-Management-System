"""Preview, confirm (update rules) and dashboard data.

Update rules on confirm
    blood group   set only when the record has none; a different value is
                  flagged and never overwrites the record
    age           never taken from a report (always calculated from date of birth)
    numeric tests every confirmed value becomes a new dated LabResult (history);
                  the patient record shows the latest. A report dated before the
                  current latest value is stored in history only.
    flagged       out-of-range values are saved only when the user accepts them

All writes for one confirmation happen in a single transaction with the report
and patient rows locked, so a failure leaves the dashboard unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.audit.utils import log_activity
from apps.lab_reports.cdsa import (
    DASHBOARD_FIELDS, ProcessingResult, _REVIEW_ONLY_PATIENT_FIELDS, _UPDATABLE_PATIENT_FIELDS,
    _normalise, _to_display,
)
from apps.lab_reports.extractor import ExtractedField, display_name
from apps.lab_reports.models import LabReport, LabReportField, LabResult
from apps.lab_reports.services import validator as v
from apps.lab_reports.units import CANONICAL_UNITS

S = LabReportField.ChangeStatus


class NotPending(Exception):
    """The report is not waiting for confirmation."""


class InvalidEdit(Exception):
    """A value typed on the confirm screen is not acceptable."""

    def __init__(self, errors: dict[str, str]):
        super().__init__('Invalid values')
        self.errors = errors


# ── Preview ──────────────────────────────────────────────────────────────────

def build_preview(report: LabReport, values: list[ExtractedField]) -> ProcessingResult:
    """Store one LabReportField per value with its planned outcome. Changes nothing else."""
    patient = report.patient
    latest = _latest_dates(patient, exclude_report=report)
    result = ProcessingResult()
    with transaction.atomic():
        LabReportField.objects.filter(report=report).delete()
        for ef in values:
            if ef.patient_field not in DASHBOARD_FIELDS:
                continue
            row = _plan(patient, ef, report.effective_date, latest)
            row.report = report
            row.save()
            result.add(row)
        report.detected_count = result.detected_count
        report.updated_count = result.updated_count
        report.unchanged_count = result.unchanged_count
        report.processed_at = timezone.now()
        report.save(update_fields=['detected_count', 'updated_count', 'unchanged_count', 'processed_at'])
    return result


def replan_preview(report: LabReport) -> ProcessingResult:
    """Plan the preview again from its own rows, e.g. after the report date changed
    (an older date turns a value into history only). Changes nothing else."""
    values = [ExtractedField(field_name=f.field_name, patient_field=f.patient_field,
                             extracted_value=f.extracted_value, unit=f.unit, reference_range=f.reference_range)
              for f in report.fields.all()]
    return build_preview(report, values)


def _plan(patient, ef: ExtractedField, eff_date: date, latest: dict) -> LabReportField:
    pf = ef.patient_field
    previous = _to_display(getattr(patient, pf, None))
    row = LabReportField(
        field_name=display_name(pf) if ef.field_name == pf else ef.field_name,
        patient_field=pf, extracted_value=ef.extracted_value[:255], unit=ef.unit[:50],
        reference_range=ef.reference_range[:100], previous_value=previous[:255],
    )

    if pf in _REVIEW_ONLY_PATIENT_FIELDS:            # blood group
        group = v.normalise_blood_group(ef.extracted_value)
        row.converted_value = (group or ef.extracted_value)[:50]
        if not group:
            row.change_status, row.flag = S.SKIPPED, v.INVALID
            row.skip_reason = 'Not a valid blood group.'
        elif not previous:
            row.change_status = S.INSERTED
        elif _normalise(previous, pf) == group:
            row.change_status = S.UNCHANGED
        else:
            row.change_status, row.flag = S.SKIPPED, v.BLOOD_GROUP_CONFLICT
            row.skip_reason = 'Different from the blood group on file, so it is not changed. Ask your care team to check.'
        return row

    checked = v.check_value(pf, ef.extracted_value, ef.unit)
    row.converted_value = (checked.value or '')[:50]
    row.converted_unit = (checked.unit or '')[:20]
    if checked.flag:
        row.change_status, row.flag, row.skip_reason = S.SKIPPED, checked.flag, checked.message[:255]
    elif pf in latest and latest[pf] > eff_date:
        row.change_status = S.HISTORY
        row.skip_reason = f'A newer result ({latest[pf]:%d %b %Y}) is already shown; this one is kept in the history.'
    elif previous and _normalise(previous, pf) == _normalise(checked.value, pf):
        row.change_status = S.UNCHANGED
    else:
        row.change_status = S.UPDATED if previous else S.INSERTED
    return row


# ── Confirm ──────────────────────────────────────────────────────────────────

@dataclass
class ConfirmOutcome:
    result: ProcessingResult
    changed_fields: list[str]
    history_rows: int


def apply_report(report: LabReport, user=None, edits: dict | None = None,
                 accept_flagged=(), request=None) -> ConfirmOutcome:
    """Apply a previewed report. ``edits`` maps test → value typed by the user
    (in the dashboard unit); ``accept_flagged`` lists out-of-range tests the user
    explicitly accepts. Raises NotPending or InvalidEdit (nothing is written)."""
    edits = {k: str(val) for k, val in (edits or {}).items()}
    accept = set(accept_flagged or ())

    with transaction.atomic():
        report = LabReport.objects.select_for_update().get(pk=report.pk)
        if report.status != LabReport.Status.PENDING_CONFIRMATION:
            raise NotPending()
        patient = report.patient.__class__.objects.select_for_update().get(pk=report.patient_id)
        rows = list(report.fields.all())

        allowed = {r.patient_field for r in rows}
        errors = {k: 'This value is not part of this report.' for k in edits if k not in allowed}
        checked_edits = {}
        for k, text in edits.items():
            if k in errors:
                continue
            if k == 'blood_group':
                if not v.normalise_blood_group(text):
                    errors[k] = 'Enter a valid blood group (A, B, AB or O with + or -).'
                continue
            c = v.check_edited_value(k, text)
            if c.flag == v.INVALID:
                errors[k] = c.message
            checked_edits[k] = c
        if errors:
            raise InvalidEdit(errors)

        eff = report.effective_date
        latest = _latest_dates(patient, exclude_report=report)
        result = ProcessingResult()
        changed: list[str] = []
        history_rows = 0

        for row in rows:
            pf = row.patient_field
            row.previous_value = _to_display(getattr(patient, pf, None))[:255]
            prior_reason = row.skip_reason
            row.skip_reason = ''

            if pf in _REVIEW_ONLY_PATIENT_FIELDS:
                group = v.normalise_blood_group(edits.get(pf, row.converted_value))
                row.converted_value = (group or row.converted_value)[:50]
                if not group:
                    row.change_status, row.flag = S.SKIPPED, v.INVALID
                    row.skip_reason = 'Not a valid blood group.'
                elif not patient.blood_group:
                    patient.blood_group = group
                    changed.append(pf)
                    row.change_status, row.flag = S.INSERTED, ''
                elif patient.blood_group == group:
                    row.change_status, row.flag = S.UNCHANGED, ''
                else:
                    row.change_status, row.flag = S.SKIPPED, v.BLOOD_GROUP_CONFLICT
                    row.skip_reason = 'Different from the blood group on file, so it was not changed.'
                row.save()
                result.add(row)
                continue

            if pf not in _UPDATABLE_PATIENT_FIELDS:
                continue

            if pf in checked_edits:
                c = checked_edits[pf]
                row.converted_value, row.converted_unit, row.flag = (c.value or '')[:50], c.unit[:20], c.flag
                message = c.message
            else:
                message = ''
                if row.flag and row.flag != v.OUT_OF_RANGE:
                    # Unknown unit / invalid / too large, not corrected by the user.
                    row.change_status = S.SKIPPED
                    row.skip_reason = prior_reason or 'This value could not be used.'
                    row.save()
                    result.add(row)
                    continue

            if row.flag == v.OUT_OF_RANGE and pf not in accept:
                row.change_status = S.SKIPPED
                reason = (message or prior_reason or 'Outside the expected range.').rstrip()
                row.skip_reason = (reason + ' Not saved because it was not accepted.')[:255]
                row.save()
                result.add(row)
                continue

            db_value = v.to_db_value(patient, pf, row.converted_value)
            if db_value is None:
                row.change_status, row.flag = S.SKIPPED, v.TOO_LARGE
                row.skip_reason = 'This value is too large to store.'
                row.save()
                result.add(row)
                continue

            LabResult.objects.create(
                patient=patient, report=report, test_name=pf, value=str(db_value)[:32],
                value_numeric=None if pf == 'blood_pressure' else Decimal(db_value),
                unit=CANONICAL_UNITS.get(pf, row.converted_unit)[:20], report_date=eff,
            )
            history_rows += 1

            current = row.previous_value
            if pf in latest and latest[pf] > eff:
                row.change_status = S.HISTORY
                row.skip_reason = f'Kept in the history; a newer result ({latest[pf]:%d %b %Y}) is shown.'
            elif current and _normalise(current, pf) == _normalise(str(db_value), pf):
                row.change_status = S.UNCHANGED
            else:
                setattr(patient, pf, db_value)
                changed.append(pf)
                row.change_status = S.UPDATED if current else S.INSERTED
            row.save()
            result.add(row)

        if changed:
            patient.save(update_fields=list(dict.fromkeys(changed)))

        report.detected_count = result.detected_count
        report.updated_count = result.updated_count
        report.unchanged_count = result.unchanged_count
        report.status = LabReport.Status.CONFIRMED
        report.error_message = ''
        report.confirmed_at = timezone.now()
        report.confirmed_by = user
        report.save(update_fields=['detected_count', 'updated_count', 'unchanged_count', 'status',
                                   'error_message', 'confirmed_at', 'confirmed_by'])

        # Audit: counts and test names only, never values.
        edited = sorted(checked_edits) + (['blood_group'] if 'blood_group' in edits else [])
        log_activity(
            user, 'CONFIRM_LAB_REPORT',
            f'Confirmed lab report {report.id} for patient {patient.patient_id}: '
            f'{len(changed)} updated, {history_rows} saved to history, {result.needs_review_count} not saved'
            + (f'; edited by user: {", ".join(edited)}' if edited else '')
            + (f'; accepted out-of-range: {", ".join(sorted(accept & allowed))}' if accept & allowed else '')
            + '.',
            request,
        )

    return ConfirmOutcome(result, changed, history_rows)


def save_without_values(report: LabReport, user=None, request=None) -> LabReport:
    """Keep a report that has no health card values as a document only: the file and
    its details are kept; no values, history rows or dashboard changes are written."""
    from apps.lab_reports.services.verifier import mask_id

    with transaction.atomic():
        report = LabReport.objects.select_for_update().select_related('patient').get(pk=report.pk)
        if report.status != LabReport.Status.NO_VALUES_SAVEABLE:
            raise NotPending()
        report.status = LabReport.Status.SAVED_NO_VALUES
        report.detected_count = report.updated_count = report.unchanged_count = 0
        report.confirmed_at = timezone.now()
        report.confirmed_by = user
        report.save(update_fields=['status', 'detected_count', 'updated_count', 'unchanged_count',
                                   'confirmed_at', 'confirmed_by'])
        log_activity(
            user, 'SAVE_LAB_REPORT_NO_VALUES',
            f'Lab report {report.id} for patient {mask_id(report.patient.patient_id)} saved without card values'
            + ('' if report.identity_verified else ' (identity not verified)') + '.',
            request,
        )
    return report


def delete_report(report: LabReport, user=None, request=None) -> list[str]:
    """Delete a report and its stored file. For a confirmed report its history
    rows go too, and every dashboard value it set falls back to the newest
    remaining result (or is cleared when none is left). A value changed since by
    hand or by another report is kept. Blood group is never changed. Returns the
    tests whose dashboard value changed."""
    with transaction.atomic():
        report = LabReport.objects.select_for_update().get(pk=report.pk)
        patient = report.patient.__class__.objects.select_for_update().get(pk=report.patient_id)
        own = {r.test_name: r.value for r in LabResult.objects.filter(report=report)}
        report_id = report.id
        report.delete()   # cascades to its fields and LabResult rows; also deletes the file

        reverted = []
        for test, value in own.items():
            current = getattr(patient, test, None)
            if current in (None, '') or _normalise(_to_display(current), test) != _normalise(value, test):
                continue   # this report's value is not the one shown
            newest = LabResult.objects.filter(patient=patient, test_name=test).order_by('-report_date', '-id').first()
            setattr(patient, test, newest.value if newest else None)
            reverted.append(test)
        if reverted:
            patient.save(update_fields=reverted)

        log_activity(
            user, 'DELETE_LAB_REPORT',
            f'Deleted lab report {report_id} for patient {patient.patient_id}'
            + (f'; dashboard values reverted: {", ".join(sorted(reverted))}' if reverted else '') + '.',
            request,
        )
    return reverted


def _latest_dates(patient, exclude_report=None) -> dict:
    """test name → date of the newest stored result."""
    qs = LabResult.objects.filter(patient=patient)
    if exclude_report is not None and exclude_report.pk:
        qs = qs.exclude(report_id=exclude_report.pk)
    latest: dict = {}
    for test, day in qs.values_list('test_name', 'report_date'):
        if test not in latest or day > latest[test]:
            latest[test] = day
    return latest


# ── Dashboard ────────────────────────────────────────────────────────────────

LOW, NORMAL, HIGH = 'Low', 'Normal', 'High'
DISCLAIMER = 'Informational only, not medical advice.'

# The cards the dashboard shows, in order. The first three are the main lab cards.
DASHBOARD_TESTS = (
    'hemoglobin', 'cholesterol_total', 'blood_sugar_random', 'blood_sugar_fasting',
    'cholesterol_hdl', 'cholesterol_ldl', 'triglycerides', 'blood_pressure', 'hba1c',
)
# Other tests appear (as smaller tiles, after the ones above) once the patient
# has a value for them, so every confirmed result is visible on the dashboard.
EXTRA_TESTS = (
    'serum_creatinine', 'blood_urea', 'uric_acid', 'sodium', 'potassium',
    'ssgpt_alt', 'ssgot_ast', 'bilirubin_total',
    'hematocrit', 'wbc_count', 'rbc_count', 'platelet_count', 'esr',
    'tsh', 't3', 't4',
)
HISTORY_POINTS = 12


def _reference(test: str, gender: str) -> tuple[float | None, float | None, str]:
    """(low, high, text) adult reference range used for the status badge."""
    female = gender == 'Female'
    table = {
        'hemoglobin': (12.0, 15.5) if female else (13.5, 17.5),
        'blood_sugar_random': (70, 139),
        'blood_sugar_fasting': (70, 99),
        'cholesterol_total': (None, 199),
        'cholesterol_hdl': (50 if female else 40, None),
        'cholesterol_ldl': (None, 129),
        'triglycerides': (None, 149),
        'hba1c': (None, 5.6),
        'serum_creatinine': (0.5, 1.1) if female else (0.7, 1.3),
        'blood_urea': (15, 45),
        'uric_acid': (2.4, 6.0) if female else (3.4, 7.0),
        'sodium': (135, 145),
        'potassium': (3.5, 5.1),
        'ssgpt_alt': (None, 40),
        'ssgot_ast': (None, 40),
        'bilirubin_total': (0.1, 1.2),
        'hematocrit': (36, 46) if female else (40, 50),
        'esr': (None, 20) if female else (None, 15),
        'tsh': (0.4, 4.0),
        't3': (80, 200),
        't4': (5.0, 12.0),
    }
    low, high = table.get(test, (None, None))
    unit = CANONICAL_UNITS.get(test, '')
    if low is not None and high is not None:
        text = f'{_n(low)}–{_n(high)} {unit}'
    elif high is not None:
        text = f'below {_n(round(high + (0.1 if isinstance(high, float) else 1), 2))} {unit}'
    elif low is not None:
        text = f'{_n(low)} {unit} or more'
    else:
        text = ''
    return low, high, text.strip()


def _n(x) -> str:
    return format(Decimal(str(x)).normalize(), 'f')


def status_for(test: str, value, gender: str = '') -> tuple[str | None, bool]:
    """(Low/Normal/High or None, severe) for a value. Severe marks values far from normal."""
    if value in (None, ''):
        return None, False
    if test == 'blood_pressure':
        try:
            sys_, dia = (int(x) for x in str(value).split('/'))
        except ValueError:
            return None, False
        if sys_ >= 130 or dia >= 80:
            return HIGH, sys_ >= 180 or dia >= 120
        if sys_ < 90 or dia < 60:
            return LOW, sys_ < 80 or dia < 50
        return NORMAL, False
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None, False
    low, high, _ = _reference(test, gender)
    if low is None and high is None:
        return None, False
    severe_high = {'blood_sugar_random': 200, 'blood_sugar_fasting': 126, 'cholesterol_total': 240,
                   'cholesterol_ldl': 160, 'triglycerides': 200, 'hba1c': 6.5}
    if low is not None and n < low:
        return LOW, n < low - 2 if test == 'hemoglobin' else n < low * 0.8
    if high is not None and n > high:
        return HIGH, n >= severe_high.get(test, float('inf'))
    return NORMAL, False


def bmi_of(patient) -> float | None:
    try:
        h, w = float(patient.height), float(patient.weight)
    except (TypeError, ValueError):
        return None
    return round(w / (h / 100) ** 2, 1) if h and w else None


def _trend(points: list[dict]) -> str | None:
    if len(points) < 2:
        return None
    prev, last = points[-2]['value'], points[-1]['value']
    if prev == 0:
        return None
    change = (last - prev) / abs(prev)
    return 'up' if change > 0.02 else 'down' if change < -0.02 else 'stable'


def build_dashboard(patient) -> dict:
    results = {}
    for r in LabResult.objects.filter(patient=patient).order_by('report_date', 'id'):
        results.setdefault(r.test_name, []).append(r)

    extra = tuple(t for t in EXTRA_TESTS if t in results or getattr(patient, t, None) not in (None, ''))
    tests = []
    for test in DASHBOARD_TESTS + extra:
        current = getattr(patient, test, None)
        rows = results.get(test, [])
        history = [{'date': r.report_date.isoformat(), 'value': float(r.value_numeric)}
                   for r in rows if r.value_numeric is not None][-HISTORY_POINTS:]
        status, severe = status_for(test, current, patient.gender)
        _, _, ref = _reference(test, patient.gender)
        tests.append({
            'test': test,
            'label': display_name(test),
            'unit': CANONICAL_UNITS.get(test, ''),
            'latest': None if current in (None, '') else {
                'value': _to_display(current),
                'date': rows[-1].report_date.isoformat() if rows else None,
            },
            'status': status,
            'severe': severe,
            'reference': ref,
            'history': history,
            'trend': _trend(history),
        })

    bmi = bmi_of(patient)
    bmi_status = None if bmi is None else (LOW if bmi < 18.5 else HIGH if bmi >= 25 else NORMAL)
    return {
        'patient_id': patient.patient_id,
        'age': patient.age,
        'gender': patient.gender,
        'blood_group': patient.blood_group or None,
        'body': {
            'height': _to_display(patient.height) or None,
            'weight': _to_display(patient.weight) or None,
            'bmi': bmi,
            'bmi_status': bmi_status,
            'bmi_severe': bool(bmi and bmi >= 30),
        },
        'tests': tests,
        'disclaimer': DISCLAIMER,
    }
