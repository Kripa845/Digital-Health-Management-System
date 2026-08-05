import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
django.setup()

import re

# Test hemoglobin pattern directly
test_lines = [
    "Hemoglobin 14.2 g/dL 13.0 - 17.0 Normal",
    "Hemoglobin (Hb) 14.6 g/dL",
    "Hemoglobin: 13.5 g/dL",
    "Hb: 12.0",
    "CARDIOVASCULAR\nHemoglobin 14.2 g/dL 13.0 - 17.0 Normal",
]

patterns = [
    r'h(?:ae?moglobin)\s*(?:\([^)]*\))?\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d{1,2})?)\s*(?P<unit>g\s*/\s*d[lL]|g%)?',
    r'\bhb\b\s*[:\-=]?\s*(?P<val>\d{1,3}(?:\.\d{1,2})?)\s*(?P<unit>g\s*/\s*d[lL]|g%)?',
]

for line in test_lines:
    print(f"\nInput: {line!r}")
    for p in patterns:
        m = re.search(p, line, re.IGNORECASE)
        if m:
            print(f"  MATCH: val={m.group('val')!r}  pattern={p[:40]}")
            break
    else:
        print("  NO MATCH")
