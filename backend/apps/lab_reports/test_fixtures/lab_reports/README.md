# Lab report fixtures

Sample reports and the values that must be read from them. `tests_table_reader.py`
(`FixtureTableTests`) runs every file listed in `expected_results.csv` through the real
pipeline (text layer or OCR → table reader) and compares.

## Adding a report

1. Put the PDF/PNG/JPG here. **Remove or blank out real patient details first**
   (name, ID, date of birth, phone); only the results table matters.
2. Add one row per test to `expected_results.csv`:

| column  | meaning |
|---------|---------|
| `file`  | file name in this folder |
| `test`  | test key from `config/lab_tests.json` (`potassium`, `rbc_count`, ...), or `unmatched` for a row that must be listed as not recognised (then `value` = the printed name) |
| `value` | the result as printed (after an auto-correction, the corrected value) |
| `unit`  | the unit as printed (compared case/spelling-insensitively); blank = not checked |
| `range` | `low-high`, `<high`, `>low`, or `not_read` |
| `check` | `exact`: value and range must match. `safe`: must match **or** be flagged for review (use for poor scans, where OCR may misread but must never pass a wrong value silently). `review`: must match and be flagged for review |

Every test the report yields must be listed (an unexpected extra test fails the run, so
a mis-matched row is caught). Scans are skipped when Tesseract is not installed.

3. Run: `venv/Scripts/python.exe -m pytest apps/lab_reports/tests_table_reader.py`

If a new report fails because of a spelling, add the spelling to the test's `aliases` in
`config/lab_tests.json` (or a unit to `unit_aliases` / the test's `units`) rather than
changing the code. Unmatched names are logged as
`Lab report row not recognised as a known test: '...'`.

## Synthetic files

`make_fixtures.py` builds them (run it after changing a layout):

- `hospital_a.pdf`: the layout from the original bug report (Test Name / Result / Unit /
  Reference Range, no ruling, `10^3/uL`, `*10^6/ul`, an `L` flag).
- `hospital_a_scanned.pdf`: the same page as an image only (200 DPI), so OCR is used.
- `hospital_a_lowres_scan.pdf`: a poor 100 DPI scan, where full-page OCR reads 4.1 as
  "41"; checked with `safe`.
- `lab_b_investigation.pdf`: Investigation / Observed Value / Biological Ref. Interval /
  Units (range before unit), `7,500 /cumm`, `lakhs/cumm`, a decimal comma, a wrapped
  name, a two-range cell, an unknown test.
- `lab_c_ruled.pdf`: a ruled table (PyMuPDF `find_tables`) with two rows that are
  the same test (a conflict).
- `hospital_a_scan_300dpi.pdf`: a clean 300 DPI image-only scan. Two readings of RBC can
  both say "4.44" here; the enlarged third reading must flag it (`safe`).
- `hospital_print_to_pdf.pdf`: a two-page hospital web report (Examination / Result /
  Unit / Reference Range, the patient box repeated on page 2, signatures and a URL
  footer) saved the way "Microsoft Print to PDF" saves it: the letters are vector
  outlines, so there is **no text layer** even though it looks typed, and it is OCR'd.
- `mixed_text_and_scan.pdf`: page 1 typed (text layer), page 2 a scanned image of another
  layout (Parameter / Value / Units / Normal Range). Each page is read its own way.

## Checking a real report without adding it

    venv/Scripts/python.exe manage.py check_lab_report "C:\path\to\report.pdf" --patient <username>

prints the text read, how each page was read, and every value with its unit, range and
review reasons. Nothing is saved.
