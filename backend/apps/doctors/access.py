"""The single rule for whether a doctor may see a patient's medical record.

A doctor has access when they hold an active DoctorAssignment for the patient
AND an approved AccessRequest. Every endpoint that returns clinical data uses
these helpers, so the rule cannot drift between modules.
"""
from django.db.models import Exists, OuterRef

from apps.doctors.models import AccessRequest, DoctorAssignment


def doctor_access_filters(user, patient_ref: str = 'pk'):
    """Queryset filters limiting rows to patients the doctor may access.

    ``patient_ref`` is the path from the queryset's model to the patient's
    primary key: ``'pk'`` for Patient itself, ``'patient'`` for models with a
    ``patient`` foreign key. Use as ``qs.filter(*doctor_access_filters(user, 'patient'))``.
    """
    return (
        Exists(DoctorAssignment.objects.filter(
            doctor__user=user, status='Active', patient=OuterRef(patient_ref),
        )),
        Exists(AccessRequest.objects.filter(
            doctor__user=user, status='APPROVED', patient=OuterRef(patient_ref),
        )),
    )


def doctor_can_access(user, patient) -> bool:
    return (
        DoctorAssignment.objects.filter(doctor__user=user, patient=patient, status='Active').exists()
        and AccessRequest.objects.filter(doctor__user=user, patient=patient, status='APPROVED').exists()
    )
