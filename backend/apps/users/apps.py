from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.users'

    def ready(self):
    
        from django.db.models.signals import post_migrate
        from .signals import ensure_admin_user
        post_migrate.connect(ensure_admin_user, sender=self)
