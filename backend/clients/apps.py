from django.apps import AppConfig
from django.db import connection
from django.db.backends.signals import connection_created


class ClientsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'clients'

    def ready(self):
        # BUG-743 : fonction SQL de repli casse/accents pour la recherche sous SQLite.
        from .search import register_sqlite_functions
        connection_created.connect(register_sqlite_functions, dispatch_uid='kiese_sqlite_fold')
        # Connexion déjà ouverte avant ready() (ex. shell) : on l'équipe aussi.
        if connection.connection is not None:
            register_sqlite_functions(connection=connection)
