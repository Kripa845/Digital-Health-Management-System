import io
import secrets
import string

from django.http import HttpResponse
from django.contrib.auth import get_user_model
from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.response import Response

from apps.audit.utils import log_activity
from apps.patients.models import Patient
from apps.patients.serializers import PatientSerializer
from apps.documents.models import Document
from apps.documents.serializers import DocumentSerializer
from apps.users.permissions import IsAdmin
from apps.users.email_service import send_welcome_email
import logging

logger = logging.getLogger(__name__)

User = get_user_model()



def _generate_password(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        pwd = ''.join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.isupper() for c in pwd)
            and any(c.islower() for c in pwd)
            and any(c.isdigit() for c in pwd)
        ):
            return pwd


class PatientViewSet(viewsets.ModelViewSet):
    serializer_class = PatientSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'blood_group', 'registration_date']
    search_fields = [
        'first_name', 'last_name', 'patient_id',
        'phone', 'allergies', 'current_medication',
    ]
    ordering_fields = ['patient_id', 'registration_date', 'last_updated']
    ordering = ['patient_id']

    def get_permissions(self):
        if self.action in ['create', 'destroy', 'update', 'partial_update', 'reset_password']:
            return [IsAdmin()]
        elif self.action in ['list', 'retrieve', 'qr_code', 'toggle_status', 'stats']:
            return [permissions.IsAuthenticated()]
        elif self.action == 'public_profile':
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return Patient.objects.none()
        qs = Patient.objects.select_related('user', 'created_by')
        if user.role == 'ADMIN':
            return qs.all()
        elif user.role == 'DOCTOR':
            return qs.filter(
                assignments__doctor__user=user,
                assignments__status='Active',
            ).distinct()
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

        email = patient.email or patient.user.email or ''
        full_name = " ".join(filter(None, [patient.first_name, patient.middle_name, patient.last_name]))
        email_sent = False

        if email:
            try:
                send_welcome_email(
                    email_address=email,
                    full_name=full_name,
                    username=patient._generated_username,
                    password=patient._generated_password
                )
                email_sent = True
            except Exception as e:
                logger.exception("Failed to send welcome email to patient %s", email)

        if email_sent:
            message = "Patient registered successfully. Login credentials have been sent to the registered email."
        else:
            message = "Account created successfully, but the email could not be sent."

        return Response({
            "success": True,
            "message": message
        }, status=status.HTTP_201_CREATED)


    def perform_update(self, serializer):
        patient = serializer.save()
        log_activity(
            self.request.user,
            'UPDATE_PATIENT',
            f"Updated patient profile: {patient.patient_id}.",
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
        except (Patient.DoesNotExist, ValueError):
            return Response(
                {'error': 'Invalid QR code or profile not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        photo_url = (
            request.build_absolute_uri(patient.photo.url)
            if patient.photo else None
        )
        return Response({
            'uuid': str(patient.uuid_token),
            'patient_id': patient.patient_id,
            'first_name': patient.first_name,
            'middle_name': patient.middle_name,
            'last_name': patient.last_name,
            'photo': photo_url,
            'dob': str(patient.dob),
            'age': patient.age,
            'gender': patient.gender,
            'blood_group': patient.blood_group,
            'phone': patient.phone,
            'emergency_contact': patient.emergency_contact,
            'email': patient.email,
            'address': patient.address,
            'height': str(patient.height),
            'weight': str(patient.weight),
            'allergies': patient.allergies,
            'status': patient.status,
        }, status=status.HTTP_200_OK)

    # QR code PNG image
    @action(detail=True, methods=['get'], url_path='qr')
    def qr_code(self, request, pk=None):
        try:
            import qrcode
        except ImportError:
            return Response(
                {'error': 'qrcode library not installed. Run: pip install qrcode[pil]'},
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )

        patient = self.get_object()
        from django.conf import settings
        frontend_base = settings.FRONTEND_URL or request.build_absolute_uri('/').rstrip('/')
        qr_url = f'{frontend_base}/public-profile/{patient.uuid_token}'

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color='black', back_color='white')

        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)

        log_activity(
            request.user, 'GENERATE_QR',
            f"Generated QR code for patient {patient.patient_id}.",
            request,
        )
        return HttpResponse(buffer, content_type='image/png')

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

        assigned = False
        request_status = None
        if doctor:
            assigned = DoctorAssignment.objects.filter(doctor=doctor, patient=patient, status='Active').exists()
            if not assigned:
                ar = AccessRequest.objects.filter(doctor=doctor, patient=patient).order_by('-created_at').first()
                request_status = ar.status if ar else None

        log_activity(user, 'SCAN_QR', f"Scanned patient {patient.patient_id}.", request)

        if is_admin or assigned:
            data = PatientSerializer(patient, context={'request': request}).data
            return Response({'assigned': True, 'access': 'FULL', 'request_status': request_status, 'patient': data})

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
        return Response({'assigned': False, 'access': 'GENERAL', 'request_status': request_status, 'patient': general})

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
            new_password = _generate_password(10)

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
