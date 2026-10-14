
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.db.models import Count, Prefetch, Q
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.doctors.scheduling import parse_window
from apps.recommendations.models import RankingSettings
from ml.ahp import BENEFIT, CRITERIA, validate_criteria_weights
from ml.topsis import topsis

# Days ahead searched for a free slot; with none, the whole horizon counts as the wait.
HORIZON_DAYS = 14
NO_SLOT_HOURS = HORIZON_DAYS * 24
# Appointments have no duration field; each booking is assumed to take this long. Review.
APPOINTMENT_HOURS = 0.5
SLOT = timedelta(hours=APPOINTMENT_HOURS)
# Bookings that still take up a doctor's time.
OPEN_APPOINTMENT_STATUSES = ('PENDING', 'ACCEPTED')


def with_ranking_data(queryset, today: date | None = None):
    """The doctors with ``active_load`` and ``open_bookings`` (open bookings in the horizon)."""
    today = today or timezone.localdate()
    bookings = Appointment.objects.filter(
        appointment_date__gte=today, appointment_date__lt=today + timedelta(days=HORIZON_DAYS),
        status__in=OPEN_APPOINTMENT_STATUSES,
    )
    return (queryset.select_related('user')
            .annotate(active_load=Count('assignments', filter=Q(assignments__status='Active'), distinct=True))
            .prefetch_related(Prefetch('appointments', queryset=bookings, to_attr='open_bookings')))


schedule_window = parse_window


def _bookings(doctor, first: date, last: date) -> list:
    """Open bookings between two dates: from the prefetch when present, else one query."""
    prefetched = getattr(doctor, 'open_bookings', None)
    if prefetched is not None:
        return [a for a in prefetched if first <= a.appointment_date <= last]
    return list(Appointment.objects.filter(doctor=doctor, appointment_date__gte=first,
                                           appointment_date__lte=last, status__in=OPEN_APPOINTMENT_STATUSES))


def hours_to_earliest_slot(doctor, now: datetime) -> float:
    """Hours from ``now`` (naive local time) to the start of the first free slot in the horizon.

    The day's schedule is cut into APPOINTMENT_HOURS slots; a slot is taken when an
    open booking starts inside it. NO_SLOT_HOURS when nothing is free.
    """
    today = now.date()
    last = today + timedelta(days=HORIZON_DAYS - 1)
    taken: dict[date, list[time]] = {}
    for a in _bookings(doctor, today, last):
        taken.setdefault(a.appointment_date, []).append(a.appointment_time)
    schedule = doctor.availability_schedule or {}
    for offset in range(HORIZON_DAYS):
        day = today + timedelta(days=offset)
        window = schedule_window(schedule.get(day.strftime('%A')))
        if window is None:
            continue
        start, end = (datetime.combine(day, t) for t in window)
        booked = [datetime.combine(day, t) for t in taken.get(day, [])]
        slot = start
        while slot + SLOT <= end:
            if slot >= now and not any(slot <= b < slot + SLOT for b in booked):
                return round((slot - now).total_seconds() / 3600, 1)
            slot += SLOT
    return float(NO_SLOT_HOURS)


def free_hours_this_week(doctor, today: date | None = None) -> float:
    """Scheduled hours from today to Sunday, minus the open bookings in those days."""
    today = today or timezone.localdate()
    days = [today + timedelta(days=i) for i in range(7 - today.weekday())]   # today .. Sunday
    schedule = doctor.availability_schedule or {}
    scheduled = 0.0
    for day in days:
        window = schedule_window(schedule.get(day.strftime('%A')))
        if window:
            scheduled += (datetime.combine(day, window[1]) - datetime.combine(day, window[0])).total_seconds() / 3600
    booked = len(_bookings(doctor, days[0], days[-1]))
    return max(scheduled - booked * APPOINTMENT_HOURS, 0.0)


def caseload(doctor) -> int:
    """Active patient assignments: the annotation when present, else one query."""
    load = getattr(doctor, 'active_load', None)
    return load if load is not None else doctor.assignments.filter(status='Active').count()


def current_weights() -> dict[str, float]:
    """The administrator's AHP weights, checked once more before use."""
    return validate_criteria_weights(RankingSettings.load().ahp_weights)


def _now(today: date | None) -> datetime:
    if today is None:
        return timezone.localtime().replace(tzinfo=None)
    return datetime.combine(today, time.min)


def score_doctors(doctors, match: dict[str, float], today: date | None = None) -> list[dict]:
    """One row per doctor with the five criteria and its TOPSIS ``score`` (0-1), best first.

    ``match`` maps department -> specialisation match; departments not in it count 0.
    Ties go to the lighter caseload, then the name.
    """
    doctors = list(doctors)
    if not doctors:
        return []
    now = _now(today)
    rows = [{
        'doctor': d,
        'earliest_slot': hours_to_earliest_slot(d, now),
        'free_hours': round(free_hours_this_week(d, now.date()), 1),
        'caseload': caseload(d),
        'experience': d.experience_years,
        'match': round(float(match.get(d.department, 0.0)), 4),
    } for d in doctors]
    weights = current_weights()
    scores = topsis([[r[c] for c in CRITERIA] for r in rows],
                    [weights[c] for c in CRITERIA], [BENEFIT[c] for c in CRITERIA])
    for r, s in zip(rows, scores):
        r['score'] = round(float(s), 3)
    rows.sort(key=lambda r: (-r['score'], r['caseload'], r['doctor'].user.get_full_name().lower()))
    return rows


def reason(row: dict, rows: list[dict]) -> str:
    """Why this doctor scored as they did, compared with the other candidates."""
    if len(rows) == 1:
        return 'only active doctor in this department'
    parts = []
    if row['earliest_slot'] < NO_SLOT_HOURS and row['earliest_slot'] == min(r['earliest_slot'] for r in rows):
        parts.append('earliest free slot')
    if row['free_hours'] == max(r['free_hours'] for r in rows):
        parts.append('most free hours')
    if row['caseload'] == min(r['caseload'] for r in rows):
        parts.append('lightest caseload')
    if row['experience'] and row['experience'] == max(r['experience'] for r in rows):
        parts.append('most experience')
    if not parts:
        parts.append(f"{row['free_hours']:g} free hours this week, {row['caseload']} active patients, "
                     f"{row['experience']} years' experience")
    return ', '.join(parts)
