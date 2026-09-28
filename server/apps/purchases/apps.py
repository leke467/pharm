from django.apps import AppConfig


class PurchasesConfig(AppConfig):
    default_auto_field = 'django.db.models.UUIDField'
    name = 'apps.purchases'

    def ready(self):
        from . import sync_handlers  # noqa: F401
