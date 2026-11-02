"""
`python manage.py ensure_local_admin` — crée ou met à jour, de façon
idempotente, le compte administrateur local de secours créé pendant
l'assistant de première installation du poste desktop
(docs/architecture/DESKTOP.md §7 étape 5).

Ce compte sert UNIQUEMENT à continuer à facturer/livrer pendant une coupure
prolongée avec le Cloud : il ne donne jamais de droit de modification de la
configuration (SYNC.md §6 H3 — aucune route de configuration n'accepte de
jeton de nœud, et ce compte reste un utilisateur ADMIN local ordinaire,
sujet aux mêmes permissions RBAC que n'importe quel compte ADMIN).

Appelé une seule fois par `desktop/src/firstRun.ts` via le backend juste
après son premier démarrage, avec le mot de passe transmis par variable
d'environnement (jamais en argument de ligne de commande, jamais journalisé).
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

User = get_user_model()


class Command(BaseCommand):
    help = "Crée/mets à jour le compte administrateur local de secours (poste desktop)."

    def add_arguments(self, parser):
        parser.add_argument('--username', required=True)
        parser.add_argument('--first-name', default='Administrateur')
        parser.add_argument('--last-name', default='Local')

    def handle(self, *args, **options):
        username = options['username'].strip()
        password = os.environ.get('KIESE_LOCAL_ADMIN_PASSWORD')
        if not username:
            raise CommandError("Le nom d'utilisateur est requis.")
        if not password:
            raise CommandError(
                "KIESE_LOCAL_ADMIN_PASSWORD doit être défini dans l'environnement "
                "(jamais en argument de ligne de commande)."
            )

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                'first_name': options['first_name'],
                'last_name': options['last_name'],
                'role': User.Role.ADMIN,
                'is_staff': True,
                'is_superuser': False,
            },
        )
        user.set_password(password)
        if not created:
            user.role = User.Role.ADMIN
            user.is_staff = True
        user.save()

        self.stdout.write(self.style.SUCCESS(
            f"Compte administrateur local {'créé' if created else 'mis à jour'} : {username}"
        ))
