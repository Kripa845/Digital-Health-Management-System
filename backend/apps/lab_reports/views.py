"""Lab report API. Views are thin: they check access, call services/ and shape
the response. Errors use one JSON shape: {"code": "...", "message": "..."}
("detail" repeats the message for older clients)."""
import io
import logging
from datetime import date

from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from django.http import FileResponse

from apps.audit.utils import log_activity
from apps.doctors.access import doctor_access_filters, doctor_can_access
from apps.lab_reports.models import LabReport
from apps.lab_reports.permissions import IsAdminReviewer, IsReportOwner
from apps.lab_reports.serializers import (
    AdminReviewSerializer, ConfirmSerializer, LabReportSerializer, LabReportUploadSerializer, ReportDateSerializer,
    ResolveSerializer,
)
from apps.lab_reports.services import upload as upload_service
from apps.lab_reports.services.date_check import evaluate, evaluate_report
from apps.lab_reports.services.dashboard import (
    InvalidEdit, NotPending, apply_report, build_dashboard, delete_report, replan_preview, save_without_values,
)
from apps.notifications.models import Notification
from apps.patients.models import Patient

logger = logging.getLogger(__name__)


def error(code: str, message: str, http_status: int, **extra) -> Response:
    return Response({'code': code, 'message': message, 'detail': message, **extra}, status=http_status)


class UploadThrottle(ScopedRateThrottle):
    scope = 'lab_upload'


