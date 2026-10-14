from __future__ import annotations

import json
import re

from ml.schema import SCHEMA_PATH, load_schema
from ml.symptom_terms import SYNONYMS_PATH, normalize

NEEDS_REVIEW = 'needs review'
MAX_WORDS = 5

# Question openings removed before a phrase is kept.
LEADS = (
    'have you recently had', 'have you noticed that', 'have you noticed', 'have you had', 'have you been',
    'have you recently', 'have you ever', 'have you', 'do you have', 'do you feel that', 'do you feel',
    'do you', 'did you', 'are you experiencing', 'are you feeling', 'are you', 'are your', 'is your',
    'does the person have', 'did your', 'any', 'a', 'an', 'the',
)

# Question fragments that are not symptoms on their own ("in your face", "which may still be present").
FRAGMENT_WORDS = {'you', 'your', 'ever', 'previously', 'currently', 'which', 'lately'}
FRAGMENT_STARTS = {'in', 'from', 'are', 'have', 'had', 'like', 'more', 'other', 'both', 'very', 'suddenly',
                   'raising', 'hard', 'made', 'new'}
FRAGMENT_ENDS = {'one', 'in', 'with', 'of', 'to', 'when'}

# Everyday wordings that do not appear in the questions (symptom name -> phrases).
EVERYDAY = {
    'E_91': ['temperature', 'high temperature', 'feverish', 'pyrexia'],
    'E_53': ['ache', 'aches'],
    'E_55_head': ['headaches', 'head ache'],
    'E_55_face': ['toothache', 'sinus pressure'],
    'E_55_ear': ['earache', 'earaches'],
    'E_55_abdomen': ['stomach ache', 'tummy ache', 'bellyache', 'stomach cramps', 'abdominal cramps'],
    'E_55_back': ['backache'],
    'E_201': ['coughing', 'dry cough'],
    'E_66': ['short of breath', 'breathless', 'breathlessness', 'difficulty breathing', 'cant breathe'],
    'E_148': ['nauseous', 'feel sick', 'queasy'],
    'E_211': ['vomiting', 'throwing up', 'vomit'],
    'E_89': ['tired', 'tiredness', 'exhausted', 'poor sleep'],
    'E_88': ['bedridden', 'too tired to work'],
    'E_76': ['dizzy', 'lightheaded', 'light headed'],
    'E_82': ['fainting', 'faint', 'about to faint'],
    'E_181': ['blocked nose', 'stuffy nose', 'nasal congestion'],
    'E_97': ['throat pain when swallowing', 'scratchy throat'],
    'E_94': ['shivering', 'shivers', 'rigors'],
    'E_50': ['sweats', 'night sweats', 'sweaty'],
    'E_155': ['racing heart', 'heart racing', 'pounding heart'],
    'E_214': ['wheeze', 'wheezy'],
    'E_212': ['hoarseness', 'lost my voice'],
    # No column means "skin redness" on its own: E_129's question is "lesions, redness or
    # problems on your skin", so redness goes there. Without these, "redness" was fuzzy-matched
    # to "tiredness" (fatigue) and "itchy" to "itch".
    'E_129': ['rash', 'skin rash', 'red skin', 'spots on skin', 'redness', 'skin redness', 'red patches',
              'red spots', 'red rash', 'blotches', 'skin irritation'],
    'E_136': ['itching', 'itchy skin', 'itch', 'itchy', 'itchiness', 'hives', 'urticaria', 'pruritus',
              'itchy patches'],
    'E_151': ['swollen', 'swollen legs', 'swollen ankles', 'oedema', 'edema', 'puffy', 'puffiness'],
    'E_74': ['pink eye', 'bloodshot eyes', 'eye redness', 'redness in eyes', 'redness in the eyes'],
    'E_51': ['loose stools', 'loose motion', 'runny stools'],
    'E_173': ['acid reflux', 'acidity', 'reflux'],
    'E_30': ['bloated', 'swollen belly'],
    'E_45': ['blood in sputum', 'haemoptysis', 'hemoptysis'],
    'E_210': ['blood in vomit', 'haematemesis'],
    'E_43': ['fits', 'convulsions', 'fit'],
    'E_159': ['fainted', 'passed out', 'blacked out', 'unconscious'],
    'E_39': ['confused', 'disoriented'],
    'E_144': ['body ache', 'body aches', 'muscle ache', 'muscle aches'],
    'E_9': ['swollen glands'],
    'E_65': ['painful swallowing', 'trouble swallowing'],
    'E_127': ['teary eyes', 'tearing'],
    'E_103': ['cant smell'],
    'E_162': ['losing weight'],
    'E_32': ['no appetite', 'poor appetite', 'not hungry'],
    'E_164': ['irregular pulse'],
    'E_192': ['neck stiffness'],
    'E_52': ['seeing double'],
    'E_172': ['droopy eyelids'],
    'E_63': ['slurred speech'],
    'E_156': ['facial droop', 'face drooping'],
    'E_169': ['itchy nose', 'itchy throat'],
}

