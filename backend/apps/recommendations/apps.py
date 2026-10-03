from django.apps import AppConfig


class RecommendationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.recommendations'

    def ready(self):
        # Load the smart symptom checker's model once, when the server starts.
        # If it is missing or cannot load, the keyword checker is used instead.
        from ml import symptom_model
        symptom_model.load()
