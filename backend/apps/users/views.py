from rest_framework import status, permissions, generics
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import AnonRateThrottle
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model, authenticate
from datetime import date, timedelta

from apps.users.serializers import (
    CustomTokenObtainPairSerializer,
    UserSerializer,
    AdminCreateSerializer,
    AdminPasswordResetSerializer,
    ChangePasswordSerializer,
)
from apps.users.permissions import IsAdmin
from apps.patients.models import Patient
from apps.doctors.models import Doctor
from apps.patients.serializers import PatientSerializer
from apps.doctors.serializers import DoctorSerializer
from apps.audit.utils import log_activity

User = get_user_model()


def build_login_response(user):
    refresh = CustomTokenObtainPairSerializer.get_token(user)
    data = {
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'role': user.role,
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'must_change_password': user.must_change_password,
    }
    if user.role == 'DOCTOR' and hasattr(user, 'doctor_profile'):
        data['profile_id'] = user.doctor_profile.doctor_id
    elif user.role == 'PATIENT' and hasattr(user, 'patient_profile'):
        data['profile_id'] = user.patient_profile.patient_id
        data['uuid_token'] = str(user.patient_profile.uuid_token)
    return data


class LoginRateThrottle(AnonRateThrottle):
    """Per-IP limit on login attempts (rate set by the 'login' scope)."""
    scope = 'login'


class LoginView(APIView):
    permission_classes = []
    authentication_classes = []
    throttle_classes = [LoginRateThrottle]

    def post(self, request):
        username = (request.data.get('username') or '').strip()
        password = request.data.get('password') or ''
        if not username or not password:
            return Response({'detail': 'Please enter both username and password.'}, status=status.HTTP_400_BAD_REQUEST)

        # Usernames are generated in lower case, but phones often capitalise the
        # first letter ("Hari.tamang"), so match the username case-insensitively.
        match = User.objects.filter(username__iexact=username).values_list('username', flat=True)
        if len(match) == 1:
            username = match[0]

        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response(
                {'detail': 'No account found with these credentials. Please check your username and password and try again.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        log_activity(user, 'LOGIN', f"User {user.username} logged in.", request)
        return Response(build_login_response(user), status=status.HTTP_200_OK)


class LogoutView(APIView):
    """Revoke the refresh token so it cannot mint new access tokens."""
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        refresh = request.data.get('refresh')
        if not refresh:
            return Response({'detail': 'Refresh token is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            RefreshToken(refresh).blacklist()
        except TokenError:
            # Already expired or revoked: the session is over either way.
            pass
        return Response(status=status.HTTP_205_RESET_CONTENT)


class UserProfileView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        serializer = UserSerializer(user)
        data = serializer.data

        if user.role == 'DOCTOR' and hasattr(user, 'doctor_profile'):
            data['doctor_profile'] = DoctorSerializer(user.doctor_profile, context={'request': request}).data
        elif user.role == 'PATIENT' and hasattr(user, 'patient_profile'):
            data['patient_profile'] = PatientSerializer(user.patient_profile, context={'request': request}).data

        return Response(data)


class ChangePasswordView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.set_password(serializer.validated_data['new_password'])
        user.must_change_password = False
        user.save(update_fields=['password', 'must_change_password'])

        log_activity(
            user, 'PASSWORD_CHANGE',
            f"User {user.username} changed their password.",
            request,
        )
        return Response(
            {'message': 'Password changed successfully. Please use your new password next time you log in.'},
            status=status.HTTP_200_OK,
        )


class AdminPasswordResetView(generics.GenericAPIView):
    permission_classes = [IsAdmin]
    serializer_class = AdminPasswordResetSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user_id = serializer.validated_data['user_id']
        new_password = serializer.validated_data['new_password']

        try:
            target_user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        target_user.set_password(new_password)
        target_user.must_change_password = True
        target_user.save()

        log_activity(
            request.user,
            'RESET_PASSWORD',
            f"Reset password for {target_user.username} (Role: {target_user.role}).",
            request
        )

        return Response(
            {"message": f"Password for user {target_user.username} has been reset successfully."},
            status=status.HTTP_200_OK
        )


class AdminManageAdminsView(generics.ListCreateAPIView):
    permission_classes = [IsAdmin]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return AdminCreateSerializer
        return UserSerializer

    def get_queryset(self):
        return User.objects.filter(role=User.Role.ADMIN)

    def perform_create(self, serializer):
        user = serializer.save()
        log_activity(
            self.request.user,
            'CREATE_ADMIN',
            f"Created new Admin account: {user.username}.",
            self.request
        )


class AdminDashboardStatsView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        today = date.today()

        total_users = User.objects.count()
        total_patients = Patient.objects.count()
        total_doctors = Doctor.objects.count()
        total_admins = User.objects.filter(role=User.Role.ADMIN).count()

        today_registrations = User.objects.filter(date_joined__date=today).count()
        active_users = User.objects.filter(is_active=True).count()
        inactive_users = User.objects.filter(is_active=False).count()

        
        recent_patients = Patient.objects.order_by('-registration_date')[:5]
        recent_doctors = Doctor.objects.order_by('-registration_date')[:5]

        recent_patients_serialized = PatientSerializer(recent_patients, many=True, context={'request': request}).data
        recent_doctors_serialized = DoctorSerializer(recent_doctors, many=True, context={'request': request}).data

        
        chart_data = []
        for i in range(6, -1, -1):
            day = today - timedelta(days=i)
            patient_cnt = Patient.objects.filter(registration_date__date=day).count()
            doctor_cnt = Doctor.objects.filter(registration_date__date=day).count()
            chart_data.append({
                'date': day.strftime('%b %d'),
                'patients': patient_cnt,
                'doctors': doctor_cnt
            })

        return Response({
            'total_users': total_users,
            'total_patients': total_patients,
            'total_doctors': total_doctors,
            'total_admins': total_admins,
            'today_registrations': today_registrations,
            'active_users': active_users,
            'inactive_users': inactive_users,
            'recent_patients': recent_patients_serialized,
            'recent_doctors': recent_doctors_serialized,
            'registration_chart': chart_data
        })
