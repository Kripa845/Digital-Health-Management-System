
import re
import unicodedata

from django.contrib.auth import get_user_model

User = get_user_model()


def normalize_name(value: str) -> str:
    """Collapse spaces and upper-case each word's first letter, keeping the rest
    as typed ("McDonald" stays "McDonald")."""
    return " ".join(word[:1].upper() + word[1:] for word in (value or "").split())


_NAME_PUNCTUATION = set(" '-.")


def is_valid_person_name(value: str) -> bool:
    """Letters in any script (including Devanagari vowel signs), spaces,
    hyphens, apostrophes and dots. Must contain at least one letter."""
    if not value or not any(unicodedata.category(c).startswith('L') for c in value):
        return False
    return all(
        unicodedata.category(c)[0] in ('L', 'M') or c in _NAME_PUNCTUATION
        for c in value
    )


def slugify_name(*parts: str) -> str:
    
    text = " ".join(p for p in parts if p)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    words = re.findall(r"[a-z0-9]+", text)
    return ".".join(words)


def unique_username(base: str, fallback: str = "") -> str:
   
    base = base or fallback or "user"
    candidate = base
    n = 2
    while User.objects.filter(username=candidate).exists():
        candidate = f"{base}{n}"
        n += 1
    return candidate


def patient_username(first_name: str, last_name: str, fallback: str) -> str:

    return unique_username(slugify_name(first_name, last_name), fallback.lower())


def doctor_username(first_name: str, last_name: str, fallback: str) -> str:
   
    stem = slugify_name(last_name) or slugify_name(first_name)
    base = f"dr.{stem}" if stem else ""
    return unique_username(base, fallback.lower())
