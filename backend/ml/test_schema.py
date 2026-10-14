"""Tests for the symptom schema and the startup checks built on it.

Run:  python -m pytest ml/test_schema.py
(needs ml/data/symptom_schema.json and ml/symptom_model.joblib: python -m ml.ddxplus_adapter, python -m ml.train_model)
"""
import json

import joblib
import pandas as pd
import pytest

from ml import ddxplus_adapter, symptom_model
from ml.disease_dept import DISEASE_DEPARTMENT, check_classes, project_departments
from ml.schema import SCHEMA_PATH, SchemaError, get, load_schema


def test_schema_loads_without_duplicates():
    schema = get()
    assert len(schema.names) == len(set(schema.names)) > 0
    assert len({s.label for s in schema.symptoms}) == len(schema.symptoms)
    assert len(schema.classes) == len(set(schema.classes)) > 0
    assert list(schema.columns[:len(schema.names)]) == schema.names


def test_duplicate_symptom_names_are_refused(tmp_path):
    data = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
    data['symptoms'].append(dict(data['symptoms'][0], label='another label'))
    path = tmp_path / 'schema.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(SchemaError, match='duplicate symptom names'):
        load_schema(path)


def test_require_rejects_unknown_symptoms():
    with pytest.raises(SchemaError, match='E_99999'):
        get().require(['E_91', 'E_99999'], 'a test module')


def test_model_load_fails_on_symptom_list_mismatch(tmp_path, monkeypatch):
    artifact = joblib.load(symptom_model.MODEL_PATH)
    symptom_model.check_artifact(artifact)                     # the shipped model agrees with the schema
    changed = dict(artifact, symptoms=list(reversed(artifact['symptoms'])))
    with pytest.raises(SchemaError, match='different symptom list'):
        symptom_model.check_artifact(changed)
    path = tmp_path / 'model.joblib'
    joblib.dump(changed, path)
    monkeypatch.setattr(symptom_model, '_loaded', False)
    with pytest.raises(SchemaError):
        symptom_model.load(path)
    monkeypatch.setattr(symptom_model, '_loaded', False)       # leave the real model loaded for later tests
    symptom_model.load()


def test_old_naive_bayes_model_file_is_refused():
    class BernoulliNB:              # stands in for the retired model type
        classes_ = list(get().classes)
    schema = get()
    old = {'model': BernoulliNB(), 'symptoms': list(schema.columns), 'classes': list(schema.classes),
           'symptom_rates': None, 'rate_columns': schema.names}
    with pytest.raises(SchemaError, match='not a Random Forest'):
        symptom_model.check_artifact(old)
    with pytest.raises(SchemaError, match='lacks'):
        symptom_model.check_artifact({'model': BernoulliNB(), 'symptoms': list(schema.columns)})


def test_model_load_fails_on_class_mismatch():
    artifact = joblib.load(symptom_model.MODEL_PATH)
    with pytest.raises(SchemaError, match='illnesses differ'):
        symptom_model.check_artifact(dict(artifact, classes=artifact['classes'][1:]))


def test_every_trained_illness_has_a_real_department():
    check_classes(get().classes)
    assert set(DISEASE_DEPARTMENT.values()) <= project_departments()
    assert len(project_departments()) == 21


def test_startup_fails_on_missing_department(monkeypatch):
    classes = list(get().classes)
    without = {k: v for k, v in DISEASE_DEPARTMENT.items() if k != 'Pneumonia'}
    with pytest.raises(SchemaError, match='Pneumonia'):
        check_classes(classes, without)
    with pytest.raises(SchemaError, match='departments the app does not have'):
        check_classes(classes, {**DISEASE_DEPARTMENT, 'Pneumonia': 'Chest Clinic'})
    # load() runs the same check at server startup.
    monkeypatch.setattr(symptom_model, 'check_classes', lambda c: check_classes(c, without))
    monkeypatch.setattr(symptom_model, '_loaded', False)
    with pytest.raises(SchemaError, match='Pneumonia'):
        symptom_model.load()
    monkeypatch.undo()
    monkeypatch.setattr(symptom_model, '_loaded', False)
    assert symptom_model.load()


def test_synonym_pointing_outside_the_schema_fails_startup(monkeypatch):
    monkeypatch.setattr(symptom_model, '_synonyms', lambda: {'made_up': 'e_99999'})
    with pytest.raises(SchemaError, match='made_up'):
        symptom_model.check_references()


def test_adapter_output_follows_schema_column_order():
    schema_dict = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
    for split in ('train', 'test'):
        path = ddxplus_adapter.DATA_DIR / split / 'ddxplus_binary.csv'
        if path.exists():
            assert list(pd.read_csv(path, nrows=0).columns) == schema_dict['columns'] + ['prognosis'], split
    evidences = json.loads(ddxplus_adapter.EVIDENCES_PATH.read_text(encoding='utf-8'))
    patients = pd.DataFrame({
        'AGE': [30, 61], 'SEX': ['F', 'M'], 'PATHOLOGY': ['Pneumonia', 'GERD'],
        'EVIDENCES': ["['E_91', 'E_201', 'E_57_@_V_123', 'E_56_@_4']", "['E_173', 'E_215', 'E_56_@_0']"],
    })
    table = ddxplus_adapter.convert(patients, schema_dict, evidences)
    assert list(table.columns) == schema_dict['columns'] + ['prognosis']
    assert table.loc[0, ['E_91', 'E_201', 'E_56']].tolist() == [1, 1, 1]
    assert table.loc[0, 'E_57'] == 0                    # V_123 "nowhere" is E_57's default: absent
    assert table.loc[1, 'E_56'] == 0                    # pain intensity 0 is the default: absent
    assert table.loc[1, ['E_173', 'E_215']].tolist() == [1, 1]
    assert table['prognosis'].tolist() == ['Pneumonia', 'GERD']


def test_adapter_options_change_columns():
    evidences = json.loads(ddxplus_adapter.EVIDENCES_PATH.read_text(encoding='utf-8'))
    conditions = json.loads(ddxplus_adapter.CONDITIONS_PATH.read_text(encoding='utf-8'))
    plain = ddxplus_adapter.build_schema(evidences, conditions, {})
    full = ddxplus_adapter.build_schema(evidences, conditions, {}, include_antecedents=True, with_demographics=True)
    assert not any(s['antecedent'] for s in plain['symptoms'])
    assert any(s['antecedent'] for s in full['symptoms'])
    assert full['columns'][-2:] == ['age', 'sex_m'] and 'age' not in plain['columns']
    assert plain['classes'] == full['classes'] and len(plain['classes']) == len(conditions)


def test_balance_caps_rows_per_class():
    table = pd.DataFrame({'E_91': range(10), 'prognosis': ['A'] * 7 + ['B'] * 3})
    counts = ddxplus_adapter.balance(table, 4)['prognosis'].value_counts().to_dict()
    assert counts == {'A': 4, 'B': 3}
