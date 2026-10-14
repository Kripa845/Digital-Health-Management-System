from django.contrib import admin

from apps.doctors.models import (
    AccessRequest, Doctor, DoctorAssignment, DoctorLeave, DoctorSchedule, Prescription,
)


class DoctorScheduleInline(admin.TabularInline):
    model = DoctorSchedule
    extra = 0


class DoctorLeaveInline(admin.TabularInline):
    model = DoctorLeave
    extra = 0


@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    list_display = ('doctor_id', 'user', 'department', 'experience_years', 'license_number', 'status')
    list_filter = ('department', 'status')
    search_fields = ('doctor_id', 'license_number', 'user__first_name', 'user__last_name')
    readonly_fields = ('doctor_id', 'uuid_token', 'registration_date', 'availability_schedule')
    inlines = [DoctorScheduleInline, DoctorLeaveInline]

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        # The schedule rows were edited directly; refresh the JSON summary.
        form.instance.sync_json_from_schedules()


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
