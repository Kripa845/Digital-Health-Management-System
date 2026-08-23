
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
from apps.doctors.models import AccessRequest

logger = logging.getLogger(__name__)




class LabReportPermission(permissions.BasePermission):
  

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
            if view.action in ('retrieve', 'download'):
                has_assignment = obj.patient.assignments.filter(
                    doctor__user=user, status='Active'
                ).exists()
                if not has_assignment:
                    return False
                return AccessRequest.objects.filter(
                    doctor__user=user, patient=obj.patient, status='APPROVED'
                ).exists()
            return False

        return False



class LabReportViewSet(viewsets.ModelViewSet):
    serializer_class = LabReportSerializer
    permission_classes = [LabReportPermission]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['patient', 'status']
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    

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
                patient__access_requests__doctor__user=user,
                patient__access_requests__status='APPROVED',
            ).distinct()

        return LabReport.objects.none()

    

    def get_serializer_class(self):
        if self.action == 'create':
            return LabReportUploadSerializer
        return LabReportSerializer

    

    def create(self, request, *args, **kwargs):
        user = request.user

       
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

       
        lab_report.ocr_text = ocr_text
        lab_report.save(update_fields=['ocr_text'])

       
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
            
            lab_report.status = LabReport.Status.COMPLETED
            lab_report.processed_at = timezone.now()
            lab_report.save(update_fields=['status', 'processed_at'])
            result_ser = LabReportSerializer(lab_report, context={'request': request})
            return Response(
                {
                    'detail': 'OCR succeeded but no standard medical values were detected. '
                              'The original file has been stored.',
                    'ocr_succeeded': True,
                    'fields_detected': False,
                    'ocr_text_length': len(ocr_text),
                    **result_ser.data,
                },
                status=status.HTTP_201_CREATED,
            )

        
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
            f'Unchanged: {processing_result.unchanged_count}, '
            f'Needs review: {processing_result.needs_review_count}.',
            request,
        )

        lab_report.refresh_from_db()
        result_ser = LabReportSerializer(lab_report, context={'request': request})
        response_data = result_ser.data
        response_data['processing_summary'] = {
            'detected': [f.field_name for f in processing_result.detected_fields],
            'updated': [f.field_name for f in processing_result.updated_fields],
            'unchanged': [f.field_name for f in processing_result.unchanged_fields],
            'needs_review': [f.field_name for f in processing_result.needs_review_fields],
        }
        return Response(response_data, status=status.HTTP_201_CREATED)

 

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
        result_ser = LabReportSerializer(lab_report, context={'request': request})
        response_data = result_ser.data
        response_data['processing_summary'] = {
            'detected': [f.field_name for f in processing_result.detected_fields],
            'updated': [f.field_name for f in processing_result.updated_fields],
            'unchanged': [f.field_name for f in processing_result.unchanged_fields],
            'needs_review': [f.field_name for f in processing_result.needs_review_fields],
        }
        return Response(response_data)



    def perform_destroy(self, instance):
        log_activity(
            self.request.user,
            'DELETE_LAB_REPORT',
            f'Deleted lab report "{instance.name}" for patient {instance.patient.patient_id}.',
            self.request,
        )
        instance.delete()
