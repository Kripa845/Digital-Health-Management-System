"""Lab report routes, included under /api/v1/ by config/urls.py.

    POST reports/upload/                 upload → preview (or review / rejection)
    GET  reports/                        history
    GET  reports/{id}/                   one report with its values
    GET  reports/{id}/status/            status only
    POST reports/{id}/confirm/           apply the preview
    POST reports/{id}/discard/           cancel an unconfirmed report
    GET  reports/{id}/download/          original file (decrypted)
    GET  dashboard/                      cards, statuses, history, trends
    GET  admin/review-queue/             reports needing review (admin)
    POST admin/reports/{id}/resolve/     approve or reject (admin)

The same viewset stays available at lab-reports/ for existing clients.
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.lab_reports.views import DashboardView, LabReportViewSet, ResolveReportView, ReviewQueueView

router = DefaultRouter()
router.register(r'reports', LabReportViewSet, basename='report')
router.register(r'lab-reports', LabReportViewSet, basename='lab-report')

urlpatterns = [
    path('dashboard/', DashboardView.as_view(), name='lab-dashboard'),
    path('admin/review-queue/', ReviewQueueView.as_view(), name='lab-review-queue'),
    path('admin/reports/<int:pk>/resolve/', ResolveReportView.as_view(), name='lab-report-resolve'),
    path('', include(router.urls)),
]
