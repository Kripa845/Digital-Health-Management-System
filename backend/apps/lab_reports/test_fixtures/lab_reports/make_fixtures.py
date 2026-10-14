"""Build the synthetic sample reports in this folder (run from backend/):

    venv/Scripts/python.exe apps/lab_reports/test_fixtures/lab_reports/make_fixtures.py

The PDFs are committed, so this only needs running after changing a layout here.
Real reports (anonymised) can be dropped in next to them: add their expected values
to expected_results.csv and tests_table_reader.py picks them up.
"""
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent
A4 = (595, 842)


def _page(doc):
    return doc.new_page(width=A4[0], height=A4[1])


def _text(page, x, y, text, size=9.5, bold=False):
    page.insert_text((x, y), text, fontsize=size, fontname='hebo' if bold else 'helv')


def _patient_block(page, lab, y=50):
    _text(page, 40, y, lab, 14, bold=True)
    _text(page, 40, y + 16, 'Kathmandu, Nepal  |  Tel 01-4000000  |  SAMPLE REPORT - NOT A REAL PATIENT', 8)
    _text(page, 40, y + 40, 'Patient Name : Ms. Test Patient')
    _text(page, 330, y + 40, 'Patient ID : PAT-0E2E0001')
    _text(page, 40, y + 54, 'Age/Sex : 34 Y / F')
    _text(page, 330, y + 54, 'Reported On : 14/09/2026')
    return y + 85


def hospital_a():
    """Mimics the report from the bug: Test Name | Result | Unit | Reference Range, no
    ruling, section titles, an L flag beside a low result, count units with ^ and *."""
    doc = pymupdf.open()
    page = _page(doc)
    y = _patient_block(page, 'SAMPLE HOSPITAL A - DEPARTMENT OF LABORATORY MEDICINE')
    cols = (40, 250, 330, 430)
    for x, title in zip(cols, ('Test Name', 'Result', 'Unit', 'Reference Range')):
        _text(page, x, y, title, bold=True)
    y += 20
    sections = [
        ('BIOCHEMISTRY', [
            ('Sodium', '137.4', '', 'mmol/L', '135 - 145'),
            ('Potassium', '4.1', '', 'mmol/L', '3.5 -5.1'),
            ('Bilirubin Direct', '0.19', '', 'mg/dL', '0 - 0.2'),
            ('Bilirubin Total', '0.8', '', 'mg/dL', '0.3-1.2'),
            ('SGPT (ALT)', '18.89', '', 'U/L', '10 - 56'),
            ('Urea', '13.81', '', 'mg/dL', '13 - 43'),
            ('Creatinine', '0.5', 'L', 'mg/dL', '0.6 - 1.1'),
            ('Glucose Random', '96.32', '', 'mg/dL', '70 - 140'),
        ]),
        ('HAEMATOLOGY', [
            ('Haemoglobin', '13.13', '', 'g/dL', '12 - 15'),
            ('Haematocrit (PCV)', '38.5', '', '%', '36 - 46'),
            ('Platelet Count', '277.2', '', '10^3/uL', '150 - 400'),
            ('RBC Count', '4.41', '', '*10^6/ul', '3.8 - 4.8'),
        ]),
    ]
    for title, rows in sections:
        _text(page, 40, y, title, bold=True)
        y += 16
        for name, value, flag, unit, ref in rows:
            _text(page, cols[0], y, name)
            _text(page, cols[1], y, value, bold=bool(flag))
            if flag:
                _text(page, cols[1] + 28, y, flag, bold=True)
            _text(page, cols[2], y, unit)
            _text(page, cols[3], y, ref)
            y += 15
        y += 8
    _text(page, 40, y + 20, 'Note: results outside the reference range are marked H (high) or L (low).', 8)
    _text(page, 40, y + 32, 'Values above 3 times the upper limit are re-checked before release.', 8)
    doc.save(HERE / 'hospital_a.pdf')
    return doc


