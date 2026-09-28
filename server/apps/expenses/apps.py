from django.apps import AppConfig


class ExpensesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.expenses'

    def ready(self):
        import apps.expenses.sync_handlers  # noqa: F401
