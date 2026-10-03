from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied

from django.utils import timezone
from django.contrib.auth import get_user_model

from apps.doctors.models import Doctor, DoctorAssignment, Prescription, AccessRequest
from apps.doctors.access import doctor_access_filters, doctor_can_access
from apps.doctors.serializers import (
    DoctorSerializer, DoctorAssignmentSerializer, PrescriptionSerializer, AccessRequestSerializer,
    PublicDoctorSerializer,
)
from apps.patients.models import Patient
from apps.notifications.models import Notification
from apps.users.permissions import IsAdmin, IsDoctor, IsPatient, IsAdminOrSelfDoctor, IsDoctorOrAdmin
from apps.users.credentials import generate_password
from apps.users.email_service import account_created_response
import logging

logger = logging.getLogger(__name__)

from apps.audit.utils import log_activity

User = get_user_model()



class DoctorViewSet(viewsets.ModelViewSet):
    serializer_class = DoctorSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'department', 'gender']
    search_fields = [
        'user__first_name', 'user__last_name',
        'doctor_id', 'uuid_token', 'license_number', 'specialization', 'phone',
    ]
    ordering_fields = ['doctor_id', 'registration_date', 'uuid_token']
    ordering = ['-registration_date', 'doctor_id']

    def get_permissions(self):
        if self.action in ['create', 'destroy']:
            return [IsAdmin()]
        elif self.action in ['update', 'partial_update']:
            return [IsAdminOrSelfDoctor()]
        elif self.action in ['list', 'retrieve']:
            return [permissions.IsAuthenticated()]
        # Extra actions (e.g. reset_password, admin only) declare their own
        # permission_classes in @action; don't override them here.
        return super().get_permissions()

    # Verified registration data: only an administrator may change these.
    ADMIN_ONLY_FIELDS = ('license_number', 'department', 'status')

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return Doctor.objects.none()
        return Doctor.objects.select_related('user').all()

    def get_serializer_class(self):
        # Patients and other doctors see a public profile without contact
        # details, date of birth, licence number or login details.
        if self.action in ('list', 'retrieve') and getattr(self.request.user, 'role', None) != 'ADMIN':
            return PublicDoctorSerializer
        return DoctorSerializer

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.user_id == request.user.id:
            return Response(DoctorSerializer(instance, context=self.get_serializer_context()).data)
        return Response(self.get_serializer(instance).data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        doctor = serializer.save()

        log_activity(
            request.user,
            'CREATE_DOCTOR',
            f"Created Doctor profile: {doctor.doctor_id} for user {doctor.user.username}.",
            request,
        )

        return Response(
            account_created_response(
                label='Doctor',
                email=doctor.email or doctor.user.email or '',
                full_name=f"Dr. {doctor.user.first_name} {doctor.user.last_name}".strip(),
                username=doctor._generated_username,
                password=doctor._generated_password,
                password_was_generated=doctor._generated_password != '[PROVIDED]',
            ),
            status=status.HTTP_201_CREATED,
        )

    def perform_update(self, serializer):
        if self.request.user.role != 'ADMIN':
            blocked = [f for f in self.ADMIN_ONLY_FIELDS if f in self.request.data]
            if blocked:
                raise PermissionDenied(
                    f"Only an administrator can change: {', '.join(blocked)}."
                )
        doctor = serializer.save()
        log_activity(
            self.request.user,
            'UPDATE_DOCTOR',
            f"Updated Doctor profile: {doctor.doctor_id}.",
            self.request,
        )

    def perform_destroy(self, instance):
        user = instance.user
        log_activity(
            self.request.user,
            'DELETE_DOCTOR',
            f"Deleted Doctor profile: {instance.doctor_id} and user: {user.username}.",
            self.request,
        )
        with transaction.atomic():
            user.delete()

    @action(detail=True, methods=['post'], url_path='reset_password', permission_classes=[IsAdmin])
    def reset_password(self, request, pk=None):
        doctor = self.get_object()
        user = doctor.user
        new_password = request.data.get('new_password', '').strip() or None

        if new_password:
            if len(new_password) < 8:
                return Response(
                    {'error': 'Password must be at least 8 characters long.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            new_password = generate_password(10)

        user.set_password(new_password)
        user.is_active = True
        user.must_change_password = True
        user.save(update_fields=['password', 'is_active', 'must_change_password'])

        log_activity(
            request.user,
            'RESET_DOCTOR_PASSWORD',
            f"Admin reset password for doctor {doctor.doctor_id} (user: {user.username}).",
            request,
        )

        return Response({
            'doctor_id': doctor.doctor_id,
            'username': user.username,
            'new_password': new_password,
            'message': f"Password for {user.username} has been reset successfully.",
        }, status=status.HTTP_200_OK)


class DoctorAssignmentViewSet(viewsets.ModelViewSet):
    serializer_class = DoctorAssignmentSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['status', 'doctor', 'patient']

    def get_permissions(self):
        if self.action in ['create', 'destroy', 'update', 'partial_update']:
            return [IsAdmin()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return DoctorAssignment.objects.none()

        qs = DoctorAssignment.objects.select_related('doctor__user', 'patient')
        if user.role == 'ADMIN':
            return qs.all()
        elif user.role == 'DOCTOR':
            return qs.filter(doctor__user=user)
        elif user.role == 'PATIENT':
            return qs.filter(patient__user=user)
        return DoctorAssignment.objects.none()

    def perform_create(self, serializer):
        with transaction.atomic():
            assignment = serializer.save()
            # An admin assigning a doctor is an approval of access, so record it
            # the same way an approved access request is recorded.
            if not AccessRequest.objects.filter(
                doctor=assignment.doctor, patient=assignment.patient, status='APPROVED'
            ).exists():
                AccessRequest.objects.create(
                    doctor=assignment.doctor, patient=assignment.patient,
                    status='APPROVED', reason='Assigned by administrator',
                    resolved_at=timezone.now(), resolved_by=self.request.user,
                )
        log_activity(
            self.request.user,
            'CREATE_ASSIGNMENT',
            f"Assigned Patient {assignment.patient.patient_id} to Dr. {assignment.doctor.user.last_name}.",
            self.request,
        )

    def perform_update(self, serializer):
        assignment = serializer.save()
        log_activity(
            self.request.user,
            'UPDATE_ASSIGNMENT',
            f"Updated assignment for Dr. {assignment.doctor.user.last_name} and Patient {assignment.patient.patient_id}.",
            self.request,
        )

    def perform_destroy(self, instance):
        log_activity(
            self.request.user,
            'DELETE_ASSIGNMENT',
            f"Deleted assignment between Dr. {instance.doctor.user.last_name} and Patient {instance.patient.patient_id}.",
            self.request,
        )
        instance.delete()


class PrescriptionViewSet(viewsets.ModelViewSet):
    serializer_class = PrescriptionSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['patient', 'doctor']
    search_fields = [
        'patient__first_name', 'patient__last_name', 'patient__patient_id',
        'doctor__first_name', 'doctor__last_name', 'doctor__username',
        'diagnosis', 'medications',
    ]
    ordering_fields = ['prescription_date']
    ordering = ['-prescription_date']

    def get_permissions(self):
        if self.action == 'create':
            return [IsDoctor()]
        if self.action in ['update', 'partial_update', 'destroy']:
            return [IsDoctorOrAdmin()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return Prescription.objects.none()

        qs = Prescription.objects.select_related('patient', 'doctor')
        if user.role == 'ADMIN':
            return qs.all()
        elif user.role == 'DOCTOR':
            return qs.filter(doctor=user).filter(*doctor_access_filters(user, 'patient'))
        elif user.role == 'PATIENT':
            return qs.filter(patient__user=user)
        return Prescription.objects.none()

    def perform_create(self, serializer):
        user = self.request.user
        patient = serializer.validated_data.get('patient')

        if patient is None or not doctor_can_access(user, patient):
            raise PermissionDenied(
                'You can only write prescriptions for patients whose records you have approved access to.'
            )

        prescription = serializer.save(doctor=user)
        log_activity(
            user,
            'CREATE_PRESCRIPTION',
            f"Created prescription for patient {prescription.patient.patient_id}.",
            self.request,
        )

    def perform_update(self, serializer):
        new_patient = serializer.validated_data.get('patient')
        if new_patient is not None and new_patient != serializer.instance.patient:
            raise PermissionDenied('A prescription cannot be moved to another patient.')
        prescription = serializer.save()
        log_activity(
            self.request.user,
            'UPDATE_PRESCRIPTION',
            f"Updated prescription for patient {prescription.patient.patient_id}.",
            self.request,
        )


class AccessRequestViewSet(viewsets.ModelViewSet):
    serializer_class = AccessRequestSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['status', 'doctor', 'patient']
    http_method_names = ['get', 'post', 'head', 'options']

    def get_permissions(self):
        if self.action == 'create':
            return [IsDoctor()]
        if self.action in ['approve', 'decline']:
            return [IsAdmin()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return AccessRequest.objects.none()
        qs = AccessRequest.objects.select_related('doctor__user', 'patient')
        if user.role == 'ADMIN':
            return qs
        if user.role == 'DOCTOR':
            return qs.filter(doctor__user=user)
        return AccessRequest.objects.none()

    def create(self, request, *args, **kwargs):
        doctor = getattr(request.user, 'doctor_profile', None)
        if not doctor:
            return Response({'detail': 'Only doctors can request access.'}, status=status.HTTP_403_FORBIDDEN)

        patient_id = request.data.get('patient')
        try:
            patient = Patient.objects.get(id=patient_id)
        except (Patient.DoesNotExist, ValueError, TypeError):
            return Response({'detail': 'Patient not found.'}, status=status.HTTP_404_NOT_FOUND)

        if DoctorAssignment.objects.filter(doctor=doctor, patient=patient, status='Active').exists():
            return Response({'detail': 'You already have access to this patient.'}, status=status.HTTP_400_BAD_REQUEST)

        if AccessRequest.objects.filter(doctor=doctor, patient=patient, status='PENDING').exists():
            return Response({'detail': 'You already have a pending access request for this patient.'}, status=status.HTTP_400_BAD_REQUEST)

        access = AccessRequest.objects.create(
            doctor=doctor, patient=patient,
            reason=request.data.get('reason', '') or '',
        )

        for admin in User.objects.filter(role='ADMIN', is_active=True):
            Notification.objects.create(
                receiver=admin, role='ADMIN',
                title='Patient Access Request',
                message=f"Dr. {doctor.user.get_full_name() or doctor.user.username} requested access to patient {patient.patient_id}.",
            )
        log_activity(request.user, 'ACCESS_REQUEST',
                     f"Requested access to patient {patient.patient_id}.", request)

        serializer = self.get_serializer(access)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        access = self.get_object()
        if access.status != 'PENDING':
            return Response({'detail': 'This request has already been resolved.'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            access.status = 'APPROVED'
            access.resolved_at = timezone.now()
            access.resolved_by = request.user
            access.save(update_fields=['status', 'resolved_at', 'resolved_by'])

            assignment = DoctorAssignment.objects.filter(doctor=access.doctor, patient=access.patient).first()
            if assignment:
                assignment.status = 'Active'
                assignment.save(update_fields=['status'])
            else:
                DoctorAssignment.objects.create(doctor=access.doctor, patient=access.patient, status='Active')

        Notification.objects.create(
            receiver=access.doctor.user, role='DOCTOR',
            title='Access Request Approved',
            message=f"Your access request for patient {access.patient.patient_id} was approved.",
        )
        Notification.objects.create(
            receiver=access.patient.user, role='PATIENT',
            title='Doctor Given Access',
            message=f"Dr. {access.doctor.user.get_full_name() or access.doctor.user.username} "
                    f"({access.doctor.department}) can now view your medical record.",
        )
        log_activity(request.user, 'APPROVE_ACCESS',
                     f"Approved access for Dr. {access.doctor.doctor_id} to patient {access.patient.patient_id}.", request)
        return Response(self.get_serializer(access).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def decline(self, request, pk=None):
        access = self.get_object()
        if access.status != 'PENDING':
            return Response({'detail': 'This request has already been resolved.'}, status=status.HTTP_400_BAD_REQUEST)

        access.status = 'DECLINED'
        access.resolved_at = timezone.now()
        access.resolved_by = request.user
        access.save(update_fields=['status', 'resolved_at', 'resolved_by'])

        Notification.objects.create(
            receiver=access.doctor.user, role='DOCTOR',
            title='Access Request Declined',
            message=f"Your access request for patient {access.patient.patient_id} was declined.",
        )
        log_activity(request.user, 'DECLINE_ACCESS',
                     f"Declined access for Dr. {access.doctor.doctor_id} to patient {access.patient.patient_id}.", request)
        return Response(self.get_serializer(access).data, status=status.HTTP_200_OK)
