import uuid as uuid_lib

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.response import Response

from apps.audit.utils import log_activity
from apps.patients.models import Patient
from apps.patients.serializers import PatientSelfUpdateSerializer, PatientSerializer, PublicPatientSerializer
from apps.notifications.models import Notification
from apps.documents.models import Document
from apps.documents.serializers import DocumentSerializer
from apps.doctors.access import doctor_access_filters, doctor_can_access
from apps.users.credentials import generate_password
from apps.users.permissions import IsAdmin, IsPatient
from apps.users.email_service import account_created_response
import logging

logger = logging.getLogger(__name__)

User = get_user_model()


class PatientViewSet(viewsets.ModelViewSet):
    serializer_class = PatientSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'blood_group', 'registration_date']
    search_fields = [
        'first_name', 'last_name', 'patient_id',
        'phone', 'allergies', 'current_medication',
    ]
    ordering_fields = ['patient_id', 'registration_date', 'last_updated']
    ordering = ['-registration_date', 'patient_id']

    def get_permissions(self):
        if self.action in ['create', 'destroy', 'update', 'partial_update']:
            return [IsAdmin()]
        if self.action in ['list', 'retrieve']:
            return [permissions.IsAuthenticated()]
        # Extra actions (me, scan, public_profile, toggle_status, reset_password,
        # regenerate_qr, stats, qr) declare their own permission_classes in
        # @action; returning a fixed list here would silently override them.
        return super().get_permissions()

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return Patient.objects.none()
        qs = Patient.objects.select_related('user', 'created_by')
        if user.role == 'ADMIN':
            return qs.all()
        elif user.role == 'DOCTOR':
            return qs.filter(*doctor_access_filters(user, 'pk'))
        elif user.role == 'PATIENT':
            return qs.filter(user=user)
        return Patient.objects.none()

    # Create

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        patient = serializer.save()

        log_activity(
            request.user,
            'CREATE_PATIENT',
            f"Created patient profile: {patient.patient_id} — login: {patient.user.username}.",
            request,
        )

        full_name = " ".join(filter(None, [patient.first_name, patient.middle_name, patient.last_name]))
        data = account_created_response(
            label='Patient',
            email=patient.email or patient.user.email or '',
            full_name=full_name,
            username=patient._generated_username,
            password=patient._generated_password,
            password_was_generated=patient._generated_password != '[PROVIDED]',
        )
        # The admin page opens the new patient's QR card straight away.
        data['patient'] = self.get_serializer(patient).data
        return Response(data, status=status.HTTP_201_CREATED)


    def perform_update(self, serializer):
        old_patient_id = serializer.instance.patient_id
        patient = serializer.save()
        log_activity(
            self.request.user,
            'UPDATE_PATIENT',
            f"Updated patient profile: {patient.patient_id}.",
            self.request,
        )
        if patient.patient_id != old_patient_id:
            # Printed cards and lab reports showing the old ID no longer match.
            log_activity(
                self.request.user,
                'CHANGE_PATIENT_ID',
                f"Changed patient ID from {old_patient_id} to {patient.patient_id}.",
                self.request,
            )

    def perform_destroy(self, instance):
        user = instance.user
        log_activity(
            self.request.user,
            'DELETE_PATIENT',
            f"Deleted patient profile: {instance.patient_id} and user: {user.username}.",
            self.request,
        )
        with transaction.atomic():
            user.delete()

    # The logged-in patient's own record: view it, or change contact details and photo.
    @action(detail=False, methods=['get', 'patch'], url_path='me', permission_classes=[IsPatient])
    def me(self, request):
        patient = getattr(request.user, 'patient_profile', None)
        if patient is None:
            return Response({'detail': 'No patient profile is linked to your account.'},
                            status=status.HTTP_404_NOT_FOUND)

        if request.method == 'PATCH':
            serializer = PatientSelfUpdateSerializer(patient, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            changed = sorted(
                name for name, value in serializer.validated_data.items()
                if name == 'photo' or (getattr(patient, name) or '') != (value or '')
            )
            old_name = ' '.join(filter(None, [patient.first_name, patient.middle_name, patient.last_name]))
            patient = serializer.save()
            if changed:
                # Field names only, never the new values.
                log_activity(request.user, 'UPDATE_OWN_PROFILE',
                             f"Patient {patient.patient_id} updated their {', '.join(changed)}.", request)
            if set(changed) & {'first_name', 'middle_name', 'last_name'}:
                # The name is used to check uploaded lab reports, so admins are told
                # about every self-made name change and can correct it if needed.
                new_name = ' '.join(filter(None, [patient.first_name, patient.middle_name, patient.last_name]))
                for admin in User.objects.filter(role='ADMIN', is_active=True):
                    Notification.objects.create(
                        receiver=admin, role='ADMIN', title='Patient Changed Their Name',
                        message=f'Patient {patient.patient_id} changed their name from "{old_name}" to "{new_name}".',
                    )

        return Response(PatientSerializer(patient, context={'request': request}).data)

    # Public QR scan endpoint
    @action(
        detail=False,
        methods=['get'],
        url_path=r'public/(?P<uuid>[^/.]+)',
        permission_classes=[permissions.AllowAny],
    )
    def public_profile(self, request, uuid=None):
        try:
            patient = Patient.objects.get(uuid_token=uuid)
        except (Patient.DoesNotExist, ValueError, DjangoValidationError):
            return Response(
                {'error': 'Invalid QR code or profile not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = PublicPatientSerializer(patient, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    # Doctor QR scan
    @action(
        detail=False,
        methods=['get'],
        url_path=r'scan/(?P<uuid>[^/.]+)',
        permission_classes=[permissions.IsAuthenticated],
    )
    def scan(self, request, uuid=None):
        from apps.doctors.models import DoctorAssignment, AccessRequest

        try:
            patient = Patient.objects.get(uuid_token=uuid)
        except (Patient.DoesNotExist, ValueError):
            return Response({'detail': 'Invalid QR code or patient not found.'}, status=status.HTTP_404_NOT_FOUND)

        user = request.user
        is_admin = user.role == 'ADMIN'
        doctor = getattr(user, 'doctor_profile', None)
        if not is_admin and not doctor:
            return Response({'detail': 'Only clinical staff can scan patient cards.'}, status=status.HTTP_403_FORBIDDEN)

        # Admin always gets full access
        if is_admin:
            data = PatientSerializer(patient, context={'request': request}).data
            log_activity(user, 'SCAN_QR', f"Scanned patient {patient.patient_id}.", request)
            return Response({'access': 'FULL', 'patient': data})

        # Doctor workflow: full record only with an active assignment AND an approved request.
        if doctor_can_access(user, patient):
            log_activity(user, 'SCAN_QR', f"Scanned patient {patient.patient_id}.", request)
            data = PatientSerializer(patient, context={'request': request}).data
            return Response({'access': 'FULL', 'patient': data})

        assigned = DoctorAssignment.objects.filter(doctor=doctor, patient=patient, status='Active').exists()
        request_obj = AccessRequest.objects.filter(doctor=doctor, patient=patient).order_by('-created_at').first()
        if assigned and not request_obj:
            request_obj = AccessRequest.objects.create(
                doctor=doctor, patient=patient, reason='QR scan initiated'
            )
            for admin in User.objects.filter(role='ADMIN', is_active=True):
                Notification.objects.create(
                    receiver=admin, role='ADMIN',
                    title='Patient Access Request',
                    message=f"Dr. {doctor.user.get_full_name() or doctor.user.username} requested access to patient {patient.patient_id} via QR scan.",
                )
            log_activity(user, 'ACCESS_REQUEST', f"Requested access to patient {patient.patient_id} via QR scan.", request)

        log_activity(user, 'SCAN_QR', f"Scanned patient {patient.patient_id}.", request)

        general = {
            'id': patient.id,
            'uuid': str(patient.uuid_token),
            'patient_id': patient.patient_id,
            'first_name': patient.first_name,
            'middle_name': patient.middle_name,
            'last_name': patient.last_name,
            'age': patient.age,
            'gender': patient.gender,
            'blood_group': patient.blood_group,
            'phone': patient.phone,
            'emergency_contact': patient.emergency_contact,
            'status': patient.status,
        }

        response_data = {'access': 'GENERAL', 'patient': general}

        if assigned:
            if request_obj and request_obj.status == 'PENDING':
                response_data['access'] = 'PENDING'
                response_data['message'] = 'Your access request is awaiting admin approval.'
            elif request_obj and request_obj.status == 'DECLINED':
                response_data['access'] = 'DECLINED'
                response_data['message'] = 'Your access request was declined. Only basic information is available.'
            else:
                response_data['message'] = 'You are not assigned to this patient. Full medical access requires authorization.'
        else:
            response_data['message'] = 'You are not assigned to this patient. Full medical access requires authorization.'

        return Response(response_data)

    # Issue a new QR token (lost or compromised card); the old QR stops working.
    @action(detail=True, methods=['post'], url_path='regenerate_qr', permission_classes=[IsAdmin])
    def regenerate_qr(self, request, pk=None):
        patient = self.get_object()
        patient.uuid_token = uuid_lib.uuid4()
        patient.save(update_fields=['uuid_token'])
        log_activity(
            request.user, 'REGENERATE_QR',
            f"Issued a new QR code for patient {patient.patient_id}; the previous card no longer works.",
            request,
        )
        return Response({'patient_id': patient.patient_id, 'uuid_token': str(patient.uuid_token)})

    # Toggle Active / Inactive
    @action(
        detail=True,
        methods=['patch'],
        url_path='toggle_status',
        permission_classes=[IsAdmin],
    )
    def toggle_status(self, request, pk=None):
        patient = self.get_object()
        patient.status = 'Inactive' if patient.status == 'Active' else 'Active'
        patient.save(update_fields=['status'])

        log_activity(
            request.user,
            'TOGGLE_PATIENT_STATUS',
            f"Changed patient {patient.patient_id} status to {patient.status}.",
            request,
        )
        return Response(
            {'patient_id': patient.patient_id, 'status': patient.status},
            status=status.HTTP_200_OK,
        )

    # Admin reset patient login password
    @action(
        detail=True,
        methods=['post'],
        url_path='reset_password',
        permission_classes=[IsAdmin],
    )
    def reset_password(self, request, pk=None):
        patient = self.get_object()
        user = patient.user

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
            'RESET_PATIENT_PASSWORD',
            f"Admin reset password for patient {patient.patient_id} (user: {user.username}).",
            request,
        )

        return Response(
            {
                'patient_id': patient.patient_id,
                'username': user.username,
                'new_password': new_password,
                'message': f"Password for {user.username} has been reset successfully.",
            },
            status=status.HTTP_200_OK,
        )

    # Quick stats for admin dashboard
    @action(
        detail=False,
        methods=['get'],
        url_path='stats',
        permission_classes=[IsAdmin],
    )
    def stats(self, request):
        return Response({
            'total_patients': Patient.objects.count(),
            'active_patients': Patient.objects.filter(status='Active').count(),
            'inactive_patients': Patient.objects.filter(status='Inactive').count(),
            'total_users': User.objects.count(),
        }, status=status.HTTP_200_OK)
