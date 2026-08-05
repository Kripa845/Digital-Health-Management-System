"""
Views for the lab_reports app.

LabReportViewSet
  POST   /api/v1/lab-reports/          – upload + auto-process
  GET    /api/v1/lab-reports/          – list (filtered by patient/role)
  GET    /api/v1/lab-reports/{id}/     – retrieve single report + fields
  DELETE /api/v1/lab-reports/{id}/     – delete (Patient own ADDITIONAL, Admin any)
  GET    /api/v1/lab-reports/{id}/download/ – download original file
  POST   /api/v1/lab-reports/{id}/reprocess/ – re-run OCR + CDSA (Admin only)

Permissions
  - Patient   : upload own reports, list/retrieve own, delete own, download own
  - Admin     : upload for any patient, full list, retrieve any, delete any, reprocess
  - Doctor    : list/retrieve for assigned patients only (read-only)
"""

import logging

from django.http import FileResponse, Http404
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.audit.utils import log_activity
from apps.lab_reports.cdsa import run_cdsa
from apps.lab_reports.extractor import extract_medical_fields
from apps.lab_reports.models import LabReport
from apps.lab_reports.ocr_service import extract_text_from_file
from apps.lab_reports.serializers import LabReportSerializer, LabReportUploadSerializer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Permission class
# ---------------------------------------------------------------------------

class LabReportPermission(permissions.BasePermission):
    """
    Custom permission for LabReportViewSet.

    create   – Patient (own) or Admin (any patient)
    list/retrieve/download – Patient (own), Admin (any), Doctor (assigned)
    destroy  – Patient (own), Admin (any)
    reprocess – Admin only
    """

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if view.action == 'create':
            return user.role in ('ADMIN', 'PATIENT')

        if view.action in ('list', 'retrieve', 'download'):
            return True   # row-level filtering done in get_queryset / has_object_permission

        if view.action == 'destroy':
            return user.role in ('ADMIN', 'PATIENT')

        if view.action == 'reprocess':
            return user.role == 'ADMIN'

        return True

    def has_object_permission(self, request, view, obj):
        user = request.user

        if user.role == 'ADMIN':
            return True

        if user.role == 'PATIENT':
            owned = obj.patient.user_id == user.id
            if view.action == 'destroy':
                return owned
            return owned

        if user.role == 'DOCTOR':
            # Read-only access for actively assigned patients
            if view.action in ('retrieve', 'download'):
                return obj.patient.assignments.filter(
                    doctor__user=user, status='Active'
                ).exists()
            return False

        return False


# ---------------------------------------------------------------------------
# ViewSet
# ---------------------------------------------------------------------------

