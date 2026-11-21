"""Verification adversariale BUG-333 / BUG-401 (testeur-charge, 2026-11-21e-b)."""
import os
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import ExpenseCategory
from core.testing import make_bread_price, make_client, make_node, make_user
from kiese.pagination import DeterministicPageNumberPagination
from sales.models import Invoice
from treasury.models import LocalExpense


class PageSize(TestCase):
    N = 130

    def setUp(self):
        for i in range(self.N):
            make_node(code=f'QP{i:03d}')
        self.api = APIClient()
        self.api.force_authenticate(make_user(role='ADMIN', node=None))

    def get(self, **p):
        return self.api.get('/api/core/nodes/', p)

    def test_valeurs_limites(self):
        total = self.get().data['count']
        cases = {1: 1, 2: 2, 500: min(500, total), 501: min(500, total), 10000: min(500, total)}
        for ps, exp in cases.items():
            r = self.get(page_size=ps)
            self.assertEqual(r.status_code, 200, ps)
            self.assertEqual(len(r.data['results']), exp, ps)

    def test_valeurs_invalides_sans_500(self):
        for ps in (0, -1, 'abc', '', '1.5', '1e2', ' ', '99999999999999999999'):
            r = self.get(page_size=ps)
            self.assertEqual(r.status_code, 200, repr(ps))
            self.assertLessEqual(len(r.data['results']), 500, repr(ps))
            if ps in (0, -1, 'abc', ''):
                self.assertEqual(len(r.data['results']), 25, repr(ps))

    def test_pages_multiples_sans_doublon_ni_trou(self):
        total = self.get().data['count']
        for ps in (7, 25, 50):
            seen, page = [], 1
            while True:
                r = self.get(page=page, page_size=ps)
                self.assertEqual(r.status_code, 200)
                seen += [x['id'] for x in r.data['results']]
                if not r.data['next']:
                    break
                page += 1
            self.assertEqual(len(seen), total, ps)
            self.assertEqual(len(set(seen)), total, ps)
        a = [x['id'] for x in self.get(page_size=500).data['results']]
        b, page = [], 1
        while True:
            r = self.get(page=page, page_size=10)
            b += [x['id'] for x in r.data['results']]
            if not r.data['next']:
                break
            page += 1
        self.assertEqual(a, b)

    def test_page_hors_limite_404(self):
        self.assertEqual(self.get(page=9999, page_size=10).status_code, 404)
        self.assertEqual(self.get(page='abc').status_code, 404)

    def test_classe(self):
        self.assertEqual(DeterministicPageNumberPagination.max_page_size, 500)
        self.assertNotIn('MAX_PAGE_SIZE', settings.REST_FRAMEWORK)


class AutresApps(TestCase):
    def setUp(self):
        self.node = make_node(code='QA1')
        self.admin = make_user(role='ADMIN', node=None)
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        cat = ExpenseCategory.objects.create(code='QCAT', label='Cat')
        for i in range(60):
            LocalExpense.objects.create(node=self.node, gerant=self.admin, description=f'd{i}',
                                        amount=Decimal('10'), category=cat, date=date(2026, 1, 1))
        make_bread_price('QCB', 'Pain', 500)
        cl = make_client(self.node)
        for i in range(55):
            Invoice.objects.create(node=self.node, client=cl, facturier=self.admin, team='A',
                                   status='PENDING', payment_type='CREDIT',
                                   payment_amount=Decimal('0'), order_total=Decimal('0'),
                                   initial_order_total=Decimal('0'))

    def walk(self, url, ps, expected_min):
        seen, page = [], 1
        while True:
            r = self.api.get(url, {'page': page, 'page_size': ps})
            self.assertEqual(r.status_code, 200, (url, r.content[:200]))
            seen += [str(x['id']) for x in r.data['results']]
            if not r.data['next']:
                break
            page += 1
        self.assertGreaterEqual(len(seen), expected_min, url)
        self.assertEqual(len(seen), len(set(seen)), url)
        self.assertEqual(len(seen), r.data['count'], url)
        self.assertGreater(page, 1, url)

    def test_treasury_expenses(self):
        self.walk('/api/treasury/expenses/', 7, 60)

    def test_sales_invoices(self):
        self.walk('/api/sales/invoices/', 10, 55)

    def test_listes_paginees_ne_cassent_pas(self):
        urls = ['/api/treasury/%s/' % s for s in (
            'expenses', 'reports', 'closures', 'cashbook', 'journal', 'savings', 'vouchers')]
        urls += ['/api/production/%s/' % s for s in (
            'sessions', 'bread-stocks', 'consumable-types', 'stocks', 'movements', 'counts',
            'transfers', 'disposals')]
        urls += ['/api/sales/invoices/', '/api/core/nodes/']
        for u in urls:
            for q in ({}, {'page_size': 1}, {'page_size': 501}, {'page_size': 0}, {'page_size': 'abc'}):
                r = self.api.get(u, q)
                self.assertNotEqual(r.status_code, 500, (u, q))
                if r.status_code == 200 and isinstance(r.data, dict) and 'results' in r.data:
                    self.assertLessEqual(len(r.data['results']), 500, (u, q))


class Bug401(TestCase):
    """Le test BUG-255 passe (ou se skippe) quel que soit DJANGO_DEBUG."""

    def _run(self, debug):
        env = dict(os.environ, DJANGO_DEBUG=debug, DJANGO_SECURE_SSL_REDIRECT='False',
                   DJANGO_SECRET_KEY='test-only-not-a-real-key-0123456789-abcdefghij',
                   PYTHONIOENCODING='utf-8')
        return subprocess.run(
            [sys.executable, 'manage.py', 'test',
             'core.tests.test_verif_bug247_248_252_255_testeur_permissions.Bug255'],
            cwd=Path(settings.BASE_DIR), env=env, capture_output=True, text=True,
            encoding='utf-8', errors='replace')

    def test_debug_true(self):
        p = self._run('True')
        self.assertEqual(p.returncode, 0, (p.stdout + p.stderr)[-1500:])

    def test_debug_false(self):
        p = self._run('False')
        self.assertEqual(p.returncode, 0, (p.stdout + p.stderr)[-1500:])
