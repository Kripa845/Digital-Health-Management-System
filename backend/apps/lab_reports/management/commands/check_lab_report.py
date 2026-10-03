"""Explain what the lab report reader sees in a file, without saving anything.

    python manage.py check_lab_report "C:\\path\\to\\report.pdf" --patient hari.tamang

Prints the text read from the file, the names, ages and dates found, the
identity check result for that patient, and the values that would be shown in
the preview. Output goes to this terminal only; nothing is stored or logged.
"""
import os

from django.core.management.base import BaseCommand, CommandError

from apps.lab_reports.extractor import extract_medical_fields
from apps.lab_reports.identity import extract_identity, find_name_in_text, verify_identity
from apps.lab_reports.ocr_service import extract_text_from_bytes
from apps.patients.models import Patient


class Command(BaseCommand):
    help = 'Show what the lab report reader finds in a file and why a patient would match or not.'

    def add_arguments(self, parser):
        parser.add_argument('path', help='PDF, PNG or JPG file')
        parser.add_argument('--patient', required=True, help="Patient's username or patient ID (PAT-…)")
        parser.add_argument('--hide-text', action='store_true', help='Do not print the text read from the file')

    def handle(self, *args, path, patient, hide_text, **options):
        try:
            p = Patient.objects.get(user__username__iexact=patient)
        except Patient.DoesNotExist:
            try:
                p = Patient.objects.get(patient_id__iexact=patient)
            except Patient.DoesNotExist:
                raise CommandError(f'No patient with username or ID "{patient}".')
        if not os.path.isfile(path):
            raise CommandError(f'File not found: {path}')

        with open(path, 'rb') as fh:
            raw = fh.read()
        try:
            text = extract_text_from_bytes(raw, os.path.splitext(path)[1])
        except (RuntimeError, ValueError) as exc:
            raise CommandError(f'The file could not be read: {exc}')

        out = self.stdout
        if not hide_text:
            out.write(self.style.MIGRATE_HEADING('Text read from the file'))
            for i, line in enumerate(text.splitlines(), 1):
                if line.strip():
                    out.write(f'  {i:>3} | {line}')

        found = extract_identity(text)
        full = ' '.join(filter(None, [p.first_name, p.middle_name, p.last_name]))
        out.write(self.style.MIGRATE_HEADING('\nIdentity'))
        out.write(f'  Patient on file     : {full} (born {p.dob})')
        out.write(f'  Names after a label : {found.strong_names or "none"}')
        out.write(f'  Names after "Name"  : {found.weak_names or "none"}')
        out.write(f'  Name found anywhere : {find_name_in_text(found.lines, p.first_name, p.last_name, p.middle_name or "")}')
        out.write(f'  Date of birth       : {found.dob or "none"}')
        out.write(f'  Report date         : {found.report_date or "none (upload date will be used)"}')

        result = verify_identity(found, p)
        if result.verified:
            out.write(self.style.SUCCESS('  Result              : MATCH'))
        else:
            out.write(self.style.ERROR(f'  Result              : NO MATCH: {result.reason}'))

        out.write(self.style.MIGRATE_HEADING('\nValues found'))
        fields = extract_medical_fields(text)
        if not fields:
            out.write('  none')
        for f in fields:
            out.write(f'  {f.field_name:24} {f.extracted_value} {f.unit}'.rstrip())
