import logging
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)

def send_welcome_email(email_address, full_name, username, password):
   
    subject = "Welcome to Mero Care Card"
    body = (
        f"Dear {full_name},\n\n"
        f"Your Mero Care Card account has been successfully created.\n\n"
        f"You can now log in using the credentials below.\n\n"
        f"Username:\n"
        f"{username}\n\n"
        f"Temporary Password:\n"
        f"{password}\n\n"
        f"Please log in and change your password after your first login.\n\n"
        f"Login Portal:\n"
        f"http://localhost:5173/login\n\n"
        f"Thank you.\n\n"
        f"Mero Care Card Team"
    )

    logger.info(f"Attempting to send welcome email to {email_address} (Username: {username})")

    
    send_mail(
        subject=subject,
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL or 'Mero Care Card <merocarecard@gmail.com>',
        recipient_list=[email_address],
        fail_silently=False,
    )
