import sys
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from core.models import Node, Config, BreadPrice

User = get_user_model()

class Command(BaseCommand):
    help = 'Seeds initial Kiese data (Nodes, Config, Bread Prices, and Default Users)'

    def handle(self, *args, **kwargs):
        self.stdout.write('Seeding initial data for ETS. KIESE...')

        # 1. Seed Config singleton
        config = Config.get_instance()
        self.stdout.write(self.style.SUCCESS(f'Global Configuration verified/created: {config}'))

        # 2. Seed Nodes (Bakery points)
        nodes_data = [
            {'code': 'K1', 'name': 'TABORA', 'address': '49, Avenue Tabora, Mbanza-Ngungu'},
            {'code': 'K2', 'name': 'COQ', 'address': 'Avenue Coq, Mbanza-Ngungu'},
            {'code': 'K3', 'name': 'ATHENEE', 'address': 'Quartier Athénée, Mbanza-Ngungu'},
            {'code': 'K4', 'name': 'LOMA', 'address': 'Quartier Loma, Mbanza-Ngungu'},
            {'code': 'K5', 'name': 'MPIANGU', 'address': 'Quartier Mpiangu, Mbanza-Ngungu'},
            {'code': 'K6', 'name': 'ZADIM', 'address': 'Quartier Zadim, Mbanza-Ngungu'},
            {'code': 'B1', 'name': 'KUMBI', 'address': 'Quartier Kumbi, Mbanza-Ngungu'},
            {'code': 'B2', 'name': 'MPETE', 'address': 'Quartier Mpete, Mbanza-Ngungu'},
        ]

        nodes = {}
        for nd in nodes_data:
            node, created = Node.objects.get_or_create(
                code=nd['code'],
                defaults={'name': nd['name'], 'address': nd['address']}
            )
            nodes[nd['code']] = node
            if created:
                self.stdout.write(f'Created Node: {node}')
            else:
                self.stdout.write(f'Node exists: {node}')

        # 3. Seed Bread Prices
        bread_prices_data = [
            {'category': 'MINI', 'label': 'Pain 200 FC', 'unit_price': 200},
            {'category': 'MOYEN', 'label': 'Pain 300 FC', 'unit_price': 300},
            {'category': 'GRAND', 'label': 'Pain 500 FC', 'unit_price': 500},
            {'category': 'PREMIUM', 'label': 'Pain 1000 FC', 'unit_price': 1000},
        ]

        for bp_d in bread_prices_data:
            bp, created = BreadPrice.objects.get_or_create(
                category=bp_d['category'],
                defaults={'label': bp_d['label'], 'unit_price': bp_d['unit_price']}
            )
            if created:
                self.stdout.write(f'Created Bread Price: {bp}')
            else:
                self.stdout.write(f'Bread Price exists: {bp}')

        # 4. Seed Default Users
        # Admin / DG
        admin_user, created = User.objects.get_or_create(
            username='pierre',
            defaults={
                'first_name': 'Pierre',
                'last_name': 'NDUNGA NSAYI',
                'email': 'pierre.ndunga@kiese.cd',
                'role': 'DIRECTION',
                'is_staff': True,
                'is_superuser': True,
            }
        )
        if created:
            admin_user.set_password('Kiese2026!')
            admin_user.save()
            self.stdout.write(self.style.SUCCESS(f'Created Direction User: pierre / Kiese2026!'))
        else:
            self.stdout.write(f'Direction User exists: {admin_user}')

        # Gérant K1
        gerant_user, created = User.objects.get_or_create(
            username='gerant_k1',
            defaults={
                'first_name': 'Jean',
                'last_name': 'Mabanza',
                'email': 'k1.gerant@kiese.cd',
                'role': 'GERANT',
                'node': nodes['K1'],
            }
        )
        if created:
            gerant_user.set_password('Kiese2026!')
            gerant_user.save()
            self.stdout.write(self.style.SUCCESS(f'Created Gerant K1 User: gerant_k1 / Kiese2026!'))
        else:
            self.stdout.write(f'Gerant User exists: {gerant_user}')

        # Facturier K1
        facturier_user, created = User.objects.get_or_create(
            username='facturier_k1',
            defaults={
                'first_name': 'Marie',
                'last_name': 'Luzolo',
                'email': 'k1.facturier@kiese.cd',
                'role': 'FACTURIER',
                'team': 'A',
                'node': nodes['K1'],
            }
        )
        if created:
            facturier_user.set_password('Kiese2026!')
            facturier_user.save()
            self.stdout.write(self.style.SUCCESS(f'Created Facturier K1 User: facturier_k1 / Kiese2026!'))
        else:
            self.stdout.write(f'Facturier User exists: {facturier_user}')

        # Livreur K1
        livreur_user, created = User.objects.get_or_create(
            username='livreur_k1',
            defaults={
                'first_name': 'Simon',
                'last_name': 'Kimbangu',
                'email': 'k1.livreur@kiese.cd',
                'role': 'LIVREUR',
                'team': 'A',
                'node': nodes['K1'],
            }
        )
        if created:
            livreur_user.set_password('Kiese2026!')
            livreur_user.save()
            self.stdout.write(self.style.SUCCESS(f'Created Livreur K1 User: livreur_k1 / Kiese2026!'))
        else:
            self.stdout.write(f'Livreur User exists: {livreur_user}')

        # 5. Seed System Notifications & Activity Logs
        from core.models import SystemNotification, ActivityLog

        # Clean existing mock logs/notifications to prevent duplicate accumulation on reseeds
        SystemNotification.objects.all().delete()
        ActivityLog.objects.all().delete()

        # Seed realistic Notifications
        SystemNotification.objects.create(
            title="Alerte Risque Client : Plafond dépassé",
            message="Le client revendeur Dieudonné Kabeya (K1) a dépassé sa limite de crédit autorisée de 500 000 FC. Encours débiteur actuel : 620 000 FC. Facturation bloquée.",
            severity="DANGER",
            node_origin="K1"
        )
        SystemNotification.objects.create(
            title="Alerte Risque Client : Plafond dépassé",
            message="Le client revendeur Florentin Nkusu (K2) a dépassé sa limite de crédit autorisée de 500 000 FC. Encours débiteur actuel : 540 000 FC. Veuillez recouvrer sa dette.",
            severity="DANGER",
            node_origin="K2"
        )
        SystemNotification.objects.create(
            title="Alerte Caisse : Clôture de Caisse K3",
            message="Écart de caisse mineur signalé lors de la clôture de l'équipe A au nœud K3 ATHENEE (-4 500 FC).",
            severity="WARNING",
            node_origin="K3"
        )
        SystemNotification.objects.create(
            title="Rapport de Synchronisation Réseau",
            message="Synchronisation décentralisée effectuée avec succès pour 8 nœuds POS. Données consolidées sur le cloud.",
            severity="SUCCESS",
            node_origin="CLOUD"
        )
        SystemNotification.objects.create(
            title="Alerte Blockchain : Signature Initiale",
            message="Intégrité du registre auditée. Aucun bloc corrompu détecté dans la chaîne décentralisée.",
            severity="INFO",
            node_origin="CLOUD"
        )

        # Seed Activity Logs
        ActivityLog.objects.create(
            user=admin_user,
            user_display=admin_user.get_full_name(),
            action="Audit Blockchain",
            description="L'administrateur a lancé un audit global de l'intégrité de la chaîne de blocs décentralisée.",
            node_origin="CLOUD"
        )
        ActivityLog.objects.create(
            user=gerant_user,
            user_display=gerant_user.get_full_name(),
            action="Inventaire Farine",
            description="Le gérant a validé l'entrée en stock de 45 sacs de farine de 50kg au nœud K1 TABORA.",
            node_origin="K1"
        )
        ActivityLog.objects.create(
            user=facturier_user,
            user_display=facturier_user.get_full_name(),
            action="Facturation POS",
            description="Facturation en caisse rapide de 150 pains Standard Moyen pour le client revendeur Marie Nzuzi.",
            node_origin="K1"
        )

        self.stdout.write(self.style.SUCCESS('Kiese Seeding completed successfully.'))

