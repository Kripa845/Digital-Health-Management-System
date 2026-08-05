import os

from django.contrib.auth import get_user_model


def ensure_admin_user(sender, **kwargs):
    password = os.environ.get('DJANGO_ADMIN_PASSWORD')
    if not password:
        return

    username = os.environ.get('DJANGO_ADMIN_USERNAME', 'admin').strip() or 'admin'
    email = os.environ.get('DJANGO_ADMIN_EMAIL', 'admin@merocare.com').strip()
    reset = os.environ.get('DJANGO_ADMIN_RESET_PASSWORD', '').lower() in ('1', 'true', 'yes')

    User = get_user_model()
    user, created = User.objects.get_or_create(
        username=username,
        defaults={'email': email},
    )

    changed = False
    if user.role != 'ADMIN':
        user.role = 'ADMIN'
        changed = True
    if not user.is_staff:
        user.is_staff = True
        changed = True
    if not user.is_superuser:
        user.is_superuser = True
        changed = True
    if created or reset:
        user.set_password(password)
        user.must_change_password = False
        changed = True

    if changed:
        user.save()

    print(f"[ensure_admin_user] {'created' if created else 'ensured'} admin '{username}' (role=ADMIN).")
