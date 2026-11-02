"""
Tests Trésorerie — Niveau 3 (Livre de Caisse Direction) et scénario de
journée complète d'intégration.

Référence : CLAUDE.md §5.5, mission testeur-tresorerie.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price, make_client
from sales.models import Invoice, InvoiceLine
from treasury.models import FacturierReport, CashClosure, LocalExpense, CashbookEntry, DisbursementVoucher
from core.models import ExpenseCategory, Node, Config


def _enable_backdated_sales():
    """BUG-086 : ces tests utilisent des dates calendaires fixes, antérieures
    à aujourd'hui dès que l'horloge système avance (même cause racine que
    BUG-068/084, sans rapport avec le réglage lui-même) — la nouvelle
    validation de date de clôture (BUG-086) exige `allow_backdated_sales=True`
    pour toute date de clôture ≠ aujourd'hui. Activé ici pour ne pas changer
    l'intention de ces tests, qui portent sur un autre comportement."""
    config = Config.get_instance()
    config.allow_backdated_sales = True
    config.save(update_fields=['allow_backdated_sales'])


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


class CashbookVersementTests(TestCase):
    """Niveau 3 : versement d'une clôture au livre de caisse."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant_cb1')
        self.comptable = make_user(role='COMPTABLE', username='comptable_cb1')
        self.api_gerant = APIClient()
        self.api_gerant.force_authenticate(self.gerant)
        self.api_comptable = APIClient()
        self.api_comptable.force_authenticate(self.comptable)
        _enable_backdated_sales()

    def _validated_closure(self, d='2026-10-22', bills_50=1):
        resp = self.api_gerant.post('/api/treasury/closures/', {'date': d, 'bills_50': bills_50}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        closure = CashClosure.objects.get(pk=resp.json()['id'])
        confirm = self.api_comptable.post(f'/api/treasury/closures/{closure.id}/validate/', {}, format='json')
        self.assertEqual(confirm.status_code, 200, confirm.content)
        return closure

    def test_push_to_cashbook_creates_entry_with_correct_piece_number_and_balance(self):
        closure = self._validated_closure('2026-10-22', bills_50=1)  # net_cash=0, physical=50 -> gap mais push quand même
        resp = self.api_comptable.post(f'/api/treasury/closures/{closure.id}/push_to_cashbook/', {}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        entry = CashbookEntry.objects.get(source_closure=closure)
        self.assertEqual(entry.piece_number, f"VC-{self.node.code}-20261022")
        self.assertEqual(entry.running_balance, entry.entry_amount - entry.exit_amount)

    def test_double_versement_of_the_same_closure_is_refused(self):
        closure = self._validated_closure('2026-10-23')
        first = self.api_comptable.post(f'/api/treasury/closures/{closure.id}/push_to_cashbook/', {}, format='json')
        self.assertEqual(first.status_code, 201, first.content)
        second = self.api_comptable.post(f'/api/treasury/closures/{closure.id}/push_to_cashbook/', {}, format='json')
        self.assertEqual(second.status_code, 400, second.content)
        self.assertEqual(CashbookEntry.objects.filter(source_closure=closure).count(), 1)

    def test_cashbook_api_is_read_only(self):
        """Niveau 3 : lecture seule — aucune création/modification/suppression directe."""
        api = APIClient()
        api.force_authenticate(self.comptable)

        create = api.post('/api/treasury/cashbook/', {
            'node': str(self.node.id), 'date': '2026-10-22', 'piece_number': 'HACK-001',
            'label': 'Tentative directe', 'entry_amount': '999999.00',
        }, format='json')
        self.assertEqual(create.status_code, 405, create.content)

        closure = self._validated_closure('2026-10-24')
        self.api_comptable.post(f'/api/treasury/closures/{closure.id}/push_to_cashbook/', {}, format='json')
        entry = CashbookEntry.objects.get(source_closure=closure)

        put = api.put(f'/api/treasury/cashbook/{entry.id}/', {'label': 'Modifié'}, format='json')
        self.assertEqual(put.status_code, 405, put.content)
        patch = api.patch(f'/api/treasury/cashbook/{entry.id}/', {'label': 'Modifié'}, format='json')
        self.assertEqual(patch.status_code, 405, patch.content)
        delete = api.delete(f'/api/treasury/cashbook/{entry.id}/')
        self.assertEqual(delete.status_code, 405, delete.content)

    def test_progressive_balance_across_several_nodes(self):
        """Le solde cumulé progresse correctement, toutes boulangeries confondues."""
        node2 = make_node(code='K2', name='K2 - COQ')
        gerant2 = make_user(role='GERANT', node=node2, username='gerant_cb2')
        api_gerant2 = APIClient()
        api_gerant2.force_authenticate(gerant2)

        c1 = self._validated_closure('2026-10-25', bills_50=20)  # 1000 FC physiques
        resp2 = api_gerant2.post('/api/treasury/closures/', {'date': '2026-10-25', 'bills_50': 10}, format='json')
        self.assertEqual(resp2.status_code, 201, resp2.content)
        c2 = CashClosure.objects.get(pk=resp2.json()['id'])
        self.api_comptable.post(f'/api/treasury/closures/{c2.id}/validate/', {}, format='json')

        push1 = self.api_comptable.post(f'/api/treasury/closures/{c1.id}/push_to_cashbook/', {}, format='json')
        push2 = self.api_comptable.post(f'/api/treasury/closures/{c2.id}/push_to_cashbook/', {}, format='json')
        self.assertEqual(push1.status_code, 201, push1.content)
        self.assertEqual(push2.status_code, 201, push2.content)

        e1 = CashbookEntry.objects.get(source_closure=c1)
        e2 = CashbookEntry.objects.get(source_closure=c2)
        self.assertEqual(e2.running_balance, e1.running_balance + e2.entry_amount - e2.exit_amount)

    def test_filter_by_period(self):
        c1 = self._validated_closure('2026-09-01', bills_50=1)
        c2 = self._validated_closure('2026-10-26', bills_50=1)
        self.api_comptable.post(f'/api/treasury/closures/{c1.id}/push_to_cashbook/', {}, format='json')
        self.api_comptable.post(f'/api/treasury/closures/{c2.id}/push_to_cashbook/', {}, format='json')

        api = APIClient()
        api.force_authenticate(self.comptable)
        resp = api.get('/api/treasury/cashbook/', {'date_from': '2026-10-01', 'date_to': '2026-10-31'}, format='json')
        self.assertEqual(resp.status_code, 200)
        results = resp.json().get('results', resp.json())
        dates = {r['date'] for r in results}
        self.assertIn('2026-10-26', dates)
        self.assertNotIn('2026-09-01', dates)


class DisbursementVoucherLedgerTests(TestCase):
    """Bons de décaissement Direction — effet sur le solde du livre de caisse."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant_bv1')
        self.comptable = make_user(role='COMPTABLE', username='comptable_bv1')
        self.api_gerant = APIClient()
        self.api_gerant.force_authenticate(self.gerant)
        self.api_comptable = APIClient()
        self.api_comptable.force_authenticate(self.comptable)
        Node.objects.get_or_create(code='SIEGE', defaults={'name': 'SIEGE'})
        _enable_backdated_sales()

    def test_disbursement_voucher_reduces_balance(self):
        FacturierReport.objects.create(
            node=self.node, facturier=self.gerant, team='A', date='2026-10-22',
            total_cash_sales=Decimal('10000.00'), theoretical_cash=Decimal('10000.00'),
            node_origin=self.node.code,
        )
        resp = self.api_gerant.post('/api/treasury/closures/', {'date': '2026-10-22', 'bills_1000': 10}, format='json')
        closure = CashClosure.objects.get(pk=resp.json()['id'])
        self.api_comptable.post(f'/api/treasury/closures/{closure.id}/validate/', {}, format='json')
        push = self.api_comptable.post(f'/api/treasury/closures/{closure.id}/push_to_cashbook/', {}, format='json')
        self.assertEqual(push.status_code, 201, push.content)
        balance_before = CashbookEntry.objects.order_by('-date', '-created_at').first().running_balance

        voucher_resp = self.api_comptable.post('/api/treasury/vouchers/', {
            'date': '2026-10-23', 'motif': 'Achat farine', 'bills_1000': 5,
        }, format='json')
        self.assertEqual(voucher_resp.status_code, 201, voucher_resp.content)

        last_entry = CashbookEntry.objects.order_by('-date', '-created_at').first()
        self.assertEqual(last_entry.running_balance, balance_before - Decimal('5000.00'))

    def test_disbursement_voucher_rejected_if_exceeds_available_balance(self):
        resp = self.api_gerant.post('/api/treasury/closures/', {'date': '2026-10-22', 'bills_100': 1}, format='json')
        closure = CashClosure.objects.get(pk=resp.json()['id'])
        self.api_comptable.post(f'/api/treasury/closures/{closure.id}/validate/', {}, format='json')
        self.api_comptable.post(f'/api/treasury/closures/{closure.id}/push_to_cashbook/', {}, format='json')

        voucher_resp = self.api_comptable.post('/api/treasury/vouchers/', {
            'date': '2026-10-23', 'motif': 'Trop gros bon', 'bills_20000': 100,
        }, format='json')
        self.assertEqual(voucher_resp.status_code, 400, voucher_resp.content)
        self.assertEqual(DisbursementVoucher.objects.count(), 0)


