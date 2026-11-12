"""
BUG-036 : verrouillage de vacation après génération du Rapport Facturier
Niveau 1 (CLAUDE.md §5.5 ; scénario « Session verrouillée après génération :
plus de facture possible sur cette vacation » — mission testeur-tresorerie).

`sales.models.Invoice` ne doit pas être modifié pour ce ticket (hors
périmètre de cette itération dev-backend-tresorerie, restreinte à
`backend/treasury/`). On branche donc le contrôle via un signal `pre_save`
sur `sales.Invoice`, enregistré par l'app `treasury` elle-même (aucun
fichier de `sales/` touché) : au moment où une facture bascule vers le
statut `DELIVERED` (livraison confirmée, que ce soit via
`Invoice.deliver()` ou une création directe déjà `DELIVERED` — vente
occasionnelle livrée immédiatement), on vérifie qu'aucun `FacturierReport`
n'existe déjà pour cette vacation (nœud + équipe + date de livraison). Si
un rapport existe déjà, la livraison est refusée : plus de régénération
silencieuse, le gérant doit explicitement régénérer le rapport Niveau 1
après avoir traité ce cas (ex. division de la vacation, correction
manuelle) plutôt que de voir ses totaux déjà communiqués changer sous lui.
BUG-083 (« ventes passées », remarque.md l.360, décision client §4/point f) :
quand `Config.allow_backdated_sales=True` ET que la livraison cible
réellement une date PASSÉE (date de travail de `delivered_at` < date de travail
courante, BUG-189/BUG-161 B3 — jamais une
simple re-livraison du jour même déjà rapportée, qui reste bloquée comme
avant), on ne lève plus `ValidationError` : on laisse la sauvegarde se
poursuivre et on planifie, APRÈS COMMIT de la transaction englobante
(`Invoice.deliver()`/`InvoiceViewSet.deliver`), la régénération du rapport
et — si une `CashClosure` déjà validée existe pour ce jour — l'écriture de
correction au Livre de Caisse (`treasury.services.handle_retroactive_delivery`),
qui ne modifie jamais une `CashbookEntry` existante (CLAUDE.md §5.5).
"""
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError


@receiver(pre_save, sender='sales.Invoice', dispatch_uid='treasury_lock_vacation_on_delivery')
def block_delivery_on_already_reported_vacation(sender, instance, **kwargs):
    # On ne s'intéresse qu'au moment où la facture DEVIENT livrée.
    if instance.status != sender.Status.DELIVERED:
        return
    if not instance.delivered_at:
        return

    if getattr(instance, 'is_debt_repayment', False):
        # BUG-100 : un remboursement/dépôt sans ligne (CLAUDE.md §5.2 —
        # « facture sans ligne, commande = 0, réduit la BP, n'est pas une
        # vente ») n'est jamais une vente et ne modifie ni le stock de
        # pains ni les ventes cash théoriques déjà figées dans le Rapport
        # Facturier Niveau 1 : il ne fait qu'ajouter un versement. Le
        # verrou de vacation (BUG-036) ne doit donc jamais s'appliquer à
        # ce type de facture, quelle que soit la vacation déjà rapportée.
        # L'agrégation `total_cash_sales` capte correctement ce versement
        # si le rapport est régénéré plus tard dans la journée (voir
        # treasury.services.regenerate_facturier_reports).
        return

    if instance.pk:
        try:
            previous_status = sender.objects.only('status').get(pk=instance.pk).status
        except sender.DoesNotExist:
            previous_status = None
        if previous_status == sender.Status.DELIVERED:
            # Déjà livrée précédemment : ce n'est pas un nouvel événement de
            # livraison (ex. simple correction d'un autre champ), on ne
            # bloque pas une resauvegarde anodine.
            return

    from .models import FacturierReport

    # BUG-189 : jamais `delivered_at.date()` (datetime aware = date UTC, fausse
    # entre 00:00 et 01:00 à Kinshasa). Date de travail du nœud à l'instant de
    # la livraison : date locale hors rotation, journée de relève à relève en
    # mode rotation (BUG-161 B3).
    from core.workday import work_date_for

    delivery_date = work_date_for(instance.node, instance.delivered_at)
    already_reported = FacturierReport.objects.filter(
        node_id=instance.node_id,
        team=instance.team,
        date=delivery_date,
    ).exists()
    if not already_reported:
        return

    from core.models import Config
    config = Config.get_instance()
    is_backdated = delivery_date < work_date_for(instance.node)

    if config.allow_backdated_sales and is_backdated:
        # Ne bloque plus : régénération du rapport + correction éventuelle
        # du Livre de Caisse planifiées après commit (jamais à l'intérieur
        # de cette même transaction — on ne connaît le solde final du
        # client/l'ordre total de la facture qu'une fois celle-ci réellement
        # sauvegardée, voir sales.models.Invoice.deliver).
        node_id = instance.node_id
        team = instance.team
        invoice_pk = instance.pk

        def _run_after_commit():
            from core.models import Node
            from sales.models import Invoice
            from .services import handle_retroactive_delivery
            try:
                invoice = Invoice.objects.select_related('node').get(pk=invoice_pk)
                node = Node.objects.get(pk=node_id)
            except (Invoice.DoesNotExist, Node.DoesNotExist):
                return
            handle_retroactive_delivery(
                invoice=invoice, node=node, team=team,
                delivery_date=delivery_date, acting_user=invoice.livreur,
            )

        transaction.on_commit(_run_after_commit)
        return

    raise ValidationError({
        'detail': (
            f"Vacation déjà rapportée (Rapport Facturier Niveau 1 généré pour "
            f"l'équipe {instance.team or '—'} du {delivery_date}) — livraison "
            "bloquée. Le gérant doit régénérer explicitement le rapport après "
            "traitement de cette facture."
        )
    })
