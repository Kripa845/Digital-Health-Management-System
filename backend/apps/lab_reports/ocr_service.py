from __future__ import annotations

import io
import logging
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
import pymupdf
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

try:                       # OpenCV preprocessing; the older Pillow steps are used without it
    import cv2
except ImportError:        # pragma: no cover - opencv-python-headless is in requirements.txt
    cv2 = None

logger = logging.getLogger(__name__)


# ── Configuration ────────────────────────────────────────────────────────────

TESSERACT_CMD = os.environ.get('TESSERACT_CMD', '').strip()

# OCR runs inside the upload request, so the work per file is capped to keep
# it well inside the server's request timeout.
MAX_PDF_PAGES = int(os.environ.get('OCR_MAX_PDF_PAGES', '5'))
# 300 DPI: at 200 a decimal point is 1–2 px and is often lost ("4.1" read as "41").
PDF_DPI = int(os.environ.get('OCR_PDF_DPI', '300'))
PSM_MODES = ('6', '3')

# A PDF's own text is used when it has more than this many characters (and is real
# text, not unmapped glyph codes); otherwise its pages are read as images (a scan).
TEXT_LAYER_MIN_CHARS = 50

# Pages are first read with light preprocessing (no denoising or binarisation, which
# can erase decimal points). If that reading's mean confidence is below this, the
# heavy preprocessing (for shadowed phone photos) is tried too and the better kept.
HEAVY_RETRY_BELOW = 60.0
# Characters allowed when a result or range cell is read again on its own.
NUMERIC_WHITELIST = '0123456789.<>-/'

# Refuse decompression-bomb images (Pillow raises above twice this limit).
Image.MAX_IMAGE_PIXELS = 40_000_000

if TESSERACT_CMD and Path(TESSERACT_CMD).is_file():
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
elif os.name == 'nt':
    default = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    if Path(default).is_file():
        pytesseract.pytesseract.tesseract_cmd = default

# Image preprocessing (config/settings.py, LAB_OCR_*): see preprocess_image().
DEFAULT_PREPROCESS = {
    'LAB_OCR_TARGET_WIDTH': 2000,      # px; narrower images are enlarged to about this width
    'LAB_OCR_MAX_UPSCALE': 3.0,        # never enlarge more than this
    'LAB_OCR_MAX_DESKEW_ANGLE': 10.0,  # degrees searched either way for a tilted scan
    'LAB_OCR_DESKEW_STEP': 0.5,        # degrees between the angles tried
    'LAB_OCR_DENOISE_STRENGTH': 7,     # cv2.fastNlMeansDenoising h; higher removes more (and more detail)
    'LAB_OCR_ADAPTIVE_BLOCK_SIZE': 71, # px neighbourhood for the local threshold (odd)
    'LAB_OCR_ADAPTIVE_C': 20,          # subtracted from the local mean; higher keeps less grey as ink
}


# Skew is measured on a thumbnail of at most this many pixels a side, thresholded with this
# neighbourhood / offset; a tilt is corrected only if it lines rows up this much better.
SKEW_THUMBNAIL = 800
SKEW_THRESHOLD_BLOCK, SKEW_THRESHOLD_C = 31, 15
SKEW_MIN_GAIN = 1.05


def _cfg(name: str):
    try:
        from django.conf import settings
        if settings.configured:
            return getattr(settings, name, DEFAULT_PREPROCESS[name])
    except Exception:
        pass
    return DEFAULT_PREPROCESS[name]


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
    pages = read_pdf_pages(pdf_bytes)
    return '\n\n'.join(p.text for p in pages if p.text.strip()), [p.image for p in pages]


