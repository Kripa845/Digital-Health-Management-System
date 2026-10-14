
from django.db.models import Exists, OuterRef

from apps.doctors.models import AccessRequest, DoctorAssignment


def doctor_access_filters(user, patient_ref: str = 'pk'):
   
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
