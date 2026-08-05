from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework.permissions import AllowAny

class PublicTokenRefreshView(TokenRefreshView):
    permission_classes = [AllowAny]


def healthz(request):
    return JsonResponse({'status': 'ok'})

# Views import
from apps.users.views import (
    LoginView,
    UserProfileView,
    AdminPasswordResetView,
    AdminManageAdminsView,
    AdminDashboardStatsView,
    ChangePasswordView,
)
from apps.patients.views import PatientViewSet
from apps.doctors.views import DoctorViewSet, DoctorAssignmentViewSet, PrescriptionViewSet, AccessRequestViewSet
from apps.recommendations.views import RecommendationHistoryViewSet
from apps.documents.views import DocumentViewSet
from apps.audit.views import AuditLogViewSet
from apps.appointments.views import AppointmentViewSet
from apps.notifications.views import NotificationViewSet
from apps.lab_reports.views import LabReportViewSet

# API Routers
router = DefaultRouter()
router.register(r'patients', PatientViewSet, basename='patient')
router.register(r'doctors', DoctorViewSet, basename='doctor')
router.register(r'assignments', DoctorAssignmentViewSet, basename='assignment')
router.register(r'access-requests', AccessRequestViewSet, basename='access-request')
router.register(r'prescriptions', PrescriptionViewSet, basename='prescription')
router.register(r'recommendations', RecommendationHistoryViewSet, basename='recommendation')
router.register(r'documents', DocumentViewSet, basename='document')
router.register(r'audit-logs', AuditLogViewSet, basename='audit-log')
router.register(r'appointments', AppointmentViewSet, basename='appointment')
router.register(r'notifications', NotificationViewSet, basename='notification')
router.register(r'lab-reports', LabReportViewSet, basename='lab-report')

urlpatterns = [
    path('admin/', admin.site.urls),

    # Liveness probe / keep-alive target
    path('healthz/', healthz, name='healthz'),

    # Authentication & Profile
    path('api/v1/auth/login/', LoginView.as_view(), name='token_obtain_pair'),
    path('api/v1/auth/token/refresh/', PublicTokenRefreshView.as_view(), name='token_refresh'),
    path('api/v1/auth/me/', UserProfileView.as_view(), name='user_profile'),
    path('api/v1/auth/change-password/', ChangePasswordView.as_view(), name='change_password'),

    # Admin tools
    path('api/v1/auth/admin/reset-password/', AdminPasswordResetView.as_view(), name='admin_reset_password'),
    path('api/v1/auth/admin/manage-admins/', AdminManageAdminsView.as_view(), name='admin_manage_admins'),
    path('api/v1/auth/admin/stats/', AdminDashboardStatsView.as_view(), name='admin_stats'),

    # Registered resource routes
    path('api/v1/', include(router.urls)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

