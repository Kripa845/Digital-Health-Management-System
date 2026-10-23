import uuid as uuid_lib
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from apps.audit.utils import log_activity
from apps.patients.models import Patient, QrAccessRequest
from apps.patients.serializers import (
    PatientSelfUpdateSerializer, PatientSerializer, PublicPatientSerializer,
    QrAccessRequestCreateSerializer, QrAccessRequestSerializer, qr_extended_record,
)
from apps.notifications.models import Notification
from apps.documents.models import Document
from apps.documents.serializers import DocumentSerializer
from apps.doctors.access import doctor_access_filters, doctor_can_access
from apps.users.credentials import account_created_response, generate_password
from apps.users.permissions import IsAdmin, IsPatient
import logging

logger = logging.getLogger(__name__)

User = get_user_model()


# Per visitor IP (these endpoints are public). AnonRateThrottle honours `scope` on the
# class; ScopedRateThrottle would read it from the view instead and never limit.
class QrAccessRequestThrottle(AnonRateThrottle):
    scope = 'qr_access_request'


class QrAccessStatusThrottle(AnonRateThrottle):
    scope = 'qr_access_status'


def client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    return forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR')


def qr_access_state(access: QrAccessRequest) -> dict:
    """What the requester's page is told: EXPIRED once an approval has run out."""
    state = access.status
    if state == QrAccessRequest.Status.APPROVED and not access.is_active:
        state = 'EXPIRED'
    return {
        'token': str(access.token),
        'status': state,
        'created_at': access.created_at,
        'expires_at': access.expires_at,
    }


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

    # Opening a record is logged so admins can see who viewed which patient.
    def retrieve(self, request, *args, **kwargs):
        patient = self.get_object()
        log_activity(request.user, 'VIEW_PATIENT', f"Viewed patient record {patient.patient_id}.", request,
                     patient=patient)
        return Response(self.get_serializer(patient).data)

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

        data = account_created_response(
            label='Patient',
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

    # Someone who scanned the card asks an admin for more than the public profile.
    # No account: the token returned here, kept by their browser, is their only key.
    @action(
        detail=False,
        methods=['post'],
        url_path=r'public/(?P<uuid>[^/.]+)/access-requests',
        permission_classes=[permissions.AllowAny],
        authentication_classes=[],
        throttle_classes=[QrAccessRequestThrottle],
    )
    def request_qr_access(self, request, uuid=None):
        try:
            patient = Patient.objects.get(uuid_token=uuid)
        except (Patient.DoesNotExist, ValueError, DjangoValidationError):
            return Response({'detail': 'Invalid QR code or profile not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = QrAccessRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = serializer.validated_data['requester_phone']
        if QrAccessRequest.objects.filter(patient=patient, requester_phone=phone,
                                          status=QrAccessRequest.Status.PENDING).exists():
            return Response({'detail': 'A request from this phone number is already waiting for an admin.'},
                            status=status.HTTP_409_CONFLICT)

        access = serializer.save(patient=patient, requester_ip=client_ip(request))
        for admin in User.objects.filter(role='ADMIN', is_active=True):
            Notification.objects.create(
                receiver=admin, role='ADMIN',
                title='QR Card Access Request',
                message=f"{access.requester_name} ({access.requester_phone}) scanned the card of patient "
                        f"{patient.patient_id} and asks for more information: {access.reason}",
            )
        log_activity(None, 'QR_ACCESS_REQUEST',
                     f"{access.requester_name} ({access.requester_phone}) requested more information "
                     f"from the QR card of patient {patient.patient_id}.", request, patient=patient)
        return Response(qr_access_state(access), status=status.HTTP_201_CREATED)

    @action(
        detail=False,
        methods=['get'],
        url_path=r'public/(?P<uuid>[^/.]+)/access-requests/(?P<token>[^/.]+)',
        permission_classes=[permissions.AllowAny],
        authentication_classes=[],
        throttle_classes=[QrAccessStatusThrottle],
    )
    def qr_access_status(self, request, uuid=None, token=None):
        """The waiting page asks here until the admin decides; an approved, unexpired
        request also returns the extra information."""
        try:
            access = QrAccessRequest.objects.select_related('patient').get(token=token, patient__uuid_token=uuid)
        except (QrAccessRequest.DoesNotExist, ValueError, DjangoValidationError):
            return Response({'detail': 'Request not found.'}, status=status.HTTP_404_NOT_FOUND)

        data = qr_access_state(access)
        if access.is_active:
            data['record'] = qr_extended_record(access.patient)
            log_activity(None, 'QR_ACCESS_VIEW',
                         f"{access.requester_name} ({access.requester_phone}) viewed the extended QR record of "
                         f"patient {access.patient.patient_id}.", request, patient=access.patient)
        return Response(data)

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
            log_activity(user, 'SCAN_QR', f"Scanned patient {patient.patient_id}.", request, patient=patient)
            return Response({'access': 'FULL', 'patient': data})

        # Doctor workflow: full record only with an active assignment AND an approved request.
        if doctor_can_access(user, patient):
            log_activity(user, 'SCAN_QR', f"Scanned patient {patient.patient_id}.", request, patient=patient)
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
            log_activity(user, 'ACCESS_REQUEST', f"Requested access to patient {patient.patient_id} via QR scan.", request, patient=patient)

        log_activity(user, 'SCAN_QR', f"Scanned patient {patient.patient_id}.", request, patient=patient)

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
        now = timezone.now()
        with transaction.atomic():
            patient.uuid_token = uuid_lib.uuid4()
            patient.save(update_fields=['uuid_token'])
            # Whoever has the lost card keeps nothing it was given: end approvals, refuse waiting requests.
            requests = QrAccessRequest.objects.filter(patient=patient)
            requests.filter(status=QrAccessRequest.Status.APPROVED, expires_at__gt=now).update(expires_at=now)
            requests.filter(status=QrAccessRequest.Status.PENDING).update(
                status=QrAccessRequest.Status.DECLINED, resolved_at=now, resolved_by=request.user,
            )
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


class QrAccessRequestViewSet(viewsets.ReadOnlyModelViewSet):
    """Requests for more information from a scanned QR card, decided by an admin."""
    serializer_class = QrAccessRequestSerializer
    permission_classes = [IsAdmin]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['status', 'patient']
    queryset = QrAccessRequest.objects.select_related('patient')

    def _resolve(self, request, access, new_status):
        access.status = new_status
        access.resolved_at = timezone.now()
        access.resolved_by = request.user
        if new_status == QrAccessRequest.Status.APPROVED:
            access.expires_at = access.resolved_at + timedelta(hours=settings.QR_ACCESS_HOURS)
        access.save(update_fields=['status', 'resolved_at', 'resolved_by', 'expires_at'])

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        access = self.get_object()
        if access.status != QrAccessRequest.Status.PENDING:
            return Response({'detail': 'This request has already been resolved.'}, status=status.HTTP_400_BAD_REQUEST)
        self._resolve(request, access, QrAccessRequest.Status.APPROVED)
        if access.patient.user_id:
            Notification.objects.create(
                receiver=access.patient.user, role='PATIENT',
                title='Your Card Information Was Shared',
                message=f"{access.requester_name} ({access.requester_phone}) scanned your health card and was "
                        f"allowed to see your medical information for {settings.QR_ACCESS_HOURS} hours. "
                        f"Reason given: {access.reason}",
            )
        log_activity(request.user, 'APPROVE_QR_ACCESS',
                     f"Approved QR card access for {access.requester_name} ({access.requester_phone}) "
                     f"to patient {access.patient.patient_id} for {settings.QR_ACCESS_HOURS} hours.",
                     request, patient=access.patient)
        return Response(self.get_serializer(access).data)

    @action(detail=True, methods=['post'])
    def decline(self, request, pk=None):
        access = self.get_object()
        if access.status != QrAccessRequest.Status.PENDING:
            return Response({'detail': 'This request has already been resolved.'}, status=status.HTTP_400_BAD_REQUEST)
        self._resolve(request, access, QrAccessRequest.Status.DECLINED)
        log_activity(request.user, 'DECLINE_QR_ACCESS',
                     f"Declined QR card access for {access.requester_name} ({access.requester_phone}) "
                     f"to patient {access.patient.patient_id}.", request, patient=access.patient)
        return Response(self.get_serializer(access).data)

    @action(detail=True, methods=['post'])
    def revoke(self, request, pk=None):
        """End an approved access before it expires."""
        access = self.get_object()
        if not access.is_active:
            return Response({'detail': 'This request does not currently give access.'}, status=status.HTTP_400_BAD_REQUEST)
        access.expires_at = timezone.now()
        access.save(update_fields=['expires_at'])
        log_activity(request.user, 'REVOKE_QR_ACCESS',
                     f"Ended QR card access for {access.requester_name} ({access.requester_phone}) "
                     f"to patient {access.patient.patient_id}.", request, patient=access.patient)
        return Response(self.get_serializer(access).data)
