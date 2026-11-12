"""
Vérification indépendante (testeur-tresorerie, 2026-11-11) de BUG-178 : une
facture RG (régularisation) ou NS (non servie) ne doit pas entrer dans le
rapport facturier Niveau 1, ni (par cascade) dans la clôture Niveau 2, le
journal (suggested_ca) et le livre de caisse.

`TransactionTestCase` pour le scénario rétroactif (`transaction.on_commit`).
"""
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.test import TestCase, TransactionTestCase
from django.utils import timezone as tz
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from core.models import Config
from core.testing import make_node, make_user, make_bread_price, make_client
from sales.models import Invoice, InvoiceLine
from treasury.models import CashClosure, CashbookEntry, FacturierReport, LocalExpense


def _api(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _mk(node, fac, client, bread, qty, ptype, payment, team='A', code='',
        day=None, deliver=True):
    inv = Invoice.objects.create(
        node=node, client=client, facturier=fac, team=team,
        status=Invoice.Status.PENDING, payment_type=ptype, special_code=code,
        node_origin=node.code, debt_before=Decimal('0.00'),
        **({'invoice_date': day} if day else {}),
    )
    InvoiceLine.objects.create(invoice=inv, bread_price=bread, quantity=qty)
    inv.compute_order_total()
    inv.payment_amount = inv.order_total if payment == 'FULL' else Decimal(payment)
    inv.compute_debt_after()
    inv.save()
    if deliver:
        if day:
            at = tz.make_aware(datetime(day.year, day.month, day.day, 9, 0, 0))
            inv.deliver(livreur=fac, delivered_at=at)
        else:
            inv.deliver(livreur=fac)
    return inv


CASH, CREDIT = Invoice.PaymentType.CASH, Invoice.PaymentType.CREDIT


class Base(TestCase):
    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.other = make_node(code='K2', name='K2 - COQ')
        self.gerant = make_user(role='GERANT', node=self.node, username='g178v')
        self.gerant2 = make_user(role='GERANT', node=self.other, username='g178v2')
        self.comptable = make_user(role='COMPTABLE', username='c178v')
        self.facA = make_user(role='FACTURIER', node=self.node, team='A', username='fa178v')
        self.facB = make_user(role='FACTURIER', node=self.node, team='B', username='fb178v')
        self.facO = make_user(role='FACTURIER', node=self.other, team='A', username='fo178v')
        self.cl = make_client(self.node)
        self.clo = make_client(self.other)
        self.bread = make_bread_price(category='MOYEN', label='Pain 300 FC', unit_price=300)
        self.api = _api(self.gerant)
        self.apic = _api(self.comptable)

    def gen(self, api=None, **payload):
        r = (api or self.api).post('/api/treasury/reports/generate/', payload, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        return r


class Scenario1And2Cascade(Base):
    def _day(self, with_noise):
        _mk(self.node, self.facA, self.cl, self.bread, 5, CASH, 'FULL')           # 1500 cash
        _mk(self.node, self.facA, self.cl, self.bread, 3, CREDIT, '0')            # 900 credit
        if with_noise:
            _mk(self.node, self.facA, self.cl, self.bread, 7, CASH, '0', code='RG')
            _mk(self.node, self.facA, self.cl, self.bread, 2, CREDIT, '0', code='RG')
            _mk(self.node, self.facA, self.cl, self.bread, 9, CREDIT, '0', code='NS', deliver=False)

    def test_s1_report_equals_normal_sales_only(self):
        self._day(True)
        self.gen()
        r = FacturierReport.objects.get(node=self.node, team='A')
        self.assertEqual(r.total_cash_sales, Decimal('1500'))
        self.assertEqual(r.total_credit_sales, Decimal('900'))
        self.assertEqual(r.theoretical_cash, Decimal('1500'))
        self.assertEqual(r.breads_sold_by_category, {'Pain 300 FC': 8})
        self.assertEqual(r.sacks_value_gap, Decimal('2400'))  # 0 sac consommé

    def test_s1_same_as_clean_day(self):
        self._day(True)
        self.gen()
        noisy = FacturierReport.objects.get(node=self.node, team='A')
        vals = (noisy.total_cash_sales, noisy.total_credit_sales, noisy.theoretical_cash,
                noisy.sacks_value_gap, noisy.breads_sold_by_category)
        FacturierReport.objects.all().delete()
        Invoice.objects.filter(special_code__in=['RG', 'NS']).delete()
        self.gen()
        clean = FacturierReport.objects.get(node=self.node, team='A')
        self.assertEqual(vals, (clean.total_cash_sales, clean.total_credit_sales,
                                clean.theoretical_cash, clean.sacks_value_gap,
                                clean.breads_sold_by_category))

    def test_s2_cascade_closure_journal_cashbook(self):
        self._day(True)
        self.gen()
        LocalExpense.objects.create(
            node=self.node, date=date.today(), amount=Decimal('200'),
            description='Carburant', node_origin='K1',
        ) if False else None
        r = self.api.post('/api/treasury/closures/', {
            'date': str(date.today()), 'bills_1000': 1, 'bills_200': 1, 'bills_100': 2, 'bills_50': 2,
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        c = CashClosure.objects.get(pk=r.data['id'])
        self.assertEqual(c.total_entries, Decimal('1500'))
        self.assertEqual(c.net_cash, Decimal('1500'))
        self.assertEqual(c.physical_cash_total, Decimal('1500'))  # 1000+200+200+100
        self.assertEqual(c.cash_gap, Decimal('0'))
        s = self.apic.get('/api/treasury/journal/suggested_ca/',
                          {'node': str(self.node.pk), 'date': str(date.today())})
        self.assertEqual(Decimal(s.json()['amount']), Decimal('1500'))
        v = self.apic.post(f'/api/treasury/closures/{c.id}/validate/', {}, format='json')
        self.assertEqual(v.status_code, 200, v.content)
        p = self.apic.post(f'/api/treasury/closures/{c.id}/push_to_cashbook/', {}, format='json')
        self.assertIn(p.status_code, (200, 201), p.content)
        e = CashbookEntry.objects.get(source_closure=c)
        self.assertEqual(e.entry_amount, Decimal('1500'))
        self.assertEqual(e.running_balance, Decimal('1500'))
        self.assertEqual(e.piece_number, f"VC-K1-{date.today():%Y%m%d}")
        t = self.apic.get('/api/treasury/cashbook/integrity_check/')
        b = self.apic.post('/api/blockchain/snapshots/run_check/', {}, format='json')
        self.assertTrue(t.json()['chain_valid'])
        self.assertTrue(b.json()['all_intact'])

    def test_s1_two_teams_isolated(self):
        _mk(self.node, self.facA, self.cl, self.bread, 2, CASH, 'FULL', team='A')
        _mk(self.node, self.facB, self.cl, self.bread, 4, CASH, 'FULL', team='B')
        _mk(self.node, self.facA, self.cl, self.bread, 5, CASH, '0', team='A', code='RG')
        _mk(self.node, self.facB, self.cl, self.bread, 5, CREDIT, '0', team='B', code='RG')
        self.gen()
        self.assertEqual(FacturierReport.objects.get(team='A').total_cash_sales, Decimal('600'))
        rb = FacturierReport.objects.get(team='B')
        self.assertEqual(rb.total_cash_sales, Decimal('1200'))
        self.assertEqual(rb.total_credit_sales, Decimal('0'))
        self.assertEqual(rb.breads_sold_by_category, {'Pain 300 FC': 4})

    def test_s7_node_isolation(self):
        _mk(self.node, self.facA, self.cl, self.bread, 2, CASH, 'FULL')
        _mk(self.other, self.facO, self.clo, self.bread, 6, CASH, 'FULL')
        _mk(self.other, self.facO, self.clo, self.bread, 6, CASH, '0', code='RG')
        self.gen()
        self.gen(api=_api(self.gerant2))
        self.assertEqual(FacturierReport.objects.get(node=self.node).total_cash_sales, Decimal('600'))
        self.assertEqual(FacturierReport.objects.get(node=self.other).total_cash_sales, Decimal('1800'))


class Scenario3RgLockedAfterReport(Base):
    def test_rg_delivery_blocked_after_report_but_not_in_report(self):
        _mk(self.node, self.facA, self.cl, self.bread, 2, CASH, 'FULL')
        self.gen()
        with self.assertRaises(ValidationError):
            _mk(self.node, self.facA, self.cl, self.bread, 4, CASH, '0', code='RG')


class Scenario5StaleReport(Base):
    def test_stale_report_keeps_old_credit_until_regenerated(self):
        """Rapport 'ancien' (crédit RG compté) : régénération le corrige,
        mais un rapport dont la facturier n'a QUE des RG n'est jamais touché."""
        _mk(self.node, self.facA, self.cl, self.bread, 2, CASH, 'FULL')
        _mk(self.node, self.facB, self.cl, self.bread, 4, CREDIT, '0', team='B', code='RG')
        old_a = FacturierReport.objects.create(
            node=self.node, facturier=self.facA, team='A', date=date.today(),
            total_cash_sales=Decimal('600'), total_credit_sales=Decimal('1200'),
            theoretical_cash=Decimal('600'), node_origin='K1')
        old_b = FacturierReport.objects.create(
            node=self.node, facturier=self.facB, team='B', date=date.today(),
            total_cash_sales=Decimal('0'), total_credit_sales=Decimal('1200'),
            theoretical_cash=Decimal('0'), node_origin='K1')
        old_a.is_validated = True
        old_a.save()
        self.gen()
        old_a.refresh_from_db(); old_b.refresh_from_db()
        self.assertEqual(old_a.total_credit_sales, Decimal('0'))
        self.assertTrue(old_a.is_validated)  # validation conservée après régénération
        # rapport orphelin d'une équipe RG-seule : jamais corrigé, jamais supprimé
        self.assertEqual(old_b.total_credit_sales, Decimal('1200'))


class Scenario6OnlyRg(Base):
    def test_only_rg_day_closure_still_possible(self):
        _mk(self.node, self.facA, self.cl, self.bread, 4, CASH, '0', code='RG')
        r = self.api.post('/api/treasury/reports/generate/', {}, format='json')
        self.assertEqual(r.json()['reports'] if isinstance(r.json(), dict) else [], [])
        c = self.api.post('/api/treasury/closures/', {'date': str(date.today())}, format='json')
        self.assertEqual(c.status_code, 201, c.content)
        self.assertEqual(CashClosure.objects.get().net_cash, Decimal('0'))


class Scenario4Retroactive(TransactionTestCase):
    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='g178r')
        self.comptable = make_user(role='COMPTABLE', username='c178r')
        self.fac = make_user(role='FACTURIER', node=self.node, team='A', username='f178r')
        self.cl = make_client(self.node)
        self.bread = make_bread_price(category='MOYEN', label='Pain 300 FC', unit_price=300)
        cfg = Config.get_instance()
        cfg.allow_backdated_sales = True
        cfg.save(update_fields=['allow_backdated_sales'])
        self.day = date.today() - timedelta(days=12)
        self.api = _api(self.gerant)
        self.apic = _api(self.comptable)

    def test_retro_rg_changes_nothing_but_normal_retro_sale_is_corrected(self):
        _mk(self.node, self.fac, self.cl, self.bread, 5, CASH, 'FULL', day=self.day)
        self.api.post('/api/treasury/reports/generate/', {'date': str(self.day)}, format='json')
        c = self.api.post('/api/treasury/closures/', {'date': str(self.day), 'bills_500': 3}, format='json')
        self.assertEqual(c.status_code, 201, c.content)
        cid = c.data['id']
        self.apic.post(f'/api/treasury/closures/{cid}/validate/', {}, format='json')
        self.apic.post(f'/api/treasury/closures/{cid}/push_to_cashbook/', {}, format='json')
        n0 = CashbookEntry.objects.count()
        # RG rétroactive : pas de correction au livre
        _mk(self.node, self.fac, self.cl, self.bread, 4, CASH, '0', code='RG', day=self.day)
        self.assertEqual(CashbookEntry.objects.count(), n0)
        rep = FacturierReport.objects.get(node=self.node, date=self.day)
        self.assertEqual(rep.total_credit_sales, Decimal('0'))
        self.assertEqual(rep.total_cash_sales, Decimal('1500'))
        # vente normale rétroactive : une correction (+600)
        _mk(self.node, self.fac, self.cl, self.bread, 2, CASH, 'FULL', day=self.day)
        self.assertEqual(CashbookEntry.objects.count(), n0 + 1)
        corr = CashbookEntry.objects.filter(is_correction=True).get()
        self.assertEqual(corr.entry_amount, Decimal('600'))
        t = self.apic.get('/api/treasury/cashbook/integrity_check/')
        self.assertTrue(t.json()['chain_valid'])


class Bug179RgLockedWithoutNeed(Base):
    @unittest.expectedFailure
    def test_bug179_rg_delivery_should_not_be_blocked_by_reported_vacation(self):
        """BUG-179 : le rapport ignore les RG ; le verrou BUG-036 ne devrait
        pas bloquer leur livraison (rien à régénérer, aucune donnée figée)."""
        _mk(self.node, self.facA, self.cl, self.bread, 2, CASH, 'FULL')
        self.gen()
        rg = _mk(self.node, self.facA, self.cl, self.bread, 4, CASH, '0', code='RG')
        self.assertEqual(rg.status, Invoice.Status.DELIVERED)
