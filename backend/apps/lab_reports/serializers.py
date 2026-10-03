import os

from rest_framework import serializers
from apps.lab_reports.models import LabReport, LabReportField

# File signatures, so a renamed file (e.g. an .exe called report.pdf) is refused.
_SIGNATURES = {
    '.pdf': (b'%PDF-',),
    '.png': (b'\x89PNG\r\n\x1a\n',),
    '.jpg': (b'\xff\xd8\xff',),
    '.jpeg': (b'\xff\xd8\xff',),
}


class LabReportFieldSerializer(serializers.ModelSerializer):
    class Meta:
        model = LabReportField
        fields = (
            'id',
            'field_name',
            'patient_field',
            'extracted_value',
            'unit',
            'converted_value',
            'converted_unit',
            'previous_value',
            'reference_range',
            'change_status',
            'skip_reason',
            'flag',
        )
        read_only_fields = fields


class LabReportSerializer(serializers.ModelSerializer):

    fields = LabReportFieldSerializer(many=True, read_only=True)

    patient_name = serializers.SerializerMethodField(read_only=True)
    patient_id_code = serializers.CharField(source='patient.patient_id', read_only=True)
    uploaded_by_name = serializers.SerializerMethodField(read_only=True)
    confirmed_by_name = serializers.SerializerMethodField(read_only=True)
    review_messages = serializers.SerializerMethodField(read_only=True)
    extracted = serializers.SerializerMethodField(read_only=True)

    detected_fields = serializers.SerializerMethodField(read_only=True)
    updated_fields = serializers.SerializerMethodField(read_only=True)
    unchanged_fields = serializers.SerializerMethodField(read_only=True)
    skipped_fields = serializers.SerializerMethodField(read_only=True)

    # Report date ordering check (services/date_check.py), worked out live for reports
    # that are not confirmed yet; null for confirmed or rejected reports.
    date_check_status = serializers.SerializerMethodField(read_only=True)
    latest_report_date = serializers.SerializerMethodField(read_only=True)
    date_message = serializers.SerializerMethodField(read_only=True)
    date_ack_required = serializers.SerializerMethodField(read_only=True)
    # No health card values were found: the report can be kept as a document only.
    can_save_without_values = serializers.SerializerMethodField(read_only=True)
    no_values_message = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = LabReport
        # The report's text and stored file path are never returned; the
        # original is available only through the authenticated download action.
        fields = (
            'id',
            'patient',
            'patient_name',
            'patient_id_code',
            'name',
            'file_type',
            'size',
            'uploaded_by',
            'uploaded_by_name',
            'uploaded_at',
            'report_date',
            'report_date_source',
            'report_date_user_entered',
            'date_check_status',
            'latest_report_date',
            'date_message',
            'date_ack_required',
            'can_save_without_values',
            'no_values_message',
            'identity_verified',
            'status',
            'error_message',
            'detected_count',
            'updated_count',
            'unchanged_count',
            'processed_at',
            'confirmed_at',
            'confirmed_by_name',
            'ocr_confidence',
            'review_reasons',
            'review_messages',
            'review_note',
            'reviewed_at',
            'extracted',
            # nested
            'fields',
            # computed groupings
            'detected_fields',
            'updated_fields',
            'unchanged_fields',
            'skipped_fields',
        )
        read_only_fields = fields

    def get_patient_name(self, obj):
        return f"{obj.patient.first_name} {obj.patient.last_name}"

    def get_uploaded_by_name(self, obj):
        return _display_name(obj.uploaded_by)

    def get_confirmed_by_name(self, obj):
        return _display_name(obj.confirmed_by)

    def _date_check(self, obj):
        if obj.status not in (LabReport.Status.PENDING_CONFIRMATION, LabReport.Status.NEEDS_REVIEW,
                              LabReport.Status.NO_VALUES_SAVEABLE):
            return None
        if not hasattr(obj, '_date_check'):
            from apps.lab_reports.services.date_check import evaluate_report
            obj._date_check = evaluate_report(obj)
        return obj._date_check

    def get_date_check_status(self, obj):
        check = self._date_check(obj)
        return check.status if check else None

    def get_latest_report_date(self, obj):
        check = self._date_check(obj)
        return check.latest_date.isoformat() if check and check.latest_date else None

    def get_date_message(self, obj):
        check = self._date_check(obj)
        return check.message if check else ''

    def get_date_ack_required(self, obj):
        check = self._date_check(obj)
        return bool(check and check.ack_required)

    def get_can_save_without_values(self, obj):
        return obj.status == LabReport.Status.NO_VALUES_SAVEABLE

    def get_no_values_message(self, obj):
        if obj.status != LabReport.Status.NO_VALUES_SAVEABLE:
            return ''
        from apps.lab_reports.services.upload import NO_VALUES_MESSAGE
        return NO_VALUES_MESSAGE

    def get_review_messages(self, obj):
        from apps.lab_reports.services.verifier import REASON_MESSAGES
        return [REASON_MESSAGES.get(code, code) for code in obj.review_reasons or []]

    def get_extracted(self, obj):
        # Values only. Identity details read from the report (name, date of
        # birth, ID) are shown to admins in the review queue, not here.
        data = obj.extracted_json or {}
        return {k: data.get(k) for k in ('report_date', 'blood_group', 'tests', 'other_tests')}

    def get_detected_fields(self, obj):
        return LabReportFieldSerializer(obj.fields.all(), many=True).data

    def get_updated_fields(self, obj):
        return self._with_status(obj, LabReportField.ChangeStatus.UPDATED, LabReportField.ChangeStatus.INSERTED)

    def get_unchanged_fields(self, obj):
        return self._with_status(obj, LabReportField.ChangeStatus.UNCHANGED)

    def get_skipped_fields(self, obj):
        return self._with_status(obj, LabReportField.ChangeStatus.SKIPPED)

    @staticmethod
    def _with_status(obj, *statuses):
        rows = [f for f in obj.fields.all() if f.change_status in statuses]
        return LabReportFieldSerializer(rows, many=True).data