class TreasuryBlockchainVerdictConsistencyTests(TestCase):
    """L'intégrité vérifiée côté treasury et côté blockchain doit concorder."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant_integ1')
        self.comptable = make_user(role='COMPTABLE', username='comptable_integ1')
        self.api_gerant = APIClient()
        self.api_gerant.force_authenticate(self.gerant)
        self.api_comptable = APIClient()
        self.api_comptable.force_authenticate(self.comptable)
        _enable_backdated_sales()

    def _push_closure(self, d):
        resp = self.api_gerant.post('/api/treasury/closures/', {'date': d, 'bills_50': 1}, format='json')
        closure = CashClosure.objects.get(pk=resp.json()['id'])
        self.api_comptable.post(f'/api/treasury/closures/{closure.id}/validate/', {}, format='json')
        self.api_comptable.post(f'/api/treasury/closures/{closure.id}/push_to_cashbook/', {}, format='json')

    def test_treasury_integrity_check_and_blockchain_run_check_agree_on_healthy_chain(self):
        self._push_closure('2026-10-22')
        self._push_closure('2026-10-23')

        api_hq = APIClient()
        api_hq.force_authenticate(self.comptable)
        treasury_resp = api_hq.get('/api/treasury/cashbook/integrity_check/')
        self.assertEqual(treasury_resp.status_code, 200)
        self.assertTrue(treasury_resp.json()['chain_valid'])

        blockchain_resp = api_hq.post('/api/blockchain/snapshots/run_check/', {}, format='json')
        self.assertEqual(blockchain_resp.status_code, 200, blockchain_resp.content)
        self.assertTrue(blockchain_resp.json()['all_intact'])

    def test_treasury_integrity_check_and_blockchain_run_check_agree_on_tampered_chain(self):
        self._push_closure('2026-10-22')
        self._push_closure('2026-10-23')
        tampered = CashbookEntry.objects.order_by('date', 'created_at').first()
        CashbookEntry.objects.filter(pk=tampered.pk).update(entry_amount=Decimal('999999.00'))

        api_hq = APIClient()
        api_hq.force_authenticate(self.comptable)
        treasury_resp = api_hq.get('/api/treasury/cashbook/integrity_check/')
        self.assertFalse(treasury_resp.json()['chain_valid'])

        blockchain_resp = api_hq.post('/api/blockchain/snapshots/run_check/', {}, format='json')
        self.assertFalse(blockchain_resp.json()['all_intact'])


class FullDayIntegrationTests(TestCase):
    """
    Scénario de journée complète : 2 facturiers (équipes A et B) × 10
    factures mixtes (cash/crédit) → rapports Niveau 1 → dépenses locales →
    clôture Niveau 2 avec billetage → versement Niveau 3 → vérification du
    solde et de la chaîne.
    """

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant_day1')
        self.comptable = make_user(role='COMPTABLE', username='comptable_day1')
        self.facA = make_user(role='FACTURIER', node=self.node, team='A', username='fact_day_A')
        self.facB = make_user(role='FACTURIER', node=self.node, team='B', username='fact_day_B')
        self.client_obj = make_client(self.node)
        self.bread = make_bread_price(category='MOYEN', label='Pain 300 FC', unit_price=300)
        self.category, _ = ExpenseCategory.objects.get_or_create(code='EAU', defaults={'label': 'Eau'})

        self.api_gerant = APIClient()
        self.api_gerant.force_authenticate(self.gerant)
        self.api_comptable = APIClient()
        self.api_comptable.force_authenticate(self.comptable)
        _enable_backdated_sales()

    def test_full_day_scenario(self):
        # BUG-068 : les factures sont livrées à `timezone.now()` (Invoice.deliver) ;
        # le rapport Niveau 1 les filtre par `delivered_at__date=target_date`. Une
        # date codée en dur ('2026-10-22') ne correspond plus à la date réelle de
        # livraison dès que l'horloge système avance au-delà de cette date, et le
        # rapport généré se retrouve vide (échec sans rapport avec un vrai défaut
        # applicatif). On utilise donc la date du jour réel de l'exécution.
        target_date = timezone.localdate().isoformat()
        total_cash = Decimal('0')
        total_credit = Decimal('0')

        # 2 facturiers × 10 factures mixtes.
        for fac, team in ((self.facA, 'A'), (self.facB, 'B')):
            for i in range(10):
                is_cash = (i % 2 == 0)
                qty = i + 1
                inv = _make_invoice(
                    self.node, fac, team, self.client_obj, self.bread, qty,
                    Invoice.PaymentType.CASH if is_cash else Invoice.PaymentType.CREDIT,
                    payment_amount=None if is_cash else Decimal('0'),
                )
                if is_cash:
                    total_cash += inv.order_total
                else:
                    total_credit += inv.order_total

        gen = self.api_gerant.post('/api/treasury/reports/generate/', {'date': target_date}, format='json')
        self.assertEqual(gen.status_code, 200, gen.content)
        reports = FacturierReport.objects.filter(node=self.node, date=target_date)
        self.assertEqual(reports.count(), 2)  # une par équipe
        self.assertEqual(sum(r.total_cash_sales for r in reports), total_cash)
        self.assertEqual(sum(r.total_credit_sales for r in reports), total_credit)

        LocalExpense.objects.create(
            node=self.node, gerant=self.gerant, description='Eau',
            amount=Decimal('1000.00'), category=self.category, date=target_date,
            node_origin=self.node.code,
        )

        closure_resp = self.api_gerant.post('/api/treasury/closures/', {
            'date': target_date, 'bills_1000': 10,
        }, format='json')
        self.assertEqual(closure_resp.status_code, 201, closure_resp.content)
        closure = CashClosure.objects.get(pk=closure_resp.json()['id'])
        self.assertEqual(closure.total_entries, total_cash)
        self.assertEqual(closure.net_cash, total_cash - Decimal('1000.00'))

        confirm = self.api_comptable.post(f'/api/treasury/closures/{closure.id}/validate/', {}, format='json')
        self.assertEqual(confirm.status_code, 200, confirm.content)

        push = self.api_comptable.post(f'/api/treasury/closures/{closure.id}/push_to_cashbook/', {}, format='json')
        self.assertEqual(push.status_code, 201, push.content)
        entry = CashbookEntry.objects.get(source_closure=closure)
        self.assertEqual(entry.running_balance, closure.net_cash)

        api_hq = APIClient()
        api_hq.force_authenticate(self.comptable)
        chain_check = api_hq.get('/api/treasury/cashbook/integrity_check/')
        self.assertTrue(chain_check.json()['chain_valid'])
        blockchain_check = api_hq.post('/api/blockchain/snapshots/run_check/', {}, format='json')
        self.assertTrue(blockchain_check.json()['all_intact'])
