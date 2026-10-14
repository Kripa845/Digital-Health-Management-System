"""Which appointment slots a doctor can still be booked for.

Everything is in Asia/Kathmandu time (settings.TIME_ZONE): dates and times are
the naive local values stored on Appointment, and "now" is timezone.localtime().
"""
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from apps.appointments.models import Appointment
from apps.doctors.models import DoctorLeave, DoctorSchedule

# Bookings that hold a slot (matches the unique_active_doctor_slot constraint).
ACTIVE_STATUSES = ('PENDING', 'ACCEPTED')
BOOKING_WINDOW_DAYS = 30


def local_now(now=None) -> datetime:
    """Naive Kathmandu wall-clock time (a naive ``now`` is taken as already local)."""
    if now is not None and timezone.is_naive(now):
        return now
    return timezone.localtime(now).replace(tzinfo=None)


def doctor_is_bookable(doctor) -> bool:
    return doctor.status == 'Active' and doctor.user.is_active


def free_slots(day: date, schedules, on_leave: bool, booked: list[time], now: datetime) -> list[time]:
    """The core rule: slot starts in the day's active schedule windows, minus
    leave days, past times and slots that overlap an open booking."""
    if on_leave or day < now.date():
        return []
    taken = [datetime.combine(day, t) for t in booked]
    slots = []
    for schedule in schedules:
        if not schedule.is_active or schedule.weekday != day.weekday():
            continue
        step = timedelta(minutes=schedule.slot_minutes)
        start = datetime.combine(day, schedule.start_time)
        end = datetime.combine(day, schedule.end_time)
        while start + step <= end:
            if start > now and not any(start <= b < start + step for b in taken):
                slots.append(start.time())
            start += step
    return sorted(slots)


def get_available_slots(doctor, day: date, now: datetime | None = None) -> list[time]:
    """Free slot start times for ``doctor`` on ``day`` (Kathmandu time).

    Empty when the doctor is inactive, on leave, has no active schedule that
    weekday, or the day is past; today's slots that have already started are
    dropped, as are slots holding a pending or accepted appointment.
    """
    now = local_now(now)
    if not doctor_is_bookable(doctor) or day < now.date():
        return []
    schedules = DoctorSchedule.objects.filter(doctor=doctor, weekday=day.weekday(), is_active=True)
    on_leave = DoctorLeave.objects.filter(doctor=doctor, date=day).exists()
    booked = list(Appointment.objects.filter(
        doctor=doctor, appointment_date=day, status__in=ACTIVE_STATUSES,
    ).values_list('appointment_time', flat=True))
    return free_slots(day, schedules, on_leave, booked, now)


def get_available_dates(doctor, days: int = BOOKING_WINDOW_DAYS, now: datetime | None = None) -> list[date]:
    """Days from today (inclusive) over the next ``days`` with at least one free
    slot. Same rule as get_available_slots, with three queries in total."""
    now = local_now(now)
    if not doctor_is_bookable(doctor):
        return []
    first = now.date()
    last = first + timedelta(days=days - 1)
    schedules = list(DoctorSchedule.objects.filter(doctor=doctor, is_active=True))
    if not schedules:
        return []
    leaves = set(DoctorLeave.objects.filter(
        doctor=doctor, date__range=(first, last),
    ).values_list('date', flat=True))
    booked: dict[date, list[time]] = {}
    for d, t in Appointment.objects.filter(
        doctor=doctor, appointment_date__range=(first, last), status__in=ACTIVE_STATUSES,
    ).values_list('appointment_date', 'appointment_time'):
        booked.setdefault(d, []).append(t)

    available = []
    for offset in range(days):
        day = first + timedelta(days=offset)
        if free_slots(day, schedules, day in leaves, booked.get(day, []), now):
            available.append(day)
    return available
