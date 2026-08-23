from django.http import HttpResponse, FileResponse, Http404
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from django_filters.rest_framework import DjangoFilterBackend
from apps.documents.models import Document
from apps.documents.serializers import DocumentSerializer
from apps.audit.utils import log_activity
from apps.doctors.models import AccessRequest

class DocumentPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        if view.action in ['list', 'retrieve', 'download']:
            return True
        
        if view.action == 'create':
            report_type = request.data.get('report_type', 'ADDITIONAL')
            if report_type == 'MEDICAL':
                return request.user.role == 'ADMIN'
            return request.user.role in ('ADMIN', 'PATIENT')
        
        if view.action in ['destroy', 'update', 'partial_update']:
            if request.user.role == 'PATIENT':
                return True
            if request.user.role == 'ADMIN':
                return True
            return False
        
        return True

    def has_object_permission(self, request, view, obj):
        user = request.user
        
        if view.action in ['retrieve', 'download']:
            return True
        
        if user.role == 'ADMIN':
            if view.action in ['destroy', 'update', 'partial_update']:
                return obj.report_type == 'MEDICAL'
            return True
        
        if user.role == 'PATIENT':
            if view.action in ['destroy', 'update', 'partial_update']:
                return obj.report_type == 'ADDITIONAL' and obj.patient.user_id == user.id
            return obj.patient.user_id == user.id
        
        if user.role == 'DOCTOR':
            has_assignment = obj.patient.assignments.filter(doctor__user=user, status='Active').exists()
            if not has_assignment:
                return False
            return AccessRequest.objects.filter(
                doctor__user=user, patient=obj.patient, status='APPROVED'
            ).exists()
        
        return False

class DocumentViewSet(viewsets.ModelViewSet):
    serializer_class = DocumentSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['patient', 'report_type']
    permission_classes = [DocumentPermission]

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return Document.objects.none()

        if user.role == 'ADMIN':
            return Document.objects.all().select_related('patient', 'uploaded_by')
        elif user.role == 'DOCTOR':
            return Document.objects.filter(
                patient__assignments__doctor__user=user,
                patient__assignments__status='Active',
                patient__access_requests__doctor__user=user,
                patient__access_requests__status='APPROVED',
            ).distinct().select_related('patient', 'uploaded_by')
        elif user.role == 'PATIENT':
            return Document.objects.filter(patient__user=user).select_related('patient', 'uploaded_by')
        return Document.objects.none()

    def perform_create(self, serializer):
        user = self.request.user
        report_type = serializer.validated_data.get('report_type', 'ADDITIONAL')
        
        if user.role == 'PATIENT' and report_type == 'ADDITIONAL':
            doc = serializer.save(patient=user.patient_profile, uploaded_by=user, report_type='ADDITIONAL')
        elif user.role == 'ADMIN' and report_type == 'MEDICAL':
            doc = serializer.save(uploaded_by=user, report_type='MEDICAL')
        else:
            doc = serializer.save()
        
        log_activity(
            user,
            'UPLOAD_DOCUMENT',
            f"Uploaded {doc.report_type} document {doc.name} (type: {doc.file_type}) for Patient {doc.patient.patient_id}.",
            self.request
        )

    def perform_destroy(self, instance):
        user = self.request.user
        log_activity(
            user,
            'DELETE_DOCUMENT',
            f"Deleted {instance.report_type} document {instance.name} for Patient {instance.patient.patient_id}.",
            self.request
        )
        instance.delete()

    @action(detail=True, methods=['get'], url_path='download')
    def download(self, request, pk=None):
        doc = self.get_object()
        try:
            file_handle = doc.file.open('rb')
        except (FileNotFoundError, ValueError):
            raise Http404('The requested document file is no longer available.')
        response = FileResponse(file_handle, content_type='application/octet-stream')
        response['Content-Disposition'] = f'attachment; filename="{doc.name}"'
        return response