def _display_name(user):
    if user is None:
        return None
    name = user.get_full_name()
    return name if name.strip() else user.username


class LabReportUploadSerializer(serializers.ModelSerializer):

    class Meta:
        model = LabReport
        fields = ('patient', 'file', 'name')

    def validate_file(self, value):
        ext = os.path.splitext(value.name)[1].lower()
        if ext not in _SIGNATURES:
            raise serializers.ValidationError(
                'Unsupported file type. Allowed formats: PDF, PNG, JPG, JPEG.'
            )
        if value.size > 10 * 1024 * 1024:
            raise serializers.ValidationError('File size exceeds the 10 MB limit.')
        if value.size == 0:
            raise serializers.ValidationError('The file is empty.')
        head = value.read(16)
        value.seek(0)
        if not head.startswith(_SIGNATURES[ext]):
            raise serializers.ValidationError(
                f'This file is not a valid {ext.lstrip(".").upper()} file. It may be damaged or renamed.'
            )
        return value

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Report name cannot be blank.')
        if len(value) > 255:
            raise serializers.ValidationError('Report name cannot exceed 255 characters.')
        return value


class AdminReviewSerializer(LabReportSerializer):
    """For the admin review queue: includes what was read from the report's
    header (masked patient ID, name, date of birth, age)."""
    identity = serializers.SerializerMethodField(read_only=True)

    class Meta(LabReportSerializer.Meta):
        fields = LabReportSerializer.Meta.fields + ('identity',)
        read_only_fields = fields

    def get_identity(self, obj):
        data = obj.extracted_json or {}
        return {k: data.get(k) for k in ('patient_id', 'name', 'dob', 'age')}


class ConfirmSerializer(serializers.Serializer):
    """POST /reports/{id}/confirm/: optional corrections and accepted flags."""
    values = serializers.DictField(child=serializers.CharField(allow_blank=False, max_length=32),
                                   required=False, default=dict)
    accept_flagged = serializers.ListField(child=serializers.CharField(max_length=50),
                                           required=False, default=list)
    # Required (true) to confirm a report older than the latest confirmed one (policy "warn").
    acknowledge_older_report = serializers.BooleanField(required=False, default=False)


class ReportDateSerializer(serializers.Serializer):
    """POST /reports/{id}/report-date/: the report date typed or corrected in the preview."""
    report_date = serializers.DateField()


class ResolveSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=('approve', 'reject'))
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000, default='')
