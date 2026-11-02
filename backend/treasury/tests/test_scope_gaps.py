"""
Tests documentant des écarts entre CLAUDE.md §5.5 / le cahier des charges
et le comportement réel de `backend/treasury/` — scénarios mentionnés dans
la mission testeur-tresorerie mais absents de `remarque.md` (donc hors
périmètre strict BUG-015, mais toujours couverts par §5.5).

Chaque test `@expectedFailure` référence le ticket ouvert correspondant
dans `docs/qa/REGISTRE_BUGS.md`.
"""
import unittest
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Config
from core.testing import make_node, make_user, make_bread_price, make_client
from sales.models import Invoice, InvoiceLine
from treasury.models import CashClosure, FacturierReport


class FacturierSessionLockTests(TestCase):
    """
    Niveau 1 : une fois le rapport facturier généré pour une vacation
    (nœud + équipe + date), la vacation doit être verrouillée — aucune
    nouvelle facture ne devrait plus pouvoir s'y ajouter sans passer par
    une régénération explicite et contrôlée.
    """

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant_lock1')
        self.facA = make_user(role='FACTURIER', node=self.node, team='A', username='fact_lock_A')
        self.client_obj = make_client(self.node)
        self.bread = make_bread_price(category='MOYEN', label='Pain 300 FC', unit_price=300)
        self.api_gerant = APIClient()
        self.api_gerant.force_authenticate(self.gerant)
        self.api_fact = APIClient()
        self.api_fact.force_authenticate(self.facA)

    def _invoice(self, qty):
        inv = Invoice.objects.create(
            node=self.node, client=self.client_obj, facturier=self.facA, team='A',
            status=Invoice.Status.PENDING, payment_type=Invoice.PaymentType.CASH,
            node_origin=self.node.code, debt_before=Decimal('0.00'),
        )
        InvoiceLine.objects.create(invoice=inv, bread_price=self.bread, quantity=qty)
        inv.compute_order_total()
        inv.payment_amount = inv.order_total
        inv.compute_debt_after()
        inv.save()
        inv.deliver(livreur=self.facA)
        return inv

    def test_no_new_invoice_affects_an_already_generated_report(self):
        """
        BUG-036 (voir registre) : CLAUDE.md §5.5 / mission testeur-tresorerie
        attendent qu'une vacation (nœud+équipe+date) soit verrouillée une
        fois son `FacturierReport` Niveau 1 généré — ni l'API `sales` ni
        `FacturierReportViewSet.generate` n'empêchent la création/livraison
        de nouvelles factures après génération : une régénération silencieuse
        change alors les totaux déjà communiqués au gérant. Ce test échoue
        tant que BUG-036 n'est pas corrigé.

        Correction (dev-backend, 2026-10-22) : la mécanique de détection est
        passée d'un comptage brut de factures (qui restait à 1 même en cas
        de blocage silencieux, mais aussi — à tort — en cas de succès de
        la nouvelle livraison si celle-ci créait une facture déjà existante
        ailleurs) à une vérification explicite que (a) la tentative de
        livraison est refusée avec une erreur et (b) aucune NOUVELLE facture
        ne devient DELIVERED sur cette vacation. La ligne PENDING créée par
        `_invoice()` avant l'appel à `deliver()` reste en base (jamais
        livrée) : c'est attendu, seul le passage à DELIVERED doit être
        bloqué (remarque.md/CLAUDE.md §5.5 ne demandent pas d'empêcher la
        simple création d'une facture, seulement sa livraison sur une
        vacation déjà rapportée).
        """
        from rest_framework.exceptions import ValidationError

        self._invoice(5)
        gen1 = self.api_gerant.post('/api/treasury/reports/generate/', {}, format='json')
        self.assertEqual(gen1.status_code, 200)
        report = FacturierReport.objects.get(node=self.node, team='A')
        first_total = report.total_cash_sales

        # Une nouvelle facture est livrée APRÈS la génération du rapport.
        with self.assertRaises(ValidationError):
            self._invoice(3)

        delivered_count = Invoice.objects.filter(
            node=self.node, team='A', status=Invoice.Status.DELIVERED,
        ).count()
        self.assertEqual(
            delivered_count, 1,
            "BUG-036 : la session devrait être verrouillée — aucune nouvelle facture "
            "ne devrait pouvoir être livrée sur une vacation dont le rapport Niveau 1 "
            "a déjà été généré."
        )
        report.refresh_from_db()
        self.assertEqual(
            report.total_cash_sales, first_total,
            "BUG-036 : les totaux déjà communiqués du rapport Niveau 1 ne doivent pas "
            "être altérés par une livraison bloquée."
        )


class CashClosureBlockedByUnresolvedTransferGapTests(TestCase):
    """
    Niveau 2 : la clôture doit être bloquée si un transfert inter-
    boulangeries entrant présente un écart de quantité non résolu
    (CLAUDE.md §5.4 « écart quantité validée ≠ envoyée → alerte et blocage
    de la clôture »).
    """

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant_tgap1')
        self.api_gerant = APIClient()
        self.api_gerant.force_authenticate(self.gerant)
        # BUG-086 : la date codée en dur ci-dessous ('2026-10-22') est
        # antérieure à aujourd'hui dès que l'horloge système avance (même
        # cause racine que BUG-068/084) — sans ce réglage, la nouvelle
        # validation de date de clôture (BUG-086) la refuserait AVANT même
        # d'atteindre le contrôle de transfert en écart (BUG-037) que ce
        # test cible précisément, ce qui ferait réussir l'assertion pour la
        # mauvaise raison.
        config = Config.get_instance()
        config.allow_backdated_sales = True
        config.save(update_fields=['allow_backdated_sales'])

    def test_closure_is_blocked_by_an_unresolved_incoming_transfer_gap(self):
        """
        BUG-037 (voir registre) : `CashClosureViewSet.perform_create`/
        `push_to_cashbook` n'interrogent jamais `production.BreadTransfer`
        — aucune vérification de `quantity_gap` sur les transferts entrants
        non résolus avant de créer/pousser une clôture. Ce test échoue tant
        que BUG-037 n'est pas corrigé.
        """
        from production.models import BreadTransfer, BreadTransferLine
        from core.models import BreadPrice

        other_node = make_node(code='K2', name='K2 - COQ')
        bread = make_bread_price(category='MOYEN', label='Pain 300 FC', unit_price=300)
        transfer = BreadTransfer.objects.create(
            from_node=other_node, to_node=self.node,
            node_origin=other_node.code,
        )
        BreadTransferLine.objects.create(
            transfer=transfer, bread_price=bread,
            quantity_sent=100, quantity_received=80,  # écart non résolu de 20 pains
        )

        resp = self.api_gerant.post('/api/treasury/closures/', {'date': '2026-10-22'}, format='json')
        self.assertIn(
            resp.status_code, (400, 409),
            "BUG-037 : une clôture ne devrait pas pouvoir être créée tant qu'un "
            f"transfert entrant présente un écart non résolu. Reçu: {resp.status_code}"
        )
