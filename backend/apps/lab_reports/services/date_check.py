"""Report date ordering check: is a new report older than the patient's latest one?

The comparison date is the latest report date among this patient's CONFIRMED
reports (including reports saved as documents without card values), worked out from the data every time (never stored), so a deleted,
rejected or never-confirmed report does not count, and deleting the latest
confirmed report falls back to the next one.

    ok                 same day or later than the latest confirmed report
    first_report       no confirmed report with a date yet
    older_than_latest  earlier than the latest confirmed report
    date_missing       no reporting date could be read (the user can type it)

What happens to an older report depends on LAB_REPORT_OLDER_DATE_POLICY:
    warn  (default)  shown with a warning; confirming needs acknowledge_older_report
    block            refused (HTTP 422), nothing stored
    allow            accepted without a warning

Either way an older report never replaces a newer value on the dashboard; it
only adds dated history rows (see services/dashboard.py). Dates are never logged.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.conf import settings
from django.db.models import Max

from apps.lab_reports.models import LabReport

OK = 'ok'
FIRST_REPORT = 'first_report'
OLDER_THAN_LATEST = 'older_than_latest'
DATE_MISSING = 'date_missing'

WARN, BLOCK, ALLOW = 'warn', 'block', 'allow'


def check_report_date(new_date: date | None, latest_confirmed_date: date | None) -> str:
    """Compare a report's date with the latest confirmed one (pure function)."""
    if new_date is None:
        return DATE_MISSING
    if latest_confirmed_date is None:
        return FIRST_REPORT
    return OLDER_THAN_LATEST if new_date < latest_confirmed_date else OK


def policy() -> str:
    value = str(getattr(settings, 'LAB_REPORT_OLDER_DATE_POLICY', WARN)).lower()
    return value if value in (WARN, BLOCK, ALLOW) else WARN


def latest_confirmed_date(patient, exclude_report: LabReport | None = None) -> date | None:
    """Latest report date among this patient's confirmed reports (reports without a date are ignored)."""
    qs = LabReport.objects.filter(
        patient=patient, report_date__isnull=False,
        status__in=(LabReport.Status.CONFIRMED, LabReport.Status.SAVED_NO_VALUES),   # saved documents count too
    )
    if exclude_report is not None and exclude_report.pk:
        qs = qs.exclude(pk=exclude_report.pk)
    return qs.aggregate(latest=Max('report_date'))['latest']


def _show(d: date) -> str:
    return f'{d.day} {d:%b %Y}'


@dataclass
class DateCheck:
    status: str
    new_date: date | None
    latest_date: date | None
    policy: str

    @property
    def ack_required(self) -> bool:
        """An older report needs the user's explicit confirmation (policy "warn")."""
        return self.status == OLDER_THAN_LATEST and self.policy == WARN

    @property
    def blocked(self) -> bool:
        return self.status == OLDER_THAN_LATEST and self.policy == BLOCK

    @property
    def message(self) -> str:
        if self.status == OLDER_THAN_LATEST and self.policy != ALLOW:
            return (f'This report ({_show(self.new_date)}) is older than your latest report '
                    f'({_show(self.latest_date)}).')
        if self.status == DATE_MISSING:
            return 'No reporting date could be read from this report. Enter the date printed on the report.'
        return ''


def evaluate(patient, new_date: date | None, exclude_report: LabReport | None = None) -> DateCheck:
    latest = latest_confirmed_date(patient, exclude_report)
    return DateCheck(check_report_date(new_date, latest), new_date, latest, policy())


def evaluate_report(report: LabReport) -> DateCheck:
    return evaluate(report.patient, report.report_date, exclude_report=report)
