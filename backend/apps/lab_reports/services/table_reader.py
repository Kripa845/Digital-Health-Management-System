"""Read lab values row by row from a report's results table.

Each value is taken together with the unit and reference range printed on the SAME
row, and the row's whole test name is matched exactly (services/test_names.py).
Nothing depends on one lab's layout: the columns are found from the header row
("Test / Investigation / Parameter", "Result / Observed value", "Unit",
"Reference range / Normal range / Bio. ref. interval", synonyms in
config/lab_tests.json) wherever they are and in any order.

Each page is read the way ocr_service read it (a PDF can mix both), best first:
    PDF page with text      PyMuPDF: ruled tables (find_tables), else columns from
                            word positions under the header, else each text line
                            parsed with a regular expression
    scan / photo (OCR)      columns from Tesseract's word boxes under the header; the
                            result and range cells are read again as digits only
                            (ocr_service.ocr_numeric_cell), else text lines
    anything else           text lines

Every value that is not certain goes to the review screen with a reason
(services/review.py): low OCR confidence, an auto-corrected decimal point, two
OCR readings of a result that differ, two rows read as the same test, a range that
could not be read on a scan. Rows whose name is not a known test are never guessed:
they are logged, and the ones that look like test rows (with a unit or a range) are
listed on the review screen as not recognised (and are not saved).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import pymupdf

from apps.lab_reports import lab_config
from apps.lab_reports.extractor import _PLAUSIBLE_RANGES, ExtractedField, display_name
from apps.lab_reports.services import review
from apps.lab_reports.services.review import ReferenceRange
from apps.lab_reports.services.test_names import match_test, normalise_name
from apps.lab_reports.units import convert, normalise_unit

logger = logging.getLogger(__name__)

MAX_PAGES = 5
# OCR: a cell read again on its own replaces the first reading only with at least this
# confidence. A scanned range is shown and used only with MIN_RANGE_CONFIDENCE: below
# it the range is "not read" (a wrong range shown as fact is worse than none).
MIN_CELL_CONFIDENCE = 60.0
MIN_RANGE_CONFIDENCE = 75.0
PDF_TABLE = 'pdf_table'
PDF_COLUMNS = 'pdf_columns'
PDF_LINES = 'pdf_lines'
OCR_COLUMNS = 'ocr_columns'
TEXT_LINES = 'text_lines'


@dataclass
class Row:
    name: str
    value: str                    # the result cell as printed (may hold an H/L flag)
    unit: str = ''
    range: str = ''
    page: int = 1
    confidence: float | None = None          # lowest OCR confidence in the result cell
    range_confidence: float | None = None    # lowest OCR confidence in the range cell
    value_box: tuple | None = None           # OCR only: cell boxes, to read them again
    range_box: tuple | None = None
    prev_name: str = ''                      # a name-only line just above (wrapped name)
    next_name: str = ''                      # a name-only line just below
    notes: list[dict] = field(default_factory=list)
    ocr: bool = False                        # read by OCR (not from a PDF's own text)


@dataclass
class TableRead:
    method: str = ''
    rows: list[Row] = field(default_factory=list)


@dataclass
class TableValues:
    method: str = ''
    values: list[ExtractedField] = field(default_factory=list)
    unmatched: list[dict] = field(default_factory=list)      # rows not recognised, for the review screen


# ── Cells ────────────────────────────────────────────────────────────────────

_FLAG = r'(?:[HL]{1,2}|\*{1,2}|high|low|abnormal)'
_NUMBER = r'\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:[.,]\d+)?'
_VALUE_CELL = re.compile(
    rf'^\s*(?:{_FLAG}\s+)?(?P<cmp>[<>]=?|≤|≥)?\s*(?P<num>{_NUMBER})(?![\d/])\s*(?:{_FLAG}\b)?', re.IGNORECASE)
_RANGE = re.compile(
    r'(?P<low>\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*(?P<high>\d+(?:\.\d+)?)'
    r'|(?:<\s*=?|≤|up\s*to|less\s*than|below)\s*(?P<lt>\d+(?:\.\d+)?)'
    r'|(?:>\s*=?|≥|more\s*than|above)\s*(?P<gt>\d+(?:\.\d+)?)',
    re.IGNORECASE)
_FLAG_TOKEN = re.compile(rf'^{_FLAG}$', re.IGNORECASE)


def parse_number(text: str) -> str | None:
    """The plain number in a result cell: "2,50,000" → "250000", "13,13" → "13.13",
    "<0.5" → "<0.5" (kept with its sign so it is never stored as 0.5); None if none."""
    m = _VALUE_CELL.match(text or '')
    if not m:
        return None
    num = m.group('num')
    if re.fullmatch(r'\d{1,3}(?:,\d{2,3})*,\d{3}(?:\.\d+)?', num):
        num = num.replace(',', '')                       # thousands separators
    else:
        num = num.replace(',', '.')                      # decimal comma
    return f"{m.group('cmp')}{num}" if m.group('cmp') else num


def parse_range(text: str) -> tuple[ReferenceRange | None, str]:
    """(range, leftover text) from a reference-range cell. Tolerates spaces around the
    hyphen, en/em dashes and "to". Two or more ranges in one cell ("M: 13-17 F: 12-15")
    are ambiguous: None."""
    # Thousands separators ("4,000 - 11,000", "1,50,000 - 4,50,000"), not decimal commas.
    text = re.sub(r'(?<=\d),(?=(?:\d{2},)*\d{3}(?!\d))', '', text or '')
    found = [m for m in _RANGE.finditer(text)
             if not (m.group('low') and text[m.end():m.end() + 1] == '/')]     # not a date "1-2/3"
    if len(found) != 1:
        return None, text or ''
    m = found[0]
    low = m.group('low') or m.group('gt')
    high = m.group('high') or m.group('lt')
    low, high = (float(low) if low else None), (float(high) if high else None)
    if low is not None and high is not None and low >= high:
        return None, text
    return ReferenceRange(low, high), (text[:m.start()] + ' ' + text[m.end():]).strip()


def clean_unit(text: str) -> str:
    """The unit cell without flags, brackets or footnote marks: "L mg/dL" → "mg/dL"."""
    words = [w for w in re.split(r'\s+', (text or '').replace('(', ' ').replace(')', ' ').strip())
             if w and not _FLAG_TOKEN.match(w)]
    return ' '.join(words)[:50]


def unit_from_text(text: str) -> str:
    """A unit in free text after a value (line mode, where there is no unit column): the
    whole text if it is a known unit, else its first word if that looks like one."""
    t = clean_unit(text)
    if not t:
        return ''
    aliases = lab_config.unit_aliases()
    known = set(aliases) | set(aliases.values())
    if normalise_unit(t) in known:
        return t
    first = t.split()[0]
    return first if normalise_unit(first) in known or re.search(r'[/%]', first) else ''


# ── Lines of words (PDF text layer or OCR) ──────────────────────────────────

# A word: (x0, y0, x1, y1, text, confidence or None)


def _lines(words: list[tuple]) -> list[list[tuple]]:
    """Group words into lines by vertical centre, each sorted left to right."""
    lines: list[dict] = []
    for w in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        centre, height = (w[1] + w[3]) / 2, max(w[3] - w[1], 1.0)
        line = lines[-1] if lines else None
        if line and abs(centre - line['centre']) <= max(line['height'], height) * 0.5:
            line['words'].append(w)
            line['centre'] += (centre - line['centre']) / len(line['words'])
        else:
            lines.append({'centre': centre, 'height': height, 'words': [w]})
    return [sorted(line['words'], key=lambda w: w[0]) for line in lines]


def _header_names() -> dict[str, set[str]]:
    return {role: {_flat(s) for s in names} for role, names in lab_config.header_synonyms().items()}


def _flat(text: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'[()]', ' ', normalise_name(text))).strip()


def header_columns(line: list[tuple]) -> dict[str, tuple[float, float]] | None:
    """{role: (x0, x1)} when a line is a results-table header; None otherwise.

    Words are joined into phrases ("Reference Range", "Bio. Ref. Interval") only when
    they are a normal word gap apart, so two neighbouring column titles are not read
    as one. A header needs a result column and at least one other, and must consist
    mostly of column titles (so a sentence mentioning "result" is not a header)."""
    names = _header_names()
    tokens = [(_flat(w[4]), w) for w in line]
    tokens = [(t, w) for t, w in tokens if t]
    if not tokens:
        return None
    height = sum(w[3] - w[1] for _t, w in tokens) / len(tokens)
    found: dict[str, tuple[float, float]] = {}
    used, i = 0, 0
    while i < len(tokens):
        hit = None
        for n in (4, 3, 2, 1):
            group = tokens[i:i + n]
            if len(group) < n or any(b[1][0] - a[1][2] > height * 1.2 for a, b in zip(group, group[1:])):
                continue
            phrase = ' '.join(t for t, _w in group)
            role = next((r for r, opts in names.items() if r not in found and phrase in opts), None)
            if role:
                hit = (role, group)
                break
        if hit:
            role, group = hit
            found[role] = (min(w[0] for _t, w in group), max(w[2] for _t, w in group))
            used += len(group)
            i += len(group)
        else:
            i += 1
    if 'value' not in found or len(found) < 2 or used < 0.6 * len(tokens):
        return None
    return found


def _bounds(columns: dict[str, tuple[float, float]], height: float) -> list[tuple[str, float, float]]:
    """(role, left, right) slices of the page for each column. Test names run long and
    are left-aligned, so the name column reaches to just before the result column;
    between other columns the boundary is halfway between their titles."""
    cols = sorted(columns.items(), key=lambda c: c[1][0])
    if 'name' not in columns:
        cols = [('name', (float('-inf'), float('-inf')))] + cols
    out = []
    for idx, (role, (x0, x1)) in enumerate(cols):
        left = float('-inf') if idx == 0 else out[-1][2]
        if idx + 1 < len(cols):
            nxt = cols[idx + 1][1]
            right = nxt[0] - height if role == 'name' else (x1 + nxt[0]) / 2
        else:
            right = float('inf')
        out.append((role, left, right))
    return out


def _box(words: list[tuple]) -> tuple | None:
    return (min(w[0] for w in words), min(w[1] for w in words),
            max(w[2] for w in words), max(w[3] for w in words)) if words else None


def fix_ocr_digits(text: str) -> str:
    """In a number cell read by OCR, a letter O beside a digit is 0 and l, I or | is 1
    ("O-0.2" → "0-0.2", "l3.2" → "13.2")."""
    text = re.sub(r'(?<![A-Za-z])[Oo](?=\s*[\d.\-–])|(?<=[\d.\-–])[Oo](?![A-Za-z])', '0', text or '')
    return re.sub(r'(?<![A-Za-z])[lI|](?=[\d.])|(?<=[\d.])[lI|](?![A-Za-z])', '1', text)


def _min_conf(words: list[tuple]) -> float | None:
    confs = [w[5] for w in words if len(w) > 5 and w[5] is not None]
    return min(confs) if confs else None


def _row_from_line(line: list[tuple], bounds, page: int) -> Row:
    cells: dict[str, list[tuple]] = {role: [] for role, _l, _r in bounds}
    for w in line:
        centre = (w[0] + w[2]) / 2
        role = next((r for r, left, right in bounds if left <= centre < right), bounds[-1][0])
        cells[role].append(w)
    # Words of a long name that spill into the result column belong to the name.
    value_words = cells.get('value', [])
    while value_words and not re.search(r'[\d<>≤≥]', value_words[0][4]) and not _FLAG_TOKEN.match(value_words[0][4]):
        cells['name'].append(value_words.pop(0))
    text = {role: ' '.join(w[4] for w in ws) for role, ws in cells.items()}
    ocr = _min_conf(line) is not None
    return Row(
        name=text.get('name', '').strip(' :-–'),
        value=fix_ocr_digits(text.get('value', '')) if ocr else text.get('value', ''),
        unit=text.get('unit', ''),
        range=fix_ocr_digits(text.get('range', '')) if ocr else text.get('range', ''),
        page=page,
        confidence=_min_conf(value_words),
        range_confidence=_min_conf(cells.get('range', [])),
        value_box=_box([w for w in value_words if re.search(r'\d', w[4])]),
        range_box=_box(cells.get('range', [])) or (_empty_cell(line, bounds, 'range') if ocr else None),
        ocr=ocr,
    )


def _empty_cell(line: list[tuple], bounds, role: str) -> tuple | None:
    """The box of a column's cell on this line when OCR found no words in it (faint or bold
    print is sometimes skipped by a full-page read), so it can be read again on its own."""
    column = next(((left, right) for r, left, right in bounds if r == role), None)
    if column is None or column[0] == float('-inf'):
        return None
    y0, y1 = min(w[1] for w in line), max(w[3] for w in line)
    left, right = column
    if right == float('inf'):
        right = left + (y1 - y0) * 12                  # about a dozen characters
    return left, y0, right, y1


def rows_from_words(words: list[tuple], page: int = 1, columns=None) -> tuple[list[Row], dict | None]:
    """Rows of the results table on one page, found under a header line. ``columns`` is
    the previous page's header, used for a continuation page without one. Returns the
    rows and the last header seen."""
    rows: list[Row] = []
    lines = _lines(words)
    heights = [w[3] - w[1] for w in words] or [10.0]
    height = sorted(heights)[len(heights) // 2]
    # The previous page's columns apply only to a continuation page without its own
    # header; on a page with one, the lines above it (letterhead, patient details) are
    # not table rows.
    if columns and any(header_columns(line) for line in lines):
        columns = None
    bounds = _bounds(columns, height) if columns else None
    pending: Row | None = None                       # a name-only line (wrapped name / section title)
    for line in lines:
        header = header_columns(line)
        if header:
            columns, bounds, pending = header, _bounds(header, height), None
            continue
        if not bounds:
            continue
        row = _row_from_line(line, bounds, page)
        # A known test whose result could not be parsed (OCR "orr.2") is kept, so it is
        # read again or shown as not saved rather than silently dropped.
        has_value = parse_number(row.value) is not None or bool(
            row.value.strip() and re.search(r'\d', row.value) and match_test(row.name))
        if row.name and not has_value and not row.range.strip():
            if rows and rows[-1].next_name == '' and rows[-1] is not pending:
                rows[-1].next_name = row.name
            pending = row
            continue
        if not has_value:
            pending = None
            continue
        if not row.name and pending:
            row.name = pending.name                  # the result printed beside a wrapped name
        elif pending:
            row.prev_name = pending.name
        pending = None
        if row.name:
            rows.append(row)
    return rows, columns


# ── PDF text layer (PyMuPDF) ─────────────────────────────────────────────────

def _cells_to_rows(table: list[list], page: int) -> list[Row]:
    """Rows of one ruled table (a list of rows of cell texts), if it has a recognised header row."""
    names = _header_names()
    for h, header in enumerate(table):
        roles = {}
        for i, cell in enumerate(header):
            phrase = _flat(cell or '')
            role = next((r for r, opts in names.items() if phrase in opts and r not in roles.values()), None)
            if role:
                roles[i] = role
        if 'value' in roles.values() and len(roles) >= 2:
            break
    else:
        return []
    col = {role: i for i, role in roles.items()}
    rows = []
    for cells in table[h + 1:]:
        get = {role: (cells[i] or '') if i < len(cells) else '' for role, i in col.items()}
        parts = {role: text.split('\n') for role, text in get.items()}
        n = len(parts.get('value', ['']))
        if n > 1 and all(len(p) in (n, 1) for p in parts.values()):
            lines = [{role: (p[k] if len(p) == n else (p[0] if k == 0 else '')) for role, p in parts.items()}
                     for k in range(n)]                       # several tests in one ruled cell
        else:
            lines = [{role: ' '.join(p) for role, p in parts.items()}]
        for line in lines:
            row = Row(name=line.get('name', '').strip(' :-–'), value=line.get('value', ''),
                      unit=line.get('unit', ''), range=line.get('range', ''), page=page)
            if row.name and parse_number(row.value) is not None:
                rows.append(row)
    return rows


def _ruled_tables(pdf_page) -> list[list[list]]:
    """The ruled tables PyMuPDF finds on a page, as rows of cell texts."""
    if pdf_page is None:
        return []
    try:
        return [t.extract() for t in pdf_page.find_tables().tables]
    except Exception as exc:                          # a page PyMuPDF cannot analyse
        logger.warning('Table detection failed on page %d: %s', pdf_page.number + 1, type(exc).__name__)
        return []


def _text_page_rows(pdf_page, page, columns) -> tuple[list[Row], str, dict | None]:
    """Rows of a page read from its own text: ruled tables, else columns found from the
    header, else text lines. Returns the rows, the method and the header seen."""
    found = [r for t in _ruled_tables(pdf_page) for r in _cells_to_rows(t, page.number)]
    if found:
        return found, PDF_TABLE, columns
    words = [(*w[:5], None) for w in page.words]
    found, columns = rows_from_words(words, page.number, columns)
    if found:
        return found, PDF_COLUMNS, columns
    found = rows_from_lines(page.text, page.number)
    return found, PDF_LINES if found else '', columns


# ── Plain text lines (fallback) ──────────────────────────────────────────────

_LINE = re.compile(
    rf'^\s*(?P<name>[A-Za-z(][^\n]*?)\s*[:=]?\s+(?P<value>(?:{_FLAG}\s+)?(?:[<>]=?\s?)?(?:{_NUMBER}))(?=\s|$)'
    r'(?P<rest>[^\n]*)$', re.IGNORECASE)


def rows_from_lines(text: str, page: int = 1) -> list[Row]:
    """Rows from text with one test per line: "Sodium  137.4  mmol/L  135 - 145"."""
    rows = []
    for line in (text or '').splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        ref, leftover = parse_range(m.group('rest'))
        rows.append(Row(name=m.group('name').strip(' :-–'), value=m.group('value'), unit=unit_from_text(leftover),
                        range=m.group('rest') if ref else '', page=page))
    return rows


# ── OCR word boxes ───────────────────────────────────────────────────────────

def _reread_numeric(rows: list[Row], images: dict) -> None:
    """Read each result (and range) cell again as digits only, and keep the better
    reading: the one with a decimal point when the digits are otherwise the same
    (OCR drops dots, it does not invent them), else the more confident one. When the
    two readings disagree on the digits the value is marked for review. Each result is
    then read a third time, enlarged (_check_enlarged)."""
    from apps.lab_reports.ocr_service import ocr_numeric_cell

    for row in rows:
        image = images.get(row.page)
        if image is None:
            continue
        if row.value_box:
            text, conf = ocr_numeric_cell(image, row.value_box)
            old, new = parse_number(row.value), parse_number(fix_ocr_digits(text))
            if new and old != new and (conf or 0) >= MIN_CELL_CONFIDENCE:
                digits_same = re.sub(r'\D', '', old or '') == re.sub(r'\D', '', new)
                if old is None or (digits_same and '.' in new and '.' not in old):
                    row.value, row.confidence = new, conf
                elif not digits_same:
                    kept = new if row.confidence is None or conf > row.confidence else old
                    row.notes.append(_reason(review.READINGS_DIFFER,
                                             f'Two readings of this result differed ({old} / {new}); {kept} was '
                                             'kept. Check it against the scan.'))
                    if kept == new:
                        row.value, row.confidence = new, conf
            if not any(n['code'] == review.READINGS_DIFFER for n in row.notes):
                _check_enlarged(row, image)
        if row.range_box:
            text, conf = ocr_numeric_cell(image, row.range_box)
            text = fix_ocr_digits(text)
            new, _rest = parse_range(text)
            old, _rest = parse_range(row.range)
            if new and (conf or 0) >= MIN_CELL_CONFIDENCE and (
                    old is None or (new.text != old.text and _same_digits(new, old))):
                row.range, row.range_confidence = text, conf
            elif old is not None and new is not None and new.text == old.text:
                row.range_confidence = max(row.range_confidence or 0, conf or 0)
                if row.range_confidence < MIN_RANGE_CONFIDENCE:
                    # Tesseract scores "-" and short numbers low even when they are right, so a
                    # range read the same way three times (whole page, digits-only cell, cell
                    # enlarged) is used. Two agreeing readings are not enough: on a poor scan
                    # both can read "0.6-1.1" as "0.6-1.4".
                    big, _rest = parse_range(fix_ocr_digits(ocr_numeric_cell(image, row.range_box, scale=2.0)[0]))
                    if big is not None and big.text == old.text:
                        row.range_confidence = MIN_RANGE_CONFIDENCE


def _check_enlarged(row: Row, image) -> None:
    """Read the result cell once more at twice the size. Two readings that agree can still
    both be wrong (a small "1" read as "4" twice), and an enlarged cell often shows a tight
    decimal point. A confident enlarged reading that adds the missing dot is used; one that
    differs otherwise is shown beside the kept value. Either way the value must be confirmed."""
    from apps.lab_reports.ocr_service import ocr_numeric_cell

    current = parse_number(row.value)
    if not current or not row.value_box:
        return
    text, conf = ocr_numeric_cell(image, row.value_box, scale=2.0)
    big = parse_number(fix_ocr_digits(text))
    if not big or big == current or (conf or 0) < MIN_CELL_CONFIDENCE:
        return
    if '.' not in current and '.' in big and re.sub(r'\D', '', big) == current:
        row.value, row.confidence = big, conf
        row.notes.append(_reason(
            review.DECIMAL_POINT,
            f'Read as {current} at first and as {big} when the cell was read again larger: '
            'the decimal point is faint on the scan. Please confirm.', value=big))
    else:
        row.notes.append(_reason(
            review.READINGS_DIFFER,
            f'Two readings of this result differed ({current} / {big}); {current} was kept. '
            'Check it against the scan.'))


def _same_digits(a: ReferenceRange, b: ReferenceRange) -> bool:
    return re.sub(r'\D', '', a.text) == re.sub(r'\D', '', b.text)


def _ocr_page_rows(page, columns) -> tuple[list[Row], str, dict | None]:
    found, columns = rows_from_words(page.words, page.number, columns)
    if found:
        return found, OCR_COLUMNS, columns
    found = rows_from_lines(page.text, page.number)
    for row in found:
        row.ocr = True
    return found, TEXT_LINES if found else '', columns


def _read_pages(raw: bytes, ext: str, pages) -> TableRead:
    """Rows from every page, each read the way ocr_service read it."""
    doc = None
    if ext == '.pdf' and any(p.source == 'text_layer' for p in pages):
        try:
            doc = pymupdf.open(stream=raw, filetype='pdf')
        except Exception as exc:                      # pragma: no cover - ocr_service opened it already
            logger.warning('PyMuPDF could not reopen the report: %s', type(exc).__name__)
    rows: list[Row] = []
    methods: list[str] = []
    columns, last_source = None, None
    try:
        for page in pages:
            if page.source != last_source:
                columns = None              # PDF points vs OCR pixels: a header does not carry over
            last_source = page.source
            if page.source == 'text_layer':
                pdf_page = doc[page.number - 1] if doc is not None and page.number <= doc.page_count else None
                found, method, columns = _text_page_rows(pdf_page, page, columns)
            else:
                found, method, columns = _ocr_page_rows(page, columns)
            if found:
                rows.extend(found)
                methods.append(method)
    finally:
        if doc is not None:
            doc.close()
    ocr_rows = [r for r in rows if r.ocr]
    if ocr_rows:
        _reread_numeric(ocr_rows, {p.number: p.image for p in pages if p.image is not None})
    return TableRead('+'.join(dict.fromkeys(methods)), rows)


def read_rows(raw: bytes, ext: str, ocr) -> TableRead:
    """The table rows of a report (see the module docstring for the order tried)."""
    pages = getattr(ocr, 'pages', None) or []
    if pages:
        found = _read_pages(raw, ext, pages)
        if found.rows:
            return found
    rows = rows_from_lines(ocr.text)
    for row in rows:
        row.ocr = ocr.source != 'text_layer'
    return TableRead(TEXT_LINES if rows else '', rows)


# ── Rows → values ────────────────────────────────────────────────────────────

def _reason(code: str, message: str, **extra) -> dict:
    return {'code': code, 'message': message, **extra}


def _match(row: Row) -> str | None:
    key = match_test(row.name)
    if key:
        return key
    for combined in (f'{row.prev_name} {row.name}', f'{row.name} {row.next_name}'):
        if combined.strip() != row.name:
            key = match_test(combined)
            if key:
                return key
    return None


def _plausible(key: str, value: float, unit: str) -> bool:
    bounds = _PLAUSIBLE_RANGES.get(key)
    converted = convert(key, repr(value), unit)
    if bounds is None or converted.value is None:
        return bounds is None
    return bounds[0] <= float(converted.value) <= bounds[1]


def _range_plausible(key: str, ref: ReferenceRange, unit: str) -> bool:
    """A printed range should overlap the test's plausible values; "35-51" for potassium
    is a misread range (decimal points lost), not one to check against."""
    bounds = _PLAUSIBLE_RANGES.get(key)
    if bounds is None:
        return True
    lo = ref.low if ref.low is not None else ref.high
    hi = ref.high if ref.high is not None else ref.low
    conv_lo, conv_hi = convert(key, repr(lo), unit), convert(key, repr(hi), unit)
    if conv_lo.value is None or conv_hi.value is None:
        return True                                    # unknown unit: the unit check reports it
    return float(conv_lo.value) <= bounds[1] * 1.5 and float(conv_hi.value) >= bounds[0] / 1.5


def decimal_fix(key: str, raw: str, ref: ReferenceRange | None, unit: str) -> str | None:
    """For a whole number read from a scan: the same digits with the decimal point OCR
    probably lost ("41" → "4.1", "441" → "4.41"), when the reading is outside the row's
    own range and value/10 or value/100 fits it. Without a usable range, only a reading
    with more digits than any plausible value can have is corrected (as in
    validator.decimal_suggestion: haemoglobin "134" → 13.4, but "45" may be another misread),
    and only when exactly one candidate is plausible. None otherwise."""
    if not re.fullmatch(r'\d{2,}', raw or ''):
        return None
    n = int(raw)
    candidates = [(f'{raw[:-k]}.{raw[-k:]}' if len(raw) > k else f'0.{raw.zfill(k)}', n / 10 ** k) for k in (1, 2)]
    if ref is not None and ref.low is not None and ref.high is not None:
        if ref.low <= n <= ref.high:
            return None
        for text, x in candidates:
            if ref.low <= x <= ref.high and _plausible(key, x, unit):
                return text
        return None
    bounds = _PLAUSIBLE_RANGES.get(key)
    converted = convert(key, raw, unit).value
    if bounds is None or converted is None or _plausible(key, n, unit):
        return None
    if len(str(int(float(converted)))) <= len(str(int(bounds[1]))):
        return None
    plausible = [text for text, x in candidates if _plausible(key, x, unit)]
    return plausible[0] if len(plausible) == 1 else None


# OCR misreads or drops the "^" of a count unit ("10%3/uL", "*10�6/ul", "103/uL"); such a
# unit is shown in the test's own spelling when it means the same unit.
_GARBLED_UNIT = re.compile(r'''[^\x20-\x7eµμ³]|10[%°'"`~]|^[*x×]?10\d{1,2}/''')


def _display_unit(key: str, unit: str) -> str:
    canonical = lab_config.canonical_units().get(key, '')
    if canonical and _GARBLED_UNIT.search(unit) and normalise_unit(unit) == normalise_unit(canonical):
        return canonical
    return unit


def _to_field(key: str, row: Row, source: str = '') -> ExtractedField:
    """``source`` is the document's (ocr_service): in a 'mixed' one, each row says whether
    it was read by OCR; in an 'ocr' one, every row was."""
    ocr = row.ocr or source == 'ocr'
    value = parse_number(row.value) or row.value.strip()
    unit = _display_unit(key, clean_unit(row.unit))
    ref, leftover = parse_range(row.range)
    if ref is not None and row.range_confidence is not None and row.range_confidence < MIN_RANGE_CONFIDENCE:
        ref = None                                     # too unsure of a scanned range to show or use it
    if not unit and ref is not None and leftover:
        unit = unit_from_text(leftover)                # "135 - 145 mmol/L" in one cell
    reasons = list(row.notes)
    # A range that cannot be read is shown as "range not read" (never replaced by a
    # default range). One that was read but cannot be right for this test is a misread.
    if ref is not None and not _range_plausible(key, ref, unit):
        reasons.append(_reason(review.RANGE_MISREAD,
                               f'The reference range was read as "{ref.text}", which does not fit this test, '
                               'so it was not used. Check the value against the scan.'))
        ref = None
    if ref is not None:
        ref.unit = unit
    ef = ExtractedField(
        field_name=display_name(key), patient_field=key, extracted_value=value[:255], unit=unit,
        reference_range=ref.text[:100] if ref else '', confidence='high', raw_match=row.name,
        ocr_confidence=row.confidence if ocr else 100.0,
        printed_name=row.name[:100],
    )
    if ocr and not any(r['code'] == review.DECIMAL_POINT for r in reasons):
        fix = decimal_fix(key, value, ref, unit)
        if fix:
            ef.suggested_value = fix
            reasons.append(_reason(review.DECIMAL_POINT,
                                   f'Auto-corrected from {value} to {fix}: a decimal point was probably lost when '
                                   'the scan was read. Please confirm.', value=fix))
    ef.review_reasons = reasons
    return ef


def _looks_like_test_row(row: Row) -> bool:
    """An unrecognised row worth listing on the review screen: it has a range or a unit,
    not a footer or a "Date: 2026-07-26 14:46" line that happens to hold a number."""
    return parse_range(row.range)[0] is not None or bool(unit_from_text(row.unit))


def to_values(read: TableRead, source: str = '') -> TableValues:
    """ExtractedFields for the rows whose name is a known test; the others are unmatched.
    Two rows read as the same test with different values are a conflict: the first is
    kept and must be confirmed, the second is listed as not saved."""
    out = TableValues(read.method)
    by_key: dict[str, ExtractedField] = {}
    for row in read.rows:
        key = _match(row)
        printed = {'name': row.name[:100], 'value': row.value.strip()[:40], 'unit': clean_unit(row.unit),
                   'range': row.range.strip()[:60]}
        if not key:
            if read.method in (TEXT_LINES, PDF_LINES) and not row.range:
                continue                               # free text with a number, not a test row
            logger.info('Lab report row not recognised as a known test: %r', row.name[:60])
            if _looks_like_test_row(row):
                out.unmatched.append({**printed, 'reason': 'Not a recognised test name.'})
            continue
        ef = _to_field(key, row, source)
        first = by_key.get(key)
        if first is None:
            by_key[key] = ef
            out.values.append(ef)
            continue
        if (first.extracted_value, first.reference_range) == (ef.extracted_value, ef.reference_range):
            continue                                   # the same row printed twice (e.g. a repeated page)
        logger.info('Two report rows were read as the same test (%s).', key)
        first.review_reasons.append(_reason(
            review.CONFLICT,
            f'Two rows on this report were read as {first.field_name}: "{first.printed_name}" '
            f'{first.extracted_value} and "{ef.printed_name}" {ef.extracted_value}. Check which one is correct.'))
        out.unmatched.append({**printed, 'reason': f'Also read as {first.field_name}; the first row is shown above.'})
    return out


# Tests the table reader looks for (the ones with aliases). Values of other fields
# (blood group, blood pressure, height, weight ...) still come from extractor.py.
def table_tests() -> frozenset[str]:
    return frozenset(k for k, t in lab_config.tests().items() if t.get('aliases'))


LOOSE_MATCH_MESSAGE = ('This value was found by searching the report text, not read from a row of its results '
                       'table, so it may belong to another test. Check it against the scan.')


def merge_into(extracted, table: TableValues) -> None:
    """Use the table's values for the tests it found. Values the free-text extractor found
    for other table tests are kept but must be confirmed (they were not read from a row)."""
    found = {v.patient_field for v in table.values}
    tests = table_tests()
    kept = []
    for x in extracted.values:
        if x.patient_field in found:
            continue
        if x.patient_field in tests:
            x.review_reasons = list(x.review_reasons) + [_reason(review.LOOSE_MATCH, LOOSE_MATCH_MESSAGE)]
        kept.append(x)
    extracted.values = table.values + kept
    extracted.unmatched_rows = table.unmatched
    extracted.table_method = table.method


def read_values(raw: bytes, ext: str, ocr) -> TableValues:
    out = to_values(read_rows(raw, ext, ocr), ocr.source)
    # Rows read from OCR text lines (no word boxes): the confidence of the word the value
    # was read from, as for the free-text extractor (services/review.attach_confidences).
    review.attach_confidences([x for x in out.values if x.ocr_confidence is None], ocr)
    return out
