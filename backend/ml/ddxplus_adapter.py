
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ML_DIR = Path(__file__).resolve().parent
DATA_DIR = ML_DIR / 'data'
DDXPLUS_DIR = DATA_DIR / 'ddxplus'
EVIDENCES_PATH = DDXPLUS_DIR / 'release_evidences.json'
CONDITIONS_PATH = DDXPLUS_DIR / 'release_conditions.json'
LABELS_PATH = DATA_DIR / 'ddxplus_labels.json'
SCHEMA_PATH = DATA_DIR / 'symptom_schema.json'
TEMPLATE_PATH = DATA_DIR / 'disease_dept_template.json'
TARGET = 'prognosis'
PREVALENCE_FILE = 'prevalence.json'
DEMOGRAPHICS = ['age', 'sex_m']
DEFAULT_PER_CLASS = 2000
RANDOM_STATE = 42


PAIN_LOCATION = 'E_55'
PAIN_REGIONS: dict[str, tuple[str, str, tuple[str, ...]]] = {
   
    'head': ('headache', 'Do you have a headache?',
             ('forehead', 'top of the head', 'temple', 'back of head', 'occiput')),
    'face': ('face pain', 'Do you have pain in your face, sinuses, eyes or nose?',
             ('cheek', 'nose', 'eye', 'mouth', 'jaw', 'chin', 'lower teeth', 'upper teeth', 'lower gum',
              'upper gum', 'internal cheek', 'commissure', 'bottom lip', 'upper lip', 'vermilion',
              'under the tongue', 'above the tongue')),
    'ear': ('ear pain', 'Do you have pain in your ear?', ('ear',)),
    'throat': ('throat pain', 'Do you have pain in your throat?',
               ('pharynx', 'tonsil', 'palace', 'thyroid cartilage', 'under the jaw', 'trachea', 'uvula')),
    'neck': ('neck pain', 'Do you have pain in your neck?',
             ('back of the neck', 'side of the neck', 'cervical spine', 'trapezius')),
    'chest': ('chest pain', 'Do you have pain in your chest?',
              ('upper chest', 'lower chest', 'side of the chest', 'breast', 'posterior chest wall')),
    'back': ('back pain', 'Do you have pain in your back?',
             ('scapula', 'thoracic spine', 'lumbar spine', 'coccyx', 'renal fossa')),
    'abdomen': ('stomach pain', 'Do you have pain in your stomach or belly?',
                ('epigastric', 'belly', 'hypochondrium', 'flank', 'iliac fossa', 'pubis', 'iliac wing',
                 'iliac crest')),
    'groin': ('groin pain', 'Do you have pain in your groin, hip or genitals?',
              ('groin', 'hip', 'testicle', 'scrotum', 'penis', 'glans', 'clitoris', 'labia majora',
               'labia minora', 'vagina', 'vaginal wall', 'vulval vestibule', 'hymen', 'urethra', 'anus',
               'buttock')),
    'arm': ('arm or shoulder pain', 'Do you have pain in your arm or shoulder?',
            ('shoulder', 'axilla', 'biceps', 'triceps', 'elbow', 'forearm', 'palmar side of the forearm')),
    'hand': ('hand or wrist pain', 'Do you have pain in your hand, wrist or fingers?',
             ('dorsal aspect of the wrist', 'palmar face of the wrist', 'dorsal aspect of the hand', 'palm',
              'thumb', 'finger (index)', 'finger (middle)', 'finger (ring finger)', 'finger (little finger)')),
    'leg': ('leg or foot pain', 'Do you have pain in your leg or foot?',
            ('thigh', 'knee', 'popliteal fossa', 'ischio jambier', 'calf', 'tibia', 'ankle',
             'posterior aspect of the ankle', 'dorsal aspect of the foot', 'lateral side of the foot', 'sole',
             'heel', 'big toe', 'toe (1)', 'toe (2)', 'toe (3)', 'little toe (4)')),
}


def _side_free(meaning: str) -> str:
    """'temple(R)' -> 'temple'."""
    return meaning.removesuffix('(R)').removesuffix('(L)').strip()


