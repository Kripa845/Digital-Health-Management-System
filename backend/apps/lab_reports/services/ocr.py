"""Thin wrapper around the project's existing OCR (apps/lab_reports/ocr_service.py)."""
from dataclasses import dataclass, field

from apps.lab_reports.ocr_service import read_report_file


class UnreadableFile(Exception):
    """The file could not be read (damaged, encrypted PDF, unsupported type)."""


@dataclass
class OcrResult:
    text: str
    confidence: float | None    # 0–100; selectable PDF text counts as 100; None when nothing was read
    page_images: list[bytes] = field(default_factory=list, repr=False)   # for the optional AI fallback
    source: str = 'ocr'         # 'text_layer', 'ocr' or '' (no text)
    ocr_error: str = ''         # why there is no text, when there is none


def read_document(raw: bytes, ext: str) -> OcrResult:
    try:
        doc = read_report_file(raw, ext)
    except (RuntimeError, ValueError) as exc:
        raise UnreadableFile(str(exc)) from exc
    return OcrResult(doc.text or '', doc.confidence, doc.page_images, doc.source, doc.ocr_error)