@dataclass
class PdfPage:
    text: str                      # the page's text layer, one table row per line ('' when none)
    words: list[tuple]             # text-layer word boxes (x0, y0, x1, y1, text), in PDF points
    image: bytes = field(repr=False, default=b'')   # PNG of the page at PDF_DPI
    image_cover: float = 0.0       # share of the page area covered by embedded images (0–1)

    @property
    def has_text(self) -> bool:
        """Read from its own text, not OCR: real text, and not a scan with a little typed
        text on top (a page mostly covered by an image is OCR'd, which reads both)."""
        return has_text_layer(self.text) and self.image_cover < PAGE_IMAGE_COVER_FOR_OCR


# A page whose embedded images cover at least this share of it is OCR'd even when it
# has some text (a scanned results table under a typed letterhead).
PAGE_IMAGE_COVER_FOR_OCR = 0.5


def read_pdf_pages(pdf_bytes: bytes) -> list[PdfPage]:
    """Each page (up to MAX_PDF_PAGES): its text layer, word boxes and a PNG for OCR."""
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype='pdf')
    except Exception as exc:
        raise RuntimeError('The PDF is damaged or is not a valid PDF file.') from exc
    with doc:
        if doc.needs_pass:
            raise RuntimeError('The PDF is password-protected. Upload a copy without a password.')
        if doc.page_count == 0:
            raise RuntimeError('The PDF is damaged or has no pages.')
        pages: list[PdfPage] = []
        try:
            for page in doc.pages(0, min(doc.page_count, MAX_PDF_PAGES)):
                words = [w[:5] for w in page.get_text('words')]   # (x0, y0, x1, y1, word, block, line, word_no)
                pages.append(PdfPage(
                    text=_join_rows(words), words=words,
                    image=page.get_pixmap(dpi=PDF_DPI, colorspace=pymupdf.csGRAY).tobytes('png'),
                    image_cover=_image_cover(page),
                ))
        except Exception as exc:
            raise RuntimeError('The PDF is damaged and its pages could not be read.') from exc
    return pages


def _image_cover(page) -> float:
    area = abs(page.rect) or 1.0
    try:
        covered = sum(abs(r & page.rect) for img in page.get_images(full=True) for r in page.get_image_rects(img[0]))
    except Exception:                          # pragma: no cover - unusual image references
        return 0.0
    return min(covered / area, 1.0)


def _rows(words) -> list[list[tuple]]:
    """Group word boxes (x0, y0, x1, y1, text[, confidence]) into rows, top to bottom;
    each row is a list of (x0, x1, text, confidence) sorted left to right."""
    rows: list[dict] = []
    for w in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        x0, y0, x1, y1, word = w[:5]
        conf = w[5] if len(w) > 5 else None
        centre, height = (y0 + y1) / 2, max(y1 - y0, 1.0)
        row = rows[-1] if rows else None
        if row and abs(centre - row['centre']) <= max(row['height'], height) * 0.5:
            row['words'].append((x0, x1, word, conf))
            # Follow a slightly tilted scan along the row.
            row['centre'] += (centre - row['centre']) / len(row['words'])
        else:
            rows.append({'centre': centre, 'height': height, 'words': [(x0, x1, word, conf)]})
    return [sorted(row['words'], key=lambda w: (w[0], w[1])) for row in rows]


def _join_rows(words) -> str:
    """Join word boxes (x0, y0, x1, y1, text[, confidence]) into lines, one per row of the page.

    PDF text is stored in drawing order, which often lists a table column by column
    ("Haemoglobin, Cholesterol ... 13.4, 210 ..."), so a label and its value end up far
    apart; OCR does the same. Words are regrouped into rows by their vertical position
    instead, and a wide horizontal gap becomes two spaces."""
    if not words:
        return ''
    lines = []
    for row in _rows(words):
        parts, last_x1 = [], None
        for x0, x1, word, _conf in row:
            if last_x1 is not None:
                char_width = (x1 - x0) / max(len(word), 1)
                parts.append('  ' if x0 - last_x1 > char_width * 2.5 else ' ')
            parts.append(word)
            last_x1 = x1
        lines.append(''.join(parts))
    return '\n'.join(lines)