def pain_region_values(evidences: dict) -> dict[str, str]:
    
    default = str(evidences[PAIN_LOCATION]['default_value'])
    meanings = {code: _side_free(v['en']) for code, v in evidences[PAIN_LOCATION]['value_meaning'].items()
                if code != default}
    region_of = {loc: f'{PAIN_LOCATION}_{key}' for key, (_, _, locs) in PAIN_REGIONS.items() for loc in locs}
    unknown = sorted(set(region_of) - set(meanings.values()))
    unplaced = sorted(set(meanings.values()) - set(region_of))
    if unknown or unplaced:
        raise ValueError(f'PAIN_REGIONS out of date: unknown {unknown}, not in any region {unplaced}')
    return {code: region_of[m] for code, m in meanings.items()}


def _read_json(path: Path) -> dict:
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def _code_order(code: str) -> int:
   
    return int(code.split('_')[1])


def build_schema(evidences: dict, conditions: dict, labels: dict[str, str],
                 include_antecedents: bool = False, with_demographics: bool = False) -> dict:
    
    chosen = sorted((e for e in evidences.values() if include_antecedents or not e['is_antecedent']),
                    key=lambda e: _code_order(e['name']))
    symptoms = []
    for e in chosen:
        parent = e['code_question'] if e['code_question'] != e['name'] else None
        symptoms.append({
            'name': e['name'],
            'label': labels.get(e['name']) or e['question_en'].rstrip('?:').strip().lower(),
            'question': e['question_en'],
            'data_type': e['data_type'],
            'antecedent': bool(e['is_antecedent']),
            'parent': parent,
        })
        if e['name'] == PAIN_LOCATION:
            symptoms += [{'name': f'{PAIN_LOCATION}_{key}', 'label': label, 'question': question,
                          'data_type': 'B', 'antecedent': False, 'parent': PAIN_LOCATION}
                         for key, (label, question, _) in PAIN_REGIONS.items()]
    columns = [s['name'] for s in symptoms] + (DEMOGRAPHICS if with_demographics else [])
    return {
        '_note': 'Generated by ml/ddxplus_adapter.py from DDXPlus (synthetic). Do not edit by hand: '
                 'labels come from ml/data/ddxplus_labels.json. NEEDS REVIEW: labels and questions '
                 'are shown to patients.',
        'source': 'DDXPlus, Fansi Tchango et al., NeurIPS 2022 Datasets and Benchmarks, CC-BY 4.0',
        'options': {'include_antecedents': include_antecedents, 'with_demographics': with_demographics},
        'columns': columns,
        'symptoms': symptoms,
        'classes': sorted(c['cond-name-eng'] for c in conditions.values()),
    }


def present_evidences(tokens: list[str], evidences: dict, regions: dict[str, str] | None = None) -> set[str]:
    
    regions = pain_region_values(evidences) if regions is None else regions
    present = set()
    for token in tokens:
        base, _, value = token.partition('_@_')
        if value and value == str(evidences[base]['default_value']):
            continue
        present.add(base)
        if base == PAIN_LOCATION and value in regions:
            present.add(regions[value])
    return present


def convert(patients: pd.DataFrame, schema: dict, evidences: dict) -> pd.DataFrame:

    symptom_names = [s['name'] for s in schema['symptoms']]
    index = {name: i for i, name in enumerate(symptom_names)}
    x = np.zeros((len(patients), len(symptom_names)), dtype=np.int8)
    regions = pain_region_values(evidences)
    for row, raw in enumerate(patients['EVIDENCES']):
        for code in present_evidences(json.loads(raw.replace("'", '"')), evidences, regions):
            if code in index:                      # antecedents are skipped unless included
                x[row, index[code]] = 1
    out = pd.DataFrame(x, columns=symptom_names)
    if schema['options']['with_demographics']:
        out['age'] = patients['AGE'].astype(int).to_numpy()
        out['sex_m'] = (patients['SEX'] == 'M').astype(np.int8).to_numpy()
    out[TARGET] = patients['PATHOLOGY'].to_numpy()
    unknown = set(out[TARGET]) - set(schema['classes'])
    if unknown:
        raise ValueError(f'Pathologies not in release_conditions.json: {sorted(unknown)}')
    return out[schema['columns'] + [TARGET]]


def balance(table: pd.DataFrame, per_class: int | None, seed: int = RANDOM_STATE) -> pd.DataFrame:
    
    if not per_class:
        return table
    shuffled = table.sample(frac=1, random_state=seed)
    return shuffled.groupby(TARGET, sort=False).head(per_class).sort_index().reset_index(drop=True)