# Body words for the pain-region symptoms (ml/ddxplus_adapter.py PAIN_REGIONS): each gives
# "<word> pain", "<word> ache", "pain in <word>", "pain in the <word>", "pain in my <word>".
PAIN_WORDS = {
    'E_55_head': ['head'],
    'E_55_face': ['face', 'facial', 'sinus', 'eye', 'eyes', 'tooth', 'teeth', 'jaw', 'cheek'],
    'E_55_ear': ['ear', 'ears'],
    'E_55_throat': ['throat'],
    'E_55_neck': ['neck'],
    'E_55_chest': ['chest', 'breast'],
    'E_55_back': ['back', 'lower back', 'upper back', 'spine'],
    'E_55_abdomen': ['stomach', 'abdominal', 'abdomen', 'belly', 'tummy', 'epigastric'],
    'E_55_groin': ['groin', 'hip', 'pelvic', 'testicle', 'testicular'],
    'E_55_arm': ['arm', 'arms', 'shoulder', 'elbow'],
    'E_55_hand': ['hand', 'wrist', 'finger', 'fingers'],
    'E_55_leg': ['leg', 'legs', 'knee', 'ankle', 'foot', 'feet', 'calf', 'thigh'],
}


def pain_phrases(word: str) -> list[str]:
    """'chest' -> ['chest pain', 'chest ache', 'pain in chest', 'pain in the chest', 'pain in my chest']."""
    return [f'{word} pain', f'{word} ache', f'pain in {word}', f'pain in the {word}', f'pain in my {word}']


# Not loaded: needs a Nepali speaker and a clinician.
NEPALI_TODO = {
    '_status': 'TODO - not loaded. Add Nepali (Devanagari) and Romanised Nepali phrases to "synonyms" '
               'once a Nepali speaker and a clinician have agreed them. Examples to consider:',
    'examples': {
        'ज्वरो / jwaro': 'E_91 fever',
        'खोकी / khoki': 'E_201 cough',
        'टाउको दुख्यो / tauko dukhyo': 'E_55_head headache',
        'घाँटी दुख्यो / ghanti dukhyo': 'E_97 sore throat',
        'सास फेर्न गाह्रो / saas ferna garo': 'E_66 shortness of breath',
        'वाकवाकी / wakwaki': 'E_148 nausea',
        'बान्ता / banta': 'E_211 repeated vomiting',
        'पखाला / pakhala': 'E_51 diarrhea',
        'चक्कर / chakkar': 'E_76 dizziness',
        'थकाई / thakai': 'E_89 fatigue',
    },
}


def question_phrases(question: str) -> list[str]:
    """'Do you have nasal congestion or a clear runny nose?' -> ['nasal congestion', 'clear runny nose']."""
    text = re.sub(r'\([^)]*\)', ' ', question.lower())
    text = re.sub(r'[?:.]', ' ', text).replace('’', "'")
    phrases = []
    for part in re.split(r',| or | and/or |/', text):
        words = part.split()
        changed = True
        while changed and words:
            changed = False
            for lead in LEADS:
                n = len(lead.split())
                if words[:n] == lead.split():
                    words, changed = words[n:], True
                    break
        if (2 <= len(words) <= MAX_WORDS and not FRAGMENT_WORDS & set(words)
                and words[0] not in FRAGMENT_STARTS and words[-1] not in FRAGMENT_ENDS):
            phrases.append(' '.join(words))
    return phrases


def draft(schema) -> tuple[dict, list[str]]:
    labels = {normalize(s.label) for s in schema.symptoms}
    candidates: dict[str, set[str]] = {}
    sources: dict[str, str] = {}
    for s in schema.symptoms:
        if s.parent:                              # follow-up details ("How intense is the pain?") are not typed
            continue
        for phrase in question_phrases(s.question):
            candidates.setdefault(phrase, set()).add(s.name)
            sources.setdefault(phrase, 'question')
    everyday = {name: list(phrases) for name, phrases in EVERYDAY.items()}
    for name, words in PAIN_WORDS.items():
        everyday.setdefault(name, []).extend(p for w in words for p in pain_phrases(w))
    for name, phrases in everyday.items():
        for phrase in phrases:
            candidates.setdefault(phrase, set()).add(name)
            sources[phrase] = 'everyday'
    synonyms, dropped = {}, []
    for phrase, names in sorted(candidates.items()):
        if normalize(phrase) in labels:
            continue
        if len(names) > 1:
            dropped.append(f'{phrase} -> {sorted(names)}')
            continue
        name = next(iter(names))
        synonyms[phrase] = {'symptom': name, 'label': schema.label(name), 'source': sources[phrase],
                            'status': NEEDS_REVIEW}
    return synonyms, dropped


def main():
    schema = load_schema(SCHEMA_PATH)
    synonyms, dropped = draft(schema)
    data = {
        '_note': 'FIRST DRAFT generated by ml/draft_synonyms.py from the English questions in '
                 'symptom_schema.json plus a short list of everyday wordings. Every entry NEEDS REVIEW '
                 'by a clinician. Targets are schema symptom names (DDXPlus codes); the server refuses '
                 'to start if a target is not in the schema.',
        'TODO_nepali_and_romanised': NEPALI_TODO,
        'synonyms': synonyms,
    }
    SYNONYMS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Wrote {len(synonyms)} draft synonyms to {SYNONYMS_PATH.name}')
    for d in dropped:
        print(f'  left out (ambiguous): {d}')


if __name__ == '__main__':
    main()
