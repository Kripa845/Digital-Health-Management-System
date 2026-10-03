from django.contrib import admin

from apps.documents.models import Document


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ('name', 'patient', 'report_type', 'file_type', 'uploaded_by', 'uploaded_at')
    list_filter = ('report_type', 'file_type')
    search_fields = ('name', 'patient__patient_id')
