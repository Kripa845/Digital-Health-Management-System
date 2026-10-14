from django.apps import AppConfig


class RecommendationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.recommendations'

    def ready(self):
        # Load the smart symptom checker's model once, when the server starts.
        # If it is missing or cannot load, the keyword checker is used instead.
        # If it, the synonyms, the red-flag rules or the department map disagree with
        # ml/data/symptom_schema.json, SchemaError stops the server from starting.
        from ml import symptom_model
        symptom_model.load()
