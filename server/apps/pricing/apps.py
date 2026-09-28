from django.apps import AppConfig


class PricingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.pricing'

    def ready(self):
        import apps.pricing.sync_handlers  # noqa: F401