# ── Public API ───────────────────────────────────────────────────────────────

@dataclass
class OcrPage:
    """One page of the report and its word boxes, so the results table can be rebuilt
    by position. ``source`` says how it was read: 'text_layer' (the PDF's own words, in
    PDF points, no image, confidence None) or 'ocr' (Tesseract's words on the
    preprocessed ``image``, so single cells can be read again)."""
    image: Image.Image | None = field(repr=False)
    words: list[tuple] = field(default_factory=list, repr=False)   # (x0, y0, x1, y1, text[, confidence])
    source: str = 'ocr'
    text: str = field(default='', repr=False)
    number: int = 1                                                 # page number in the file (1-based)
    confidence: float | None = None                                 # OCR only: mean word confidence


@dataclass
class DocumentText:
    text: str
    confidence: float | None                  # 0–100; a PDF's own text counts as 100
    page_images: list[bytes] = field(default_factory=list, repr=False)
    source: str = ''                           # 'text_layer', 'ocr', 'mixed' (some pages each) or ''
    ocr_error: str = ''                        # why OCR produced no text, if it did not
    # Each line's words with a confidence (0–100), in reading order, so a value can carry
    # the confidence of the word it was read from. Empty for a text-layer-only PDF.
    words: list[list[tuple[str, float]]] = field(default_factory=list, repr=False)
    pages: list[OcrPage] = field(default_factory=list, repr=False)


def read_report_file(raw_bytes: bytes, ext: str) -> DocumentText:
    """Read a lab report, page by page: a PDF page's own text when it has real text,
    otherwise OCR of that page's image (a scan, a photo, or text saved as outlines by
    "Print to PDF"). A PDF can mix both. Raises RuntimeError/ValueError only when the
    file itself cannot be opened; OCR problems are reported in ``ocr_error`` so a caller
    can still use the text pages and the page images."""
    ext = _normalise_ext(ext)
    if ext == '.pdf' and not raw_bytes.startswith(_IMAGE_SIGNATURES):
        pdf_pages = read_pdf_pages(raw_bytes)
    elif ext in IMAGE_EXTENSIONS or ext == '.pdf':
        _open_image(raw_bytes).close()        # damaged image → RuntimeError
        pdf_pages = [PdfPage('', [], raw_bytes, 1.0)]
    else:
        raise ValueError(f'Unsupported file extension "{ext}". Allowed: PDF, JPG, JPEG, PNG.')
    images = [p.image for p in pdf_pages]

    doc_has_text = has_text_layer('\n'.join(p.text for p in pdf_pages))
    pages: dict[int, OcrPage] = {}
    to_ocr: list[int] = []
    for number, p in enumerate(pdf_pages, start=1):
        # In a document with a text layer, a short page ("End of report") keeps its own text.
        if p.has_text or (doc_has_text and p.image_cover < PAGE_IMAGE_COVER_FOR_OCR
                          and has_text_layer(p.text, min_chars=0)):
            pages[number] = OcrPage(None, p.words, 'text_layer', p.text, number)
        else:
            to_ocr.append(number)
    if not to_ocr:
        ordered = [pages[n] for n in sorted(pages)]
        return DocumentText('\n\n'.join(p.text for p in ordered if p.text.strip()), 100.0, images,
                            'text_layer', pages=ordered)

    ocr_error = ''
    try:
        _text, _conf, _words, ocr_pages = _ocr_images([images[n - 1] for n in to_ocr], to_ocr)
        pages.update({p.number: p for p in ocr_pages})
    except RuntimeError as exc:
        ocr_error = str(exc)
    ordered = [pages[n] for n in sorted(pages)]
    if not any(p.source == 'ocr' for p in ordered):
        text = '\n\n'.join(p.text for p in ordered if p.text.strip())
        return DocumentText(text, 100.0 if text.strip() else None, images, 'text_layer' if text.strip() else '',
                            ocr_error, pages=ordered)

    # Line words with confidences across every page (text-layer words count as 100).
    words: list[list[tuple[str, float]]] = []
    for p in ordered:
        words.extend([(w, 100.0 if c is None else c) for _x0, _x1, w, c in row] for row in _rows(p.words))
    page_conf = [100.0 if p.source == 'text_layer' else (p.confidence or 0.0) for p in ordered]
    source = 'ocr' if all(p.source == 'ocr' for p in ordered) else 'mixed'
    return DocumentText('\n\n'.join(p.text for p in ordered if p.text.strip()),
                        round(sum(page_conf) / len(page_conf), 1), images, source, ocr_error, words, ordered)


