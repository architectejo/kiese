from django.apps import AppConfig


class TreasuryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'treasury'

    def ready(self):
        # BUG-036 : enregistre le signal de verrouillage de vacation
        # (voir treasury/signals.py — ne modifie aucun fichier de `sales`).
        from . import signals  # noqa: F401