def describe(counts: pd.Series) -> str:
    return f'min {counts.min()}, median {int(counts.median())}, max {counts.max()}'


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def write_prevalence(path: Path, raw_counts: pd.Series, source: str) -> None:
    s
    write_json(path, {
        '_note': f'Patients per pathology in {source} before deduplication and capping '
                 '(DDXPlus generator prevalence, synthetic). Written by ml/ddxplus_adapter.py.',
        'counts': {str(k): int(v) for k, v in raw_counts.sort_index().items()},
    })


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--split', required=True, help='output folder name: ml/data/<split>/')
    parser.add_argument('--input', type=Path, help='patients CSV (default ml/data/ddxplus/release_<split>_patients)')
    parser.add_argument('--per-class', type=int, default=DEFAULT_PER_CLASS,
                        help=f'rows kept per pathology after removing duplicates (default {DEFAULT_PER_CLASS}; 0 = all)')
    parser.add_argument('--include-antecedents', action='store_true', help='add history items as columns')
    parser.add_argument('--with-demographics', action='store_true', help="add 'age' and 'sex_m' columns")
    args = parser.parse_args(argv)

    evidences = _read_json(EVIDENCES_PATH)
    schema = build_schema(evidences, _read_json(CONDITIONS_PATH), _read_json(LABELS_PATH)['labels'],
                          args.include_antecedents, args.with_demographics)
    labels = [s['label'] for s in schema['symptoms']]
    if len(set(labels)) != len(labels):
        raise ValueError('Symptom labels must be unique; check ml/data/ddxplus_labels.json.')
    if SCHEMA_PATH.exists():
        old = _read_json(SCHEMA_PATH)
        if old.get('columns') != schema['columns'] and args.split != 'train':
            raise SystemExit(f'{SCHEMA_PATH.name} has different columns. Use the same flags as the '
                             'training split (or regenerate the training split first).')

    source = args.input or DDXPLUS_DIR / f'release_{args.split}_patients'
    patients = pd.read_csv(source, usecols=['AGE', 'SEX', 'PATHOLOGY', 'EVIDENCES'])
    print(f'{source.name}: {len(patients)} patients, {patients["PATHOLOGY"].nunique()} pathologies')
    n_symptoms = sum(not s['antecedent'] for s in schema['symptoms'])
    print(f'Columns: {n_symptoms} symptoms, {len(schema["symptoms"]) - n_symptoms} antecedents'
          + (', age, sex_m' if args.with_demographics else ''))

    table = convert(patients, schema, evidences)
    print(f'Rows per pathology (raw):           {describe(table[TARGET].value_counts())}')
    raw_counts = table[TARGET].value_counts()
    deduped = table.drop_duplicates().reset_index(drop=True)
    print(f'Duplicates removed: {len(table) - len(deduped)} ({len(table)} -> {len(deduped)} rows)')
    print(f'Rows per pathology (deduplicated):  {describe(deduped[TARGET].value_counts())}')
    sampled = balance(deduped, args.per_class)
    counts = sampled[TARGET].value_counts()
    print(f'Rows per pathology (per-class {args.per_class or "all"}): {describe(counts)}  -> {len(sampled)} rows')
    for name, n in counts.sort_values().items():
        print(f'  {n:6d}  {name}')

    out_dir = DATA_DIR / args.split
    out_dir.mkdir(parents=True, exist_ok=True)
    sampled.to_csv(out_dir / 'ddxplus_binary.csv', index=False)
    write_prevalence(out_dir / PREVALENCE_FILE, raw_counts, source.name)
    write_json(SCHEMA_PATH, schema)
    write_json(TEMPLATE_PATH, {
        '_note': 'Copy to disease_dept.json and give every pathology one department name used by the '
                 'app (Doctor.department choices). NEEDS CLINICIAN REVIEW.',
        'departments': {name: '' for name in schema['classes']},
    })
    print(f'Wrote {out_dir.relative_to(ML_DIR.parent)}/ddxplus_binary.csv, {SCHEMA_PATH.name}, {TEMPLATE_PATH.name}')


if __name__ == '__main__':
    main()