def has_text_layer(text: str, min_chars: int = TEXT_LAYER_MIN_CHARS) -> bool:
    """Whether a PDF's own text is real text: longer than ``min_chars``, and not mostly
    unmapped glyph codes ("(cid:12)" or U+FFFD), which some PDF generators produce
    instead of letters."""
    t = (text or '').strip()
    if len(t) <= min_chars:
        return False
    junk = t.count('�') + 6 * len(re.findall(r'\(cid:\d+\)', t))
    return junk < 0.05 * len(t) and sum(ch.isalnum() for ch in t) >= 0.3 * len(t)


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
    """Prepare a scan or photo for Tesseract with OpenCV:

    1. grayscale
    2. denoise       non-local means removes speckle and JPEG noise but keeps edges
                     (done before enlarging: the same result in about a third of the time)
    3. upscale       small images are enlarged towards LAB_OCR_TARGET_WIDTH (at least
                     1200 px each way); Tesseract reads 10–12 px tall letters poorly
    4. deskew        the angle (±LAB_OCR_MAX_DESKEW_ANGLE) whose rows of ink line up best
                     is found on a small copy, and the page is rotated back
    5. binarize      adaptive (local) threshold, so shadows and uneven lighting from
                     phone photos do not black out part of the page
    Returns a black-and-white 'L' image. Without OpenCV the older Pillow steps are used.
    """
    if cv2 is None:
        return _preprocess_pil(img)
    gray = np.array(img.convert('L'))
    gray = cv2.fastNlMeansDenoising(gray, None, h=float(_cfg('LAB_OCR_DENOISE_STRENGTH')),
                                    templateWindowSize=7, searchWindowSize=21)
    gray = _upscale(gray)
    gray = _deskew(gray)
    block = int(_cfg('LAB_OCR_ADAPTIVE_BLOCK_SIZE')) | 1          # must be odd
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY,
                                   max(block, 3), float(_cfg('LAB_OCR_ADAPTIVE_C')))
    return Image.fromarray(binary)            # uint8, one channel: an 'L' image


def prepare_page(img: Image.Image) -> Image.Image:
    """Light preprocessing, tried first: grayscale, enlarge small images, level a tilted
    scan. No denoising or binarisation: both can erase a decimal point (a 1–2 px dot),
    and Tesseract binarises internally. Returns an 'L' image."""
    if cv2 is None:
        gray = img.convert('L')
        w, h = gray.size
        if w < 1200 or h < 1200:
            scale = max(1200 / w, 1200 / h)
            gray = gray.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        return gray
    gray = _deskew(_upscale(np.array(img.convert('L'))))
    return Image.fromarray(gray)


def _upscale(gray: np.ndarray) -> np.ndarray:
    h, w = gray.shape[:2]
    scale = max(float(_cfg('LAB_OCR_TARGET_WIDTH')) / w, 1200 / w, 1200 / h, 1.0)
    scale = min(scale, max(float(_cfg('LAB_OCR_MAX_UPSCALE')), 1200 / w, 1200 / h))
    if scale <= 1.0:
        return gray
    return cv2.resize(gray, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_CUBIC)