def lab_b():
    """Different lab: Investigation | Observed Value | Biological Ref. Interval | Units
    (range before unit), Indian digit grouping, a decimal comma, a wrapped test name,
    a two-range cell, an unknown test and a non-numeric result."""
    doc = pymupdf.open()
    page = _page(doc)
    y = _patient_block(page, 'SAMPLE DIAGNOSTICS B')
    cols = (40, 235, 330, 480)
    for x, title in zip(cols, ('Investigation', 'Observed Value', 'Biological Ref. Interval', 'Units')):
        _text(page, x, y, title, bold=True)
    y += 20
    rows = [
        ('Total Leucocyte Count (TLC)', '7,500', '4,000 - 11,000', '/cumm'),
        ('Platelet Count', '2.5', '1.5 -  4.0', 'lakhs/cumm'),
        ('Haemoglobin', '12.6', 'M: 13 - 17  F: 12 - 15', 'g/dL'),
        ('Fasting Blood Sugar', '92', '70 to 110', 'mg/dL'),
        ('Glucose PP', '128', '70 - 140', 'mg/dL'),
        ('Cholesterol, Total', '186', '< 200', 'mg/dL'),
        ('S. Creatinine', '1,2', '0.6 - 1.3', 'mg/dL'),
        ('Thyroid Stimulating', '2.5', '0.4 - 4.0', 'µIU/mL'),
        ('Hormone', '', '', ''),
        ('Blood Group', 'B Positive', '', ''),
    ]
    for name, value, ref, unit in rows:
        for x, text in zip(cols, (name, value, ref, unit)):
            if text:
                _text(page, x, y, text)
        y += 15
    doc.save(HERE / 'lab_b_investigation.pdf')
    return doc


def lab_c_ruled():
    """A ruled table (PyMuPDF find_tables): Parameter | Result | Units | Normal Range,
    and two rows that are the same test with different results (a conflict)."""
    doc = pymupdf.open()
    page = _page(doc)
    y = _patient_block(page, 'SAMPLE CLINIC C')
    cols = (40, 220, 300, 400, 540)
    rows = [('Parameter', 'Result', 'Units', 'Normal Range'),
            ('Sodium (Na+)', '141', 'mEq/L', '136-145'),
            ('Potassium (K+)', '3.9', 'mEq/L', '3.5-5.0'),
            ('HbA1c', '6.1', '%', '4.0-5.6'),
            ('Uric Acid', '5.4', 'mg/dL', '2.4-6.0'),
            ('Glucose Random', '110', 'mg/dL', '70-140'),
            ('RBS', '150', 'mg/dL', '70-140')]
    top = y - 12
    for i, row in enumerate(rows):
        for x, text in zip(cols, row):
            _text(page, x + 4, top + 12 + i * 18, text, bold=i == 0)
    bottom = top + 18 * len(rows)
    for i in range(len(rows) + 1):
        page.draw_line((cols[0], top + i * 18 - 2), (cols[-1], top + i * 18 - 2), width=0.6)
    for x in cols:
        page.draw_line((x, top - 2), (x, bottom - 2), width=0.6)
    doc.save(HERE / 'lab_c_ruled.pdf')
    return doc


def scanned(source: pymupdf.Document, name: str, dpi: int = 200):
    """An image-only copy (no text layer), as a scanner or "print to image" produces."""
    out = pymupdf.open()
    for page in source:
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        new = out.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, stream=pix.tobytes('png'))
    out.save(HERE / name)


def outlined(source: pymupdf.Document) -> pymupdf.Document:
    """A copy whose letters are vector outlines with no text layer, as "Microsoft Print to
    PDF" saves a web page: sharp when rendered, but get_text() finds nothing."""
    out = pymupdf.open()
    for page in source:
        svg = page.get_svg_image(text_as_path=True)
        with pymupdf.open('svg', svg.encode()) as vector:
            out.insert_pdf(pymupdf.open('pdf', vector.convert_to_pdf()))
    return out


