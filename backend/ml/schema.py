"""The symptom schema: the one list of symptoms and illnesses every module uses.

ml/data/symptom_schema.json is written by ml/ddxplus_adapter.py from DDXPlus
(synthetic data). Nothing else names symptoms or illnesses on its own: the model,
the text matcher, the red-flag rules, the follow-up questions and the department
map are all checked against this file, and the server refuses to start when one of
them names a symptom or illness the schema does not have.

    schema = get()
    schema.columns          model input columns, in training order
    schema.label('E_91')    'fever'  (shown to users, matched in their text)
    schema.question('E_91') 'Do you have a fever (either felt or measured with a thermometer)?'
    schema.classes          the illnesses (DDXPlus pathologies, English names)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent / 'data' / 'symptom_schema.json'


class SchemaError(RuntimeError):
    """A module, model or data file does not agree with the symptom schema."""


@dataclass(frozen=True)
class Symptom:
    name: str                 # DDXPlus evidence code, e.g. 'E_91' (the model column)
    label: str                # short English name, e.g. 'fever'
    question: str             # DDXPlus English question
    data_type: str            # 'B' yes/no, 'C' categorical, 'M' multi-choice (collapsed to present/absent)
    antecedent: bool          # history item rather than a symptom
    parent: str | None        # the question this one follows up (e.g. pain intensity -> pain)


@dataclass(frozen=True)
class Schema:
    columns: tuple[str, ...]
    symptoms: tuple[Symptom, ...]
    classes: tuple[str, ...]
    options: dict

    @property
    def names(self) -> list[str]:
        return [s.name for s in self.symptoms]

    def symptom(self, name: str) -> Symptom:
        return self._by_name()[name]

    def label(self, name: str) -> str:
        return self._by_name()[name].label

    def question(self, name: str) -> str:
        return self._by_name()[name].question

    def labels(self) -> dict[str, str]:
        return {s.name: s.label for s in self.symptoms}

    def _by_name(self) -> dict[str, Symptom]:
        return {s.name: s for s in self.symptoms}

    def require(self, names, where: str) -> None:
        """Raise SchemaError if ``where`` refers to a symptom the schema does not have."""
        unknown = sorted(set(names) - set(self.names))
        if unknown:
            raise SchemaError(f'{where} refers to symptoms not in {SCHEMA_PATH.name}: {unknown}')


def _duplicates(values) -> list:
    seen, dup = set(), set()
    for v in values:
        (dup if v in seen else seen).add(v)
    return sorted(dup)


def load_schema(path: Path = SCHEMA_PATH) -> Schema:
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except OSError as exc:
        raise SchemaError(f'{path.name} is missing: run python -m ml.ddxplus_adapter first.') from exc
    symptoms = tuple(Symptom(**s) for s in data['symptoms'])
    schema = Schema(tuple(data['columns']), symptoms, tuple(data['classes']), dict(data.get('options', {})))
    for what, values in (('symptom names', schema.names), ('labels', [s.label for s in symptoms]),
                         ('columns', schema.columns), ('classes', schema.classes)):
        dup = _duplicates(values)
        if dup:
            raise SchemaError(f'{path.name} has duplicate {what}: {dup}')
    missing = [n for n in schema.names if n not in schema.columns]
    if missing:
        raise SchemaError(f'{path.name}: symptoms missing from columns: {missing}')
    schema.require([s.parent for s in symptoms if s.parent], f'{path.name} (parent questions)')
    return schema


@lru_cache(maxsize=1)
def get() -> Schema:
    """The schema, loaded once."""
    return load_schema()