def skew_angle(gray: np.ndarray) -> float:
    """Rotation in degrees (OpenCV convention, positive = counter-clockwise) that levels
    the text lines; 0 when the page is level, blank or the result is unclear.

    Projection profile: rotate a small black-and-white copy through the allowed angles;
    text lines are level when the row sums vary the most (dark rows, white gaps).
    """
    max_angle = float(_cfg('LAB_OCR_MAX_DESKEW_ANGLE'))
    step = float(_cfg('LAB_OCR_DESKEW_STEP'))
    if max_angle <= 0 or step <= 0:
        return 0.0
    h, w = gray.shape[:2]
    small_scale = min(1.0, SKEW_THUMBNAIL / max(h, w))
    small = cv2.resize(gray, (max(1, round(w * small_scale)), max(1, round(h * small_scale))),
                       interpolation=cv2.INTER_AREA)
    # A local threshold, as in preprocess_image: a global one turns the dark side of an
    # unevenly lit photo into "ink" and reports a large false tilt.
    ink = cv2.adaptiveThreshold(small, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV,
                                SKEW_THRESHOLD_BLOCK, SKEW_THRESHOLD_C)
    if cv2.countNonZero(ink) < 0.001 * ink.size:
        return 0.0                                   # blank page
    centre = (ink.shape[1] / 2, ink.shape[0] / 2)
    best_angle, best_score, base = 0.0, -1.0, None
    for angle in np.arange(-max_angle, max_angle + step / 2, step):
        m = cv2.getRotationMatrix2D(centre, float(angle), 1.0)
        rotated = cv2.warpAffine(ink, m, (ink.shape[1], ink.shape[0]), flags=cv2.INTER_NEAREST, borderValue=0)
        score = float(np.var(rotated.sum(axis=1, dtype=np.float64)))
        if abs(angle) < 1e-9:
            base = score
        if score > best_score:
            best_angle, best_score = float(angle), score
    # Only correct when the improvement is clear; noise gives tiny differences.
    if base is not None and best_score < base * SKEW_MIN_GAIN:
        return 0.0
    return round(best_angle, 2)


def _deskew(gray: np.ndarray) -> np.ndarray:
    angle = skew_angle(gray)
    if abs(angle) < 0.25:
        return gray
    h, w = gray.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def _preprocess_pil(img: Image.Image) -> Image.Image:
    """The original Pillow preprocessing, used only when OpenCV is not installed."""
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


def _ocr_rows(img: Image.Image) -> tuple[str, float, list[list[tuple[str, float]]]]:
    """OCR a page keeping table rows together; returns the text, the mean word confidence
    and each line's (word, confidence) pairs.

    Tesseract reads a table column by column (all test names, then all
    results), which separates each result from its name. Its word boxes are
    regrouped into rows by position instead, as for a PDF's own text.
    """
    words = _ocr_word_boxes(img)
    confidence = _mean_confidence(words)
    lines = [[(word, conf) for _x0, _x1, word, conf in row] for row in _rows(words)] if words else []
    return _join_rows(words), confidence, lines


def _ocr_word_boxes(img: Image.Image) -> list[tuple]:
    """Tesseract's words on a page as (x0, y0, x1, y1, text, confidence)."""
    data = pytesseract.image_to_data(
        img, lang='eng', config=f'--psm {PSM_MODES[1]}', output_type=pytesseract.Output.DICT,
    )
    words = []
    for text, conf, left, top, width, height in zip(
            data['text'], data['conf'], data['left'], data['top'], data['width'], data['height']):
        text = str(text).strip()
        if not text or float(conf) < 0:
            continue
        words.append((left, top, left + width, top + height, text, float(conf)))
    return words


def _mean_confidence(words: list[tuple]) -> float:
    return round(sum(w[5] for w in words) / len(words), 1) if words else 0.0


