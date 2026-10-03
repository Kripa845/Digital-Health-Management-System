"""Generate the fake lab reports used by tests and the end-to-end check.

All people, IDs and values are invented. Run from backend/:

    python samples/lab_reports/make_samples.py

The "e2e" patient (see `python manage.py seed_e2e`) is Asha Gurung,
patient ID PAT-0E2E0001, born 10 April 1992.
"""
from __future__ import annotations

import io
import pathlib

HERE = pathlib.Path(__file__).resolve().parent

MATCH_LINES = [
    'KATHMANDU VALLEY DIAGNOSTIC LABORATORY',
    'Lalitpur-3, Nepal  |  Phone 01-5550100  |  This is a sample report',
    '',
    'Patient ID : PAT-0E2E0001          Report Date : 14/09/2026',
    'Patient Name : Ms. Asha Gurung     Age/Sex : 34 Y / F',
    'Ref. By : Dr. A. Sharma            Sample : Venous blood',
    '',
    'TEST                        RESULT      UNIT       REFERENCE',
    'Haemoglobin (Hb)            12.8        g/dL       12.0-15.5',
    'T. Chol                     5.2         mmol/L     < 5.2',
    'RBS (Random Blood Sugar)    142         mg/dL      70-140',
    'Blood Group                 O +ve',
    '',
    'Results relate only to the sample tested. Fake data for software testing.',
]

MISMATCH_LINES = [line.replace('PAT-0E2E0001', 'PAT-7B31C9D2').replace('Asha Gurung', 'Rina Shrestha')
                  for line in MATCH_LINES]

REVIEW_LINES = [  # a hospital's own ID only: cannot be compared, so an admin must review
    'BIR HOSPITAL CLINICAL LABORATORY  (sample report)',
    'UHID : 2081-004512                 Date : 20/09/2026',
    'Name : Asha Gurung                 Age : 34 Years   Sex : F',
    '',
    'HGB          13.1     g/dL',
    'Total Cholesterol   188   mg/dL',
    'Random Blood Sugar  6.1   mmol/L',
    '',
    'Fake data for software testing.',
]


def text_pdf(lines: list[str]) -> bytes:
    """A minimal one-page PDF with selectable text (no extra libraries)."""
    def esc(s: str) -> str:
        return s.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')

    content = ['BT', '/F1 10 Tf', '13 TL', '50 790 Td']
    for line in lines:
        content.append(f'({esc(line)}) Tj T*')
    content.append('ET')
    stream = '\n'.join(content).encode('latin-1')

    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>',
        b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream',
    ]
    out = io.BytesIO()
    out.write(b'%PDF-1.4\n')
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f'{i} 0 obj\n'.encode() + body + b'\nendobj\n')
    xref = out.tell()
    out.write(f'xref\n0 {len(objects) + 1}\n0000000000 65535 f \n'.encode())
    for off in offsets:
        out.write(f'{off:010d} 00000 n \n'.encode())
    out.write(f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    return out.getvalue()


def image_png(lines: list[str]) -> bytes:
    from PIL import Image, ImageDraw, ImageFont
    try:
        font = ImageFont.truetype('arial.ttf', 30)
    except OSError:
        try:
            font = ImageFont.truetype('DejaVuSans.ttf', 30)
        except OSError:
            font = ImageFont.load_default(size=30)
    img = Image.new('RGB', (1500, 80 + 52 * len(lines)), 'white')
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((50, 40 + i * 52), line, fill='black', font=font)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


SAMPLES = {
    'report_match.pdf': lambda: text_pdf(MATCH_LINES),
    'report_mismatch.pdf': lambda: text_pdf(MISMATCH_LINES),
    'report_match.png': lambda: image_png(MATCH_LINES[3:12]),
    'report_needs_review.png': lambda: image_png(REVIEW_LINES),
}


def main():
    for name, make in SAMPLES.items():
        (HERE / name).write_bytes(make())
        print('wrote', HERE / name)


if __name__ == '__main__':
    main()
