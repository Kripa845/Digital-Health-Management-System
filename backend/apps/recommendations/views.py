import csv
import json
from datetime import date as date_type
from pathlib import Path

from rest_framework import viewsets, permissions, status
from rest_framework.response import Response

from apps.recommendations.models import RecommendationHistory
from apps.recommendations.serializers import RecommendationHistorySerializer
from apps.doctors.models import Doctor
from apps.doctors.serializers import DoctorSerializer
from apps.patients.models import Patient
from apps.audit.utils import log_activity


_DATA_DIR = Path(__file__).resolve().parent / 'data'


def _load_department_map():
    with open(_DATA_DIR / 'symptom_department_map.json', encoding='utf-8') as fh:
        data = json.load(fh)
    return data['department_rules'], data['department_equivalences']


def _load_symptom_severity():
    severity = {}
    path = _DATA_DIR / 'symptom_severity.csv'
    if not path.exists():
        return severity
    with open(path, encoding='utf-8') as fh:
        for row in csv.DictReader(fh):
            name = (row.get('Symptom') or '').strip().lower()
            try:
                weight = int(row.get('weight') or 0)
            except (TypeError, ValueError):
                continue
            if name:
                severity[name] = weight
    return severity


DEPARTMENT_RULES, DEPARTMENT_EQUIVALENCES = _load_department_map()
SYMPTOM_SEVERITY = _load_symptom_severity()
_MAX_SEVERITY = 7


def clinical_severity_index(symptoms: str) -> int:
    text = (symptoms or '').lower()
    matched = [
        weight for name, weight in SYMPTOM_SEVERITY.items()
        if name.replace('_', ' ') in text
    ]
    if not matched:
        return 0
    return round(100 * max(matched) / _MAX_SEVERITY)


def score_departments(symptoms: str, medical_history: str = '') -> dict:
    symptoms_lower = (symptoms or '').lower()
    history_lower = (medical_history or '').lower()
    scores: dict[str, float] = {}

    for dept, keywords in DEPARTMENT_RULES.items():
        total = 0.0
        for kw, weight in keywords.items():
            if kw in symptoms_lower:
                total += weight
            if history_lower and kw in history_lower:
                total += weight * 0.5
        if total > 0:
            scores[dept] = total

    return scores


def match_department(symptoms: str, medical_history: str = '') -> str:
    scores = score_departments(symptoms, medical_history)
    if not scores:
        return 'General Medicine'
    return max(scores, key=lambda d: scores[d])


def department_confidence(dept_scores: dict, primary_dept: str) -> int:
    if not dept_scores:
        return 40
    total = sum(dept_scores.values())
    top = dept_scores.get(primary_dept, 0)
    if total <= 0:
        return 40
    raw = round(100 * top / total)
    return max(25, min(98, raw))


def age_fit(department: str, age) -> tuple:
    if age is None:
        return 0.0, None
    if department == 'Pediatrics':
        if age <= 14:
            return 15.0, "patient age suits Pediatrics"
        return 0.0, None
    if age <= 14 and department in ('General Medicine', 'Family Medicine'):
        return 8.0, "general care appropriate for a young patient"
    if age >= 60 and department in ('Cardiology', 'General Medicine', 'Endocrinology', 'Nephrology', 'Neurology'):
        return 10.0, "age is a relevant risk factor for this department"
    return 6.0, None


def score_doctor(doctor, ctx) -> tuple:
    reasons = []
    score = 0.0

    dept_raw = ctx['dept_scores'].get(doctor.department, 0)
    if ctx['top_dept_score'] > 0:
        match_pts = 50.0 * dept_raw / ctx['top_dept_score']
    else:
        match_pts = 0.0
    score += match_pts
    if dept_raw > 0:
        reasons.append(f"symptoms match {doctor.department}")

    history_lower = ctx['history_lower']
    if history_lower:
        dept_keywords = DEPARTMENT_RULES.get(doctor.department, {})
        if any(kw in history_lower for kw in dept_keywords):
            score += 15.0
            reasons.append(f"medical history relates to {doctor.department}")

    age_pts, age_reason = age_fit(doctor.department, ctx['age'])
    score += age_pts
    if age_reason:
        reasons.append(age_reason)

    pain = ctx['pain_level'] or 0
    if dept_raw > 0:
        pain_pts = 10.0 * pain / 10.0
        score += pain_pts
        if pain >= 8:
            reasons.append(f"high pain level ({pain}/10) prioritised")

    if is_doctor_available(doctor):
        score += 5.0
        reasons.append("available today")

    active_load = doctor.assignments.filter(status='Active').count()
    score += 5.0 / (1 + active_load)
    if active_load == 0:
        reasons.append("no current caseload")

    return round(score, 2), reasons