def _read_page(img: Image.Image) -> tuple[Image.Image, list[tuple]]:
    """(preprocessed image, word boxes): light preprocessing first; the heavy one only
    when the light reading is empty or poor, keeping whichever reads more confidently."""
    light = prepare_page(img)
    best = (light, _ocr_word_boxes(light))
    if not best[1] or _mean_confidence(best[1]) < HEAVY_RETRY_BELOW:
        heavy = preprocess_image(img)
        heavy_words = _ocr_word_boxes(heavy)
        if heavy_words and _mean_confidence(heavy_words) > _mean_confidence(best[1]):
            best = (heavy, heavy_words)
    return best


def ocr_numeric_cell(image: Image.Image, box: tuple[float, float, float, float],
                     scale: float = 1.0) -> tuple[str, float | None]:
    """Read one result or range cell again as a single line of digits (--psm 7, whitelist
    0-9 . < > - /), which keeps decimal points a full-page read drops. ``scale`` enlarges
    the cell first (a tight "4.41" often keeps its dot only when bigger). Returns (text,
    lowest word confidence); ('', None) when nothing was read."""
    x0, y0, x1, y1 = box
    pad = max(4, int((y1 - y0) * 0.35))
    crop = image.crop((max(0, int(x0 - pad)), max(0, int(y0 - pad)),
                       min(image.width, int(x1 + pad)), min(image.height, int(y1 + pad))))
    if scale != 1.0:
        crop = crop.resize((max(1, round(crop.width * scale)), max(1, round(crop.height * scale))), Image.LANCZOS)
    crop = ImageOps.expand(crop.convert('L'), border=12, fill=255)
    try:
        data = pytesseract.image_to_data(
            crop, lang='eng', config=f'--psm 7 -c tessedit_char_whitelist={NUMERIC_WHITELIST}',
            output_type=pytesseract.Output.DICT,
        )
    except Exception as exc:                     # pragma: no cover - Tesseract failure
        logger.warning('Numeric cell OCR failed: %s', exc)
        return '', None
    found = [(str(t).strip(), float(c)) for t, c in zip(data['text'], data['conf'])
             if str(t).strip() and float(c) >= 0]
    if not found:
        return '', None
    return ' '.join(t for t, _c in found), min(c for _t, c in found)


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


def _ocr_images(images: list[bytes], numbers: list[int] | None = None,
                ) -> tuple[str, float, list[list[tuple[str, float]]], list[OcrPage]]:
    """OCR each page image; returns the combined text, the mean confidence, the words of
    every line with their confidences, and each page's image and word boxes. ``numbers``
    are the images' page numbers in the file (default 1, 2, ...)."""
    if not tesseract_available():
        raise RuntimeError('Scanned reports cannot be read because Tesseract OCR is not installed on the server.')
    texts, confidences, words, pages = [], [], [], []
    for i, raw in enumerate(images, start=1):
        img = _open_image(raw)
        try:
            processed, boxes = _read_page(img)
            if boxes:
                text, confidence = _join_rows(boxes), _mean_confidence(boxes)
                lines = [[(word, conf) for _x0, _x1, word, conf in row] for row in _rows(boxes)]
            else:
                processed = preprocess_image(img)
                text, confidence, lines = _run_ocr_on_image(processed), _confidence(processed), []
            texts.append(text)
            confidences.append(confidence)
            words.extend(lines)
            pages.append(OcrPage(processed, boxes, 'ocr', text, numbers[i - 1] if numbers else i, confidence))
        except RuntimeError:
            logger.info('OCR found no text on page %d.', numbers[i - 1] if numbers else i)
        finally:
            img.close()
    combined = '\n\n'.join(texts)
    if not combined.strip():
        raise RuntimeError('OCR found no text. The scan may be too blurry or low-resolution.')
    logger.info('OCR complete: %d page(s), %d characters', len(texts), len(combined))
    return combined, round(sum(confidences) / len(confidences), 1), words, pages
