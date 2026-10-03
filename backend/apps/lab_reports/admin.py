from django.contrib import admin
from apps.lab_reports.models import LabReport, LabReportField


class LabReportFieldInline(admin.TabularInline):
    model = LabReportField
    extra = 0
    readonly_fields = (
        'field_name', 'patient_field', 'extracted_value',
        'previous_value', 'unit', 'reference_range', 'change_status',
    )
    can_delete = False


@admin.register(LabReport)
class LabReportAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'name', 'patient', 'file_type', 'status',
        'detected_count', 'updated_count', 'unchanged_count',
        'uploaded_by', 'uploaded_at',
    )
    list_filter = ('status', 'file_type', 'uploaded_at')
    search_fields = ('name', 'patient__patient_id', 'patient__first_name', 'patient__last_name')
    readonly_fields = (
        'file_type', 'size', 'uploaded_at', 'status', 'error_message',
        'detected_count', 'updated_count', 'unchanged_count', 'processed_at',
    )
    inlines = [LabReportFieldInline]
    ordering = ['-uploaded_at']


@admin.register(LabReportField)
class LabReportFieldAdmin(admin.ModelAdmin):
    list_display = ('id', 'report', 'field_name', 'extracted_value', 'previous_value', 'change_status')
    list_filter = ('change_status',)
    search_fields = ('field_name', 'report__patient__patient_id')
    readonly_fields = (
        'report', 'field_name', 'patient_field', 'extracted_value',
        'previous_value', 'unit', 'reference_range', 'change_status',
    )
