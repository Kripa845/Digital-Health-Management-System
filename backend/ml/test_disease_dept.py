"""Checks for ml/disease_dept.py.

Run:  python -m ml.test_disease_dept     or     python -m pytest ml/test_disease_dept.py
"""
import json
from collections import Counter
from pathlib import Path

import pandas as pd

from ml.disease_dept import DISEASE_DEPARTMENT, FALLBACK_DEPARTMENT, UNCERTAIN, department_for

ML_DIR = Path(__file__).resolve().parent
DEPARTMENTS_FILE = ML_DIR.parent / 'apps' / 'recommendations' / 'data' / 'symptom_department_map.json'


def project_departments() -> set[str]:
    with open(DEPARTMENTS_FILE, encoding='utf-8') as fh:
        return set(json.load(fh)['department_rules'])


def dataset_diseases() -> list[str]:
    return sorted(pd.read_csv(ML_DIR / 'data' / 'dataset.csv')['Disease'].str.strip().unique())


def check() -> list[str]:
    problems = []
    departments = project_departments()
    diseases = dataset_diseases()
    if len(departments) != 21:
        problems.append(f'expected 21 project departments, found {len(departments)}')
    unmapped = [d for d in diseases if d not in DISEASE_DEPARTMENT]
    if unmapped:
        problems.append(f'diseases without a department: {unmapped}')
    extra = [d for d in DISEASE_DEPARTMENT if d not in diseases]
    if extra:
        problems.append(f'mapped names not in the dataset: {extra}')
    invalid = {d: dept for d, dept in DISEASE_DEPARTMENT.items() if dept not in departments}
    if invalid:
        problems.append(f'departments that do not exist in the project: {invalid}')
    if any(d not in DISEASE_DEPARTMENT for d in UNCERTAIN):
        problems.append('UNCERTAIN lists a disease that is not mapped')
    if department_for('Some unknown illness') != FALLBACK_DEPARTMENT:
        problems.append('unknown disease does not fall back to General Medicine')
    if department_for('  (VERTIGO) paroymsal positional vertigo ') != 'ENT':
        problems.append('lookup is not case/space insensitive')
    return problems


def test_disease_department_map():
    problems = check()
    assert not problems, problems


if __name__ == '__main__':
    problems = check()
    for p in problems:
        print('FAIL', p)
    diseases = dataset_diseases()
    print(f'{len(diseases)} dataset diseases, {len(DISEASE_DEPARTMENT)} mapped, '
          f'{len(project_departments())} project departments')
    for dept, n in Counter(DISEASE_DEPARTMENT.values()).most_common():
        print(f'  {dept:20} {n}')
    print(f'{7 - len(problems)} of 7 checks passed')
    raise SystemExit(1 if problems else 0)
