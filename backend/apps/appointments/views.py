from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.utils import timezone
from django.db.models import Count

from apps.appointments.models import Appointment
from apps.appointments.serializers import AppointmentSerializer
from apps.notifications.models import Notification
from apps.audit.utils import log_activity

User = get_user_model()


def _doctor_name(appointment):
    user = appointment.doctor.user
    return user.get_full_name() or user.username


def _patient_name(appointment):
    return f"{appointment.patient.first_name} {appointment.patient.last_name}".strip()


class AppointmentPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return True

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.role == 'ADMIN':
            return True
        if user.role == 'PATIENT':
            return obj.patient.user_id == user.id
        if user.role == 'DOCTOR':
            return obj.doctor.user_id == user.id
        return False


class AppointmentViewSet(viewsets.ModelViewSet):
    serializer_class = AppointmentSerializer
    permission_classes = [AppointmentPermission]
    pagination_class = None
    # Appointments change only through the workflow actions below
    # (accept, decline, cancel, complete). Direct PUT/PATCH/DELETE would let a
    # patient move an accepted appointment or skip admin approval.
    http_method_names = ['get', 'post', 'head', 'options']
    filterset_fields = ['status', 'doctor', 'appointment_date', 'doctor__department']
    search_fields = [
        'patient__first_name', 'patient__last_name', 'patient__patient_id',
        'doctor__user__first_name', 'doctor__user__last_name', 'doctor__doctor_id',
        'doctor__department',
    ]
    ordering_fields = ['appointment_date', 'appointment_time', 'created_at', 'status']

    def get_queryset(self):
        user = self.request.user
        qs = Appointment.objects.select_related(
            'patient', 'doctor', 'doctor__user', 'approved_by'
        )

        if user.role == 'ADMIN':
            return qs.all()
        elif user.role == 'PATIENT':
            return qs.filter(patient__user=user)
        elif user.role == 'DOCTOR':
            return qs.filter(doctor__user=user)
        return Appointment.objects.none()

    def create(self, request, *args, **kwargs):
        try:
            return super().create(request, *args, **kwargs)
        except IntegrityError:
            # Two requests raced for the same slot; the database constraint won.
            return Response(
                {'non_field_errors': ['This time slot is already booked for the selected doctor.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def perform_create(self, serializer):
        appointment = serializer.save()

        for admin in User.objects.filter(role='ADMIN', is_active=True):
            self._send_notification(
                receiver=admin,
                role='ADMIN',
                title='New Appointment Request',
                message=f"{_patient_name(appointment)} requested an appointment with Dr. {_doctor_name(appointment)} on {appointment.appointment_date} at {appointment.appointment_time} — awaiting your approval.",
                appointment=appointment
            )

        log_activity(
            self.request.user,
            'CREATE_APPOINTMENT',
            f"Appointment requested for {_patient_name(appointment)} with Dr. {_doctor_name(appointment)} on {appointment.appointment_date} at {appointment.appointment_time}.",
            self.request,
        )

    @action(detail=False, methods=['get'])
    def my(self, request):
        qs = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def doctor(self, request):
        qs = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def stats(self, request):
        qs = self.get_queryset()
        counts = {row['status']: row['total'] for row in qs.values('status').annotate(total=Count('id'))}
        today = timezone.localdate()
        return Response({
            'total': qs.count(),
            'pending': counts.get('PENDING', 0),
            'accepted': counts.get('ACCEPTED', 0),
            'declined': counts.get('DECLINED', 0),
            'completed': counts.get('COMPLETED', 0),
            'cancelled': counts.get('CANCELLED', 0),
            'today': qs.filter(appointment_date=today).count(),
        })

    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        if request.user.role != 'ADMIN':
            return Response({'detail': 'Only an administrator can accept appointments.'}, status=status.HTTP_403_FORBIDDEN)

        appointment = self.get_object()
        if appointment.status != 'PENDING':
            return Response({'detail': 'Only pending appointments can be accepted.'}, status=status.HTTP_400_BAD_REQUEST)

        appointment.status = 'ACCEPTED'
        appointment.approved_by = request.user
        appointment.save(update_fields=['status', 'approved_by', 'updated_at'])

        self._send_notification(
            receiver=appointment.patient.user,
            role='PATIENT',
            title='Appointment Accepted',
            message=f"Your appointment with Dr. {_doctor_name(appointment)} on {appointment.appointment_date} at {appointment.appointment_time} has been accepted.",
            appointment=appointment
        )

        self._send_notification(
            receiver=appointment.doctor.user,
            role='DOCTOR',
            title='New Appointment Assigned',
            message=f"You have been assigned an appointment with {_patient_name(appointment)} on {appointment.appointment_date} at {appointment.appointment_time}.",
            appointment=appointment
        )

        log_activity(
            request.user, 'ACCEPT_APPOINTMENT',
            f"Accepted appointment for {_patient_name(appointment)} with Dr. {_doctor_name(appointment)} on {appointment.appointment_date}.",
            request,
        )

        return Response({'detail': 'Appointment accepted successfully.'}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def decline(self, request, pk=None):
        if request.user.role != 'ADMIN':
            return Response({'detail': 'Only an administrator can decline appointments.'}, status=status.HTTP_403_FORBIDDEN)

        appointment = self.get_object()
        if appointment.status != 'PENDING':
            return Response({'detail': 'Only pending appointments can be declined.'}, status=status.HTTP_400_BAD_REQUEST)

        appointment.status = 'DECLINED'
        appointment.save(update_fields=['status', 'updated_at'])

        self._send_notification(
            receiver=appointment.patient.user,
            role='PATIENT',
            title='Appointment Declined',
            message=f"Your appointment request with Dr. {_doctor_name(appointment)} on {appointment.appointment_date} at {appointment.appointment_time} has been declined.",
            appointment=appointment
        )

        log_activity(
            request.user, 'DECLINE_APPOINTMENT',
            f"Declined appointment for {_patient_name(appointment)} with Dr. {_doctor_name(appointment)} on {appointment.appointment_date}.",
            request,
        )

        return Response({'detail': 'Appointment declined successfully.'}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        appointment = self.get_object()
        if appointment.status not in ['PENDING', 'ACCEPTED']:
            return Response({'detail': 'Only pending or accepted appointments can be cancelled.'}, status=status.HTTP_400_BAD_REQUEST)

        was_accepted = appointment.status == 'ACCEPTED'
        appointment.status = 'CANCELLED'
        appointment.cancelled_at = timezone.now()
        appointment.save(update_fields=['status', 'cancelled_at', 'updated_at'])

        message = (
            f"Appointment for {_patient_name(appointment)} with Dr. {_doctor_name(appointment)} "
            f"on {appointment.appointment_date} at {appointment.appointment_time} has been cancelled."
        )
        for admin in User.objects.filter(role='ADMIN', is_active=True).exclude(pk=request.user.pk):
            self._send_notification(admin, 'ADMIN', 'Appointment Cancelled', message, appointment)
        # The doctor only knows about accepted appointments; tell them it is off.
        if was_accepted and appointment.doctor.user_id != request.user.id:
            self._send_notification(appointment.doctor.user, 'DOCTOR', 'Appointment Cancelled', message, appointment)
        if appointment.patient.user_id != request.user.id:
            self._send_notification(appointment.patient.user, 'PATIENT', 'Appointment Cancelled', message, appointment)

        log_activity(
            request.user, 'CANCEL_APPOINTMENT',
            f"Cancelled appointment for {_patient_name(appointment)} with Dr. {_doctor_name(appointment)} on {appointment.appointment_date}.",
            request,
        )

        return Response({'detail': 'Appointment cancelled successfully.'}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        if request.user.role not in ('DOCTOR', 'ADMIN'):
            return Response(
                {'detail': 'Only the doctor or an administrator can mark an appointment as completed.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        appointment = self.get_object()
        if appointment.status != 'ACCEPTED':
            return Response({'detail': 'Only accepted appointments can be marked as completed.'}, status=status.HTTP_400_BAD_REQUEST)

        appointment.status = 'COMPLETED'
        appointment.completed_at = timezone.now()
        appointment.save(update_fields=['status', 'completed_at', 'updated_at'])

        self._send_notification(
            receiver=appointment.patient.user,
            role='PATIENT',
            title='Appointment Completed',
            message=f"Your appointment with Dr. {_doctor_name(appointment)} on {appointment.appointment_date} has been marked as completed.",
            appointment=appointment
        )

        log_activity(
            request.user, 'COMPLETE_APPOINTMENT',
            f"Completed appointment for {_patient_name(appointment)} with Dr. {_doctor_name(appointment)} on {appointment.appointment_date}.",
            request,
        )

        return Response({'detail': 'Appointment marked as completed.'}, status=status.HTTP_200_OK)

    def _send_notification(self, receiver, role, title, message, appointment=None):
        if receiver:
            Notification.objects.create(
                receiver=receiver,
                role=role,
                title=title,
                message=message,
                related_appointment=appointment
            )
