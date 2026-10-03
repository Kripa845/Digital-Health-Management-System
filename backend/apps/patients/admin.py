from django.contrib import admin

from apps.patients.models import Patient


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ('patient_id', 'first_name', 'last_name', 'gender', 'blood_group', 'status', 'registration_date')
    list_filter = ('status', 'gender', 'blood_group')
    search_fields = ('patient_id', 'first_name', 'last_name', 'phone')
    readonly_fields = ('uuid_token', 'registration_date', 'last_updated')