_LETTER = (612, 792)


def _hospital_header(page, title):
    """Letterhead and patient box as in a hospital's web report printed from a browser."""
    _text(page, 30, 22, '03/10/2026, 15:29', 8)
    _text(page, 285, 22, 'Lab Result', 8)
    _text(page, 225, 62, 'Sample Military Hospital', 13, bold=True)
    _text(page, 245, 77, 'Kathmandu, Nepal', 10, bold=True)
    _text(page, 440, 100, 'Reception Number: 000000001', 7)
    for i, (left, right) in enumerate([('Name: TEST PATIENT', 'EncID: SAMPLE-0001'),
                                       ('(PAT-0E2E0001)', 'Sample Id: SAMPLE-0001'),
                                       ('Age/: 50yrs', 'Sampled Collection: 2026-07-26 14:46:24'),
                                       ('Sex: Female', 'Reporting Date: 2026-07-26 16:17:14'),
                                       ('Referred By:', 'Verified Date: 2026-07-26 16:17:22')]):
        _text(page, 36, 125 + i * 12, left, 9)
        _text(page, 205, 125 + i * 12, right, 9)
    page.draw_rect(pymupdf.Rect(33, 114, 580, 185), width=1)
    _text(page, 280, 205, title, 8, bold=True)
    cols = (40, 305, 385, 460)
    for x, head in zip(cols, ('Examination', 'Result', 'Unit', 'Reference Range')):
        _text(page, x, 245, head, 7.5)
    page.draw_rect(pymupdf.Rect(35, 235, 580, 250), width=1)
    return cols, 270


def _hospital_rows(page, cols, y, section, rows):
    _text(page, 40, y, section, 7.5, bold=True)
    y += 17
    for name, value, unit, ref in rows:
        for x, text in zip(cols, (name, value, unit, ref)):
            if text:
                _text(page, x + (8 if x == cols[0] and name.startswith('  ') else 0), y, text.strip(), 7.5,
                      bold=x == cols[1] and value == '11.27')
        y += 17
    return y


def _hospital_footer(page, y):
    _text(page, 36, y, 'Performed By :', 8)
    _text(page, 310, y, 'Approved By :', 8)
    _text(page, 36, y + 14, 'MEDICAL LABORATORY TECHNOLOGIST', 8)
    _text(page, 310, y + 14, 'MD Pathologist   NMC: 6240', 8)
    _text(page, 30, 770, 'https://labreport.example.org/printReport2?patientid=UWXfK-sF80u0LMrITTn9EQ', 7)


