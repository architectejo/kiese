from django.apps import AppConfig


class SyncConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'sync'
    verbose_name = 'Synchronisation Local ↔ Cloud'

    def ready(self):
        # BUG-062 : sous SQLite (nœud desktop en dev/mono-poste, ou le Cloud
        # avant sa migration recommandée vers PostgreSQL), le délai d'attente
        # par défaut de Django (`timeout=5` au connect) peut être écourté
        # dans certains modes de connexion (ex. base de test en mémoire
        # partagée `cache=shared`) — on relève explicitement le
        # `busy_timeout` SQLite sur CHAQUE connexion ouverte, en complément
        # (pas en remplacement) des retentatives applicatives déjà en place
        # (`sync.models.NodeAuthToken.authenticate()`, `sync.views.PushView`,
        # `sync.services`, `sales.views.InvoiceViewSet`, `treasury.views`) :
        # moins de retentatives nécessaires côté application, sans rien
        # retirer de cette protection applicative. Sans effet sur
        # PostgreSQL (le signal ne s'applique qu'au moteur sqlite3).
        from django.db.backends.signals import connection_created

        def _raise_sqlite_busy_timeout(sender, connection, **kwargs):
            if connection.vendor == 'sqlite':
                connection.cursor().execute('PRAGMA busy_timeout = 30000;')

        connection_created.connect(_raise_sqlite_busy_timeout)
