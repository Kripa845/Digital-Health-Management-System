"""Human-friendly, guaranteed-unique username generation for admin-created accounts.

Patients get `firstname.lastname`; doctors get `dr.lastname`. If a name is
already taken, a numeric suffix is appended (`hari.tamang`, `hari.tamang2`, …).
Accents are stripped and non-alphanumerics dropped so the result is always a
valid, readable login. Falls back to the card id when no usable name exists.
"""
import re
import unicodedata

from django.contrib.auth import get_user_model

User = get_user_model()


def normalize_name(value: str) -> str:
    """Collapse whitespace and Title-Case each word: 'rojina' -> 'Rojina', 'MARY jane' -> 'Mary Jane'."""
    return " ".join(word.capitalize() for word in (value or "").split())


def slugify_name(*parts: str) -> str:
    """Join name parts into a lowercase dotted slug: ("Hari", "Tamang") -> "hari.tamang"."""
    text = " ".join(p for p in parts if p)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    words = re.findall(r"[a-z0-9]+", text)
    return ".".join(words)


def unique_username(base: str, fallback: str = "") -> str:
    """Return `base`, or `base2`, `base3`, … until it is unused. Uses `fallback` if base is empty."""
    base = base or fallback or "user"
    candidate = base
    n = 2
    while User.objects.filter(username=candidate).exists():
        candidate = f"{base}{n}"
        n += 1
    return candidate


def patient_username(first_name: str, last_name: str, fallback: str) -> str:
    """`firstname.lastname`, unique, e.g. hari.tamang / hari.tamang2. Fallback to card id."""
    return unique_username(slugify_name(first_name, last_name), fallback.lower())


def doctor_username(first_name: str, last_name: str, fallback: str) -> str:
    """`dr.lastname` (or `dr.firstname` if no surname), unique. Fallback to card id."""
    stem = slugify_name(last_name) or slugify_name(first_name)
    base = f"dr.{stem}" if stem else ""
    return unique_username(base, fallback.lower())