def hospital_print_to_pdf():
    """The layout of a two-page hospital web report (Examination | Result | Unit |
    Reference Range, sections HAEMATOLOGY / BIOCHEMISTRY, the patient box repeated above
    the table on page 2, signatures and a URL footer), then saved with its letters as
    outlines. Mimics the report where 4.1 was read as 41 and Bilirubin Total took Bilirubin
    Direct's row."""
    doc = pymupdf.open()
    page = doc.new_page(width=_LETTER[0], height=_LETTER[1])
    cols, y = _hospital_header(page, 'Hematology')
    y = _hospital_rows(page, cols, y, 'BLOOD', [
        ('Total Leukocytes Counts (Blood)', '11.27', '10^3/uL', '4- 11'),
        ('Differential Leukocytes Count (Blood)', '', '', ''),
        ('  Neutrophil', '82.21', '', '40-75%'),
        ('  Lymphocyte', '13.21', '', '20-40%'),
        ('Haemoglobin', '13.13', 'g/dl', '12- 15'),
        ('Packed Cell Volume/ Haematocrit', '38.5', '%', '36- 46'),
        ('Platelets Count', '277.2', '10^3/uL', '150- 400'),
        ('RBC Count (Blood)', '4.41', '*10^6/ul', '3.8- 4.8'),
        ('MPV', '8.24', '', ''),
        ('Blood Grouping Rh Typing', 'A Positive', '', ''),
    ])
    _hospital_footer(page, y + 40)
    page = doc.new_page(width=_LETTER[0], height=_LETTER[1])
    cols, y = _hospital_header(page, 'Biochemistry')
    y = _hospital_rows(page, cols, y, 'SERUM', [
        ('Sodium (Serum)', '137.4', 'mEq/L', '135- 145'),
        ('Potassium (Serum)', '4.1', 'mEq/L', '3.5- 5.1'),
        ('Bilirubin Direct', '0.19', 'mg/dL', '0- 0.2'),
        ('SGPT (ALT)', '18.89', 'U/L', '10- 56'),
        ('ALP', '86.72', 'U/L', '38- 126'),
        ('Bilirubin Total', '0.8', 'mg/dL', '0.3- 1.2'),
        ('Urea (Blood)', '13.81', 'mg/dl', '13- 43'),
        ('Creatinine (Serum)', '0.5', 'mg/dl', '0.6- 1.1'),
        ('Glucose Random(Blood)', '96.32', 'mg/dl', '70- 140'),
    ])
    _hospital_footer(page, y + 40)
    outlined(doc).save(HERE / 'hospital_print_to_pdf.pdf')
    return doc


def lab_d_thyroid_lipids() -> pymupdf.Document:
    """A third layout for the scanned half of the mixed report: Parameter | Value | Units |
    Normal Range, tests that the typed page does not have."""
    doc = pymupdf.open()
    page = _page(doc)
    y = _patient_block(page, 'SAMPLE LAB D - THYROID AND LIPID PROFILE')
    cols = (40, 250, 330, 430)
    for x, title in zip(cols, ('Parameter', 'Value', 'Units', 'Normal Range')):
        _text(page, x, y, title, bold=True)
    y += 20
    for row in [('TSH', '2.85', 'uIU/mL', '0.35 - 5.5'),
                ('Total Cholesterol', '186', 'mg/dL', '< 200'),
                ('Triglycerides', '142', 'mg/dL', '< 150'),
                ('HDL Cholesterol', '48', 'mg/dL', '> 40'),
                ('Uric Acid', '5.4', 'mg/dL', '2.4 - 6.0')]:
        for x, text in zip(cols, row):
            _text(page, x, y, text)
        y += 15
    return doc


def mixed(text_source: pymupdf.Document, scan_source: pymupdf.Document, name: str, dpi: int = 300):
    """Page 1 keeps its text layer; page 2 is a scanned image (a report assembled from a
    typed page and a scanned one)."""
    out = pymupdf.open()
    out.insert_pdf(text_source, from_page=0, to_page=0)
    page = scan_source[0]
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    new = out.new_page(width=page.rect.width, height=page.rect.height)
    new.insert_image(new.rect, stream=pix.tobytes('png'))
    out.save(HERE / name)


if __name__ == '__main__':
    a = hospital_a()
    lab_b()
    lab_c_ruled()
    scanned(a, 'hospital_a_scanned.pdf')
    # A poor scan: at 100 DPI a full-page OCR reads Potassium 4.1 as "41" and Creatinine
    # 0.5 as "05" (the bug this suite guards); the cell re-read / auto-fix must recover them.
    scanned(a, 'hospital_a_lowres_scan.pdf', dpi=100)
    # A clean 300 DPI scan where the page read and the cell re-read can both read RBC
    # 4.41 as "4.44": the enlarged third reading must catch it (or read it right).
    scanned(a, 'hospital_a_scan_300dpi.pdf', dpi=300)
    hospital_print_to_pdf()
    mixed(a, lab_d_thyroid_lipids(), 'mixed_text_and_scan.pdf')
    print('Fixtures written to', HERE)
