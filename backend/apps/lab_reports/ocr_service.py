"""
OCR Service for Lab Report Processing
--------------------------------------
Extracts raw text from uploaded PDF, JPG, JPEG, and PNG lab reports.

The service uses a graceful fallback chain:
  1. pytesseract  (local Tesseract OCR)
  2. pdf2image    (converts PDF pages to images before OCR)

All OCR libraries are imported LAZILY inside each function so that a missing
installation does NOT crash the server at startup — the error only surfaces
when a lab report is actually uploaded and the view catches it gracefully.

The original file is NEVER modified.  All operations are read-only.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_text_from_file(file_field) -> str:
    """
    Accept a Django FieldFile (or anything with a .name and readable bytes)
    and return the OCR-extracted text as a plain string.

    Raises
    ------
    RuntimeError  – OCR library missing, Tesseract not installed, or extraction failed.
    ValueError    – Unsupported file extension.
    """
    name: str = file_field.name or ''
    ext = Path(name).suffix.lower()

    try:
        file_field.seek(0)
        raw_bytes: bytes = file_field.read()
    except Exception as exc:
        raise RuntimeError(f'Could not read the uploaded file: {exc}') from exc

    if ext == '.pdf':
        return _ocr_pdf(raw_bytes)
    elif ext in ('.jpg', '.jpeg', '.png'):
        return _ocr_image(raw_bytes)
    else:
        raise ValueError(f'Unsupported file extension "{ext}". Allowed: PDF, JPG, JPEG, PNG.')


# ---------------------------------------------------------------------------
# Internal helpers – all imports are lazy
# ---------------------------------------------------------------------------

def _get_tesseract():
    """
    Lazily import pytesseract and verify Tesseract binary is reachable.
    Raises RuntimeError with a clear install hint if anything is missing.
    """
    try:
        import pytesseract  # noqa: PLC0415
    except ImportError:
        raise RuntimeError(
            'pytesseract is not installed. '
            'Run:  pip install pytesseract  '
            'and install Tesseract-OCR from https://github.com/UB-Mannheim/tesseract/wiki'
        )

    # On Windows, help pytesseract find the binary automatically.
    import os, shutil
    if os.name == 'nt':
        common = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
        if os.path.isfile(common):
            pytesseract.pytesseract.tesseract_cmd = common
        elif not shutil.which('tesseract'):
            raise RuntimeError(
                'Tesseract-OCR binary not found. '
                'Download and install it from https://github.com/UB-Mannheim/tesseract/wiki '
                'then restart the Django server.'
            )

    # Quick smoke-test: calling get_tesseract_version() will throw if the binary is missing.
    try:
        pytesseract.get_tesseract_version()
    except pytesseract.TesseractNotFoundError as exc:
        raise RuntimeError(
            f'Tesseract-OCR binary not found or not in PATH: {exc}. '
            'Install Tesseract from https://github.com/UB-Mannheim/tesseract/wiki'
        ) from exc

    return pytesseract


def _get_pil():
    """Lazily import Pillow Image."""
    try:
        from PIL import Image  # noqa: PLC0415
        return Image
    except ImportError:
        raise RuntimeError('Pillow is not installed. Run: pip install Pillow')


def _get_pdf2image():
    """Lazily import pdf2image."""
    try:
        from pdf2image import convert_from_bytes  # noqa: PLC0415
        return convert_from_bytes
    except ImportError:
        raise RuntimeError(
            'pdf2image is not installed. '
            'Run: pip install pdf2image  '
            'and install poppler from https://github.com/oschwartz10612/poppler-windows/releases/'
        )


def _ocr_image(raw_bytes: bytes) -> str:
    """Run OCR on a raw image byte-string."""
    pytesseract = _get_tesseract()
    Image = _get_pil()

    try:
        img = Image.open(io.BytesIO(raw_bytes))
        # Convert to RGB to avoid mode issues with RGBA / palette images
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        text = pytesseract.image_to_string(img, lang='eng', config='--psm 6')
        return text.strip()
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f'Image OCR failed: {exc}') from exc


def _ocr_pdf(raw_bytes: bytes) -> str:
    """Convert each PDF page to an image and run OCR on it."""
    convert_from_bytes = _get_pdf2image()
    pytesseract = _get_tesseract()
    Image = _get_pil()

    try:
        pages = convert_from_bytes(raw_bytes, dpi=300)
    except Exception as exc:
        raise RuntimeError(f'PDF to image conversion failed: {exc}') from exc

    if not pages:
        raise RuntimeError('The PDF appears to be empty (no pages found).')

    page_texts: list[str] = []
    for i, page in enumerate(pages, start=1):
        try:
            text = pytesseract.image_to_string(page, lang='eng', config='--psm 6')
            page_texts.append(text.strip())
        except Exception as exc:
            logger.warning('OCR failed on PDF page %d: %s', i, exc)

    combined = '\n\n'.join(filter(None, page_texts))
    if not combined.strip():
        raise RuntimeError(
            'OCR extracted no text from the PDF. '
            'The scan may be too blurry, low-resolution, or the file may be empty.'
        )
    return combined
