"""Which of the project's 21 departments should see each of the 41 dataset illnesses.

!!! This mapping NEEDS REVIEW BY A MEDICAL PROFESSIONAL BEFORE REAL USE. !!!
It was written as a reasonable first-contact routing for a general hospital, not
as medical advice. Entries in UNCERTAIN are the least clear-cut.

The department names are the real ones used by the project
(Doctor.department choices and apps/recommendations/data/symptom_department_map.json).
Disease names are written exactly as in ml/data/dataset.csv, including its own
spellings ("Osteoarthristis", "Peptic ulcer diseae"); lookups ignore case and
extra spaces. Any unknown disease falls back to General Medicine.
"""
from __future__ import annotations

FALLBACK_DEPARTMENT = 'General Medicine'

DISEASE_DEPARTMENT: dict[str, str] = {
    # Skin
    'Acne': 'Dermatology',
    'Drug Reaction': 'Dermatology',          # usually seen as rash / itching
    'Fungal infection': 'Dermatology',
    'Impetigo': 'Dermatology',
    'Psoriasis': 'Dermatology',
    # Digestive system and liver
    'Alcoholic hepatitis': 'Gastroenterology',
    'Chronic cholestasis': 'Gastroenterology',
    'Dimorphic hemmorhoids(piles)': 'Gastroenterology',
    'GERD': 'Gastroenterology',
    'Gastroenteritis': 'Gastroenterology',
    'Jaundice': 'Gastroenterology',
    'Peptic ulcer diseae': 'Gastroenterology',
    'hepatitis A': 'Gastroenterology',
    'Hepatitis B': 'Gastroenterology',
    'Hepatitis C': 'Gastroenterology',
    'Hepatitis D': 'Gastroenterology',
    'Hepatitis E': 'Gastroenterology',
    # Hormones and metabolism
    'Diabetes': 'Endocrinology',
    'Hyperthyroidism': 'Endocrinology',
    'Hypothyroidism': 'Endocrinology',
    'Hypoglycemia': 'Endocrinology',
    # Heart and blood vessels
    'Hypertension': 'Cardiology',
    'Varicose veins': 'Cardiology',          # vascular; there is no vascular surgery department
    'Heart attack': 'Emergency Medicine',    # needs emergency care first, then Cardiology
    # Lungs
    'Bronchial Asthma': 'Pulmonology',
    'Pneumonia': 'Pulmonology',
    'Tuberculosis': 'Pulmonology',
    # Brain and nerves
    'Migraine': 'Neurology',
    'Paralysis (brain hemorrhage)': 'Neurology',
    # Bones and joints
    'Arthritis': 'Orthopedics',
    'Cervical spondylosis': 'Orthopedics',
    'Osteoarthristis': 'Orthopedics',
    # Ear (inner ear balance disorder)
    '(vertigo) Paroymsal  Positional Vertigo': 'ENT',
    # Urinary tract
    'Urinary tract infection': 'Urology',
    # Infections and general illness (no infectious-disease department in the project)
    'AIDS': 'General Medicine',
    'Allergy': 'General Medicine',
    'Chicken pox': 'General Medicine',
    'Common Cold': 'General Medicine',
    'Dengue': 'General Medicine',
    'Malaria': 'General Medicine',
    'Typhoid': 'General Medicine',
}

# The least clear-cut choices, to check first.
UNCERTAIN = {
    'Heart attack': 'Emergency Medicine chosen over Cardiology because it is an emergency.',
    'Varicose veins': 'No vascular surgery department; Cardiology is the closest match.',
    'Drug Reaction': 'Could also be General Medicine depending on the reaction.',
    'Chicken pox': 'Could be Dermatology or Pediatrics (for children).',
    'Paralysis (brain hemorrhage)': 'Needs Emergency Medicine first in a real emergency.',
    'Allergy': 'No allergy/immunology department; could be ENT or Dermatology by symptom.',
}


def _key(name: str) -> str:
    return ' '.join(str(name or '').split()).lower()


_LOOKUP = {_key(disease): dept for disease, dept in DISEASE_DEPARTMENT.items()}


def department_for(disease: str) -> str:
    """The department for a dataset illness; General Medicine when it is unknown."""
    return _LOOKUP.get(_key(disease), FALLBACK_DEPARTMENT)
