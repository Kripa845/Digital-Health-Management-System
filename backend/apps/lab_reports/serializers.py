
from rest_framework import serializers
from apps.lab_reports.models import LabReport, LabReportField


class LabReportFieldSerializer(serializers.ModelSerializer):
    class Meta:
        model = LabReportField
        fields = (
            'id',
            'field_name',
            'patient_field',
            'extracted_value',
            'previous_value',
            'unit',
            'reference_range',
            'change_status',
        )
        read_only_fields = fields


class LabReportSerializer(serializers.ModelSerializer):


    fields = LabReportFieldSerializer(many=True, read_only=True)

    patient_name = serializers.SerializerMethodField(read_only=True)
    patient_id_code = serializers.CharField(source='patient.patient_id', read_only=True)
    uploaded_by_name = serializers.SerializerMethodField(read_only=True)

    
    detected_fields = serializers.SerializerMethodField(read_only=True)
    updated_fields = serializers.SerializerMethodField(read_only=True)
    unchanged_fields = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = LabReport
        fields = (
            'id',
            'patient',
            'patient_name',
            'patient_id_code',
            'file',
            'name',
            'file_type',
            'size',
            'uploaded_by',
            'uploaded_by_name',
            'uploaded_at',
            'status',
            'error_message',
            'ocr_text',
            'detected_count',
            'updated_count',
            'unchanged_count',
            'processed_at',
            # nested
            'fields',
            # computed groupings
            'detected_fields',
            'updated_fields',
            'unchanged_fields',
        )
        read_only_fields = (
            'id', 'file_type', 'size', 'uploaded_at',
            'status', 'error_message', 'ocr_text',
            'detected_count', 'updated_count', 'unchanged_count',
            'processed_at',
        )

    def get_patient_name(self, obj):
        return f"{obj.patient.first_name} {obj.patient.last_name}"

    def get_uploaded_by_name(self, obj):
        if obj.uploaded_by:
            name = obj.uploaded_by.get_full_name()
            return name if name.strip() else obj.uploaded_by.username
        return None

    def get_detected_fields(self, obj):
        all_fields = obj.fields.all()
        return LabReportFieldSerializer(all_fields, many=True).data

    def get_updated_fields(self, obj):
        qs = obj.fields.filter(
            change_status__in=[
                LabReportField.ChangeStatus.UPDATED,
                LabReportField.ChangeStatus.INSERTED,
            ]
        )
        return LabReportFieldSerializer(qs, many=True).data

    def get_unchanged_fields(self, obj):
        qs = obj.fields.filter(change_status=LabReportField.ChangeStatus.UNCHANGED)
        return LabReportFieldSerializer(qs, many=True).data


class LabReportUploadSerializer(serializers.ModelSerializer):
  

    class Meta:
        model = LabReport
        fields = ('patient', 'file', 'name')

    def validate_file(self, value):
        import os
        ext = os.path.splitext(value.name)[1].lower()
        allowed = ['.pdf', '.png', '.jpg', '.jpeg']
        if ext not in allowed:
            raise serializers.ValidationError(
                'Unsupported file type. Allowed formats: PDF, PNG, JPG, JPEG.'
            )
        if value.size > 10 * 1024 * 1024:
            raise serializers.ValidationError('File size exceeds the 10 MB limit.')
        return value

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Report name cannot be blank.')
        if len(value) > 255:
            raise serializers.ValidationError('Report name cannot exceed 255 characters.')
        return value
