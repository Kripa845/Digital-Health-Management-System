from __future__ import annotations

import io
import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pymupdf
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter

logger = logging.getLogger(__name__)


# ── Configuration ────────────────────────────────────────────────────────────

TESSERACT_CMD = os.environ.get('TESSERACT_CMD', '').strip()

# OCR runs inside the upload request, so the work per file is capped to keep
# it well inside the server's request timeout.
MAX_PDF_PAGES = int(os.environ.get('OCR_MAX_PDF_PAGES', '5'))
PDF_DPI = int(os.environ.get('OCR_PDF_DPI', '200'))
PSM_MODES = ('6', '3')

# A PDF's own text is used when it has more than this many characters;
# otherwise its pages are read as images (a scanned PDF).
TEXT_LAYER_MIN_CHARS = 50

# Refuse decompression-bomb images (Pillow raises above twice this limit).
Image.MAX_IMAGE_PIXELS = 40_000_000

if TESSERACT_CMD and Path(TESSERACT_CMD).is_file():
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
elif os.name == 'nt':
    default = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    if Path(default).is_file():
        pytesseract.pytesseract.tesseract_cmd = default

IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png')
_IMAGE_SIGNATURES = (b'\x89PNG\r\n\x1a\n', b'\xff\xd8\xff')


# ── PDF reading (PyMuPDF; no Poppler needed) ─────────────────────────────────

def read_pdf(pdf_bytes: bytes) -> tuple[str, list[bytes]]:
    """Return (text from the PDF's text layer, PNG bytes of each page at PDF_DPI).

    A PNG or JPG passed in goes straight to the image list (with no text). Only
    the first MAX_PDF_PAGES pages are read. Raises RuntimeError with a message
    that can be shown to the user when the file is damaged, encrypted or empty.
    """
    if pdf_bytes.startswith(_IMAGE_SIGNATURES):
        return '', [pdf_bytes]
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype='pdf')
    except Exception as exc:
        raise RuntimeError('The PDF is damaged or is not a valid PDF file.') from exc
    with doc:
        if doc.needs_pass:
            raise RuntimeError('The PDF is password-protected. Upload a copy without a password.')
        if doc.page_count == 0:
            raise RuntimeError('The PDF is damaged or has no pages.')
        texts: list[str] = []
        images: list[bytes] = []
        try:
            for page in doc.pages(0, min(doc.page_count, MAX_PDF_PAGES)):
                texts.append(_page_text(page))
                images.append(page.get_pixmap(dpi=PDF_DPI, colorspace=pymupdf.csGRAY).tobytes('png'))
        except Exception as exc:
            raise RuntimeError('The PDF is damaged and its pages could not be read.') from exc
    return '\n\n'.join(t for t in texts if t.strip()), images


def _page_text(page) -> str:
    """The page's text with each table row on one line.

    PDF text is stored in drawing order, which often lists a table column by
    column ("Haemoglobin, Cholesterol ... 13.4, 210 ..."), so a label and its
    value end up far apart. Words are regrouped into rows by their vertical
    position instead; a wide horizontal gap becomes two spaces, like OCR output.
    """
    words = page.get_text('words')        # (x0, y0, x1, y1, word, block, line, word_no)
    return _join_rows([w[:5] for w in words])


def _join_rows(words) -> str:
    """Join word boxes (x0, y0, x1, y1, text) into lines, one per row of the page."""
    if not words:
        return ''
    rows: list[dict] = []
    for x0, y0, x1, y1, word in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        centre, height = (y0 + y1) / 2, max(y1 - y0, 1.0)
        row = rows[-1] if rows else None
        if row and abs(centre - row['centre']) <= max(row['height'], height) * 0.5:
            row['words'].append((x0, x1, word))
            # Follow a slightly tilted scan along the row.
            row['centre'] += (centre - row['centre']) / len(row['words'])
        else:
            rows.append({'centre': centre, 'height': height, 'words': [(x0, x1, word)]})

    lines = []
    for row in rows:
        parts, last_x1 = [], None
        for x0, x1, word in sorted(row['words']):
            if last_x1 is not None:
                char_width = (x1 - x0) / max(len(word), 1)
                parts.append('  ' if x0 - last_x1 > char_width * 2.5 else ' ')
            parts.append(word)
            last_x1 = x1
        lines.append(''.join(parts))
    return '\n'.join(lines)


# ── Public API ───────────────────────────────────────────────────────────────

@dataclass
class DocumentText:
    text: str
    confidence: float | None                  # 0–100; a PDF's own text counts as 100
    page_images: list[bytes] = field(default_factory=list, repr=False)
    source: str = ''                           # 'text_layer', 'ocr' or '' (nothing read)
    ocr_error: str = ''                        # why OCR produced no text, if it did not


