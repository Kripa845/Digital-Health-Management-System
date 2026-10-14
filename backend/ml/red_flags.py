"""Red-flag rules: symptoms that need emergency care, checked BEFORE the model.

    check({'E_45', 'E_201'})          ->  [RedFlag('coughing_up_blood', ...)]
    check_text("my throat is closing") ->  [PhraseFlag('throat_swelling', ...)]

When any rule matches, the smart check returns status "emergency" and the model is
not called. Symptom names are DDXPlus evidence codes from ml/data/symptom_schema.json
(the label is in the comment); the server refuses to start if a rule names a code
the schema does not have.

Two kinds of rule:
- RULES read the recognised symptoms (after synonyms, base forms and spelling).
- PHRASE_RULES read the text itself, for warning signs the schema has no column for
  ("throat swelling", "lips turning blue", "fainting"): these words would otherwise be
  "unrecognised" and the model would run on the rest. Negation is respected
  ("no throat swelling" does not fire), using ml/negation.py as the symptom matcher does.

Chest pain alone and shortness of breath alone are NOT red flags: they are the main
symptoms of GERD, asthma and COPD, which the model handles. They are red flags together,
or with fainting, sweating or swelling, or when described as severe.

!!! These rules NEED CLINICIAN REVIEW. They were written by a developer as a
conservative starting point, not as medical guidance. !!!
"""
from __future__ import annotations

from dataclasses import dataclass

EMERGENCY_DEPARTMENT = 'Emergency Medicine'
EMERGENCY_MESSAGE = ('Some of your symptoms can be signs of an emergency. Please go to the nearest '
                     'emergency department or call an ambulance now.')


@dataclass(frozen=True)
class RedFlag:
    id: str
    message: str
    all_of: tuple[str, ...] = ()     # every one of these must be present
    any_of: tuple[str, ...] = ()     # and, if given, at least one of these

    def matches(self, present: set[str]) -> bool:
        return set(self.all_of) <= present and (not self.any_of or bool(set(self.any_of) & present))

    @property
    def symptoms(self) -> set[str]:
        return set(self.all_of) | set(self.any_of)

    def as_dict(self) -> dict:
        return {'id': self.id, 'message': self.message}


RULES: tuple[RedFlag, ...] = (
    RedFlag('loss_of_consciousness', 'Loss of consciousness', any_of=('E_159',)),       # loss of consciousness
    RedFlag('seizure', 'Seizure or absence episode', any_of=('E_43',)),                 # seizure
    RedFlag('stroke_signs', 'Possible stroke: weakness of the face or limbs, or difficulty speaking',
            any_of=('E_156', 'E_176', 'E_63')),       # one sided facial weakness, limb or face paralysis, difficulty speaking
    RedFlag('chest_pain_at_rest', 'Chest pain at rest', any_of=('E_14',)),              # chest pain at rest
    RedFlag('airway', 'Choking or noisy, blocked breathing', any_of=('E_75', 'E_194')),  # choking sensation, stridor
    RedFlag('allergic_reaction', 'Allergen exposure with breathing problems (possible anaphylaxis)',
            all_of=('E_42',), any_of=('E_66', 'E_214', 'E_75', 'E_194')),   # allergen exposure + breath/wheezing/choking/stridor
    RedFlag('coughing_up_blood', 'Coughing up blood', any_of=('E_45',)),               # coughing up blood
    RedFlag('gi_bleeding', 'Vomiting blood or black stools', any_of=('E_210', 'E_140')),  # vomiting blood, black stools
    RedFlag('confusion', 'New confusion or disorientation', any_of=('E_39',)),         # confusion
    RedFlag('breathless_and_faint', 'Shortness of breath with feeling faint',
            all_of=('E_66', 'E_82')),                 # shortness of breath + feeling faint
    RedFlag('swelling_with_breathing_problem',
            'Swelling with difficulty breathing or swallowing (possible severe allergic reaction)',
            all_of=('E_151',), any_of=('E_66', 'E_214', 'E_194', 'E_75', 'E_65')),
            # swelling + shortness of breath / wheezing / stridor / choking / difficulty swallowing
    RedFlag('chest_pain_with_warning_signs', 'Chest pain with shortness of breath, sweating or feeling faint',
            all_of=('E_55_chest',), any_of=('E_66', 'E_50', 'E_82')),
            # chest pain + shortness of breath / sweating / feeling faint
)


@dataclass(frozen=True)
class PhraseFlag:
    """A warning sign found in the text itself (no schema symptom says it)."""
    id: str
    message: str
    phrases: tuple[str, ...]

    def as_dict(self) -> dict:
        return {'id': self.id, 'message': self.message}


PHRASE_RULES: tuple[PhraseFlag, ...] = (
    PhraseFlag('throat_swelling', 'Swelling of the throat, tongue, lips or face (possible severe allergic reaction)', (
        'throat swelling', 'swelling in my throat', 'swollen throat', 'throat is swelling', 'throat swelling up',
        'throat closing', 'throat is closing', 'throat closing up', 'throat feels tight', 'tight throat',
        'tongue swelling', 'swollen tongue', 'tongue is swelling', 'lip swelling', 'lips swelling',
        'swollen lips', 'swollen lip', 'lips are swelling', 'face swelling', 'facial swelling', 'swollen face',
        'face is swelling')),
    PhraseFlag('severe_breathing_difficulty', 'Severe difficulty breathing', (
        "can't breathe", 'cannot breathe', 'can not breathe', 'unable to breathe', 'struggling to breathe',
        'gasping', 'gasping for air', 'gasping for breath', 'blue lips', 'lips turning blue', 'lips are blue',
        'turning blue', 'choking')),
    PhraseFlag('fainting', 'Fainting or collapse', (
        'fainting', 'fainted', 'fainting spells', 'collapsed', 'collapsing', 'blackout', 'blackouts',
        'blacking out', 'passing out', 'passed out')),
    PhraseFlag('severe_chest_pain', 'Severe, crushing or pressing chest pain', (
        'crushing chest pain', 'severe chest pain', 'chest pressure', 'pressure in my chest',
        'pressure in the chest', 'chest pain spreading to my arm', 'chest pain spreading to my jaw',
        'chest pain radiating to my arm', 'chest pain radiating to my jaw')),
)


def symptoms_named() -> set[str]:
    """Every symptom any rule refers to (checked against the schema at startup)."""
    return set().union(*(r.symptoms for r in RULES))


def check(present) -> list[RedFlag]:
    """The rules matched by the present symptoms (evidence codes)."""
    present = set(present)
    return [r for r in RULES if r.matches(present)]


def check_text(text: str) -> list[PhraseFlag]:
    """The phrase rules whose phrase appears in the text and is not negated."""
    from ml.negation import _words, longest_matches, negated_spans
    words = _words(text)
    rule_of = {tuple(_words(p)): rule for rule in PHRASE_RULES for p in rule.phrases}
    found = longest_matches(words, rule_of)
    flags = negated_spans(words, [(start, end) for start, end, _ in found])
    hit = {rule_of[phrase].id for (_, _, phrase), negated in zip(found, flags) if not negated}
    return [r for r in PHRASE_RULES if r.id in hit]
