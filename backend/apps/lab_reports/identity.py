"""Identity check for uploaded lab reports.

Before any value from a report is applied, the patient named on the report
must be the patient whose record is being updated: the name must match
(ignoring case, titles such as Mr./Dr. and small OCR errors) and a printed date
of birth must agree. The age is not read or compared. Nothing found on the report is stored
or logged by this module; only the outcome and a generic reason are returned.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime

from django.conf import settings

# Titles and honorifics printed before names on Nepali and international reports.
_TITLES = {
    'mr', 'mrs', 'ms', 'miss', 'mx', 'dr', 'prof', 'master', 'mstr', 'baby', 'bby', 'smt', 'shri',
    'sri', 'kumari', 'km', 'late', 'sir', 'madam', 'md', 'b/o', 'bo',
}

# Separators printed (or misread by OCR) between a label and its value.
_SEP = r'[ \t]*[:\-–.;|=]*[ \t]*'

# Words that end a name on the same line ("Name: Hari Tamang  Age: 34").
_NAME_STOP = (
    r'(?=\s{2,}|\s+(?:age|sex|gender|dob|d\.o\.b|date|ref|referred|reg|registration|id|uhid|'
    r'mrn|patient\s*id|lab\s*no|sample|collected|received|reported|contact|phone|mobile|address|'
    r'bill|ward|bed|opd|ipd)\b|[|,;]|\d|$)'
)
# Multi-word labels are unambiguous; a bare "Name"/"Patient" only counts when
# a separator follows it (otherwise "Patient Copy" would read as a name).
_STRONG_LABEL = r"patient(?:'s)?\s*na(?:me|rne)|name\s*of\s*(?:the\s*)?patient|pt\.?\s*na(?:me|rne)"
_WEAK_LABEL = r'patient|na(?:me|rne)'
_NAME_RE = re.compile(
    rf"(?<![a-z])(?P<label>{_STRONG_LABEL}|{_WEAK_LABEL})(?![a-z])(?P<sep>{_SEP})(?P<name>[^\n]*?)" + _NAME_STOP,
    re.IGNORECASE,
)
_STRONG_LABEL_RE = re.compile(rf'^(?:{_STRONG_LABEL})$', re.IGNORECASE)

# A name belongs to someone else when one of these labels comes right before it.
_NOT_PATIENT = re.compile(r'\b(?:ref(?:erred|\.)?|doctor|dr\.?\s*name|consultant|physician|'
                          r'technician|technologist|pathologist|lab\s*name|hospital|signature|'
                          r'father|mother|husband|guardian|s\s*/\s*o|d\s*/\s*o|w\s*/\s*o|c\s*/\s*o)\b',
                          re.IGNORECASE)
# "Dr. Hari Tamang" in free text is a doctor, not the patient.
_DOCTOR_TITLE = re.compile(r'\bdr\.?\s*$', re.IGNORECASE)
# A line that is itself a label (so it is not the value printed under another label).
_LABEL_LINE = re.compile(r'\b(?:age|sex|gender|ref|referred|by|date|dob|id|no|lab|sample|collected|received|'
                         r'reported|doctor|dr|consultant|address|phone|mobile|contact|bill|ward|bed|uhid|mrn|'
                         r'reg|registration|specimen|test|investigation|result|unit)\b', re.IGNORECASE)
# Relationship markers that end a name: "Hari Tamang S/O Ram Tamang".
_RELATION = re.compile(r'\b[sdwc]\s*/\s*o\b.*$', re.IGNORECASE)
_SEX_WORDS = {'m', 'f', 'male', 'female', 'other'}

_DOB_RE = re.compile(
    rf'(?:d\.?\s*o\.?\s*b\.?|date\s+of\s+birth|birth\s*date){_SEP}(?P<date>[^\n]{{6,20}})', re.IGNORECASE)
# The report date is the REPORTING date. The collection / sample date is used only
# when no reporting date is printed. Registration, printed and birth dates are never used.
_REPORTING_DATE_RE = re.compile(
    r'(?<![a-z])(?:report(?:ed|ing)?\s*(?:date|on)|date\s*of\s*report(?:ing)?)'
    rf'{_SEP}(?P<date>[^\n]{{6,22}})',
    re.IGNORECASE,
)
_COLLECTION_DATE_RE = re.compile(
    r'(?<![a-z])(?:collect(?:ed|ion)\s*(?:date|on)|sample\s*(?:date|collected(?:\s*on)?)|'
    r'date\s*of\s*(?:collection|sample))'
    rf'{_SEP}(?P<date>[^\n]{{6,22}})',
    re.IGNORECASE,
)
REPORTING, COLLECTION = 'reporting', 'collection'

_MONTHS = {m: i for i, m in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'], start=1)}


@dataclass
class ReportIdentity:
    # Names printed after a clear "Patient Name"-style label, and after a bare "Name".
    strong_names: list[str] = field(default_factory=list)
    weak_names: list[str] = field(default_factory=list)
    dob: date | None = None
    report_date: date | None = None
    report_date_source: str = ''      # 'reporting' or 'collection' (which label the date came from)
    # The report's lines, kept in memory only for the name search; never stored.
    lines: list[str] = field(default_factory=list, repr=False)

    @property
    def name(self) -> str | None:
        return (self.strong_names or self.weak_names or [None])[0]


@dataclass
class IdentityResult:
    verified: bool
    reason: str = ''              # safe to show to the user; never contains report contents


# ── Extraction ────────────────────────────────────────────────────────────────

def extract_identity(text: str, today: date | None = None) -> ReportIdentity:
    today = today or date.today()
    lines = [ln for ln in (text or '').splitlines()]
    found = ReportIdentity(lines=lines)
    reporting = collection = None

    for i, line in enumerate(lines):
        for m in _NAME_RE.finditer(line):
            if _NOT_PATIENT.search(line[max(0, m.start() - 25):m.start()]):
                continue
            strong = bool(_STRONG_LABEL_RE.match(m.group('label').strip())) or bool(m.group('sep').strip())
            after = line[m.end('sep'):].strip()
            # In a table header ("Patient Name   Age / Sex") the text after the
            # label is the next column heading, not a name.
            header_row = bool(_LABEL_LINE.match(after))
            name = '' if header_row else _clean_name(m.group('name'))
            if not name and (not after or header_row):
                # The value is printed below the label (next line or next table row).
                name, from_sep = _name_below(lines, i)
                strong = strong or from_sep
            if name:
                (found.strong_names if strong else found.weak_names).append(name)

        if found.dob is None:
            m = _DOB_RE.search(line)
            if m:
                found.dob = parse_date(m.group('date'), today)
        # These labels always name the report or the sample, never the date of birth,
        # so a line that also prints "DOB:" is still read.
        if reporting is None:
            m = _REPORTING_DATE_RE.search(line)
            if m:
                reporting = parse_date(m.group('date'), today)
        if collection is None:
            m = _COLLECTION_DATE_RE.search(line)
            if m:
                collection = parse_date(m.group('date'), today)

    if reporting is not None:
        found.report_date, found.report_date_source = reporting, REPORTING
    elif collection is not None:
        found.report_date, found.report_date_source = collection, COLLECTION
    return found


def _name_below(lines: list[str], idx: int) -> tuple[str, bool]:
    """The first following line that looks like a value rather than another label."""
    for line in lines[idx + 1: idx + 5]:
        raw = line.strip()
        if not raw:
            continue
        value = raw.lstrip(':-–.;|= \t')
        had_sep = value != raw
        if _LABEL_LINE.search(value) and not had_sep:
            continue                      # another label in a column of labels
        if _NOT_PATIENT.search(value[:25]):
            continue
        name = _clean_name(re.split(r'\s{2,}|[|,;]|\d', value)[0])
        if name:
            return name, had_sep
    return '', False


def _clean_name(raw: str) -> str:
    raw = re.sub(r'\([^)]*\)', ' ', raw or '')       # "(M)", "(Male)"
    raw = re.sub(r'\([^)]*$', ' ', raw)              # "(PAT-" when the name was cut at the ID's digits
    raw = _RELATION.sub('', raw)                      # "S/O Ram Tamang"
    words = re.findall(r"[^\W\d_][^\W\d_'.\-]*", raw)
    words = [w.strip(".'-") for w in words]
    words = [w for w in words if w and normalise_token(w) not in _TITLES]
    while words and normalise_token(words[-1]) in _SEX_WORDS:
        words.pop()                                    # "Hari Tamang M"
    return ' '.join(words[:5])


def parse_date(raw: str, today: date | None = None) -> date | None:
    """Parse the common report date formats (day first, as used in Nepal).

    Bikram Sambat dates (years ~2070–2090) and future dates are rejected,
    since they cannot be compared with Gregorian dates of birth.
    """
    today = today or date.today()
    s = _fix_date_ocr((raw or '').strip()).lower()
    candidates: list[date] = []

    m = re.search(r'(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})', s)               # 2026-09-14
    if m:
        candidates.append(_safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
    m = re.search(r'(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})', s)              # 14/09/2026
    if m:
        first, second, y = int(m.group(1)), int(m.group(2)), _year(m.group(3))
        d, mo = (second, first) if date_order() == 'MDY' else (first, second)
        if mo > 12 and d <= 12:
            d, mo = mo, d                                                   # unambiguous the other way round
        candidates.append(_safe_date(y, mo, d))
    m = re.search(r'(\d{1,2})[\s\-/.]*([a-z]{3})[a-z]*[\s\-/.,]*(\d{2,4})', s)  # 14 Sep 2026
    if m and m.group(2) in _MONTHS:
        candidates.append(_safe_date(_year(m.group(3)), _MONTHS[m.group(2)], int(m.group(1))))
    m = re.search(r'([a-z]{3})[a-z]*[\s\-/.]*(\d{1,2})[\s,]+(\d{4})', s)       # Sep 14, 2026
    if m and m.group(1) in _MONTHS:
        candidates.append(_safe_date(int(m.group(3)), _MONTHS[m.group(1)], int(m.group(2))))

    for c in candidates:
        if c and date(1900, 1, 1) <= c <= today:
            return c
    return None


def date_order() -> str:
    """'DMY' (day first, the default in Nepal) or 'MDY', from LAB_REPORT_DATE_ORDER."""
    order = str(getattr(settings, 'LAB_REPORT_DATE_ORDER', 'DMY')).upper()
    return order if order in ('DMY', 'MDY') else 'DMY'


# A numeric date such as "l4/O9/2O26": digits with OCR look-alikes, split by / - or .
_DATE_TOKEN = re.compile(r'(?<![A-Za-z0-9])[0-9OoIl|S]{1,4}(?:[/\-.][0-9OoIl|S]{1,4}){2}(?![A-Za-z0-9])')
_DATE_LOOKALIKES = str.maketrans({'O': '0', 'o': '0', 'I': '1', 'l': '1', '|': '1', 'S': '5'})


def _fix_date_ocr(text: str) -> str:
    """Undo O→0, I/l→1, S→5 only inside numeric date tokens (month names are untouched)."""
    def fix(m):
        token = m.group(0)
        return token.translate(_DATE_LOOKALIKES) if sum(ch.isdigit() for ch in token) >= 2 else token
    return _DATE_TOKEN.sub(fix, text)


def _year(text: str) -> int:
    y = int(text)
    return y + 2000 if y < 100 else y


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


# ── Comparison ────────────────────────────────────────────────────────────────

def normalise_token(word: str) -> str:
    ascii_word = unicodedata.normalize('NFKD', word).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-z]', '', ascii_word.lower())


def name_tokens(name: str) -> list[str]:
    tokens = [normalise_token(w) for w in re.split(r"[\s.'\-]+", name or '')]
    return [t for t in tokens if t and t not in _TITLES]


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def tokens_match(a: str, b: str) -> bool:
    """Equal, or within the OCR tolerance: 1 edit for short names, 2 for long ones."""
    if a == b:
        return True
    allowed = 1 if max(len(a), len(b)) <= 6 else 2
    return min(len(a), len(b)) >= 3 and edit_distance(a, b) <= allowed


def names_match(report_name: str, first: str, last: str, middle: str = '') -> bool:
    """First and last name must both appear on the report (in any order, with
    small OCR errors allowed). A middle name may be missing from the report.

    Extra words on the report must belong to the patient's middle name. When the
    record has no middle name, one extra word is allowed, because Nepali middle
    names (Bahadur, Prasad, Kumari...) are often left off one or the other.
    """
    report = name_tokens(report_name)
    if not report:
        return False
    first_t, last_t = name_tokens(first), name_tokens(last)
    required = first_t + last_t
    if not required:
        return False
    optional = name_tokens(middle or '')

    unused = list(range(len(report)))
    matched: list[int] = []
    for token in required:
        hit = next((i for i in unused if tokens_match(token, report[i])), None)
        if hit is None:
            return False
        unused.remove(hit)
        matched.append(hit)
    if not optional:
        # At most one extra word, and only between the first and last names
        # ("Hari Bahadur Tamang"), never added on ("Hari Tamang Sharma").
        return not unused or (len(unused) == 1 and min(matched) < unused[0] < max(matched))
    return all(any(tokens_match(o, report[i]) for o in optional) for i in unused)


def find_name_in_text(lines: list[str], first: str, last: str, middle: str = '') -> bool:
    """Is the patient's name printed anywhere, not right after a doctor/referrer label?

    Used when the report has no recognisable "Name:" label (for example a digital
    PDF whose labels and values come out in separate columns).
    """
    size = len(name_tokens(f'{first} {last}'))
    longest = size + len(name_tokens(middle or ''))
    for line in lines:
        words = list(re.finditer(r"[^\W\d_]+", line))
        for i in range(len(words)):
            for n in range(size, longest + 1):
                window = words[i:i + n]
                if len(window) < n:
                    break
                before = line[max(0, window[0].start() - 25):window[0].start()]
                if _NOT_PATIENT.search(before) or _DOCTOR_TITLE.search(before):
                    continue
                if names_match(' '.join(w.group() for w in window), first, last, middle):
                    return True
    return False


def verify_identity(found: ReportIdentity, patient, today: date | None = None) -> IdentityResult:
    """Compare what the report says with the patient record."""
    first, middle, last = patient.first_name, patient.middle_name or '', patient.last_name
    if not name_tokens(f'{first} {last}'):
        return IdentityResult(False, (
            "The patient's name in Mero Care Card is not written in English letters, so it cannot be "
            "checked against the report. Ask an administrator to update the name or enter the values."
        ))

    labelled = found.strong_names + found.weak_names
    if any(names_match(n, first, last, middle) for n in labelled):
        pass
    elif found.strong_names:
        # The report clearly names someone else.
        return IdentityResult(False, "The name on the report does not match this patient's name. "
                                     "No values were updated.")
    elif not find_name_in_text(found.lines, first, last, middle):
        return IdentityResult(False, (
            "This patient's name could not be found on the report. Check that it is the right report and "
            "that the name is printed clearly. If the name on file is spelt differently from the report, "
            "update it in your profile first."
        ))

    if found.dob is not None and found.dob != patient.dob:
        return IdentityResult(False, "The date of birth on the report does not match this patient. "
                                     "No values were updated.")
    return IdentityResult(True)


def effective_date(report_date: date | None, uploaded: datetime) -> date:
    return report_date or uploaded.date()
