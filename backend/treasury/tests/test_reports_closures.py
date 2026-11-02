"""
Tests Trésorerie — Niveau 1 (rapport facturier) et Niveau 2 (clôture gérant).

Référence : CLAUDE.md §5.5, mission testeur-tresorerie (scénarios niveau 1/2),
BUG-015 (audit remarque.md, lignes 120, 142, 150-157, 163, 176-178).

Ces tests ne modifient aucun code applicatif — ils documentent le
comportement réel (conforme ou non) de `backend/treasury/`.
"""
import unittest
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import BreadPrice, Config
from core.testing import make_node, make_user, make_bread_price, make_client
from sales.models import Invoice, InvoiceLine
from treasury.models import FacturierReport, CashClosure, LocalExpense
from core.models import ExpenseCategory


def _make_invoice(node, facturier, team, client, bread, qty, payment_type, payment_amount=None):
    inv = Invoice.objects.create(
        node=node, client=client, facturier=facturier, team=team,
        status=Invoice.Status.PENDING, payment_type=payment_type,
        node_origin=node.code, debt_before=Decimal('0.00'),
    )
    InvoiceLine.objects.create(invoice=inv, bread_price=bread, quantity=qty)
    inv.compute_order_total()
    inv.payment_amount = payment_amount if payment_amount is not None else (
        inv.order_total if payment_type == Invoice.PaymentType.CASH else Decimal('0')
    )
    inv.compute_debt_after()
    inv.save()
    inv.deliver(livreur=facturier)
    return inv


