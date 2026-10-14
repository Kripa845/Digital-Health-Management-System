"""Smart symptom check: text → negation detection → red flags → Random Forest → department
→ information-gain question if unsure → AHP-weighted TOPSIS → doctors.

POST /api/v1/smart-symptom-check/
    {"text": "...", "answers": {"E_77": true, "E_91": false}, "dismissed": ["feverr"]}

"answers" (optional) are the replies to earlier follow-up questions and confirmed
"Did you mean ...?" suggestions, keyed by symptom name (ml/data/symptom_schema.json).
"dismissed" (optional) lists suggestion terms the user said were not meant as that symptom.

Statuses (ml/symptom_model.py):
- "ok": department, illnesses and TOPSIS-ranked doctors; saved to the symptom history.
- "emergency": a red-flag rule matched; the model was not called; not saved.
- "needs_confirmation": "suggestions" to confirm or dismiss first; the model was not called.
- "not_enough_info" / "low_confidence": "not enough information": General Medicine doctors
  as the first point of contact, maybe a follow-up "question"; saved to the history.
- "model_unavailable" (503): the frontend uses the keyword checker (POST /api/v1/recommendations/).

The output is a suggestion, never a diagnosis.
"""
from __future__ import annotations

import logging

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.utils import log_activity
from apps.doctors.models import Doctor
from apps.patients.models import Patient
from apps.recommendations.models import RankingSettings, RecommendationHistory
from apps.recommendations.serializers import RankingSettingsSerializer
from apps.users.permissions import IsAdmin
from apps.recommendations.ranking import (  # noqa: F401  (free_hours_this_week, caseload: used by tests)
    caseload, free_hours_this_week, reason, score_doctors, with_ranking_data,
)
from ml import symptom_model
from ml.schema import get as get_schema

DISCLAIMER = symptom_model.DISCLAIMER
MAX_TEXT_LENGTH = 2000
TOP_DOCTORS = 3
FALLBACK_DEPARTMENT = 'General Medicine'
UNAVAILABLE_MESSAGE = ('The smart symptom check is not available right now. Please try again later, '
                       'or use the general symptom checker.')

logger = logging.getLogger(__name__)


# ── Doctor ranking (AHP-weighted TOPSIS, apps/recommendations/ranking.py) ────

def department_match(department: str, departments: dict[str, float] | None = None) -> dict[str, float]:
    """Specialisation match: 1.0 for the suggested department, the model's share for the others."""
    return {**(departments or {}), department: 1.0}


def rank_doctors(doctors: list[Doctor], today=None, match: dict[str, float] | None = None) -> list[dict]:
    """Top doctors by AHP-weighted TOPSIS on the five criteria.

    Doctors not loaded through with_ranking_data are loaded again with it, so the
    number of queries stays the same however many doctors there are.
    """
    doctors = list(doctors)
    if any(not hasattr(d, 'open_bookings') for d in doctors):
        doctors = list(with_ranking_data(Doctor.objects.filter(pk__in=[d.pk for d in doctors]), today))
    if match is None:                       # no department suggested: every doctor fits equally
        match = {d.department: 1.0 for d in doctors}
    rows = score_doctors(doctors, match, today)
    return [{
        'id': r['doctor'].id,
        'name': r['doctor'].user.get_full_name() or r['doctor'].user.username,
        'department': r['doctor'].department,
        'specialization': r['doctor'].specialization,
        'score': r['score'],
        'earliest_slot_hours': r['earliest_slot'],
        'free_hours': r['free_hours'],
        'caseload': r['caseload'],
        'experience_years': r['experience'],
        'match': r['match'],
        'reason': reason(r, rows),
    } for r in rows[:TOP_DOCTORS]]


