"""Tests for ml/symptom_terms.py: normalisation, synonyms, fuzzy matching, unrecognised words.

Run:  python -m ml.test_symptom_terms     or     python -m pytest ml/test_symptom_terms.py
(the shipped-file checks need ml/symptom_model.joblib: python -m ml.train_model)
The fixture vocabulary below is made up for testing the matcher; real symptoms come
from ml/data/symptom_schema.json.
"""
from ml import symptom_model
from ml.symptom_terms import SYNONYMS_PATH, SymptomVocabulary, load_synonyms, normalize

COLUMNS = ['high fever', 'mild fever', 'headache', 'stomach pain', 'skin rash', 'itching',
           'cough', 'chest pain', 'fatigue', 'continuous sneezing', 'runny nose']
SYNONYMS = {'fever': 'high_fever', 'slight_fever': 'mild_fever', 'tummy_ache': 'stomach_pain',
            'rash': 'skin_rash', 'tired': 'fatigue', 'sneezing': 'continuous_sneezing',
            'not_a_column': 'made_up_symptom'}


def vocab(threshold=85):
    return SymptomVocabulary(COLUMNS, SYNONYMS, threshold)


def mapping(analysis):
    return [(m.term, m.symptom, m.method, m.negated) for m in analysis.matches]


def cases():
    # ── Normalisation ────────────────────────────────────────────────────────
    yield 'normalize: case, spaces, hyphens', normalize('  Skin-Rash ') == 'skin_rash'
    yield 'normalize: dataset typo "dischromic _patches"', normalize('dischromic _patches') == 'dischromic_patches'
    yield 'normalize: None and empty', normalize(None) == '' and normalize('   ') == ''

    v = vocab()
    yield 'synonym pointing at no column is reported, not used', v.invalid_synonyms == ['not_a_column']

    # ── Exact names (case and separators do not matter) ──────────────────────
    a = v.analyse('HEADACHE and Skin-Rash')
    yield 'exact: case and hyphen', a.present == ['headache', 'skin rash'] and a.unrecognized == []
    a = v.analyse('skin rash')
    yield 'exact: "skin rash" is one match, not also "rash"', mapping(a) == [('skin rash', 'skin rash', 'exact', False)]

    # ── Synonyms ─────────────────────────────────────────────────────────────
    a = v.analyse('tummy ache and sneezing, feeling tired')
    yield 'synonyms map to dataset names', a.present == ['continuous sneezing', 'fatigue', 'stomach pain']
    yield 'synonyms are labelled "synonym"', {m.method for m in a.matches} == {'synonym'}
    yield 'synonym keeps the words the user typed', a.matches[0].term == 'tummy ache'
    a = v.analyse('slight fever')
    yield 'longest synonym wins: "slight fever" -> mild fever', a.present == ['mild fever']
    a = v.analyse('no fever but tummy ache')
    yield 'negation applies to synonyms', a.present == ['stomach pain'] and a.negated == ['high fever']

    # ── Typos (fuzzy) ────────────────────────────────────────────────────────
    a = v.analyse('hedache and itchng')
    yield 'typos matched with fuzzy', a.present == ['headache', 'itching'] and a.unrecognized == []
    yield 'fuzzy matches carry a score >= threshold', all(
        m.method == 'fuzzy' and m.score >= 85 for m in a.matches)
    a = v.analyse('skin rashh, chets pain')
    yield 'typos in multi-word symptoms', a.present == ['chest pain', 'skin rash']
    a = v.analyse('tummy ach')
    yield 'typo in a synonym', a.present == ['stomach pain'] and a.matches[0].method == 'fuzzy'
    a = v.analyse('no hedache but cough')
    yield 'negation applies to fuzzy matches', a.present == ['cough'] and a.negated == ['headache']

    # ── Threshold comes from the caller (config) ─────────────────────────────
    yield 'strict threshold rejects the typo', vocab(99).analyse('hedache').present == []
    a = vocab(99).analyse('hedache')
    yield 'below a strict threshold the typo is only a "Did you mean" suggestion', (
        a.matches, [(m.term, m.symptom, m.method) for m in a.suggestions]) == ([], [('hedache', 'headache', 'suggestion')])
    yield 'loose threshold accepts it', vocab(80).analyse('hedache').present == ['headache']
    yield 'words under 4 letters are never guessed', v.analyse('cof').present == [] and v.analyse('cof').unrecognized == ['cof']
    yield 'words under 5 letters are never guessed: cogh', (
        v.analyse('cogh').present, v.analyse('cogh').suggestions, v.analyse('cogh').unrecognized) == ([], [], ['cogh'])

    # ── Nonsense and leftovers are never silently dropped ────────────────────
    a = v.analyse('asdfgh qwerty zzz')
    yield 'nonsense -> no symptoms', a.present == [] and a.matches == []
    yield 'nonsense -> reported as unrecognized', a.unrecognized == ['asdfgh qwerty zzz']
    a = v.analyse('no fever, but tummy ache and hedache, blorf')
    yield 'mixed: present, negated, unrecognized', (a.present, a.negated, a.unrecognized) == (
        ['headache', 'stomach pain'], ['high fever'], ['blorf'])
    a = v.analyse('I have been feeling a bit tired since 3 days')
    yield 'filler words and numbers are not unrecognized', a.present == ['fatigue'] and a.unrecognized == []
    a = v.analyse('I only have itching')
    yield '"only" is a filler', a.present == ['itching'] and a.unrecognized == []
    a = v.analyse('itching and purple elbows')
    yield 'unknown phrase kept whole', a.present == ['itching'] and a.unrecognized == ['purple elbows']
    yield 'empty text', (v.analyse('').matches, v.analyse('').unrecognized) == ([], [])

    # ── Labels are the exact phrases; synonyms may target a name or a label ──
    lv = SymptomVocabulary(['E_1', 'E_2'], {'temperature': 'e_1', 'blocked_nose': 'runny_nose'}, 85,
                           labels={'E_1': 'fever', 'E_2': 'runny nose'})
    a = lv.analyse('no temperature, but a blocked nose and runny nose')
    yield 'labels match exactly and map to the symptom name', a.present == ['E_2'] and a.negated == ['E_1']
    yield 'the code itself is not a phrase when a label exists', lv.analyse('e 1').present == []

    # ── The shipped synonym file against the schema and trained model ────────
    import json
    from ml.schema import get
    schema = get()
    synonyms = load_synonyms(SYNONYMS_PATH)
    entries = json.loads(SYNONYMS_PATH.read_text(encoding='utf-8'))['synonyms']
    yield 'synonym file loads (at least 50 entries)', len(synonyms) >= 50
    yield 'every synonym entry is marked "needs review"', all(
        isinstance(v, dict) and v.get('status') == 'needs review' for v in entries.values())
    real = SymptomVocabulary(schema.names, synonyms, labels=schema.labels())
    yield 'every synonym targets a schema symptom', real.invalid_synonyms == []
    yield 'no synonym is itself a symptom label', not set(synonyms) & {normalize(s.label) for s in schema.symptoms}
    if not symptom_model.load():
        yield 'trained model available (run python -m ml.train_model)', False
        return
    r = symptom_model.predict('high temperature, coughing and a scratchy throat')
    yield 'predict(): synonyms reach the model', {'fever', 'cough', 'sore throat'} <= set(r['symptoms'])
    yield 'predict(): mapping returned with the label', any(
        m == {'term': 'high temperature', 'symptom': 'fever', 'method': 'synonym', 'score': None}
        for m in r['matched'])
    r = symptom_model.predict('feverr and sore throaat')
    yield 'predict(): a close typo (96%) reaches the model, a less sure one (91%) is asked first', (
        r['status'], r['symptoms'], [(s['term'], s['label']) for s in r['suggestions']]) == (
        'needs_confirmation', ['sore throat'], [('feverr', 'fever')])
    r = symptom_model.predict('feverr and sore throaat', answers={'E_91': True})
    yield 'predict(): a confirmed suggestion reaches the model', set(r['symptoms']) == {'fever', 'sore throat'}
    r = symptom_model.predict('blorf zzyzx')
    yield 'predict(): nonsense -> not_enough_info with unrecognized', (
        r['status'], r['symptoms'], r['unrecognized']) == ('not_enough_info', [], ['blorf zzyzx'])


def run():
    results = list(cases())
    return results, sum(ok for _, ok in results)


def test_symptom_terms_cases():
    results, _ = run()
    failed = [name for name, ok in results if not ok]
    assert not failed, failed


if __name__ == '__main__':
    results, passed = run()
    for name, ok in results:
        print(('  ok   ' if ok else '  FAIL ') + name)
    print(f'{passed} of {len(results)} passed')
    raise SystemExit(0 if passed == len(results) else 1)
