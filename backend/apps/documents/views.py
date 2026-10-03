import os

from django.http import FileResponse, Http404
from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from django_filters.rest_framework import DjangoFilterBackend
from apps.documents.models import Document
from apps.documents.serializers import DocumentSerializer
from apps.audit.utils import log_activity
from apps.doctors.access import doctor_access_filters, doctor_can_access


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
            return request.user.role in ('ADMIN', 'PATIENT')

        return True

    def has_object_permission(self, request, view, obj):
        user = request.user

        # Rows are already limited to what the user may see by get_queryset.
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
            return doctor_can_access(user, obj.patient)

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

        qs = Document.objects.select_related('patient', 'uploaded_by')
        if user.role == 'ADMIN':
            return qs.all()
        elif user.role == 'DOCTOR':
            return qs.filter(*doctor_access_filters(user, 'patient'))
        elif user.role == 'PATIENT':
            return qs.filter(patient__user=user)
        return Document.objects.none()

    def perform_create(self, serializer):
        user = self.request.user
        # report_type is read-only on the serializer (clients cannot set it on
        # update), so the requested type is read from the request here.
        # DocumentPermission has already checked that this role may use it.
        report_type = self.request.data.get('report_type', 'ADDITIONAL')

        if user.role == 'PATIENT':
            doc = serializer.save(patient=user.patient_profile, uploaded_by=user, report_type='ADDITIONAL')
        elif report_type == 'MEDICAL':
            doc = serializer.save(uploaded_by=user, report_type='MEDICAL')
        else:
            doc = serializer.save(uploaded_by=user, report_type='ADDITIONAL')

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
        ext = os.path.splitext(doc.file.name or '')[1]
        filename = doc.name if doc.name.lower().endswith(ext.lower()) else f'{doc.name}{ext}'
        return FileResponse(
            file_handle,
            as_attachment=True,
            filename=filename,
            content_type='application/octet-stream',
        )
