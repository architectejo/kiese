"""BUG-506 : liste (lecture seule) les comptes GERANT/FACTURIER/LIVREUR sans boulangerie."""
from django.core.management.base import BaseCommand

from core.models import User


class Command(BaseCommand):
    help = "Liste les comptes liés à une boulangerie (gérant, facturier, livreur) sans nœud. Ne modifie rien."

    def handle(self, *args, **options):
        users = User.objects.filter(
            role__in=[User.Role.GERANT, User.Role.FACTURIER, User.Role.LIVREUR],
            node__isnull=True, is_superuser=False,
        ).order_by('role', 'username')
        total = users.count()
        if not total:
            self.stdout.write("Aucun compte sans boulangerie.")
            return
        self.stdout.write(f"{total} compte(s) sans boulangerie (aucune donnée visible tant qu'un nœud n'est pas assigné) :")
        for u in users:
            actif = 'actif' if u.is_active else 'inactif'
            self.stdout.write(f"  - {u.username} ({u.role}, {actif})")
