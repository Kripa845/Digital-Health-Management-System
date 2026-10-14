"""Which of the project's departments should see each illness the model can predict.

DDXPlus has no departments. The pathology -> department map is read from
ml/data/disease_dept.json (start from disease_dept_template.json, written by
ml/ddxplus_adapter.py). Department names must be ones the app already uses
(Doctor.department choices, the same names as apps/recommendations/data/symptom_department_map.json).

!!! The shipped map is PROVISIONAL and NEEDS REVIEW BY A CLINICIAN BEFORE REAL USE. !!!

check_classes() runs at server startup: the server refuses to start when a trained
illness has no department or a department name is not one of the app's.
"""
from __future__ import annotations

import json
from pathlib import Path

from ml.schema import SchemaError

ML_DIR = Path(__file__).resolve().parent
DEPT_MAP_PATH = ML_DIR / 'data' / 'disease_dept.json'
PROJECT_DEPARTMENTS_PATH = ML_DIR.parent / 'apps' / 'recommendations' / 'data' / 'symptom_department_map.json'
FALLBACK_DEPARTMENT = 'General Medicine'   # only for names that are not trained illnesses (hand-made test models)


def _key(name: str) -> str:
    return ' '.join(str(name or '').split()).lower()


def project_departments() -> set[str]:
    with open(PROJECT_DEPARTMENTS_PATH, encoding='utf-8') as fh:
        return set(json.load(fh)['department_rules'])


def load_map(path: Path = DEPT_MAP_PATH) -> tuple[dict[str, str], dict[str, str]]:
    """(illness -> department, illness -> note on the least clear-cut choices)."""
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except OSError as exc:
        raise SchemaError(f'{path.name} is missing: copy disease_dept_template.json and fill it in.') from exc
    return dict(data.get('departments', {})), dict(data.get('uncertain', {}))


DISEASE_DEPARTMENT, UNCERTAIN = load_map()
_LOOKUP = {_key(disease): dept for disease, dept in DISEASE_DEPARTMENT.items()}


def department_for(disease: str) -> str:
    """The department for an illness (General Medicine for names outside the map)."""
    return _LOOKUP.get(_key(disease), FALLBACK_DEPARTMENT)


def check_classes(classes, mapping: dict[str, str] | None = None) -> None:
    """Raise SchemaError when a trained illness has no department, or a department is not the app's."""
    mapping = DISEASE_DEPARTMENT if mapping is None else mapping
    lookup = {_key(k): v for k, v in mapping.items()}
    missing = [c for c in classes if not lookup.get(_key(c))]
    if missing:
        raise SchemaError(f'{DEPT_MAP_PATH.name}: trained illnesses without a department: {missing}')
    invalid = {c: lookup[_key(c)] for c in classes if lookup[_key(c)] not in project_departments()}
    if invalid:
        raise SchemaError(f'{DEPT_MAP_PATH.name}: departments the app does not have: {invalid}')
