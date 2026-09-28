from django.apps import AppConfig


class SalesConfig(AppConfig):
    default_auto_field = 'django.db.models.UUIDField'
    name = 'apps.sales'
    verbose_name = 'Sales & POS'

    def ready(self):
        from . import sync_handlers  # noqa: F401
