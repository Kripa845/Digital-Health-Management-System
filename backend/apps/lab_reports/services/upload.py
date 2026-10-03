"""The upload pipeline: file checks → text → extraction → identity gate → preview.

Text comes from the PDF's own text layer, or OCR of the page images (scans and
photos). If no usable dashboard value is found that way and the optional AI
fallback is on (LAB_LLM_FALLBACK), the page images are read by Claude instead.

Nothing is written to the patient record here; a report only becomes a
preview (PENDING_CONFIRMATION) or goes to an admin (NEEDS_REVIEW). A report
whose patient ID belongs to someone else is not stored at all.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import timedelta
from dataclasses import dataclass, field

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status

from apps.audit.utils import log_activity
from apps.lab_reports import crypto
from apps.lab_reports.cdsa import DASHBOARD_FIELDS
from apps.lab_reports.models import LabReport
from apps.lab_reports.services import files
from apps.lab_reports.services.dashboard import build_preview
from apps.lab_reports.services import date_check, llm
from apps.lab_reports.services import validator as v
from apps.lab_reports.services.extractor import extract_report, find_patient_ids
from apps.lab_reports.services.ocr import UnreadableFile, read_document
from apps.lab_reports.services.verifier import (
    LOW_OCR_CONFIDENCE, MISMATCH_MESSAGE, PASS, REJECT, REVIEW, mask_id, verify,
)
from apps.notifications.models import Notification

logger = logging.getLogger(__name__)

NO_VALUES_MESSAGE = ('No health card values were found. You can save this report as a document only. '
                     'Dashboard values will not change.')
VALUES_NOT_USABLE_MESSAGE = ('Values were found on this report, but none could be used: they are outside the '
                             'expected ranges or could not be read. Nothing was saved. Check the report, or '
                             'enter the values in the patient record.')
# Unconfirmed previews (and their encrypted files) are deleted after this long.
PREVIEW_LIFETIME = timedelta(hours=24)


class UploadError(Exception):
    def __init__(self, code: str, message: str, http_status: int, **extra):
        super().__init__(message)
        self.code, self.message, self.http_status, self.extra = code, message, http_status, extra


@dataclass
class UploadOutcome:
    report: LabReport
    review_reasons: list[str] = field(default_factory=list)


def _validated_bytes(uploaded) -> tuple[bytes, str]:
    ext = os.path.splitext(uploaded.name or '')[1].lower()
    if ext not in files.ALLOWED_TYPES:
        raise UploadError('invalid_file', 'Only PDF, PNG or JPG files are accepted.', status.HTTP_400_BAD_REQUEST)
    if uploaded.size > files.MAX_UPLOAD_BYTES:
        raise UploadError('file_too_large', 'The file is larger than 10 MB.', status.HTTP_400_BAD_REQUEST)
    raw = uploaded.read()
    if not raw:
        raise UploadError('invalid_file', 'The file is empty.', status.HTTP_400_BAD_REQUEST)
    if files.detect_type(raw) != files.ALLOWED_TYPES[ext]:
        raise UploadError('invalid_file',
                          f'This is not a valid {ext.lstrip(".").upper()} file. It may be damaged or renamed.',
                          status.HTTP_400_BAD_REQUEST)
    return raw, ext


def _usable(values) -> list:
    """Values that could be saved: not dropped as invalid, out of range (main tests) or in an unknown unit."""
    return [x for x in values if v.is_usable(x.patient_field, x.extracted_value, x.unit)]


def _read(raw: bytes, ext: str, patient):
    try:
        ocr = read_document(raw, ext)
    except UnreadableFile as exc:
        raise UploadError('unreadable', f'This file could not be read. {exc}', status.HTTP_400_BAD_REQUEST)
    extracted = extract_report(ocr.text)
    values = [x for x in extracted.values if x.patient_field in DASHBOARD_FIELDS]
    values_from = 'regex'
    tried_llm = False

    if not _usable(values) and llm.enabled() and ocr.page_images:
        tried_llm = True
        reading = llm.read_values(ocr.page_images)
        if reading and reading.values:
            read = {x.patient_field for x in reading.values}
            values = reading.values + [x for x in values if x.patient_field not in read]
            extracted.values = values + [x for x in extracted.values if x.patient_field not in DASHBOARD_FIELDS]
            if reading.patient_id:
                card_ids, other_ids = find_patient_ids(f'Patient ID: {reading.patient_id}')
                extracted.card_ids = list(dict.fromkeys(extracted.card_ids + card_ids))
                extracted.other_ids = list(dict.fromkeys(extracted.other_ids + other_ids))
            values_from = 'llm'

    # An empty text (blank or unreadable scan) no longer stops the upload: with no
    # values and no identity, the report can still be saved as an unverified document.
    if not ocr.text.strip():
        logger.info('Lab report text empty: ocr_error=%s', bool(ocr.ocr_error))

    # Method and sizes only: never names, IDs or values.
    logger.info('Lab report read: source=%s text_length=%d values_from=%s values=%d usable=%d',
                ocr.source or 'none', len(ocr.text), values_from, len(values), len(_usable(values)))
    gate = verify(extracted, patient, ocr.confidence)
    return ocr, extracted, gate, values, values_from


def process_upload(patient, uploaded, name: str, user, request=None) -> UploadOutcome:
    patient = patient.__class__.objects.get(pk=patient.pk)   # fresh from the database
    raw, ext = _validated_bytes(uploaded)
    file_hash = files.sha256(raw)
    if LabReport.objects.filter(patient=patient, file_hash=file_hash).exists():
        raise UploadError('duplicate', 'This file has already been uploaded for this patient.',
                          status.HTTP_409_CONFLICT)

    ocr, extracted, gate, values, values_from = _read(raw, ext, patient)

    if gate.outcome == REJECT:
        # Nothing is stored. The attempt is audited with masked IDs only.
        log_activity(user, 'REJECT_LAB_REPORT',
                     f'Lab report upload for patient {patient.patient_id} rejected: the patient ID on the report '
                     f'({", ".join(mask_id(i) for i in extracted.card_ids)}) does not match.', request)
        raise UploadError('patient_id_mismatch', MISMATCH_MESSAGE, status.HTTP_422_UNPROCESSABLE_ENTITY)

    # Values were found, but every one failed the range or unit checks: not the
    # "no values" case, and never silently saved as a document.
    if values and not _usable(values):
        log_activity(user, 'REJECT_LAB_REPORT',
                     f'Lab report upload for patient {patient.patient_id} rejected: values found but none usable.',
                     request)
        raise UploadError('values_not_usable', VALUES_NOT_USABLE_MESSAGE, status.HTTP_422_UNPROCESSABLE_ENTITY)
    no_values = not values

    # Report date ordering (after the identity check; never for another patient's report).
    dates = date_check.evaluate(patient, extracted.report_date)
    logger.info('Lab report date check: status=%s policy=%s', dates.status, dates.policy)   # never the dates
    if dates.blocked:
        log_activity(user, 'REJECT_LAB_REPORT',
                     f'Lab report upload for patient {patient.patient_id} rejected: it is older than the '
                     'latest confirmed report.', request)
        raise UploadError('older_report', f'{dates.message} It was not uploaded.',
                          status.HTTP_422_UNPROCESSABLE_ENTITY)

    needs_review = gate.outcome == REVIEW
    if no_values and needs_review and _unreadable_identity(extracted, ocr):
        # Nothing to verify against (no ID, name or date of birth, and an empty or
        # poor scan): the user may still keep it as a document, marked unverified.
        needs_review = False
    if needs_review:
        new_status = LabReport.Status.NEEDS_REVIEW
    elif no_values:
        new_status = LabReport.Status.NO_VALUES_SAVEABLE
    else:
        new_status = LabReport.Status.PENDING_CONFIRMATION
    logger.info('Lab report upload outcome: status=%s', new_status)          # never names, IDs or values
    try:
        with transaction.atomic():
            report = LabReport(
                patient=patient,
                name=files.safe_display_name(name or uploaded.name),
                uploaded_by=user,
                status=new_status,
                identity_verified=gate.outcome == PASS,
                review_reasons=gate.reasons,
                report_date=extracted.report_date,
                report_date_source=extracted.report_date_source,
                file_type=ext.lstrip('.').upper(),
                size=len(raw),
                file_hash=file_hash,
                is_encrypted=True,
                extracted_json=extracted.to_json(),
                ocr_confidence=ocr.confidence,
            )
            report.file.save(f'{uuid.uuid4().hex}.enc', ContentFile(crypto.encrypt(raw)), save=False)
            report.save()
            build_preview(report, values)
    except IntegrityError:
        raise UploadError('duplicate', 'This file has already been uploaded for this patient.',
                          status.HTTP_409_CONFLICT)

    log_activity(user, 'UPLOAD_LAB_REPORT',
                 f'Uploaded lab report {report.id} ({report.file_type}) for patient {patient.patient_id}: '
                 + (f'sent for review ({", ".join(gate.reasons)}).' if needs_review
                    else 'no health card values found; can be saved as a document'
                    + ('' if gate.outcome == PASS else ' (identity not verified)') + '.'
                    if no_values else 'identity verified, awaiting confirmation.')
                 + (' Values were read by the AI fallback.' if values_from == 'llm' else ''),
                 request)
    if needs_review:
        for admin in get_user_model().objects.filter(role='ADMIN', is_active=True):
            Notification.objects.create(
                receiver=admin, role='ADMIN', title='Lab Report Needs Review',
                message=f'A lab report for patient {patient.patient_id} could not be verified automatically.',
            )
    return UploadOutcome(report, gate.reasons)


def _unreadable_identity(extracted, ocr) -> bool:
    """No ID, name or date of birth on the report, and an empty or low-confidence scan."""
    identity = extracted.identity
    nothing = not (extracted.card_ids or extracted.other_ids or (identity and (identity.name or identity.dob)))
    poor = not ocr.text.strip() or (ocr.confidence is not None and ocr.confidence < LOW_OCR_CONFIDENCE)
    return nothing and poor


def purge_stale_previews(older_than: timedelta = PREVIEW_LIFETIME) -> int:
    """Delete previews never confirmed or saved (and their encrypted files) after ``older_than``."""
    cutoff = timezone.now() - older_than
    stale = LabReport.objects.filter(
        status__in=(LabReport.Status.PENDING_CONFIRMATION, LabReport.Status.NO_VALUES_SAVEABLE),
        uploaded_at__lt=cutoff,
    )
    count = 0
    for report in stale:
        report.delete()            # the post_delete signal removes the stored file
        count += 1
    logger.info('Purged %d unconfirmed lab report preview(s).', count)
    return count


def stored_bytes(report: LabReport) -> bytes:
    with report.file.open('rb') as fh:
        data = fh.read()
    return crypto.decrypt(data) if report.is_encrypted else data


def reprocess(report: LabReport, user, request=None) -> LabReport:
    """Admin: read a stored report again and rebuild its preview."""
    if not report.file:
        raise UploadError('no_file', 'The original file of this report is no longer stored.', status.HTTP_400_BAD_REQUEST)
    if report.status in (LabReport.Status.CONFIRMED, LabReport.Status.SAVED_NO_VALUES):
        raise UploadError('already_confirmed', 'This report has already been applied. Upload it again to re-read it.',
                          status.HTTP_409_CONFLICT)
    ocr, extracted, gate, values, _ = _read(stored_bytes(report), f'.{report.file_type.lower()}', report.patient)
    if gate.outcome == REJECT:
        raise UploadError('patient_id_mismatch', MISMATCH_MESSAGE, status.HTTP_422_UNPROCESSABLE_ENTITY)
    if values and not _usable(values):
        raise UploadError('values_not_usable', VALUES_NOT_USABLE_MESSAGE, status.HTTP_422_UNPROCESSABLE_ENTITY)
    needs_review = gate.outcome == REVIEW and not (not values and _unreadable_identity(extracted, ocr))
    with transaction.atomic():
        if needs_review:
            report.status = LabReport.Status.NEEDS_REVIEW
        elif not values:
            report.status = LabReport.Status.NO_VALUES_SAVEABLE
        else:
            report.status = LabReport.Status.PENDING_CONFIRMATION
        report.identity_verified = gate.outcome == PASS
        report.review_reasons = gate.reasons
        if not report.report_date_user_entered:      # keep a date the user typed
            report.report_date = extracted.report_date
            report.report_date_source = extracted.report_date_source
        report.extracted_json = extracted.to_json()
        report.ocr_confidence = ocr.confidence
        report.error_message = ''
        report.save()
        build_preview(report, values)
    log_activity(user, 'REPROCESS_LAB_REPORT', f'Re-read lab report {report.id} for patient {report.patient.patient_id}.',
                 request)
    return report
