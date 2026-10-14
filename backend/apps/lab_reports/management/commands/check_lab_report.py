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
from apps.lab_reports.services import table_reader
from apps.lab_reports.services.ocr import UnreadableFile, read_document
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
        ext = os.path.splitext(path)[1].lower()
        try:
            ocr = read_document(raw, ext)
        except UnreadableFile as exc:
            raise CommandError(f'The file could not be read: {exc}')
        text = ocr.text
        if not text.strip():
            raise CommandError(f'The file could not be read: {ocr.ocr_error or "no text was found."}')

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

        table = table_reader.read_values(raw, ext, ocr)
        source = {'text_layer': "the PDF's own text", 'ocr': f'OCR ({ocr.confidence}% mean confidence)',
                  'mixed': f"the PDF's own text and OCR of its scanned pages ({ocr.confidence}% mean confidence)"}
        out.write(self.style.MIGRATE_HEADING('\nResults table'))
        out.write(f'  Read from           : {source.get(ocr.source, "nothing")}')
        out.write(f'  Table read as       : {table.method or "no table found"}')
        for f in table.values:
            value = f'{f.extracted_value} → {f.suggested_value}' if f.suggested_value else f.extracted_value
            conf = f'  [{f.ocr_confidence:.0f}%]' if f.ocr_confidence is not None and f.ocr_confidence < 100 else ''
            out.write(f'  {f.field_name:22} {value:>14} {f.unit:12} range: {f.reference_range or "not read":20}'
                      f' <- "{f.printed_name}"{conf}')
            for r in f.review_reasons:
                out.write(self.style.WARNING(f'      ! {r["message"]}'))
        for u in table.unmatched:
            out.write(self.style.ERROR(f'  NOT RECOGNISED: "{u["name"]}" {u["value"]} {u["unit"]} ({u["reason"]})'))

        out.write(self.style.MIGRATE_HEADING('\nFree-text values (used only for tests not in the table; need confirming)'))
        fields = extract_medical_fields(text)
        if not fields:
            out.write('  none')
        for f in fields:
            out.write(f'  {f.field_name:24} {f.extracted_value} {f.unit}'.rstrip())