def read_report_file(raw_bytes: bytes, ext: str) -> DocumentText:
    """Read a lab report: a PDF's text layer if it has one, otherwise OCR of the
    page images. Raises RuntimeError/ValueError only when the file itself cannot
    be opened; OCR problems are reported in ``ocr_error`` so a caller can still
    use the page images."""
    ext = _normalise_ext(ext)
    layer_text = ''
    if ext == '.pdf':
        layer_text, images = read_pdf(raw_bytes)
        if len(layer_text.strip()) > TEXT_LAYER_MIN_CHARS:
            return DocumentText(layer_text, 100.0, images, 'text_layer')
    elif ext in IMAGE_EXTENSIONS:
        _open_image(raw_bytes).close()        # damaged image → RuntimeError
        images = [raw_bytes]
    else:
        raise ValueError(f'Unsupported file extension "{ext}". Allowed: PDF, JPG, JPEG, PNG.')

    try:
        text, confidence = _ocr_images(images)
    except RuntimeError as exc:
        return DocumentText(layer_text, None, images, 'text_layer' if layer_text.strip() else '', str(exc))
    return DocumentText(text, confidence, images, 'ocr')


def extract_text_with_confidence(raw_bytes: bytes, ext: str) -> tuple[str, float]:
    """Text plus Tesseract's mean word confidence (a PDF's own text is 100)."""
    doc = read_report_file(raw_bytes, ext)
    if not doc.text.strip():
        raise RuntimeError(doc.ocr_error or 'No text was found in the file.')
    return doc.text, doc.confidence if doc.confidence is not None else 0.0


def extract_text_from_file(file_field) -> str:
    try:
        file_field.seek(0)
        raw_bytes: bytes = file_field.read()
    except Exception as exc:
        raise RuntimeError(f'Could not read the uploaded file: {exc}') from exc
    return extract_text_from_bytes(raw_bytes, Path(file_field.name or '').suffix)


def extract_text_from_bytes(raw_bytes: bytes, ext: str) -> str:
    """Extract text from file contents; ``ext`` is the original extension, e.g. ".pdf"."""
    return extract_text_with_confidence(raw_bytes, ext)[0]


def _normalise_ext(ext: str) -> str:
    ext = (ext or '').lower()
    return ext if ext.startswith('.') else f'.{ext}'


def _open_image(raw_bytes: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img.load()
        return img
    except Exception as exc:
        raise RuntimeError('The image is damaged or is not a valid PNG/JPG file.') from exc


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

@lru_cache(maxsize=1)
def tesseract_available() -> bool:
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _run_ocr_on_image(img: Image.Image) -> str:
    best_text = ''
    best_len = 0

    for psm in PSM_MODES:
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


def _ocr_rows(img: Image.Image) -> tuple[str, float]:
    """OCR a page keeping table rows together; returns the text and the mean word confidence.

    Tesseract reads a table column by column (all test names, then all
    results), which separates each result from its name. Its word boxes are
    regrouped into rows by position instead, as for a PDF's own text.
    """
    data = pytesseract.image_to_data(
        img, lang='eng', config=f'--psm {PSM_MODES[1]}', output_type=pytesseract.Output.DICT,
    )
    words, scores = [], []
    for text, conf, left, top, width, height in zip(
            data['text'], data['conf'], data['left'], data['top'], data['width'], data['height']):
        text = str(text).strip()
        if not text or float(conf) < 0:
            continue
        words.append((left, top, left + width, top + height, text))
        scores.append(float(conf))
    confidence = round(sum(scores) / len(scores), 1) if scores else 0.0
    return _join_rows(words), confidence


def _confidence(img: Image.Image) -> float:
    """Mean confidence of the words Tesseract recognises in a preprocessed image."""
    try:
        data = pytesseract.image_to_data(
            img, lang='eng', config=f'--psm {PSM_MODES[0]}', output_type=pytesseract.Output.DICT,
        )
        scores = [float(c) for c, w in zip(data['conf'], data['text']) if str(w).strip() and float(c) >= 0]
        return round(sum(scores) / len(scores), 1) if scores else 0.0
    except Exception as exc:
        logger.warning('Could not measure OCR confidence: %s', exc)
        return 0.0


def _ocr_images(images: list[bytes]) -> tuple[str, float]:
    """OCR each page image; returns the combined text and the mean confidence."""
    if not tesseract_available():
        raise RuntimeError('Scanned reports cannot be read because Tesseract OCR is not installed on the server.')
    texts, confidences = [], []
    for i, raw in enumerate(images, start=1):
        img = _open_image(raw)
        try:
            processed = preprocess_image(img)
            text, confidence = _ocr_rows(processed)
            if not text.strip():
                text, confidence = _run_ocr_on_image(processed), _confidence(processed)
            texts.append(text)
            confidences.append(confidence)
        except RuntimeError:
            logger.info('OCR found no text on page %d.', i)
        finally:
            img.close()
    combined = '\n\n'.join(texts)
    if not combined.strip():
        raise RuntimeError('OCR found no text. The scan may be too blurry or low-resolution.')
    logger.info('OCR complete: %d page(s), %d characters', len(texts), len(combined))
    return combined, round(sum(confidences) / len(confidences), 1)
