from rest_framework import serializers
from apps.documents.models import Document

class DocumentSerializer(serializers.ModelSerializer):
    patient_name = serializers.SerializerMethodField(read_only=True)
    patient_id_code = serializers.CharField(source='patient.patient_id', read_only=True)
    uploaded_by_name = serializers.CharField(source='uploaded_by.get_full_name', read_only=True)

    class Meta:
        model = Document
        fields = ('id', 'patient', 'patient_name', 'patient_id_code', 'file', 'name', 'file_type', 'size', 'uploaded_at', 'report_type', 'uploaded_by', 'uploaded_by_name')
        read_only_fields = ('id', 'file_type', 'size', 'uploaded_at', 'report_type', 'uploaded_by', 'uploaded_by_name')
        extra_kwargs = {'file': {'write_only': True}}

    def validate(self, attrs):
        # A document stays on the patient record it was uploaded to.
        if self.instance is not None and 'patient' in attrs and attrs['patient'] != self.instance.patient:
            raise serializers.ValidationError({'patient': 'A document cannot be moved to another patient.'})
        return attrs

    def get_patient_name(self, obj):
        return f"{obj.patient.first_name} {obj.patient.last_name}"
