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
    LogoutView,
    UserProfileView,
    AdminPasswordResetView,
    AdminManageAdminsView,
    AdminDashboardStatsView,
    ChangePasswordView,
)
from apps.patients.views import PatientViewSet
from apps.doctors.views import DoctorViewSet, DoctorAssignmentViewSet, PrescriptionViewSet, AccessRequestViewSet
from apps.recommendations.views import RecommendationHistoryViewSet
from apps.recommendations.smart_views import RankingSettingsView, SmartSymptomCheckView
from apps.documents.views import DocumentViewSet
from apps.audit.views import (
    ActivityAnalysisView, ActivityFlagViewSet, ActivitySettingsView, AuditLogViewSet, SuspiciousAlertViewSet,
)
from apps.appointments.views import AppointmentViewSet
from apps.notifications.views import NotificationViewSet

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
router.register(r'activity-flags', ActivityFlagViewSet, basename='activity-flag')
router.register(r'suspicious-alerts', SuspiciousAlertViewSet, basename='suspicious-alert')
router.register(r'appointments', AppointmentViewSet, basename='appointment')
router.register(r'notifications', NotificationViewSet, basename='notification')

urlpatterns = [
    path('admin/', admin.site.urls),

    # Liveness probe / keep-alive target
    path('healthz/', healthz, name='healthz'),

    # Authentication & Profile
    path('api/v1/auth/login/', LoginView.as_view(), name='token_obtain_pair'),
    path('api/v1/auth/token/refresh/', PublicTokenRefreshView.as_view(), name='token_refresh'),
    path('api/v1/auth/refresh/', PublicTokenRefreshView.as_view(), name='token_refresh_short'),
    path('api/v1/auth/logout/', LogoutView.as_view(), name='logout'),
    path('api/v1/auth/me/', UserProfileView.as_view(), name='user_profile'),
    path('api/v1/auth/change-password/', ChangePasswordView.as_view(), name='change_password'),

    # Admin tools
    path('api/v1/auth/admin/reset-password/', AdminPasswordResetView.as_view(), name='admin_reset_password'),
    path('api/v1/auth/admin/manage-admins/', AdminManageAdminsView.as_view(), name='admin_manage_admins'),
    path('api/v1/auth/admin/stats/', AdminDashboardStatsView.as_view(), name='admin_stats'),

    # Smart symptom check (Random Forest + AHP-weighted TOPSIS); the keyword checker stays at /recommendations/
    path('api/v1/smart-symptom-check/', SmartSymptomCheckView.as_view(), name='smart_symptom_check'),
    # AHP comparisons that set the doctor-ranking weights (admin only)
    path('api/v1/ranking-settings/', RankingSettingsView.as_view(), name='ranking_settings'),
    # Window and DBSCAN parameters for activity anomaly flagging (admin only)
    path('api/v1/activity-settings/', ActivitySettingsView.as_view(), name='activity_settings'),
    # Step-by-step DBSCAN analysis for the admin page (GET previews, POST saves flags)
    path('api/v1/activity-analysis/', ActivityAnalysisView.as_view(), name='activity_analysis'),

    # Registered resource routes
    path('api/v1/', include(router.urls)),
    path('api/v1/', include('apps.lab_reports.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

