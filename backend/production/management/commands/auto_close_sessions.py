"""
BUG-1074 : clôture automatique des fournées à l'heure de clôture de chaque
boulangerie, pour une planification externe (tâche planifiée / cron toutes les
5 à 15 minutes). Idempotente. Aucun service d'arrière-plan n'est requis : le
même traitement est aussi déclenché paresseusement par `shift-end-status`.
"""
from django.core.management.base import BaseCommand

from core.models import Node
from production.services import auto_close_due_days


class Command(BaseCommand):
    help = "Clôture automatiquement les fournées ouvertes dont l'heure de clôture est passée."

    def add_arguments(self, parser):
        parser.add_argument('--node', help="Code d'une boulangerie (défaut : toutes).")
        parser.add_argument('--grace', type=int, default=None, help="Délai de grâce en minutes (défaut : 30).")
        parser.add_argument(
            '--ignore-switch', action='store_true',
            help="Ignorer l'interrupteur par boulangerie (block_sales_after_closure).",
        )

    def handle(self, *args, **options):
        nodes = Node.objects.filter(is_active=True).exclude(code='SIEGE')
        if options['node']:
            nodes = nodes.filter(code=options['node'])
        total = 0
        for node in nodes:
            out = auto_close_due_days(
                node, grace_minutes=options['grace'], require_switch=not options['ignore_switch'],
            )
            for day, res in out.items():
                total += len(res['closed'])
                if res['closed'] or res['skipped']:
                    self.stdout.write(
                        f"{node.code} {day} : {len(res['closed'])} clôturée(s), "
                        f"{len(res['skipped'])} laissée(s) ouverte(s)."
                    )
        self.stdout.write(self.style.SUCCESS(f"{total} fournée(s) clôturée(s) automatiquement."))
