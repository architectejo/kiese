"""
Vérification indépendante (testeur-tresorerie, 2026-11-21) de BUG-179 et BUG-176.

BUG-179 : une facture RG livrée sur une vacation déjà rapportée ne doit plus
être bloquée par le verrou BUG-036 (le rapport ignore les RG depuis BUG-178).
BUG-176 : tri déterministe (`-pk` en dernier critère) des listes treasury.
"""
import unittest
from datetime import date
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from core.models import ExpenseCategory
from core.testing import make_node, make_user, make_bread_price, make_client
from kiese.pagination import with_unique_tiebreak
from production.models import BreadStock
from sales.models import Invoice, InvoiceLine
from treasury.models import (
    CashbookEntry, CashClosure, FacturierReport, LocalExpense, DailySavings,
)
from treasury.views import (
    append_cashbook_entry, CashbookEntryViewSet, CashClosureViewSet,
    DailySavingsViewSet, DirectionCashCountViewSet, DisbursementVoucherViewSet,
    FacturierReportViewSet, JournalEntryViewSet, LocalExpenseViewSet,
)
from .test_bug178_verification_2026_11_11 import _mk, CASH, CREDIT

CODES = ('RG', 'NV', 'NS')


def _api(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


class Base(TestCase):
    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='g179')
        self.comptable = make_user(role='COMPTABLE', username='c179')
        self.facA = make_user(role='FACTURIER', node=self.node, team='A', username='fa179')
        self.facB = make_user(role='FACTURIER', node=self.node, team='B', username='fb179')
        self.livreur = make_user(role='LIVREUR', node=self.node, team='A', username='l179')
        self.cl = make_client(self.node)
        self.bread = make_bread_price(category='MOYEN', label='Pain 300 FC', unit_price=300)
        self.api = _api(self.gerant)
        self.apic = _api(self.comptable)

    def gen(self):
        r = self.api.post('/api/treasury/reports/generate/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def report(self, team='A'):
        return FacturierReport.objects.get(node=self.node, team=team)


class Bug179Tests(Base):
    def _reported_day(self):
        _mk(self.node, self.facA, self.cl, self.bread, 2, CASH, 'FULL')
        self.gen()

    def test_rg_delivered_on_reported_vacation_passes(self):
        self._reported_day()
        rg = _mk(self.node, self.facA, self.cl, self.bread, 4, CASH, '0', code='RG')
        rg.refresh_from_db()
        self.assertEqual(rg.status, Invoice.Status.DELIVERED)

    def test_rg_delivery_via_api_by_livreur_passes(self):
        self._reported_day()
        rg = _mk(self.node, self.facA, self.cl, self.bread, 4, CASH, '0', code='RG', deliver=False)
        r = _api(self.livreur).post(f'/api/sales/invoices/{rg.pk}/deliver/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_normal_sale_still_blocked_bug036(self):
        self._reported_day()
        with self.assertRaises(ValidationError):
            _mk(self.node, self.facA, self.cl, self.bread, 1, CASH, 'FULL')
        with self.assertRaises(ValidationError):
            _mk(self.node, self.facA, self.cl, self.bread, 1, CREDIT, '0')

    def test_normal_sale_blocked_even_after_rg_passed(self):
        self._reported_day()
        _mk(self.node, self.facA, self.cl, self.bread, 4, CASH, '0', code='RG')
        with self.assertRaises(ValidationError):
            _mk(self.node, self.facA, self.cl, self.bread, 1, CASH, 'FULL')

    def test_nv_sale_still_blocked(self):
        """NV (nouveau client) est une vente : le verrou s'applique."""
        self._reported_day()
        with self.assertRaises(ValidationError):
            _mk(self.node, self.facA, self.cl, self.bread, 1, CASH, 'FULL', code='NV')

    def test_other_team_unaffected_by_lock(self):
        self._reported_day()  # seule A est rapportée
        inv = _mk(self.node, self.facB, self.cl, self.bread, 1, CASH, 'FULL', team='B')
        self.assertEqual(inv.status, Invoice.Status.DELIVERED)

    def test_ns_cannot_be_delivered_via_api(self):
        self._reported_day()
        ns = _mk(self.node, self.facA, self.cl, self.bread, 2, CREDIT, '0', code='NS', deliver=False)
        r = _api(self.livreur).post(f'/api/sales/invoices/{ns.pk}/deliver/', {}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        ns.refresh_from_db()
        self.assertNotEqual(ns.status, Invoice.Status.DELIVERED)

    def test_rg_not_counted_in_report_after_regeneration(self):
        """BUG-178 : RG livrée après rapport, puis régénération : totaux inchangés."""
        self._reported_day()
        before = self.report()
        vals = (before.total_cash_sales, before.total_credit_sales, before.theoretical_cash,
                before.breads_sold_by_category)
        _mk(self.node, self.facA, self.cl, self.bread, 4, CASH, '0', code='RG')
        _mk(self.node, self.facA, self.cl, self.bread, 3, CREDIT, '0', code='RG')
        FacturierReport.objects.all().delete()
        self.gen()
        after = self.report()
        self.assertEqual(vals, (after.total_cash_sales, after.total_credit_sales,
                                after.theoretical_cash, after.breads_sold_by_category))
        self.assertEqual(after.total_cash_sales, Decimal('600'))

    def test_rg_delivery_leaves_client_debt_and_cash_untouched(self):
        self._reported_day()
        self.cl.refresh_from_db()
        debt = self.cl.current_debt
        rg = _mk(self.node, self.facA, self.cl, self.bread, 4, CASH, '0', code='RG')
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, debt)
        self.assertEqual(rg.payment_amount, Decimal('0'))

    def test_rg_delivery_does_not_alter_existing_report_row(self):
        self._reported_day()
        r0 = self.report()
        snap = (r0.pk, r0.total_cash_sales, r0.total_credit_sales, r0.theoretical_cash,
                r0.updated_at)
        _mk(self.node, self.facA, self.cl, self.bread, 4, CASH, '0', code='RG')
        r1 = self.report()
        self.assertEqual(snap, (r1.pk, r1.total_cash_sales, r1.total_credit_sales,
                                r1.theoretical_cash, r1.updated_at))
        self.assertEqual(FacturierReport.objects.filter(node=self.node, team='A').count(), 1)

    def test_rg_delivery_stock_effect_recorded(self):
        """Information : effet d'une RG livrée sur le stock de pains (pas d'assertion
        de métier, on vérifie seulement que la livraison ne casse pas le stock)."""
        self._reported_day()
        _mk(self.node, self.facA, self.cl, self.bread, 4, CASH, '0', code='RG')
        for s in BreadStock.objects.filter(node=self.node):
            self.assertIsNotNone(s.qty_available)


class Bug179NoForgeryTests(Base):
    """Seul le `special_code` stocké côté serveur sur la facture est lu."""

    def _payload(self, code=None, qty=2, payment='600.00'):
        p = {
            'client': str(self.cl.pk), 'payment_type': 'CASH', 'payment_amount': payment,
            'lines': [{'bread_price': self.bread.pk, 'quantity': qty}],
        }
        if code is not None:
            p['special_code'] = code
        return p

    def _reported(self):
        _mk(self.node, self.facA, self.cl, self.bread, 2, CASH, 'FULL')
        self.gen()

    def test_deliver_payload_special_code_ignored(self):
        """Une vente normale PENDING ne devient pas RG en envoyant special_code
        dans le corps de /deliver/."""
        self._reported()
        inv = _mk(self.node, self.facA, self.cl, self.bread, 1, CASH, 'FULL', deliver=False)
        for who in (self.livreur, self.facA):
            r = _api(who).post(f'/api/sales/invoices/{inv.pk}/deliver/',
                               {'special_code': 'RG'}, format='json')
            self.assertEqual(r.status_code, 400, r.content)
            inv.refresh_from_db()
            self.assertEqual(inv.special_code, '')
            self.assertNotEqual(inv.status, Invoice.Status.DELIVERED)

    def test_patch_special_code_refused(self):
        self._reported()
        inv = _mk(self.node, self.facA, self.cl, self.bread, 1, CASH, 'FULL', deliver=False)
        for who in (self.gerant, self.facA, self.livreur):
            r = _api(who).patch(f'/api/sales/invoices/{inv.pk}/',
                                {'special_code': 'RG'}, format='json')
            self.assertIn(r.status_code, (400, 403, 405), r.content)
            inv.refresh_from_db()
            self.assertEqual(inv.special_code, '')

    def test_put_special_code_refused(self):
        self._reported()
        inv = _mk(self.node, self.facA, self.cl, self.bread, 1, CASH, 'FULL', deliver=False)
        r = _api(self.gerant).put(f'/api/sales/invoices/{inv.pk}/',
                                  {'special_code': 'RG'}, format='json')
        self.assertIn(r.status_code, (400, 403, 405), r.content)
        inv.refresh_from_db()
        self.assertEqual(inv.special_code, '')

    def test_livreur_cannot_create_invoice(self):
        r = _api(self.livreur).post('/api/sales/invoices/', self._payload('RG'), format='json')
        self.assertEqual(r.status_code, 403, r.content)

    def test_invalid_special_code_rejected(self):
        r = _api(self.facA).post('/api/sales/invoices/', self._payload('XX'), format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_created_rg_is_neutral_money_wise(self):
        """Créer une facture RG via l'API (donc via les règles existantes) force
        paiement = 0 : aucun contournement pour encaisser/vendre après rapport."""
        self._reported()
        self.cl.refresh_from_db()
        debt = self.cl.current_debt
        r = _api(self.facA).post('/api/sales/invoices/', self._payload('RG', payment='9999.00'),
                                 format='json')
        self.assertEqual(r.status_code, 201, r.content)
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual(inv.special_code, 'RG')
        self.assertEqual(inv.payment_amount, Decimal('0'))
        self.assertEqual(inv.commission_rate, Decimal('0'))
        d = _api(self.livreur).post(f'/api/sales/invoices/{inv.pk}/deliver/', {}, format='json')
        self.assertEqual(d.status_code, 200, d.content)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, debt)
        self.gen_again_values_unchanged()

    def gen_again_values_unchanged(self):
        r0 = self.report()
        FacturierReport.objects.all().delete()
        self.gen()
        r1 = self.report()
        self.assertEqual((r0.total_cash_sales, r0.total_credit_sales),
                         (r1.total_cash_sales, r1.total_credit_sales))

    def test_normal_create_with_empty_code_then_deliver_blocked(self):
        """Pas de special_code => vente normale : livraison refusée après rapport."""
        self._reported()
        r = _api(self.facA).post('/api/sales/invoices/', self._payload(None), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual(inv.special_code, '')
        d = _api(self.livreur).post(f'/api/sales/invoices/{inv.pk}/deliver/', {}, format='json')
        self.assertGreaterEqual(d.status_code, 400, d.content)
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.Status.PENDING)

    def test_signal_reads_server_special_code_only(self):
        """Le signal lit `instance.special_code` (modèle). Le vérifier au niveau
        source : aucune lecture de request/payload."""
        import inspect
        import treasury.signals as sig
        src = inspect.getsource(sig.block_delivery_on_already_reported_vacation)
        self.assertIn("getattr(instance, 'special_code'", src)
        self.assertNotIn('request', src)


class CashClosureUnaffectedTests(Base):
    def test_closure_and_cashbook_same_with_or_without_rg_after_report(self):
        _mk(self.node, self.facA, self.cl, self.bread, 5, CASH, 'FULL')      # 1500
        _mk(self.node, self.facA, self.cl, self.bread, 3, CREDIT, '0')       # 900 crédit
        self.gen()
        _mk(self.node, self.facA, self.cl, self.bread, 7, CASH, '0', code='RG')
        r = self.api.post('/api/treasury/closures/', {
            'date': str(date.today()), 'bills_1000': 1, 'bills_200': 1, 'bills_100': 2, 'bills_50': 2,
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        c = CashClosure.objects.get(pk=r.data['id'])
        self.assertEqual(c.total_entries, Decimal('1500'))
        self.assertEqual(c.net_cash, Decimal('1500'))
        self.assertEqual(c.cash_gap, Decimal('0'))
        v = self.apic.post(f'/api/treasury/closures/{c.id}/validate/', {}, format='json')
        self.assertEqual(v.status_code, 200, v.content)
        p = self.apic.post(f'/api/treasury/closures/{c.id}/push_to_cashbook/', {}, format='json')
        self.assertIn(p.status_code, (200, 201), p.content)
        e = CashbookEntry.objects.get(source_closure=c)
        self.assertEqual(e.entry_amount, Decimal('1500'))
        self.assertEqual(e.running_balance, Decimal('1500'))
        self.assertTrue(self.apic.get('/api/treasury/cashbook/integrity_check/').json()['chain_valid'])
        b = self.apic.post('/api/blockchain/snapshots/run_check/', {}, format='json')
        self.assertTrue(b.json()['all_intact'])
        # double versement toujours refusé
        p2 = self.apic.post(f'/api/treasury/closures/{c.id}/push_to_cashbook/', {}, format='json')
        self.assertGreaterEqual(p2.status_code, 400)
        self.assertEqual(CashbookEntry.objects.filter(source_closure=c).count(), 1)


TREASURY_VIEWSETS = [
    LocalExpenseViewSet, FacturierReportViewSet, CashClosureViewSet, DailySavingsViewSet,
    DirectionCashCountViewSet, DisbursementVoucherViewSet, CashbookEntryViewSet,
    JournalEntryViewSet,
]


class Bug176Tests(TestCase):
    def setUp(self):
        self.node = make_node(code='ZV176')
        self.admin = make_user(role='ADMIN', node=None, username='adm176')
        self.api = _api(self.admin)

    def _walk(self, url, page_size=25):
        ids, page, pages = [], 1, 0
        while True:
            r = self.api.get(url, {'page': page, 'page_size': page_size})
            self.assertEqual(r.status_code, 200, r.content)
            ids += [str(x['id']) for x in r.data['results']]
            pages += 1
            if not r.data.get('next'):
                return ids, pages, r.data['count']
            page += 1

    def test_every_treasury_viewset_ordering_ends_with_pk(self):
        for vs in TREASURY_VIEWSETS:
            with self.subTest(viewset=vs.__name__):
                order = list(with_unique_tiebreak(vs.queryset.all()).query.order_by)
                self.assertTrue(order)
                self.assertIn(order[-1], ('pk', '-pk', 'id', '-id'))
                declared = getattr(vs, 'ordering', None)
                self.assertTrue(declared, f'{vs.__name__}.ordering non déclaré')
                self.assertIn(declared[-1], ('pk', '-pk'))

    def test_paginator_is_deterministic_class(self):
        from django.conf import settings
        self.assertEqual(settings.REST_FRAMEWORK['DEFAULT_PAGINATION_CLASS'],
                         'kiese.pagination.DeterministicPageNumberPagination')

    def _mk_expenses(self, n, day, prefix):
        cat = ExpenseCategory.objects.create(code=f'CB{prefix}', label=f'Cat{prefix}')
        objs = [LocalExpense.objects.create(
            node=self.node, description=f'{prefix}{i}', amount=Decimal('10'), category=cat,
            date=day) for i in range(n)]
        LocalExpense.objects.all().update(created_at=objs[0].created_at)
        return objs

    def test_expenses_identical_date_and_timestamp_pages_no_dup_no_gap(self):
        """BUG-331 corrigé : `page_size` est honoré (2 par page) → 6 lignes
        donnent 3 pages réelles."""
        objs = self._mk_expenses(6, '2026-05-01', 'A')
        ids, pages, count = self._walk('/api/treasury/expenses/')
        self.assertEqual(count, 6)
        self.assertEqual(pages, 3)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {str(o.pk) for o in objs})
        ids2, _, _ = self._walk('/api/treasury/expenses/')
        self.assertEqual(ids, ids2)

    def test_two_explicit_pages_union_equals_all(self):
        objs = self._mk_expenses(40, '2026-05-02', 'B')
        p1 = self.api.get('/api/treasury/expenses/', {'page': 1}).data['results']
        p2 = self.api.get('/api/treasury/expenses/', {'page': 2}).data['results']
        got = [str(x['id']) for x in p1 + p2]
        self.assertEqual(len(got), 40)
        self.assertEqual(len(set(got)), 40)
        self.assertEqual(set(got), {str(o.pk) for o in objs})

    def test_bug331_page_size_param_is_honored(self):
        """BUG-331 : `?page_size=2` devrait limiter la page à 2 lignes
        (settings.py : PAGE_SIZE_QUERY_PARAM / MAX_PAGE_SIZE ne sont pas des
        réglages DRF valides ; `page_size_query_param` doit être posé sur la
        classe de pagination)."""
        self._mk_expenses(5, '2026-05-03', 'C')
        r = self.api.get('/api/treasury/expenses/', {'page': 1, 'page_size': 2})
        self.assertEqual(len(r.data['results']), 2)

    def test_reports_closures_savings_same_date(self):
        nodes = [make_node(code=f'ZW{i}') for i in range(5)]
        reps = [FacturierReport.objects.create(node=n, team='A', date='2026-05-03',
                                               node_origin=n.code) for n in nodes]
        ids, _, _ = self._walk('/api/treasury/reports/')  # NB: 1 page réelle
        self.assertEqual(set(ids), {str(r.pk) for r in reps})
        self.assertEqual(len(ids), 5)
        sav = [DailySavings.objects.create(node=n, date='2026-05-03') for n in nodes]
        ids, _, _ = self._walk('/api/treasury/savings/')
        self.assertEqual(set(ids), {str(s.pk) for s in sav})
        self.assertEqual(len(ids), 5)

    def test_cashbook_identical_created_at_no_dup_no_gap_and_newest_first(self):
        entries = []
        for i in range(5):
            entries.append(append_cashbook_entry(
                node=self.node, date='2026-10-01', piece_number=f'P-{i}', imputation='7000',
                label=f'e{i}', entry_amount=Decimal('100'), exit_amount=Decimal('0'),
                node_origin=self.node.code))
        CashbookEntry.objects.all().update(created_at=entries[0].created_at)
        ids, pages, count = self._walk('/api/treasury/cashbook/')
        self.assertEqual(count, 5)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {str(e.pk) for e in entries})
        ids2, _, _ = self._walk('/api/treasury/cashbook/')
        self.assertEqual(ids, ids2)