class LabReportViewSet(viewsets.ModelViewSet):
    serializer_class = LabReportSerializer
    permission_classes = [IsReportOwner]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['patient', 'status']
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_throttles(self):
        if self.action in ('create', 'upload'):
            return [UploadThrottle()]
        return super().get_throttles()

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return LabReport.objects.none()

        base = LabReport.objects.select_related('patient', 'uploaded_by', 'confirmed_by').prefetch_related('fields')

        if user.role == 'ADMIN':
            return base.all()

        if user.role == 'PATIENT':
            return base.filter(patient__user=user)

        if user.role == 'DOCTOR':
            # Doctors see confirmed reports and saved documents only, never unconfirmed previews.
            return base.filter(*doctor_access_filters(user, 'patient'),
                               status__in=(LabReport.Status.CONFIRMED, LabReport.Status.SAVED_NO_VALUES))

        return LabReport.objects.none()

    def get_serializer_class(self):
        if self.action in ('create', 'upload'):
            return LabReportUploadSerializer
        return LabReportSerializer

    # ── Upload: verify and preview; nothing is applied yet ───────────────────

    def create(self, request, *args, **kwargs):
        user = request.user
        if user.role == 'PATIENT':
            patient = getattr(user, 'patient_profile', None)
            if patient is None:
                return error('no_profile', 'No patient profile is linked to your account.', status.HTTP_400_BAD_REQUEST)
        else:
            try:
                patient = Patient.objects.get(pk=request.data.get('patient'))
            except (Patient.DoesNotExist, ValueError, TypeError):
                return error('invalid_patient', 'Choose the patient this report belongs to.', status.HTTP_400_BAD_REQUEST)

        uploaded = request.FILES.get('file')
        if uploaded is None:
            return error('invalid_file', 'Choose a PDF, PNG or JPG file to upload.', status.HTTP_400_BAD_REQUEST)

        try:
            outcome = upload_service.process_upload(patient, uploaded, request.data.get('name', ''), user, request)
        except upload_service.UploadError as exc:
            return error(exc.code, exc.message, exc.http_status, **exc.extra)
        except Exception:
            logger.exception('Unexpected error while processing a lab report upload')
            return error('server_error', 'Something went wrong while reading the report. Please try again.',
                         status.HTTP_500_INTERNAL_SERVER_ERROR)

        data = LabReportSerializer(outcome.report, context={'request': request}).data
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='upload')
    def upload(self, request):
        return self.create(request)

    # ── Confirm or cancel a preview ──────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='confirm')
    def confirm(self, request, pk=None):
        report = self.get_object()
        payload = ConfirmSerializer(data=request.data or {})
        if not payload.is_valid():
            return error('invalid_values', 'The values sent could not be read.', status.HTTP_400_BAD_REQUEST,
                         errors=payload.errors)

        # Report date ordering, enforced here and not only in the app.
        save_only = report.status == LabReport.Status.NO_VALUES_SAVEABLE
        dates = (evaluate_report(report)
                 if report.status == LabReport.Status.PENDING_CONFIRMATION or save_only else None)
        acknowledged = payload.validated_data['acknowledge_older_report']
        if dates and dates.blocked:
            return error('older_report', f'{dates.message} It cannot be confirmed.',
                         status.HTTP_422_UNPROCESSABLE_ENTITY)
        if dates and dates.ack_required and not acknowledged:
            return error('older_report_not_acknowledged',
                         f'{dates.message} Confirm that you want to add this older report.',
                         status.HTTP_400_BAD_REQUEST)
        try:
            if save_only:
                # No health card values: keep the file as a document; no values or history rows.
                save_without_values(report, user=request.user, request=request)
            else:
                apply_report(report, user=request.user, edits=payload.validated_data['values'],
                             accept_flagged=payload.validated_data['accept_flagged'], request=request)
        except NotPending:
            message = ('This report is waiting for review by the care team.'
                       if report.status == LabReport.Status.NEEDS_REVIEW
                       else 'This report has already been confirmed or is not ready.')
            return error('not_pending', message, status.HTTP_409_CONFLICT)
        except InvalidEdit as exc:
            return error('invalid_values', 'Some values need correcting.', status.HTTP_400_BAD_REQUEST,
                         errors=exc.errors)
        if dates and dates.ack_required:
            # Audited without the dates themselves.
            log_activity(request.user, 'OVERRIDE_OLDER_REPORT_DATE',
                         f'Confirmed lab report {report.id} for patient {report.patient.patient_id} although it is '
                         'older than the latest confirmed report.', request)
        report.refresh_from_db()
        return Response(LabReportSerializer(report, context={'request': request}).data)

    @action(detail=True, methods=['post'], url_path='report-date')
    def report_date(self, request, pk=None):
        """Set the report date typed (or corrected) in the preview, then compare it again."""
        report = self.get_object()
        if report.status not in (LabReport.Status.PENDING_CONFIRMATION, LabReport.Status.NEEDS_REVIEW,
                                 LabReport.Status.NO_VALUES_SAVEABLE):
            return error('not_pending', 'The report date can only be changed before the report is confirmed.',
                         status.HTTP_409_CONFLICT)
        payload = ReportDateSerializer(data=request.data or {})
        if not payload.is_valid():
            return error('invalid_date', 'Enter the report date as a valid date.', status.HTTP_400_BAD_REQUEST,
                         errors=payload.errors)
        new_date = payload.validated_data['report_date']
        if new_date > timezone.localdate():
            return error('invalid_date', 'The report date cannot be in the future.', status.HTTP_400_BAD_REQUEST)
        if new_date < date(1900, 1, 1):
            return error('invalid_date', 'Enter the report date as a valid date.', status.HTTP_400_BAD_REQUEST)
        dates = evaluate(report.patient, new_date, exclude_report=report)
        if dates.blocked:
            return error('older_report', f'{dates.message} It cannot be used.', status.HTTP_422_UNPROCESSABLE_ENTITY)

        report.report_date = new_date
        report.report_date_source = 'user'
        report.report_date_user_entered = True
        report.save(update_fields=['report_date', 'report_date_source', 'report_date_user_entered'])
        replan_preview(report)
        logger.info('Lab report date entered by user: status=%s', dates.status)   # never the date
        log_activity(request.user, 'EDIT_LAB_REPORT_DATE',
                     f'Report date of lab report {report.id} entered in the preview (date check: {dates.status}).',
                     request)
        report.refresh_from_db()
        return Response(LabReportSerializer(report, context={'request': request}).data)

    @action(detail=True, methods=['post'], url_path='discard')
    def discard(self, request, pk=None):
        report = self.get_object()
        if report.status not in (LabReport.Status.PENDING_CONFIRMATION, LabReport.Status.NEEDS_REVIEW,
                                 LabReport.Status.NO_VALUES_SAVEABLE):
            return error('not_pending', 'Only a report that has not been confirmed can be cancelled.',
                         status.HTTP_409_CONFLICT)
        log_activity(request.user, 'DISCARD_LAB_REPORT',
                     f'Cancelled lab report {report.id} for patient {report.patient.patient_id}.', request)
        report.delete()   # also deletes the stored file
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get'], url_path='status')
    def status(self, request, pk=None):
        report = self.get_object()
        data = LabReportSerializer(report, context={'request': request}).data
        return Response({k: data[k] for k in (
            'id', 'status', 'review_reasons', 'review_messages', 'review_note',
            'uploaded_at', 'reviewed_at', 'confirmed_at', 'updated_count')})

    # ── Original file ────────────────────────────────────────────────────────

    @action(detail=True, methods=['get'], url_path='download')
    def download(self, request, pk=None):
        report = self.get_object()
        if not report.file:
            return error('no_file', 'The original file of this report is no longer stored.', status.HTTP_404_NOT_FOUND)
        try:
            data = upload_service.stored_bytes(report)
        except (FileNotFoundError, ValueError, OSError):
            return error('no_file', 'The original file of this report is no longer available.', status.HTTP_404_NOT_FOUND)
        ext = f'.{report.file_type.lower()}' if report.file_type else ''
        base = report.name or 'lab-report'
        filename = base if base.lower().endswith(ext) else f'{base}{ext}'
        return FileResponse(io.BytesIO(data), as_attachment=True, filename=filename,
                            content_type='application/octet-stream')

    @action(detail=True, methods=['post'], url_path='reprocess')
    def reprocess(self, request, pk=None):
        report = self.get_object()
        try:
            report = upload_service.reprocess(report, request.user, request)
        except upload_service.UploadError as exc:
            return error(exc.code, exc.message, exc.http_status)
        return Response(LabReportSerializer(report, context={'request': request}).data)

    def perform_destroy(self, instance):
        # Any status; a confirmed report's dashboard values are reverted too.
        delete_report(instance, self.request.user, self.request)


