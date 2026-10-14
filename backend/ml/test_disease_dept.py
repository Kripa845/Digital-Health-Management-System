"""Checks for ml/disease_dept.py and ml/data/disease_dept.json.

Run:  python -m ml.test_disease_dept     or     python -m pytest ml/test_disease_dept.py
"""
from collections import Counter

from ml.disease_dept import (
    DISEASE_DEPARTMENT, FALLBACK_DEPARTMENT, UNCERTAIN, department_for, project_departments,
)
from ml.schema import get


def check() -> list[str]:
    problems = []
    departments = project_departments()
    illnesses = list(get().classes)
    if len(departments) != 21:
        problems.append(f'expected 21 project departments, found {len(departments)}')
    unmapped = [d for d in illnesses if not DISEASE_DEPARTMENT.get(d)]
    if unmapped:
        problems.append(f'illnesses without a department: {unmapped}')
    extra = [d for d in DISEASE_DEPARTMENT if d not in illnesses]
    if extra:
        problems.append(f'mapped names not in the schema: {extra}')
    invalid = {d: dept for d, dept in DISEASE_DEPARTMENT.items() if dept not in departments}
    if invalid:
        problems.append(f'departments that do not exist in the project: {invalid}')
    if any(d not in DISEASE_DEPARTMENT for d in UNCERTAIN):
        problems.append('"uncertain" lists an illness that is not mapped')
    if department_for('Some unknown illness') != FALLBACK_DEPARTMENT:
        problems.append('unknown name does not fall back to General Medicine')
    if department_for('  gerd ') != 'Gastroenterology':
        problems.append('lookup is not case/space insensitive')
    return problems


def test_disease_department_map():
    problems = check()
    assert not problems, problems


if __name__ == '__main__':
    problems = check()
    for p in problems:
        print('FAIL', p)
    print(f'{len(get().classes)} schema illnesses, {len(DISEASE_DEPARTMENT)} mapped, '
          f'{len(project_departments())} project departments')
    for dept, n in Counter(DISEASE_DEPARTMENT.values()).most_common():
        print(f'  {dept:20} {n}')
    print(f'{7 - len(problems)} of 7 checks passed')
    raise SystemExit(1 if problems else 0)