class LabReportViewSet(viewsets.ModelViewSet):
    serializer_class = LabReportSerializer
    permission_classes = [LabReportPermission]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['patient', 'status']
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    # --- queryset scoping ---------------------------------------------------

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return LabReport.objects.none()

        base = LabReport.objects.select_related('patient', 'uploaded_by').prefetch_related('fields')

        if user.role == 'ADMIN':
            return base.all()

        if user.role == 'PATIENT':
            return base.filter(patient__user=user)

        if user.role == 'DOCTOR':
            return base.filter(
                patient__assignments__doctor__user=user,
                patient__assignments__status='Active',
            ).distinct()

        return LabReport.objects.none()

    # --- serializer selection -----------------------------------------------

    def get_serializer_class(self):
        if self.action == 'create':
            return LabReportUploadSerializer
        return LabReportSerializer

    # --- CREATE: upload + OCR pipeline --------------------------------------

    def create(self, request, *args, **kwargs):
        user = request.user

        # For PATIENT role, force patient to their own profile
        data = request.data.copy()
        if user.role == 'PATIENT':
            patient_profile = getattr(user, 'patient_profile', None)
            if not patient_profile:
                return Response(
                    {'detail': 'No patient profile linked to your account.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            data['patient'] = patient_profile.id

        upload_ser = LabReportUploadSerializer(data=data)
        upload_ser.is_valid(raise_exception=True)

        # Check for duplicate: same patient + same filename + same size within last 24h.
        # Only block if a successfully completed (or still-processing) record exists.
        # FAILED records are ignored so the user can simply retry the same file.
        from datetime import timedelta
        patient_obj = upload_ser.validated_data['patient']
        file_obj = upload_ser.validated_data['file']
        cutoff = timezone.now() - timedelta(hours=24)
        if LabReport.objects.filter(
            patient=patient_obj,
            name=upload_ser.validated_data.get('name', ''),
            size=file_obj.size,
            uploaded_at__gte=cutoff,
            status__in=[LabReport.Status.COMPLETED, LabReport.Status.PROCESSING],
        ).exists():
            return Response(
                {'detail': 'This report was already uploaded and processed recently. Check your existing lab reports.'},
                status=status.HTTP_409_CONFLICT,
            )

        # Save the report record in PROCESSING state
        lab_report = upload_ser.save(
            uploaded_by=user,
            status=LabReport.Status.PROCESSING,
        )

        log_activity(
            user,
            'UPLOAD_LAB_REPORT',
            f'Uploaded lab report "{lab_report.name}" ({lab_report.file_type}) '
            f'for patient {lab_report.patient.patient_id}.',
            request,
        )

        # --- OCR pipeline ---------------------------------------------------
        try:
            ocr_text = extract_text_from_file(lab_report.file)
        except RuntimeError as exc:
            lab_report.status = LabReport.Status.FAILED
            lab_report.error_message = str(exc)
            lab_report.save(update_fields=['status', 'error_message'])
            return Response(
                {
                    'detail': f'OCR extraction failed: {exc}',
                    'report_id': lab_report.id,
                    'status': lab_report.status,
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except Exception as exc:
            lab_report.status = LabReport.Status.FAILED
            lab_report.error_message = f'Unexpected OCR error: {exc}'
            lab_report.save(update_fields=['status', 'error_message'])
            logger.exception('Unexpected OCR error for lab report %d', lab_report.id)
            return Response(
                {'detail': 'An unexpected error occurred during OCR processing.', 'report_id': lab_report.id},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Store raw OCR text (read-only reference, never fed back to the file)
        lab_report.ocr_text = ocr_text
        lab_report.save(update_fields=['ocr_text'])

        # --- Extract medical fields -----------------------------------------
        try:
            extracted = extract_medical_fields(ocr_text)
        except Exception as exc:
            lab_report.status = LabReport.Status.FAILED
            lab_report.error_message = f'Field extraction failed: {exc}'
            lab_report.save(update_fields=['status', 'error_message'])
            return Response(
                {'detail': f'Medical field extraction failed: {exc}', 'report_id': lab_report.id},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        if not extracted:
            # OCR succeeded but no recognisable medical values found – still mark complete
            lab_report.status = LabReport.Status.COMPLETED
            lab_report.processed_at = timezone.now()
            lab_report.save(update_fields=['status', 'processed_at'])
            result_ser = LabReportSerializer(lab_report, context={'request': request})
            return Response(
                {
                    'detail': 'Report processed but no standard medical values were detected. '
                              'The original file has been stored.',
                    **result_ser.data,
                },
                status=status.HTTP_201_CREATED,
            )

        # --- Run CDSA -------------------------------------------------------
        try:
            processing_result = run_cdsa(lab_report, extracted)
        except Exception as exc:
            lab_report.status = LabReport.Status.FAILED
            lab_report.error_message = f'CDSA failed: {exc}'
            lab_report.save(update_fields=['status', 'error_message'])
            logger.exception('CDSA error for lab report %d', lab_report.id)
            return Response(
                {'detail': f'Patient record update failed: {exc}', 'report_id': lab_report.id},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        log_activity(
            user,
            'PROCESS_LAB_REPORT',
            f'Lab report "{lab_report.name}" processed for patient '
            f'{lab_report.patient.patient_id}. '
            f'Detected: {processing_result.detected_count}, '
            f'Updated: {processing_result.updated_count}, '
            f'Unchanged: {processing_result.unchanged_count}.',
            request,
        )

        # Refresh from DB to get accurate counts
        lab_report.refresh_from_db()
        result_ser = LabReportSerializer(lab_report, context={'request': request})
        return Response(result_ser.data, status=status.HTTP_201_CREATED)

    # --- custom action: download original file ------------------------------

    @action(detail=True, methods=['get'], url_path='download')
    def download(self, request, pk=None):
        lab_report = self.get_object()
        try:
            file_handle = lab_report.file.open('rb')
        except (FileNotFoundError, ValueError):
            raise Http404('The original lab report file is no longer available.')
        response = FileResponse(file_handle, content_type='application/octet-stream')
        response['Content-Disposition'] = f'attachment; filename="{lab_report.name}"'
        return response

    # --- custom action: reprocess (Admin only) ------------------------------

    @action(detail=True, methods=['post'], url_path='reprocess')
    def reprocess(self, request, pk=None):
        if request.user.role != 'ADMIN':
            return Response({'detail': 'Only admins can reprocess lab reports.'}, status=status.HTTP_403_FORBIDDEN)

        lab_report = self.get_object()

        lab_report.status = LabReport.Status.PROCESSING
        lab_report.error_message = ''
        lab_report.save(update_fields=['status', 'error_message'])

        try:
            ocr_text = extract_text_from_file(lab_report.file)
            lab_report.ocr_text = ocr_text
            lab_report.save(update_fields=['ocr_text'])
        except RuntimeError as exc:
            lab_report.status = LabReport.Status.FAILED
            lab_report.error_message = str(exc)
            lab_report.save(update_fields=['status', 'error_message'])
            return Response({'detail': str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        extracted = extract_medical_fields(ocr_text)

        try:
            processing_result = run_cdsa(lab_report, extracted)
        except Exception as exc:
            lab_report.status = LabReport.Status.FAILED
            lab_report.error_message = str(exc)
            lab_report.save(update_fields=['status', 'error_message'])
            return Response({'detail': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        log_activity(
            request.user,
            'REPROCESS_LAB_REPORT',
            f'Reprocessed lab report "{lab_report.name}" for patient '
            f'{lab_report.patient.patient_id}.',
            request,
        )

        lab_report.refresh_from_db()
        return Response(LabReportSerializer(lab_report, context={'request': request}).data)

    # --- destroy with audit -------------------------------------------------

    def perform_destroy(self, instance):
        log_activity(
            self.request.user,
            'DELETE_LAB_REPORT',
            f'Deleted lab report "{instance.name}" for patient {instance.patient.patient_id}.',
            self.request,
        )
        instance.delete()
