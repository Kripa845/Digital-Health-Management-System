from __future__ import annotations

import io
import logging
import os
import re
from pathlib import Path

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter

logger = logging.getLogger(__name__)


# ── Configuration ────────────────────────────────────────────────────────────

TESSERACT_CMD = os.environ.get('TESSERACT_CMD', '').strip()
POPPLER_PATH = os.environ.get('POPPLER_PATH', '').strip()

if TESSERACT_CMD and Path(TESSERACT_CMD).is_file():
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
elif os.name == 'nt':
    default = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    if Path(default).is_file():
        pytesseract.pytesseract.tesseract_cmd = default


# ── Public API ───────────────────────────────────────────────────────────────

def extract_text_from_file(file_field) -> str:
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
        raise ValueError(
            f'Unsupported file extension "{ext}". Allowed: PDF, JPG, JPEG, PNG.'
        )


# ── Image preprocessing ──────────────────────────────────────────────────────

def preprocess_image(img: Image.Image) -> Image.Image:
    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')

    img = img.convert('L')

    w, h = img.size
    if w < 1200 or h < 1200:
        scale = max(1200 / w, 1200 / h, 1.5)
        new_w, new_h = int(w * scale), int(h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)

    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.8)

    enhancer = ImageEnhance.Sharpness(img)
    img = enhancer.enhance(2.0)

    img = img.filter(ImageFilter.MedianFilter(size=3))

    img = img.point(lambda p: 255 if p > 180 else 0)

    return img


# ── OCR helpers ──────────────────────────────────────────────────────────────

def _run_ocr_on_image(img: Image.Image) -> str:
    psm_modes = ['6', '3', '4', '11', '12']
    best_text = ''
    best_len = 0

    for psm in psm_modes:
        try:
            text = pytesseract.image_to_string(
                img, lang='eng', config=f'--psm {psm}'
            ).strip()
            if len(text) > best_len:
                best_text = text
                best_len = len(text)
        except Exception as exc:
            logger.warning('Tesseract PSM %s failed: %s', psm, exc)

    if not best_text:
        raise RuntimeError('Tesseract returned empty text for the image.')
    return best_text


def _ocr_image(raw_bytes: bytes) -> str:
    try:
        img = Image.open(io.BytesIO(raw_bytes))
    except Exception as exc:
        raise RuntimeError(f'Could not open image file: {exc}') from exc

    try:
        processed = preprocess_image(img)
        text = _run_ocr_on_image(processed)
        logger.info('OCR image complete: %d characters', len(text))
        return text
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f'Image OCR failed: {exc}') from exc


def _extract_text_from_pdf_direct(raw_bytes: bytes) -> str | None:
    try:
        from pdfminer.high_level import extract_text
        text = extract_text(io.BytesIO(raw_bytes))
        cleaned = re.sub(r'\s+', ' ', text).strip()
        if len(cleaned) > 200:
            logger.info('Extracted %d chars of selectable PDF text', len(cleaned))
            return text
    except Exception as exc:
        logger.info('Direct PDF text extraction failed: %s', exc)
    return None


def _ocr_pdf(raw_bytes: bytes) -> str:
    direct_text = _extract_text_from_pdf_direct(raw_bytes)
    if direct_text:
        return direct_text

    try:
        from pdf2image import convert_from_bytes
    except ImportError:
        raise RuntimeError(
            'pdf2image is not installed. '
            'Run: pip install pdf2image  '
            'and install poppler from https://github.com/oschwartz10612/poppler-windows/releases/'
        )

    try:
        pages = convert_from_bytes(
            raw_bytes,
            dpi=300,
            poppler_path=POPPLER_PATH if POPPLER_PATH else None,
        )
    except Exception as exc:
        raise RuntimeError(f'PDF to image conversion failed: {exc}') from exc

    if not pages:
        raise RuntimeError('The PDF appears to be empty (no pages found).')

    page_texts: list[str] = []
    for i, page in enumerate(pages, start=1):
        try:
            processed = preprocess_image(page)
            text = _run_ocr_on_image(processed)
            page_texts.append(text)
        except Exception as exc:
            logger.warning('OCR failed on PDF page %d: %s', i, exc)

    combined = '\n\n'.join(filter(None, page_texts))
    if not combined.strip():
        raise RuntimeError(
            'OCR extracted no text from the PDF. '
            'The scan may be too blurry, low-resolution, or the file may be empty.'
        )
    logger.info('OCR PDF complete: %d pages, %d characters', len(page_texts), len(combined))
    return combined
