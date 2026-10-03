import secrets
import string

# Characters that are easy to confuse when a password is read out or retyped
# (l/I/1, O/0) are left out of generated passwords.
_AMBIGUOUS = set('lI1O0')
_ALPHABET = ''.join(c for c in string.ascii_letters + string.digits if c not in _AMBIGUOUS)


def generate_password(length: int = 10) -> str:
    """Random password with at least one upper-case letter, lower-case letter and digit."""
    alphabet = _ALPHABET
    while True:
        pwd = ''.join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.isupper() for c in pwd)
            and any(c.islower() for c in pwd)
            and any(c.isdigit() for c in pwd)
        ):
            return pwd
