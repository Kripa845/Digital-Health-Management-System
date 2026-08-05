from apps.audit.models import AuditLog

def log_activity(user, action, description, request=None):
    ip_address = None
    if request:
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(',')[0].strip()
        else:
            ip_address = request.META.get('REMOTE_ADDR')
    
    return AuditLog.objects.create(
        user=user,
        action=action,
        description=description,
        ip_address=ip_address
    )
