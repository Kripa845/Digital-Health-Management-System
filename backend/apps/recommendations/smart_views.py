"""Smart symptom check: text → negation detection → Naive Bayes → department → TOPSIS → doctors.

POST /api/v1/smart-symptom-check/   {"text": "..."}

Runs alongside the existing keyword-based checker (POST /api/v1/recommendations/),
which stays unchanged and is the fallback: when the model is not confident
(status other than "ok") this endpoint returns that status, and the frontend
then runs the keyword checker. Only "ok" results are saved to the symptom
history here; fallback checks are saved by the keyword checker as before.

The output is a suggestion, never a diagnosis.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.appointments.models import Appointment
from apps.audit.utils import log_activity
from apps.doctors.models import Doctor
from apps.patients.models import Patient
from apps.recommendations.models import RecommendationHistory
from ml import symptom_model
from ml.topsis import BENEFIT, criteria_weights, topsis

DISCLAIMER = symptom_model.DISCLAIMER
MAX_TEXT_LENGTH = 2000
TOP_DOCTORS = 3
FALLBACK_DEPARTMENT = 'General Medicine'
# Appointments have no duration field; each booking is assumed to take this long. Review.
APPOINTMENT_HOURS = 0.5
# Bookings that still take up a doctor's time.
OPEN_APPOINTMENT_STATUSES = ('PENDING', 'ACCEPTED')
# The Doctor model has no experience field, so two criteria are used (weights renormalised).
CRITERIA = ['free_hours', 'caseload']


# ── Doctor criteria from real model fields ───────────────────────────────────

def _scheduled_hours(slot) -> float:
    """Hours in a schedule entry such as "09:00-17:00"; 0 for "closed", empty or unreadable."""
    text = str(slot or '').strip().lower()
    if not text or text == 'closed' or '-' not in text:
        return 0.0
    try:
        start, end = (datetime.strptime(part.strip(), '%H:%M') for part in text.split('-', 1))
    except ValueError:
        return 0.0
    return max((end - start).total_seconds() / 3600, 0.0)


def free_hours_this_week(doctor: Doctor, today=None) -> float:
    """Scheduled hours from today to Sunday, minus the open bookings in those days."""
    today = today or timezone.localdate()
    days = [today + timedelta(days=i) for i in range(7 - today.weekday())]   # today .. Sunday
    schedule = doctor.availability_schedule or {}
    scheduled = sum(_scheduled_hours(schedule.get(day.strftime('%A'))) for day in days)
    booked = Appointment.objects.filter(
        doctor=doctor, appointment_date__gte=days[0], appointment_date__lte=days[-1],
        status__in=OPEN_APPOINTMENT_STATUSES,
    ).count()
    return max(scheduled - booked * APPOINTMENT_HOURS, 0.0)


def caseload(doctor: Doctor) -> int:
    """Active patient assignments (the same measure the keyword checker uses)."""
    return doctor.assignments.filter(status='Active').count()


def _reason(row: dict, rows: list[dict]) -> str:
    if len(rows) == 1:
        return 'only active doctor in this department'
    parts = []
    if row['free_hours'] == max(r['free_hours'] for r in rows):
        parts.append('most free hours')
    if row['caseload'] == min(r['caseload'] for r in rows):
        parts.append('lightest caseload')
    if not parts:
        parts.append(f"{row['free_hours']:g} free hours this week, {row['caseload']} active patients")
    return ', '.join(parts)


def rank_doctors(doctors: list[Doctor], today=None) -> list[dict]:
    """Top doctors by TOPSIS on free hours (benefit) and caseload (cost)."""
    rows = [{
        'doctor': d,
        'free_hours': round(free_hours_this_week(d, today), 1),
        'caseload': caseload(d),
    } for d in doctors]
    if not rows:
        return []
    matrix = [[r[c] for c in CRITERIA] for r in rows]
    scores = topsis(matrix, criteria_weights(CRITERIA), [BENEFIT[c] for c in CRITERIA])
    for r, s in zip(rows, scores):
        r['score'] = round(float(s), 3)
    rows.sort(key=lambda r: (-r['score'], r['caseload'], r['doctor'].user.get_full_name().lower()))
    top = rows[:TOP_DOCTORS]
    return [{
        'id': r['doctor'].id,
        'name': r['doctor'].user.get_full_name() or r['doctor'].user.username,
        'department': r['doctor'].department,
        'specialization': r['doctor'].specialization,
        'score': r['score'],
        'free_hours': r['free_hours'],
        'caseload': r['caseload'],
        'reason': _reason(r, rows),
    } for r in top]


def _active_doctors(department: str) -> list[Doctor]:
    return list(Doctor.objects.filter(department=department, status='Active').select_related('user'))


# ── The endpoint ─────────────────────────────────────────────────────────────

class SmartSymptomCheckView(APIView):
    permission_classes = [permissions.AllowAny]   # same as the keyword checker

    def post(self, request):
        text = request.data.get('text', '')
        if not isinstance(text, str) or not text.strip():
            return Response({'detail': 'Describe your symptoms, for example "fever, cough and headache".',
                             'disclaimer': DISCLAIMER}, status=status.HTTP_400_BAD_REQUEST)
        if len(text) > MAX_TEXT_LENGTH:
            return Response({'detail': f'Please keep the description under {MAX_TEXT_LENGTH} characters.',
                             'disclaimer': DISCLAIMER}, status=status.HTTP_400_BAD_REQUEST)

        patient, error = self._patient_for(request)
        if error:
            return error

        result = symptom_model.predict(text)
        if result['status'] != 'ok':
            return Response({**result, 'disclaimer': DISCLAIMER})

        department = result['department']
        doctors_department, note = department, ''
        candidates = _active_doctors(department)
        if not candidates and department != FALLBACK_DEPARTMENT:
            candidates = _active_doctors(FALLBACK_DEPARTMENT)
            doctors_department = FALLBACK_DEPARTMENT
            note = (f'No {department} doctor is available right now, so General Medicine doctors are shown '
                    'as a first point of contact.')
        if not candidates:
            doctors_department = None
            note = f'No {department} doctor is available right now. Please contact the hospital.'
        doctors = rank_doctors(candidates)

        history = self._save_history(request, patient, text, result, doctors)
        return Response({
            **result,
            'doctors': doctors,
            'doctors_department': doctors_department,
            'doctors_note': note,
            'history_id': history.id,
            'patient': {'id': patient.id, 'patient_id': patient.patient_id,
                        'name': f'{patient.first_name} {patient.last_name}'} if patient else None,
            'disclaimer': DISCLAIMER,
        })

    def _patient_for(self, request):
        """The patient this check is for: a patient checks for themselves; an admin may
        choose an existing patient with "patient_id". Returns (patient or None, error response)."""
        user = request.user
        if not (user and user.is_authenticated):
            return None, None
        if user.role == 'PATIENT':
            return getattr(user, 'patient_profile', None), None
        if user.role == 'ADMIN':
            raw = request.data.get('patient_id')
            if raw in (None, ''):
                return None, None
            patient = Patient.objects.filter(pk=raw).first() if str(raw).isdigit() else None
            if patient is None:
                return None, Response({'detail': 'Patient not found.', 'disclaimer': DISCLAIMER},
                                      status=status.HTTP_400_BAD_REQUEST)
            return patient, None
        return None, None

    def _save_history(self, request, patient, text, result, doctors) -> RecommendationHistory:
        """Saved the same way as the keyword checker saves its results."""
        user = request.user
        illnesses = ', '.join(f"{i['name']} {round(100 * i['probability'])}%" for i in result['illnesses'])
        top = doctors[0] if doctors else None
        reason = (f"Smart check (Naive Bayes + TOPSIS): likely area {result['department']} "
                  f"({round(100 * result['dept_probability'])}%). Possible illnesses: {illnesses}. "
                  + (f"Dr. {top['name']}: {top['reason']}. " if top else 'No doctor available. ')
                  + DISCLAIMER)
        history = RecommendationHistory.objects.create(
            patient=patient,
            symptoms=text,
            pain_level=5,                 # not asked by the smart check; the keyword checker's default
            recommended_doctor_id=top['id'] if top else None,
            recommended_department=result['department'],
            score=top['score'] if top else None,
            confidence=round(100 * result['dept_probability']),
            reason=reason,
        )
        if user and user.is_authenticated:
            log_activity(user, 'RECOMMENDATION',
                         f"Smart symptom check"
                         + (f" for patient {patient.patient_id}" if patient else '')
                         + f": department {result['department']} "
                         f"({round(100 * result['dept_probability'])}%).", request)
        return history