def build_recommendation(symptoms, pain_level, age, medical_history):
    dept_scores = score_departments(symptoms, medical_history)
    primary_dept = match_department(symptoms, medical_history)
    confidence = department_confidence(dept_scores, primary_dept)
    severity = clinical_severity_index(symptoms)

    ctx = {
        'dept_scores': dept_scores,
        'top_dept_score': max(dept_scores.values()) if dept_scores else 0,
        'age': age,
        'pain_level': pain_level,
        'history_lower': (medical_history or '').lower(),
    }

    candidate_depts = list(dept_scores.keys())
    for d in get_equivalenced_depts(symptoms, primary_dept):
        if d not in candidate_depts:
            candidate_depts.append(d)
    candidates = list(Doctor.objects.filter(department__in=candidate_depts, status='Active'))

    if not candidates:
        candidates = list(Doctor.objects.filter(department='General Medicine', status='Active'))
    if not candidates:
        candidates = list(Doctor.objects.filter(status='Active'))

    scored = [(d, *score_doctor(d, ctx)) for d in candidates]
    scored.sort(key=lambda t: (t[1], -t[0].assignments.filter(status='Active').count()), reverse=True)

    escalate = (pain_level or 0) >= 8 or severity >= 70
    limit = 2 if escalate else 3
    ranked = scored[:limit]

    primary = ranked[0][0] if ranked else None
    primary_score = ranked[0][1] if ranked else None
    primary_reasons = ranked[0][2] if ranked else []

    if not dept_scores:
        reason_text = (
            "No specific symptoms were matched, so General Medicine is recommended "
            "as a safe first point of contact."
        )
    elif primary:
        who = primary.user.get_full_name() or primary.user.username
        reason_text = (
            f"Recommended {primary_dept} (confidence {confidence}%). "
            f"Dr. {who}: " + ", ".join(primary_reasons) + "."
        )
        other_depts = [d for d in dept_scores if d != primary_dept]
        if other_depts:
            reason_text += (
                f" Your description also mentions other areas "
                f"({', '.join(other_depts)}); alternative doctors are listed below."
            )
    else:
        reason_text = (
            f"Symptoms indicate {primary_dept} (confidence {confidence}%), but no "
            f"active doctor is currently available in this department."
        )

    if severity >= 70:
        reason_text += f" These symptoms rate high on clinical severity ({severity}/100)."

    return {
        'department': primary_dept,
        'confidence': confidence,
        'primary': primary,
        'score': primary_score,
        'reason': reason_text,
        'clinical_severity': severity,
        'ranked': ranked,
    }


def is_doctor_available(doctor: Doctor) -> bool:
    schedule = doctor.availability_schedule or {}
    if not schedule:
        return True
    today_name = date_type.today().strftime('%A')
    slot = schedule.get(today_name, '').strip().lower()
    return bool(slot) and slot != 'closed'


def get_equivalenced_depts(symptoms: str, primary_dept: str) -> list:
    depts = [primary_dept]
    symptoms_lower = symptoms.lower()
    for sym, equiv_depts in DEPARTMENT_EQUIVALENCES.items():
        if sym in symptoms_lower:
            for d in equiv_depts:
                if d not in depts:
                    depts.append(d)
    return depts


def rank_doctors(qs) -> list:
    return sorted(
        qs,
        key=lambda d: (d.assignments.filter(status='Active').count(), d.user.first_name.lower()),
    )


class RecommendationHistoryViewSet(viewsets.ModelViewSet):
    serializer_class = RecommendationHistorySerializer

    def get_permissions(self):
        if self.action == 'create':
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return RecommendationHistory.objects.none()

        if user.role == 'ADMIN':
            return RecommendationHistory.objects.all().order_by('-recommendation_date')
        elif user.role == 'DOCTOR':
            return RecommendationHistory.objects.filter(
                patient__assignments__doctor__user=user,
                patient__assignments__status='Active',
            ).distinct().order_by('-recommendation_date')
        elif user.role == 'PATIENT':
            return RecommendationHistory.objects.filter(
                patient__user=user
            ).order_by('-recommendation_date')
        return RecommendationHistory.objects.none()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data.copy()

        symptoms = validated_data.get('symptoms', '')
        pain_level = validated_data.get('pain_level', 5)
        age = validated_data.get('age', None)
        medical_history = validated_data.get('medical_history', '')

        if not score_departments(symptoms, medical_history):
            return Response(
                {'detail': "We couldn't recognise any symptoms in your description. "
                           "Please describe your symptoms using clear terms "
                           "(for example: fever, chest pain, cough, headache, rash)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = build_recommendation(symptoms, pain_level, age, medical_history)

        patient_obj = None
        if request.user and request.user.is_authenticated:
            if request.user.role == 'PATIENT' and hasattr(request.user, 'patient_profile'):
                patient_obj = request.user.patient_profile
            elif request.user.role == 'ADMIN':
                patient_id = request.data.get('patient_id')
                if patient_id:
                    try:
                        patient_obj = Patient.objects.get(id=patient_id)
                    except (Patient.DoesNotExist, ValueError):
                        pass

        rec = RecommendationHistory.objects.create(
            patient=patient_obj,
            symptoms=symptoms,
            pain_level=pain_level,
            age=age,
            medical_history=medical_history,
            recommended_doctor=result['primary'],
            recommended_department=result['department'],
            score=result['score'],
            confidence=result['confidence'],
            reason=result['reason'],
        )

        if request.user and request.user.is_authenticated:
            log_activity(
                request.user, 'RECOMMENDATION',
                f"Recommendation for department {result['department']} "
                f"(confidence {result['confidence']}%).",
                request,
            )

        data = self.get_serializer(rec).data
        data['clinical_severity'] = result['clinical_severity']
        data['ranked_doctors'] = [
            {
                **DoctorSerializer(doc, context={'request': request}).data,
                'score': doc_score,
                'reasons': reasons,
            }
            for doc, doc_score, reasons in result['ranked']
        ]
        return Response(data, status=status.HTTP_201_CREATED)