class FacturierReportGenerationTests(TestCase):
    """Niveau 1 : rapport facturier par équipe — cumul cash/crédit/théorique."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant1')
        self.facA = make_user(role='FACTURIER', node=self.node, team='A', username='factA')
        self.client_obj = make_client(self.node)
        self.bread300 = make_bread_price(category='MOYEN', label='Pain 300 FC', unit_price=300)
        self.api = APIClient()
        self.api.force_authenticate(self.gerant)

    def test_report_totals_equal_sum_of_delivered_invoices(self):
        _make_invoice(self.node, self.facA, 'A', self.client_obj, self.bread300, 5, Invoice.PaymentType.CASH)
        _make_invoice(self.node, self.facA, 'A', self.client_obj, self.bread300, 3, Invoice.PaymentType.CREDIT, payment_amount=Decimal('0'))

        resp = self.api.post('/api/treasury/reports/generate/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)

        report = FacturierReport.objects.get(node=self.node, team='A')
        # 5 pains cash à 300 FC = 1500 FC cash ; 3 pains crédit = 900 FC crédit
        self.assertEqual(report.total_cash_sales, Decimal('1500.00'))
        self.assertEqual(report.total_credit_sales, Decimal('900.00'))
        self.assertEqual(report.theoretical_cash, Decimal('1500.00'))

        # Doit être égal à la somme réelle des factures livrées de la vacation.
        delivered = Invoice.objects.filter(node=self.node, team='A', status=Invoice.Status.DELIVERED)
        self.assertEqual(report.total_cash_sales, sum(i.payment_amount for i in delivered))

    def test_report_filtered_by_node(self):
        """remarque.md l.150/163 : le Niveau 1 doit être filtrable par boulangerie."""
        node2 = make_node(code='K2', name='K2 - COQ')
        fac2 = make_user(role='FACTURIER', node=node2, team='B', username='factB2')
        client2 = make_client(node2)
        _make_invoice(node2, fac2, 'B', client2, self.bread300, 2, Invoice.PaymentType.CASH)
        _make_invoice(self.node, self.facA, 'A', self.client_obj, self.bread300, 1, Invoice.PaymentType.CASH)

        api2 = APIClient()
        hq = make_user(role='DIRECTION', username='direction_filter_test')
        api2.force_authenticate(hq)
        gen1 = api2.post('/api/treasury/reports/generate/', {'node': str(self.node.id)}, format='json')
        self.assertEqual(gen1.status_code, 200, gen1.content)
        gen2 = api2.post('/api/treasury/reports/generate/', {'node': str(node2.id)}, format='json')
        self.assertEqual(gen2.status_code, 200, gen2.content)

        resp = self.api.get('/api/treasury/reports/', {'node': str(self.node.id)}, format='json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        results = data.get('results', data)
        node_ids = {str(r['node']) for r in results}
        self.assertEqual(node_ids, {str(self.node.id)})


class FacturierReportDetailFieldsTests(TestCase):
    """
    remarque.md l.142 : le rapport facturier Niveau 1 doit afficher le
    nombre de sacs consommés, le nombre de pains produits/vendus PAR
    CATÉGORIE (200/300/400/500/1000 FC), et les écarts entre le montant
    théorique issu des sacs et le montant obtenu après vente.
    """

    def test_facturier_report_model_has_no_category_breakdown_fields(self):
        """
        BUG-033 (voir docs/qa/REGISTRE_BUGS.md) : `FacturierReport` n'expose
        que des totaux agrégés (total_cash_sales/total_credit_sales/
        theoretical_cash) — aucun champ ne porte le détail par catégorie de
        pain, ni le nombre de sacs consommés, ni l'écart sacs/ventes exigé
        par remarque.md l.142. Ce test documente l'absence réelle de ces
        champs — il échoue tant que BUG-033 n'est pas corrigé.
        """
        field_names = {f.name for f in FacturierReport._meta.get_fields()}
        expected_detail_fields = {
            'sacks_consumed',
            'breads_produced_by_category',
            'breads_sold_by_category',
            'sacks_value_gap',
        }
        missing = expected_detail_fields - field_names
        self.assertEqual(
            missing, set(),
            "BUG-033 : champs de détail (sacs consommés / pains produits-vendus "
            "par catégorie / écart) absents de FacturierReport — remarque.md l.142 "
            f"non implémenté. Champs manquants : {sorted(missing)}"
        )


class CashClosureNetCashTests(TestCase):
    """Niveau 2 : caisse nette = ventes cash − dépenses locales."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant2')
        self.facA = make_user(role='FACTURIER', node=self.node, team='A', username='factA2')
        self.client_obj = make_client(self.node)
        self.bread300 = make_bread_price(category='MOYEN', label='Pain 300 FC', unit_price=300)
        self.category, _ = ExpenseCategory.objects.get_or_create(code='TRANSPORT', defaults={'label': 'Transport'})
        self.api = APIClient()
        self.api.force_authenticate(self.gerant)
        # BUG-086 : ces scénarios utilisent des dates calendaires fixes
        # (antérieures à aujourd'hui dès que l'horloge système avance,
        # même cause racine que BUG-068/084) sans rapport avec le réglage
        # lui-même — la validation de date de clôture (BUG-086) exige
        # désormais `allow_backdated_sales=True` pour toute date ≠
        # aujourd'hui, activé ici pour ne pas changer l'intention du test.
        config = Config.get_instance()
        config.allow_backdated_sales = True
        config.save(update_fields=['allow_backdated_sales'])

    def test_net_cash_is_cash_sales_minus_local_expenses(self):
        # BUG-068 : la facture est livrée à `timezone.now()` (Invoice.deliver) et le
        # rapport Niveau 1 la retrouve via `delivered_at__date=target_date`. Une date
        # codée en dur ('2026-10-22') cesse de correspondre à la date réelle de
        # livraison dès que l'horloge système avance, et le rapport généré est vide
        # (échec sans rapport avec un vrai défaut applicatif). On utilise donc la
        # date du jour réel de l'exécution pour les trois opérations liées.
        target_date = timezone.localdate().isoformat()
        _make_invoice(self.node, self.facA, 'A', self.client_obj, self.bread300, 10, Invoice.PaymentType.CASH)
        self.api.post('/api/treasury/reports/generate/', {'date': target_date}, format='json')

        LocalExpense.objects.create(
            node=self.node, gerant=self.gerant, description='Transport farine',
            amount=Decimal('500.00'), category=self.category, date=target_date,
            node_origin=self.node.code,
        )

        resp = self.api.post('/api/treasury/closures/', {
            'date': target_date,
            'bills_1000': 2, 'bills_500': 5,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        closure = CashClosure.objects.get(pk=resp.json()['id'])

        # 10 pains x 300 FC = 3000 FC cash ; dépense 500 FC → net = 2500 FC.
        self.assertEqual(closure.total_entries, Decimal('3000.00'))
        self.assertEqual(closure.total_expenses, Decimal('500.00'))
        self.assertEqual(closure.net_cash, Decimal('2500.00'))

    def test_bill_breakdown_total_equals_sum_of_quantity_times_value(self):
        resp = self.api.post('/api/treasury/closures/', {
            'date': '2026-10-23',
            'bills_20000': 2, 'bills_10000': 1, 'bills_5000': 3,
            'bills_1000': 10, 'bills_500': 4, 'bills_200': 5,
            'bills_100': 2, 'bills_50': 6,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        closure = CashClosure.objects.get(pk=resp.json()['id'])
        expected = 2 * 20000 + 1 * 10000 + 3 * 5000 + 10 * 1000 + 4 * 500 + 5 * 200 + 2 * 100 + 6 * 50
        self.assertEqual(closure.physical_cash_total, Decimal(str(expected)))

    def test_cash_gap_positive_negative_and_null(self):
        # Les rapports facturiers Niveau 1 sont créés directement (plutôt que
        # via l'agrégation des factures, dont le filtre `delivered_at__date`
        # dépend de l'horloge réelle du serveur) pour isoler précisément le
        # calcul de l'écart Niveau 2 à partir d'un théorique connu.

        # Écart nul : billetage == net_cash (aucune vente, aucune dépense, 0 billet).
        resp = self.api.post('/api/treasury/closures/', {'date': '2026-10-24'}, format='json')
        closure = CashClosure.objects.get(pk=resp.json()['id'])
        self.assertEqual(closure.cash_gap, Decimal('0.00'))

        # Écart positif : excédent physique (plus de billets comptés que de théorique).
        FacturierReport.objects.create(
            node=self.node, facturier=self.facA, team='A', date='2026-10-25',
            total_cash_sales=Decimal('300.00'), theoretical_cash=Decimal('300.00'),
            node_origin=self.node.code,
        )
        resp = self.api.post('/api/treasury/closures/', {
            'date': '2026-10-25', 'bills_1000': 1,  # 1000 FC comptés, 300 FC attendus
        }, format='json')
        closure = CashClosure.objects.get(pk=resp.json()['id'])
        self.assertGreater(closure.cash_gap, 0)

        # Écart négatif : manquant (moins de billets comptés que de théorique).
        FacturierReport.objects.create(
            node=self.node, facturier=self.facA, team='A', date='2026-10-26',
            total_cash_sales=Decimal('3000.00'), theoretical_cash=Decimal('3000.00'),
            node_origin=self.node.code,
        )
        resp2 = self.api.post('/api/treasury/closures/', {
            'date': '2026-10-26', 'bills_50': 1,  # 50 FC comptés, 3000 FC attendus
        }, format='json')
        closure2 = CashClosure.objects.get(pk=resp2.json()['id'])
        self.assertLess(closure2.cash_gap, 0)


class CashClosureWorkflowTests(TestCase):
    """Niveau 2 : workflow gérant → comptable (confirmer / infirmer / re-soumettre)."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant3')
        self.comptable = make_user(role='COMPTABLE', username='comptable1')
        self.api_gerant = APIClient()
        self.api_gerant.force_authenticate(self.gerant)
        self.api_comptable = APIClient()
        self.api_comptable.force_authenticate(self.comptable)
        # BUG-086 : voir commentaire équivalent dans CashClosureNetCashTests.
        config = Config.get_instance()
        config.allow_backdated_sales = True
        config.save(update_fields=['allow_backdated_sales'])

    def _create_closure(self, d='2026-10-22'):
        resp = self.api_gerant.post('/api/treasury/closures/', {'date': d, 'bills_50': 1}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        return CashClosure.objects.get(pk=resp.json()['id'])

    def test_double_closure_same_day_same_node_is_refused(self):
        """
        BUG-035 (voir registre) : le modèle interdit bien la double clôture
        (contrainte unique_together node+date), mais `CashClosureViewSet`
        ne l'intercepte pas : la seconde tentative lève une `IntegrityError`
        SQLite non capturée, qui remonte en erreur serveur (500) au lieu
        d'un refus propre (400/409) avec message `{"detail": "..."}`
        (CLAUDE.md §4 : « messages d'erreur API en français »).
        """
        self._create_closure('2026-10-22')
        self.api_gerant.raise_request_exception = False
        resp = self.api_gerant.post('/api/treasury/closures/', {'date': '2026-10-22', 'bills_50': 2}, format='json')
        self.assertIn(
            resp.status_code, (400, 409),
            f"BUG-035 : une double clôture {self.node.code}/2026-10-22 doit être refusée "
            f"proprement (400/409), pas planter en erreur serveur. Reçu: {resp.status_code}"
        )
        self.assertEqual(CashClosure.objects.filter(node=self.node, date='2026-10-22').count(), 1)

    def test_comptable_can_reject_then_gerant_resubmits_then_confirms(self):
        closure = self._create_closure()

        reject = self.api_comptable.post(f'/api/treasury/closures/{closure.id}/reject/', {'reason': 'Billetage incohérent'}, format='json')
        self.assertEqual(reject.status_code, 200, reject.content)
        closure.refresh_from_db()
        self.assertTrue(closure.is_rejected)
        self.assertFalse(closure.is_validated)

        # Le gérant corrige et re-soumet.
        resubmit = self.api_gerant.patch(f'/api/treasury/closures/{closure.id}/', {'bills_50': 3}, format='json')
        self.assertEqual(resubmit.status_code, 200, resubmit.content)
        closure.refresh_from_db()
        self.assertFalse(closure.is_rejected)

        confirm = self.api_comptable.post(f'/api/treasury/closures/{closure.id}/validate/', {}, format='json')
        self.assertEqual(confirm.status_code, 200, confirm.content)
        closure.refresh_from_db()
        self.assertTrue(closure.is_validated)

    def test_closure_still_editable_by_gerant_after_comptable_confirmation(self):
        """
        BUG-034 (voir registre) : remarque.md l.156 prévoit que SEULE une
        clôture infirmée peut être modifiée par le gérant avant nouvelle
        soumission. En l'état, `CashClosureViewSet.perform_update` ne
        vérifie jamais `is_rejected`/`is_validated` avant d'accepter un
        PATCH : une clôture déjà CONFIRMÉE par le comptable reste
        modifiable par le gérant. Ce test échoue tant que BUG-034 n'est pas
        corrigé (il faudrait un 400/403 sur ce PATCH).
        """
        closure = self._create_closure()
        self.api_comptable.post(f'/api/treasury/closures/{closure.id}/validate/', {}, format='json')
        closure.refresh_from_db()
        self.assertTrue(closure.is_validated)

        resp = self.api_gerant.patch(f'/api/treasury/closures/{closure.id}/', {'bills_50': 999}, format='json')
        self.assertIn(
            resp.status_code, (400, 403),
            "BUG-034 : une clôture déjà confirmée par le comptable ne doit plus être "
            f"modifiable par le gérant — reçu {resp.status_code} au lieu de 400/403."
        )
