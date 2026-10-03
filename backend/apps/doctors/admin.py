from django.contrib import admin

from apps.doctors.models import AccessRequest, Doctor, DoctorAssignment, Prescription


@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    list_display = ('doctor_id', 'user', 'department', 'license_number', 'status')
    list_filter = ('department', 'status')
    search_fields = ('doctor_id', 'license_number', 'user__first_name', 'user__last_name')
    readonly_fields = ('doctor_id', 'uuid_token', 'registration_date')


@admin.register(DoctorAssignment)
class DoctorAssignmentAdmin(admin.ModelAdmin):
    list_display = ('doctor', 'patient', 'status', 'assigned_date')
    list_filter = ('status',)


@admin.register(AccessRequest)
class AccessRequestAdmin(admin.ModelAdmin):
    list_display = ('doctor', 'patient', 'status', 'created_at', 'resolved_at', 'resolved_by')
    list_filter = ('status',)


@admin.register(Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    list_display = ('patient', 'doctor', 'prescription_date')
    search_fields = ('patient__patient_id', 'diagnosis')
