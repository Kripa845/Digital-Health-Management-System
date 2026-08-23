from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from django.db import transaction
import string
import secrets
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.decorators import action

from django.utils import timezone
from django.contrib.auth import get_user_model

from apps.doctors.models import Doctor, DoctorAssignment, Prescription, AccessRequest
from apps.doctors.serializers import (
    DoctorSerializer, DoctorAssignmentSerializer, PrescriptionSerializer, AccessRequestSerializer,
)
from apps.patients.models import Patient
from apps.notifications.models import Notification
from apps.users.permissions import IsAdmin, IsDoctor, IsPatient, IsAdminOrSelfDoctor, IsDoctorOrAdmin
from apps.users.email_service import send_welcome_email
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
    ordering = ['doctor_id']

    def get_permissions(self):
        if self.action in ['create', 'destroy']:
            return [IsAdmin()]
        elif self.action in ['update', 'partial_update']:
            return [IsAdminOrSelfDoctor()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return Doctor.objects.none()
        return Doctor.objects.select_related('user').all()

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

        email = doctor.email or doctor.user.email or ''
        full_name = f"Dr. {doctor.user.first_name} {doctor.user.last_name}".strip()
        email_sent = False

        if email:
            try:
                send_welcome_email(
                    email_address=email,
                    full_name=full_name,
                    username=doctor._generated_username,
                    password=doctor._generated_password
                )
                email_sent = True
            except Exception as e:
                logger.exception("Failed to send welcome email to doctor %s", email)

        if email_sent:
            message = "Doctor registered successfully. Login credentials have been sent to the registered email."
        else:
            message = "Account created successfully, but the email could not be sent."

        return Response({
            "success": True,
            "message": message
        }, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        doctor = serializer.save()
        log_activity(
            self.request.user,
            'CREATE_DOCTOR',
            f"Created Doctor profile: {doctor.doctor_id} for user {doctor.user.username}.",
            self.request,
        )

    def perform_update(self, serializer):
        if self.request.user.role != 'ADMIN':
            serializer.validated_data.pop('status', None)
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
            alphabet = string.ascii_letters + string.digits
            while True:
                new_password = ''.join(secrets.choice(alphabet) for _ in range(10))
                if any(c.isupper() for c in new_password) and any(c.islower() for c in new_password) and any(c.isdigit() for c in new_password):
                    break

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
        assignment = serializer.save()
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
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
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
            return qs.filter(
                doctor=user,
                patient__access_requests__doctor__user=user,
                patient__access_requests__status='APPROVED',
            ).distinct()
        elif user.role == 'PATIENT':
            return qs.filter(patient__user=user)
        return Prescription.objects.none()

    def perform_create(self, serializer):
        from rest_framework.exceptions import PermissionDenied
        from apps.doctors.models import DoctorAssignment

        user = self.request.user
        patient = serializer.validated_data.get('patient')

        if user.role == 'DOCTOR' and patient is not None:
            assigned = DoctorAssignment.objects.filter(
                doctor__user=user, patient=patient, status='Active'
            ).exists()
            if not assigned:
                raise PermissionDenied(
                    'You can only create prescriptions for patients assigned to you.'
                )

        prescription = serializer.save(doctor=user)
        log_activity(
            user,
            'CREATE_PRESCRIPTION',
            f"Created prescription for patient {prescription.patient.patient_id}.",
            self.request,
        )

    def perform_update(self, serializer):
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
