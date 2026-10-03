import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def _login_url() -> str:
    base = getattr(settings, 'FRONTEND_URL', '') or 'http://localhost:5173'
    return f"{base.rstrip('/')}/login"


def send_welcome_email(email_address, full_name, username, password=None):
    """Email new-account login details. ``password`` is None when the admin chose
    the password themselves, so it is not repeated in the email."""
    if password:
        password_block = f"Temporary Password:\n{password}\n\nPlease log in and change your password after your first login.\n\n"
    else:
        password_block = "Use the password given to you by your administrator. You will be asked to change it after your first login.\n\n"

    body = (
        f"Dear {full_name},\n\n"
        f"Your Mero Care Card account has been successfully created.\n\n"
        f"You can now log in using the details below.\n\n"
        f"Username:\n{username}\n\n"
        f"{password_block}"
        f"Login Portal:\n{_login_url()}\n\n"
        f"Thank you.\n\n"
        f"Mero Care Card Team"
    )
    logger.info("Sending welcome email to %s (username: %s)", email_address, username)
    send_mail(
        subject="Welcome to Mero Care Card",
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email_address],
        fail_silently=False,
    )


def account_created_response(label, email, full_name, username, password, password_was_generated):
    """Send the welcome email and build the API response for a new account.

    When the email cannot be sent, the response carries the generated
    credentials so the admin can hand them over; otherwise they would be lost.
    """
    email_sent = False
    if email:
        try:
            send_welcome_email(email, full_name, username, password if password_was_generated else None)
            email_sent = True
        except Exception:
            logger.exception("Failed to send welcome email to %s", email)

    if email_sent:
        return {
            'success': True,
            'email_sent': True,
            'message': f"{label} registered. Login details have been sent to {email}.",
        }

    data = {
        'success': True,
        'email_sent': False,
        'message': (
            f"{label} registered, but the welcome email could not be sent. "
            "Copy the login details now and give them to the user."
        ),
        'generated_username': username,
    }
    if password_was_generated:
        data['generated_password'] = password
    return data
