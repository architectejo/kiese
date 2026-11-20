from django.core.management.base import BaseCommand

from sales.services import expire_pending_invoices


class Command(BaseCommand):
    help = (
        "BUG-318 : passe en « Non servi » les factures en attente de livraison "
        "dont l'échéance (12 h) est dépassée. Idempotent ; sans suppression."
    )

    def handle(self, *args, **options):
        n = expire_pending_invoices()
        self.stdout.write(f"{n} facture(s) passée(s) en « Non servi ».")
