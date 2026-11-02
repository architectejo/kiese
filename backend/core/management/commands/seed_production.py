"""
`python manage.py seed_production` — initialise une base de données VIERGE
pour la mise en production : configuration globale, les 8 boulangeries, et un
compte gérant par boulangerie. Aucune donnée de démonstration (pas de client,
facture, notification ou journal d'activité fictifs) — contrairement à
`seed_kiese` qui reste le script de données de démo pour le développement.

Idempotent : peut être relancé sans dupliquer (get_or_create partout).
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from core.models import Node, Config

User = get_user_model()

NODES_DATA = [
    {'code': 'K1', 'name': 'TABORA', 'address': '49, Avenue Tabora, Mbanza-Ngungu'},
    {'code': 'K2', 'name': 'COQ', 'address': 'Avenue Coq, Mbanza-Ngungu'},
    {'code': 'K3', 'name': 'ATHENEE', 'address': 'Quartier Athénée, Mbanza-Ngungu'},
    {'code': 'K4', 'name': 'LOMA', 'address': 'Quartier Loma, Mbanza-Ngungu'},
    {'code': 'K5', 'name': 'MPIANGU', 'address': 'Quartier Mpiangu, Mbanza-Ngungu'},
    {'code': 'K6', 'name': 'ZADIM', 'address': 'Quartier Zadim, Mbanza-Ngungu'},
    {'code': 'B1', 'name': 'KUMBI', 'address': 'Quartier Kumbi, Mbanza-Ngungu'},
    {'code': 'B2', 'name': 'MPETE', 'address': 'Quartier Mpete, Mbanza-Ngungu'},
]


class Command(BaseCommand):
    help = 'Initialise une base de production vierge : configuration, 8 boulangeries, 1 gérant par boulangerie.'

    def handle(self, *args, **kwargs):
        self.stdout.write('Initialisation de la base de production ETS. KIESE...')

        # 1. Configuration globale (singleton, valeurs par défaut du modèle)
        config = Config.get_instance()
        self.stdout.write(self.style.SUCCESS(f'Configuration globale : {config}'))

        # 2. Compte Direction (ADMIN+DIRECTION, accès complet) — nécessaire
        #    pour administrer le système dès le premier démarrage.
        admin_user, created = User.objects.get_or_create(
            username='admin',
            defaults={
                'first_name': 'Pierre',
                'last_name': 'NDUNGA NSAYI',
                'role': User.Role.DIRECTION,
                'is_staff': True,
                'is_superuser': True,
            }
        )
        admin_user.set_password('admin')
        if not created:
            admin_user.role = User.Role.DIRECTION
            admin_user.is_staff = True
            admin_user.is_superuser = True
        admin_user.save()
        self.stdout.write(self.style.SUCCESS(
            f"Compte Direction {'créé' if created else 'mis à jour'} : admin / admin "
            "(à changer dès la première connexion)"
        ))

        # 3. Les 8 boulangeries
        nodes = {}
        for nd in NODES_DATA:
            node, created = Node.objects.get_or_create(
                code=nd['code'],
                defaults={'name': nd['name'], 'address': nd['address']}
            )
            nodes[nd['code']] = node
            self.stdout.write(f"Boulangerie {'créée' if created else 'déjà présente'} : {node}")

        # 4. Un compte GERANT par boulangerie
        for nd in NODES_DATA:
            code = nd['code']
            username = f"@gerant-{code.lower()}"
            password = f"@gerant-{code.lower()}"
            gerant, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'first_name': 'Gérant',
                    'last_name': nd['name'],
                    'role': User.Role.GERANT,
                    'node': nodes[code],
                }
            )
            gerant.set_password(password)
            if not created:
                gerant.role = User.Role.GERANT
                gerant.node = nodes[code]
            gerant.save()
            self.stdout.write(self.style.SUCCESS(
                f"Gérant {'créé' if created else 'mis à jour'} : {username} / {password} "
                f"(boulangerie {code})"
            ))

        self.stdout.write(self.style.SUCCESS(
            '\nInitialisation de production terminée. '
            f'{len(NODES_DATA)} boulangeries, {len(NODES_DATA)} comptes gérant + 1 compte Direction.'
        ))