def _active_doctors(department: str) -> list[Doctor]:
    return list(with_ranking_data(Doctor.objects.filter(department=department, status='Active')))


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

        answers = request.data.get('answers') or {}
        if not isinstance(answers, dict) or not all(
                k in get_schema().names and isinstance(v, bool) for k, v in answers.items()):
            return Response({'detail': 'Follow-up answers must be {symptom: true/false} for known symptoms.',
                             'disclaimer': DISCLAIMER}, status=status.HTTP_400_BAD_REQUEST)

        dismissed = request.data.get('dismissed') or []
        if not isinstance(dismissed, list) or not all(isinstance(d, str) for d in dismissed):
            return Response({'detail': 'Dismissed suggestions must be a list of terms.',
                             'disclaimer': DISCLAIMER}, status=status.HTTP_400_BAD_REQUEST)

        patient, error = self._patient_for(request)
        if error:
            return error

        result = symptom_model.predict(text, answers, dismissed=dismissed)
        if result['status'] == 'model_unavailable':
            # Not a "no symptoms found" result: nothing was analysed. 503 so the client
            # treats it as a failure and uses the keyword checker.
            logger.warning('Smart symptom check unavailable: %s', symptom_model.unavailable_reason())
            return Response({'status': 'model_unavailable', 'detail': UNAVAILABLE_MESSAGE,
                             'fallback': 'keyword', 'disclaimer': DISCLAIMER},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if result['status'] in ('not_enough_info', 'low_confidence'):
            # "Not enough information": General Medicine as the first point of contact.
            candidates = _active_doctors(FALLBACK_DEPARTMENT)
            doctors = rank_doctors(candidates, match={FALLBACK_DEPARTMENT: 1.0})
            history = self._save_history(request, patient, text, result, doctors)
            return Response({**result, 'doctors': doctors,
                             'doctors_department': FALLBACK_DEPARTMENT if candidates else None,
                             'doctors_note': '' if candidates else
                             'No General Medicine doctor is available right now. Please contact the hospital.',
                             'history_id': history.id, 'disclaimer': DISCLAIMER})
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
        doctors = rank_doctors(candidates, match=department_match(department, result.get('departments')))

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
        top = doctors[0] if doctors else None
        sure = result['status'] == 'ok'
        if sure:
            illnesses = ', '.join(f"{i['name']} {round(100 * i['probability'])}%" for i in result['illnesses'])
            summary = (f"likely area {result['department']} ({round(100 * result['dept_probability'])}%). "
                       f"Possible illnesses: {illnesses}. ")
        else:
            summary = (f"not enough information ({result.get('reason') or 'too few symptoms'}); "
                       f"{result['department']} suggested as first point of contact. ")
        reason = ("Smart check (Random Forest + AHP-weighted TOPSIS): " + summary
                  + (f"Dr. {top['name']}: {top['reason']}. " if top else 'No doctor available. ')
                  + DISCLAIMER)
        history = RecommendationHistory.objects.create(
            patient=patient,
            symptoms=text,
            pain_level=5,                 # not asked by the smart check; the keyword checker's default
            recommended_doctor_id=top['id'] if top else None,
            recommended_department=result['department'],
            score=top['score'] if top else None,
            confidence=round(100 * result['dept_probability']) if sure else None,
            reason=reason,
        )
        if user and user.is_authenticated:
            log_activity(user, 'RECOMMENDATION',
                         f"Smart symptom check"
                         + (f" for patient {patient.patient_id}" if patient else '')
                         + f": department {result['department']} "
                         + (f"({round(100 * result['dept_probability'])}%)." if sure else '(not enough information).'),
                         request)
        return history


# ── Ranking settings (the administrator's AHP comparisons) ──────────────────

class RankingSettingsView(APIView):
    """GET / PUT /api/v1/ranking-settings/   {"ahp_pairwise": [[...5 numbers], ...]}

    Saving recomputes the criterion weights and the consistency ratio; a matrix that
    is not reciprocal or too inconsistent (CR >= 0.10) is refused with 400.
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        return Response(RankingSettingsSerializer(RankingSettings.load()).data)

    def put(self, request):
        serializer = RankingSettingsSerializer(RankingSettings.load(), data=request.data)
        serializer.is_valid(raise_exception=True)
        obj = serializer.save()
        log_activity(request.user, 'UPDATE_RANKING_SETTINGS',
                     'Doctor ranking weights updated: '
                     + ', '.join(f'{k} {v:.3f}' for k, v in obj.ahp_weights.items())
                     + f' (CR {obj.ahp_cr:.3f}).', request)
        return Response(serializer.data)