class DashboardView(APIView):
    """GET /dashboard/ — age, blood group and each test's latest value, status,
    history and trend. Patients get their own; admins and doctors with approved
    access pass ?patient=<id>."""

    def get(self, request):
        user = request.user
        if user.role == 'PATIENT':
            patient = getattr(user, 'patient_profile', None)
            if patient is None:
                return error('no_profile', 'No patient profile is linked to your account.', status.HTTP_404_NOT_FOUND)
        else:
            try:
                patient = Patient.objects.get(pk=request.query_params.get('patient'))
            except (Patient.DoesNotExist, ValueError, TypeError):
                return error('invalid_patient', 'Choose a patient.', status.HTTP_400_BAD_REQUEST)
            if user.role == 'DOCTOR' and not doctor_can_access(user, patient):
                return error('forbidden', "You don't have access to this patient's record.", status.HTTP_403_FORBIDDEN)
            if user.role not in ('ADMIN', 'DOCTOR'):
                return error('forbidden', 'Not allowed.', status.HTTP_403_FORBIDDEN)
        return Response(build_dashboard(Patient.objects.get(pk=patient.pk)))


class ReviewQueueView(APIView):
    """GET /admin/review-queue/ — reports the identity gate could not verify."""
    permission_classes = [IsAdminReviewer]

    def get(self, request):
        qs = LabReport.objects.filter(status=LabReport.Status.NEEDS_REVIEW) \
            .select_related('patient', 'uploaded_by').prefetch_related('fields').order_by('uploaded_at')
        return Response(AdminReviewSerializer(qs, many=True, context={'request': request}).data)


class ResolveReportView(APIView):
    """POST /admin/reports/{id}/resolve/ {"decision": "approve" | "reject", "note": "..."}.

    approve → PENDING_CONFIRMATION (the values still need confirming; nothing is
    applied here), or NO_VALUES_SAVEABLE when the report has no card values. reject → REJECTED and the stored file is deleted."""
    permission_classes = [IsAdminReviewer]

    def post(self, request, pk):
        try:
            report = LabReport.objects.select_related('patient__user').get(pk=pk)
        except LabReport.DoesNotExist:
            return error('not_found', 'Report not found.', status.HTTP_404_NOT_FOUND)
        payload = ResolveSerializer(data=request.data)
        if not payload.is_valid():
            return error('invalid_decision', 'Choose approve or reject.', status.HTTP_400_BAD_REQUEST,
                         errors=payload.errors)
        if report.status != LabReport.Status.NEEDS_REVIEW:
            return error('not_in_review', 'This report is not waiting for review.', status.HTTP_409_CONFLICT)

        decision, note = payload.validated_data['decision'], payload.validated_data['note']
        report.reviewed_by, report.reviewed_at, report.review_note = request.user, timezone.now(), note
        if decision == 'approve':
            has_values = report.fields.exists()
            report.status = (LabReport.Status.PENDING_CONFIRMATION if has_values
                             else LabReport.Status.NO_VALUES_SAVEABLE)
            report.identity_verified = True
            title, message = ('Lab Report Checked',
                              f'Your lab report "{report.name}" was checked by the care team. '
                              + ('Open it to review and confirm the values.' if has_values
                                 else 'It has no health card values; open it to save it as a document.'))
        else:
            report.status = LabReport.Status.REJECTED
            if report.file:
                report.file.delete(save=False)
            title, message = ('Lab Report Not Accepted',
                              f'Your lab report "{report.name}" could not be accepted'
                              + (f': {note}' if note else '.'))
        report.save()
        Notification.objects.create(receiver=report.patient.user, role='PATIENT', title=title, message=message)
        log_activity(request.user, 'RESOLVE_LAB_REPORT',
                     f'{decision.title()}d lab report {report.id} for patient {report.patient.patient_id}.', request)
        return Response(AdminReviewSerializer(report, context={'request': request}).data)
