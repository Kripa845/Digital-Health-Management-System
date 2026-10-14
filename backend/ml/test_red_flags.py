"""Tests for ml/red_flags.py: rules use schema symptoms and run before the model.

Run:  python -m pytest ml/test_red_flags.py
"""
import pytest

from ml import red_flags, symptom_model
from ml.schema import get


class ModelThatMustNotRun:
    """Any use of this model fails the test: red flags must stop the pipeline first."""
    classes_ = ['x']

    def predict_proba(self, *_):
        raise AssertionError('the model was called for a red-flag input')


def test_every_rule_symptom_is_in_the_schema():
    get().require(red_flags.symptoms_named(), 'ml/red_flags.py')
    assert red_flags.symptoms_named()


def test_rules_have_unique_ids_and_messages():
    ids = [r.id for r in red_flags.RULES]
    assert len(ids) == len(set(ids)) and all(r.message for r in red_flags.RULES)


@pytest.mark.parametrize('text, flag', [
    ('I have been coughing up blood', 'coughing_up_blood'),
    ('chest pain at rest and sweating', 'chest_pain_at_rest'),
    ('slurred speech and a facial droop', 'stroke_signs'),
    ('I passed out this morning', 'loss_of_consciousness'),
    ('vomiting blood and black stools', 'gi_bleeding'),
    ('allergen exposure and wheezing', 'allergic_reaction'),
])
def test_red_flag_inputs_return_emergency_without_calling_the_model(text, flag):
    columns = list(get().columns)
    r = symptom_model.predict(text, model=ModelThatMustNotRun(), columns=columns)
    assert r['status'] == 'emergency'
    assert flag in [f['id'] for f in r['red_flags']]
    assert r['department'] == red_flags.EMERGENCY_DEPARTMENT and 'illnesses' not in r


def test_red_flag_from_a_yes_answer():
    columns = list(get().columns)
    r = symptom_model.predict('cough', answers={'E_45': True}, model=ModelThatMustNotRun(), columns=columns)
    assert r['status'] == 'emergency'


def test_negated_red_flag_does_not_fire():
    assert symptom_model.predict('no coughing up blood, but cough and fever')['status'] != 'emergency'


def test_combination_rule_needs_all_parts():
    assert not red_flags.check({'E_42'})                       # allergen exposure alone
    assert [r.id for r in red_flags.check({'E_42', 'E_214'})] == ['allergic_reaction']
