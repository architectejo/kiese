"""
Testeur ventes (Dev A, cycle a3, 2026-11-22) : nouveaux angles d'attaque sur
sales/ (CLAUDE.md 5.1-5.2, remarque.md). Donnees fictives uniquement.

Sections :
  P  parametres invalides (booleens, NaN, exposants, entiers geants, chaines enormes)
  R  roles et isolation entre boulangeries
  B  BP / plafond de credit / ventes soldees / epargne / codes speciaux
  S  sequences aleatoires verifiees par un modele independant (current_debt, stock)
  L  livraison, expiration 12 h, annulation, ajustement
  K  verrous (CLAUDE.md 4 : select_for_update sur toute lecture de solde)
"""
import random
import re
import threading
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from unittest import expectedFailure
from unittest.mock import patch

from django.db import connection
from django.db.models import F
from django.db.models.query import QuerySet
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from clients.models import Client
from core.models import ActivityLog, SystemNotification
from core.testing import get_config, make_bread_price, make_client, make_node, make_user
from production.models import BreadStock
from sales.models import Invoice, InvoiceLine

D = Decimal
INV = '/api/sales/invoices/'


def _api(user):
    a = APIClient()
    a.raise_request_exception = False      # un 500 doit etre observable, pas propage
    a.force_authenticate(user)
    return a


def _soldee_price(p):
    return int((D(p) * D('0.75')).quantize(D('1'), rounding=ROUND_HALF_UP))


class Base(TestCase):
    def setUp(self):
        self.n1 = make_node(code='AV1')
        self.n2 = make_node(code='AV2')
        self.fa1 = make_user('FACTURIER', node=self.n1, team='A', username='av1_fa')
        self.fa2 = make_user('FACTURIER', node=self.n2, team='A', username='av2_fa')
        self.lv1 = make_user('LIVREUR', node=self.n1, team='A', username='av1_lv')
        self.lv2 = make_user('LIVREUR', node=self.n2, team='A', username='av2_lv')
        self.g1 = make_user('GERANT', node=self.n1, team='A', username='av1_g')
        self.g2 = make_user('GERANT', node=self.n2, team='A', username='av2_g')
        self.adm = make_user('ADMIN', node=None, username='av_adm')
        self.bp3 = make_bread_price('AV3', 'Pain 300', 300)
        self.bp5 = make_bread_price('AV5', 'Pain 500', 500)
        self.cl = make_client(self.n1)

    def post(self, user=None, client=None, **extra):
        body = {
            'payment_type': 'CREDIT', 'payment_amount': 0,
            'lines': [{'bread_price': self.bp3.pk, 'quantity': 10}],
        }
        if client is not False:
            body['client'] = str((client or self.cl).pk)
        body.update(extra)
        return _api(user or self.fa1).post(INV, body, format='json')

    def debt(self, cl=None):
        cl = cl or self.cl
        cl.refresh_from_db()
        return cl.current_debt

    def sent(self, node=None, bp=None):
        st = BreadStock.objects.filter(node=node or self.n1, bread_price=bp or self.bp3).first()
        return st.qty_sent if st else 0


# =============================================================================== P
class ParametresInvalides(Base):
    def _assert_400(self, r, label):
        self.assertNotEqual(r.status_code, 500, f'{label} -> 500')
        self.assertEqual(r.status_code, 400, f'{label} -> {r.status_code} {getattr(r, "data", "")}')
        self.assertEqual(Invoice.objects.count(), 0, f'{label} : facture creee malgre le refus')
        self.assertEqual(self.debt(), 0)

    def test_payment_amount_valeurs_illisibles(self):
        bad = []
        for v in ['NaN', 'Infinity', '-Infinity', 'sNaN', '1e400', '1E+400', 'abc', '', ' ', None, True, False,
                  [], {}, [1], '12,5', '0x10', '9' * 40, '99999999999999.99', '1.005', '\x00',
                  'x' * 100000, '--5', '+-5']:
            r = self.post(payment_amount=v)
            if r.status_code != 400:
                bad.append((f'{v!r:.30}', r.status_code))
        self.assertEqual(bad, [], 'payment_amount illisible non refuse en 400')
        self.assertEqual(Invoice.objects.count(), 0)

    def test_payment_amount_exposant_et_formes_valides(self):
        r = self.post(payment_amount='1e3')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Invoice.objects.get(pk=r.data['id']).payment_amount, D('1000.00'))
        r = self.post(payment_amount=' 10.50 ')
        self.assertIn(r.status_code, (201, 400))
        self.assertNotEqual(r.status_code, 500)

    def test_quantite_illisible(self):
        bad = []
        for q in [True, False, 1.5, '1e2', 'NaN', 10 ** 30, 2 ** 70, -1, 0, None, [], {}, '', 'x' * 5000, 100001]:
            r = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': q}])
            if r.status_code != 400:
                bad.append((f'{q!r:.30}', r.status_code))
        self.assertEqual(bad, [])
        for q in ['１', '٣', '1.0']:
            r = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': q}])
            self.assertNotEqual(r.status_code, 500, f'quantity={q!r}')

    def test_bread_price_illisible(self):
        bad = []
        for bp in [True, False, 1.5, 'abc', 0, -1, None, [], {}]:
            r = self.post(lines=[{'bread_price': bp, 'quantity': 1}])
            if r.status_code != 400:
                bad.append((f'{bp!r:.30}', r.status_code))
        self.assertEqual(bad, [])
        self.assertEqual(Invoice.objects.count(), 0)

    def test_BUG_644_bread_price_entier_geant_500(self):
        """BUG-644 : bread_price >= 2**63 -> OverflowError SQLite (500) ; attendu 400 (borne max)."""
        bad = []
        for bp in [10 ** 30, 2 ** 70, 2 ** 63, 2 ** 31, '9' * 400]:
            r = self.post(lines=[{'bread_price': bp, 'quantity': 1}])
            if r.status_code != 400:
                bad.append((f'{bp!r:.30}', r.status_code))
        self.assertEqual(bad, [])

    def test_lignes_formes_invalides(self):
        for lines in ['abc', {'bread_price': self.bp3.pk, 'quantity': 1}, [None], [[]], [1], ['x'], [{}],
                      [{'quantity': 1}], [{'bread_price': self.bp3.pk}], 10 ** 30, True]:
            r = self.post(lines=lines)
            self.assertNotEqual(r.status_code, 500, f'lines={lines!r:.60}')
            self.assertEqual(r.status_code, 400, f'lines={lines!r:.60} -> {r.status_code}')
        self.assertEqual(Invoice.objects.count(), 0)

    def test_lignes_plus_de_deux_mille(self):
        r = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 1}] * 3000)
        self.assertIn(r.status_code, (201, 400))
        self.assertNotEqual(r.status_code, 500)

    def test_client_illisible(self):
        for c in ['abc', 123, True, [], {}, '0' * 36, '00000000-0000-0000-0000-000000000000', 'x' * 10000, -1]:
            r = _api(self.fa1).post(INV, {'payment_type': 'CASH', 'payment_amount': 0, 'client': c,
                                          'lines': [{'bread_price': self.bp3.pk, 'quantity': 1}]}, format='json')
            self.assertNotEqual(r.status_code, 500, f'client={c!r:.40}')
            self.assertEqual(r.status_code, 400, f'client={c!r:.40} -> {r.status_code}')

    def test_champs_enumeres_invalides(self):
        for extra in [{'payment_type': 'cash'}, {'payment_type': True}, {'payment_type': ['CASH']},
                      {'special_code': 'ns'}, {'special_code': 'K1'}, {'special_code': 'NSNS'},
                      {'special_code': None}, {'motif': 'x' * 1000000}, {'motif': {}},
                      {'is_soldee': 'peut-etre'}, {'is_soldee': []}, {'commission_exempt': 'oui?'},
                      {'is_debt_repayment': 'nope'}, {'commission_rate': '1e400'}, {'commission_rate': 'NaN'},
                      {'commission_rate': 0.5}, {'invoice_date': 'abc'}, {'invoice_date': '2026-02-30'},
                      {'invoice_date': '9999-12-31'}, {'invoice_date': '0001-01-01'}, {'invoice_date': []},
                      {'invoice_date': 20261122}, {'node': 'abc'}, {'node': True}, {'node': 2 ** 70}]:
            r = self.post(**extra)
            self.assertNotEqual(r.status_code, 500, f'{extra!r:.80}')

    def test_node_geant_ou_inexistant_cote_siege(self):
        for n in [2 ** 70, 10 ** 30, 999999, 0, -5]:
            r = _api(self.adm).post(INV, {'node': n, 'payment_type': 'CASH', 'payment_amount': 100,
                                          'lines': [{'bread_price': self.bp3.pk, 'quantity': 1}]}, format='json')
            self.assertNotEqual(r.status_code, 500, f'node={n!r}')
            self.assertEqual(r.status_code, 400, f'node={n!r} -> {r.status_code}')

    def test_corps_non_objet(self):
        for body in ['[]', '"abc"', '123', 'null', '{', '']:
            r = _api(self.fa1).post(INV, body, content_type='application/json')
            self.assertNotEqual(r.status_code, 500, f'corps={body!r}')
            self.assertEqual(r.status_code, 400, f'corps={body!r} -> {r.status_code}')

    def test_mass_assignment_champs_serveur_ignores(self):
        other = make_user('FACTURIER', node=self.n2, username='av_other')
        r = self.post(payment_amount=100, status='DELIVERED', debt_before='-99999', debt_after='-99999',
                      order_total='1', receipt_number='HACK-1', facturier=other.pk, is_adjustment=True,
                      adjustment_sign=-1, delivered_at='2020-01-01', node_origin='ZZ', is_synced=True,
                      initial_order_total='1', livreur=other.pk, team='B', id='00000000-0000-4000-8000-000000000001')
        self.assertEqual(r.status_code, 201, r.data)
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual(inv.status, 'PENDING')
        self.assertEqual((inv.debt_before, inv.order_total), (D(0), D(3000)))
        self.assertTrue(inv.receipt_number.startswith('AV1-'))
        self.assertEqual(inv.facturier_id, self.fa1.pk)
        self.assertFalse(inv.is_adjustment)
        self.assertIsNone(inv.livreur_id)
        self.assertIsNone(inv.delivered_at)
        self.assertEqual(inv.node_origin, 'AV1')
        self.assertEqual(inv.team, 'A')
        self.assertNotEqual(str(inv.pk), '00000000-0000-4000-8000-000000000001')

    def _delivered_at_bad(self, values):
        iid = self.post().data['id']
        bad = []
        for v in values:
            rr = _api(self.lv1).post(f'{INV}{iid}/deliver/', {'delivered_at': v}, format='json')
            if rr.status_code != 400:
                bad.append((f'{v!r:.30}', rr.status_code))
        self.assertEqual(Invoice.objects.get(pk=iid).status, 'PENDING')
        return bad

    def test_deliver_delivered_at_illisible(self):
        self.assertEqual(self._delivered_at_bad(['abc', 123, 'x' * 10000, '9999-12-31']), [])

    def test_BUG_643_delivered_at_date_impossible_500(self):
        """BUG-643 : date bien formee mais impossible -> parse_date leve ValueError (500) ; attendu 400."""
        self.assertEqual(self._delivered_at_bad(
            ['2026-02-30', '2026-13-01', '2026-00-10', '9999-99-99', '0000-00-00', '2026-02-30T10:00:00']), [])

    def test_deliver_lines_invalides(self):
        r = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 4}, {'bread_price': self.bp5.pk, 'quantity': 2}])
        iid, l0 = r.data['id'], r.data['lines'][0]['id']
        for lines in ['abc', {}, 5, True, [None], [[]], [{}], [{'id': l0}], [{'quantity': 1}],
                      [{'id': l0, 'quantity': -1}], [{'id': l0, 'quantity': 5}], [{'id': l0, 'quantity': 1.5}],
                      [{'id': l0, 'quantity': True}], [{'id': True, 'quantity': 1}], [{'id': 'x', 'quantity': 1}],
                      [{'id': 10 ** 30, 'quantity': 1}], [{'id': l0, 'quantity': 'x'}],
                      [{'id': l0, 'quantity': 1}, {'id': l0, 'quantity': 2}], [{'id': l0, 'quantity': 10 ** 30}],
                      [{'id': l0, 'quantity': '1e2'}], [{'id': l0, 'quantity': None}]]:
            rr = _api(self.lv1).post(f'{INV}{iid}/deliver/', {'lines': lines}, format='json')
            self.assertNotEqual(rr.status_code, 500, f'lines={lines!r:.60}')
            self.assertEqual(rr.status_code, 400, f'lines={lines!r:.60} -> {rr.status_code}')
        inv = Invoice.objects.get(pk=iid)
        self.assertEqual((inv.status, inv.order_total), ('PENDING', D(2200)))
        self.assertEqual(self.debt(), D(2200))

    def test_deliver_ligne_id_decimal_ne_doit_pas_etre_tronque(self):
        """Un identifiant de ligne 1.9 ne doit pas etre lu comme 1."""
        r = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 4}, {'bread_price': self.bp5.pk, 'quantity': 2}])
        iid, l0 = r.data['id'], r.data['lines'][0]['id']
        rr = _api(self.lv1).post(f'{INV}{iid}/deliver/', {'lines': [{'id': l0 + 0.9, 'quantity': 1}]}, format='json')
        self.assertEqual(rr.status_code, 400, rr.data)

    def test_mark_not_served_motif_invalide(self):
        r = self.post()
        iid = r.data['id']
        for reason in [123, [], {}, True, 'x' * 201, 'x' * 1000000]:
            rr = _api(self.fa1).post(f'{INV}{iid}/mark-not-served/', {'reason': reason}, format='json')
            self.assertNotEqual(rr.status_code, 500, f'reason={reason!r:.30}')
            self.assertEqual(rr.status_code, 400, f'reason={reason!r:.30} -> {rr.status_code}')
        self.assertEqual(Invoice.objects.get(pk=iid).status, 'PENDING')

    def test_adjust_parametres_invalides(self):
        r = self.post(payment_amount=0)
        iid = r.data['id']
        _api(self.lv1).post(f'{INV}{iid}/deliver/', {}, format='json')
        bad = [
            {'adjustment_sign': 0}, {'adjustment_sign': 2}, {'adjustment_sign': 'x'}, {'adjustment_sign': True},
            {'payment_amount': 'NaN'}, {'payment_amount': '-5'}, {'payment_amount': 'Infinity'},
            {'payment_amount': '1e400'}, {'lines': []}, {'lines': 'x'}, {'lines': [None]},
            {'lines': [{}]}, {'lines': [{'bread_price': self.bp3.pk}]}, {'lines': [{'quantity': 1}]},
            {'lines': [{'bread_price': 'x', 'quantity': 1}]}, {'lines': [{'bread_price': self.bp3.pk, 'quantity': 'x'}]},
            {'lines': [{'bread_price': self.bp3.pk, 'quantity': 0}]}, {'lines': [{'bread_price': self.bp3.pk, 'quantity': -3}]},
            {'lines': [{'bread_price': self.bp3.pk, 'quantity': None}]},
            {'lines': [{'bread_price': self.bp3.pk, 'quantity': 10 ** 30}]},
            {'lines': [{'bread_price': 2 ** 70, 'quantity': 1}]},
            {'lines': [{'bread_price': [], 'quantity': 1}]}, {'lines': [{'bread_price': self.bp3.pk, 'quantity': []}]},
            {'invoice_date': 'abc'}, {'invoice_date': '2026-02-30'}, {'invoice_date': '9999-12-31'},
        ]
        for extra in bad:
            body = {'adjustment_sign': 1, 'payment_amount': 0,
                    'lines': [{'bread_price': self.bp3.pk, 'quantity': 1}]}
            body.update(extra)
            before = Invoice.objects.count()
            rr = _api(self.g1).post(f'{INV}{iid}/adjust/', body, format='json')
            self.assertNotEqual(rr.status_code, 500, f'adjust {extra!r:.80}')
            self.assertEqual(rr.status_code, 400, f'adjust {extra!r:.80} -> {rr.status_code}')
            self.assertEqual(Invoice.objects.count(), before)
        self.assertEqual(self.debt(), D(3000))

    def test_adjust_quantite_decimale_ou_booleenne_non_tronquee(self):
        """quantity 1.9 / True ne doivent pas etre silencieusement lus comme 1."""
        r = self.post(payment_amount=0)
        iid = r.data['id']
        _api(self.lv1).post(f'{INV}{iid}/deliver/', {}, format='json')
        for q in (1.9, True, 2.5):
            rr = _api(self.g1).post(f'{INV}{iid}/adjust/', {
                'adjustment_sign': 1, 'payment_amount': 0,
                'lines': [{'bread_price': self.bp3.pk, 'quantity': q}]}, format='json')
            self.assertEqual(rr.status_code, 400, f'quantity={q!r} -> {rr.status_code}')

    def _filters_500(self, queries):
        self.post()
        bad = []
        for qs in queries:
            r = _api(self.g1).get(f'{INV}?{qs}')
            if r.status_code == 500:
                bad.append(qs[:40])
        return bad

    def test_filtres_et_pagination_illisibles(self):
        self.assertEqual(self._filters_500([
            'page=abc', 'page=0', 'page=-1', 'page=99999999999999999999', 'page_size=abc',
            'page_size=-1', 'page_size=0', f'page_size={10 ** 30}', 'status=XX', 'node=abc',
            f'node={2 ** 70}', 'client=abc', 'client=' + 'x' * 5000, 'invoice_date=abc', 'invoice_date=2026-02-30',
            'adjusts=abc', 'is_adjustment=maybe', 'ordering=-nope', 'ordering=' + 'a,' * 500,
            'payment_type=zz', 'search=%00', 'search=%27%20OR%201=1']), [])

    def test_BUG_645_search_tres_long_500(self):
        """BUG-645 : ?search= de 100 000 caracteres -> 500 (SQLite : LIKE pattern too complex) ; attendu 400/200."""
        self.assertEqual(self._filters_500(['search=' + 'x' * 100000, 'search=' + 'x' * 60000]), [])

    def test_actions_get_dates_illisibles(self):
        for d in ['abc', '2026-02-30', '9999-99-99', '', '0000-00-00', 'x' * 100000, '2026-1-1', '20261122']:
            for ep in ('daily_summary', 'bread_summary'):
                r = _api(self.g1).get(f'{INV}{ep}/', {'date': d})
                self.assertNotEqual(r.status_code, 500, f'{ep}?date={d[:20]!r}')
        for node in ['abc', '2' * 400, str(2 ** 70), '-1', '1.5', '', 'AV1; DROP']:
            r = _api(self.adm).get(f'{INV}bread_summary/', {'node': node})
            self.assertNotEqual(r.status_code, 500, f'bread_summary?node={node[:20]!r}')
            r = _api(self.adm).get(f'{INV}daily_summary/', {'node': node})
            self.assertNotEqual(r.status_code, 500, f'daily_summary?node={node[:20]!r}')

    def test_identifiant_facture_dans_url_illisible(self):
        for pk in ['abc', '0', '-1', '9' * 400, '00000000-0000-0000-0000-000000000000', '%00', 'x' * 5000]:
            for act in ('', 'deliver/', 'cancel/', 'adjust/', 'mark-not-served/'):
                url = f'{INV}{pk}/{act}'
                r = _api(self.g1).post(url, {}, format='json') if act else _api(self.g1).get(url)
                self.assertNotEqual(r.status_code, 500, url[:80])
                self.assertIn(r.status_code, (404, 400, 405), f'{url[:60]} -> {r.status_code}')

    def test_methodes_interdites(self):
        r = self.post()
        iid = r.data['id']
        for m in ('put', 'delete'):
            rr = getattr(_api(self.adm), m)(f'{INV}{iid}/', {}, format='json')
            self.assertEqual(rr.status_code, 405, m)
        self.assertEqual(_api(self.fa1).patch(f'{INV}{iid}/', {'commission_exempt': True}, format='json').status_code, 403)
        self.assertEqual(Invoice.objects.get(pk=iid).status, 'PENDING')

    def test_patch_commission_exempt_valeurs_illisibles(self):
        r = self.post()
        iid = r.data['id']
        for v in ['maybe', [], {}, None, 'NaN', 2, 'x' * 10000]:
            rr = _api(self.g1).patch(f'{INV}{iid}/', {'commission_exempt': v}, format='json')
            self.assertNotEqual(rr.status_code, 500, repr(v)[:30])
        for body in ['[]', '"x"', '1', 'null']:
            rr = _api(self.g1).patch(f'{INV}{iid}/', body, content_type='application/json')
            self.assertNotEqual(rr.status_code, 500, body)


# =============================================================================== R
class RolesEtIsolation(Base):
    def test_facturier_node_force_ignore(self):
        r = self.post(user=self.fa1, node=self.n2.pk)
        self.assertEqual(r.status_code, 201, r.data)
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual(inv.node_id, self.n1.pk)
        self.assertEqual(inv.node_origin, 'AV1')
        self.assertTrue(inv.receipt_number.startswith('AV1-'))
        self.assertEqual(self.sent(self.n2), 0)

    def test_gerant_node_force_ignore(self):
        r = self.post(user=self.g1, node=self.n2.pk)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Invoice.objects.get(pk=r.data['id']).node_id, self.n1.pk)

    def test_livreur_ne_cree_ni_annule_ni_ajuste(self):
        r = self.post()
        iid = r.data['id']
        a = _api(self.lv1)
        self.assertEqual(self.post(user=self.lv1).status_code, 403)
        self.assertEqual(a.post(f'{INV}{iid}/cancel/', {}, format='json').status_code, 403)
        self.assertEqual(a.post(f'{INV}{iid}/adjust/', {}, format='json').status_code, 403)
        self.assertEqual(a.post(f'{INV}cleanup_expired/', {}, format='json').status_code, 403)
        self.assertEqual(a.patch(f'{INV}{iid}/', {'commission_exempt': True}, format='json').status_code, 403)
        self.assertEqual(Invoice.objects.get(pk=iid).status, 'PENDING')

    def test_facturier_ne_peut_ni_ajuster_ni_exonerer_ni_expirer(self):
        r = self.post()
        iid = r.data['id']
        a = _api(self.fa1)
        self.assertEqual(a.post(f'{INV}{iid}/adjust/', {}, format='json').status_code, 403)
        self.assertEqual(a.patch(f'{INV}{iid}/', {'commission_exempt': True}, format='json').status_code, 403)
        self.assertEqual(a.post(f'{INV}cleanup_expired/', {}, format='json').status_code, 403)

    def test_anonyme_401_partout(self):
        r = self.post()
        iid = r.data['id']
        a = APIClient()
        a.raise_request_exception = False
        for method, url in [('get', INV), ('get', f'{INV}{iid}/'), ('post', INV), ('post', f'{INV}{iid}/deliver/'),
                            ('post', f'{INV}{iid}/cancel/'), ('post', f'{INV}{iid}/mark-not-served/'),
                            ('post', f'{INV}{iid}/adjust/'), ('get', f'{INV}pending_deliveries/'),
                            ('get', f'{INV}daily_summary/'), ('get', f'{INV}bread_summary/'),
                            ('post', f'{INV}cleanup_expired/')]:
            self.assertEqual(getattr(a, method)(url).status_code, 401, f'{method} {url}')

    def test_autre_boulangerie_404_sur_toutes_les_actions(self):
        r = self.post()
        iid = r.data['id']
        for user in (self.fa2, self.lv2, self.g2):
            a = _api(user)
            self.assertEqual(a.get(f'{INV}{iid}/').status_code, 404)
            for act in ('deliver', 'cancel', 'mark-not-served', 'adjust'):
                rr = a.post(f'{INV}{iid}/{act}/', {'adjustment_sign': 1, 'lines': []}, format='json')
                self.assertIn(rr.status_code, (403, 404), f'{user.role} {act}')
        self.assertEqual(Invoice.objects.get(pk=iid).status, 'PENDING')
        self.assertEqual(self.debt(), D(3000))
        self.assertEqual(_api(self.fa2).get(INV).data['count'], 0)
        self.assertEqual(_api(self.fa2).get(f'{INV}?node={self.n1.pk}').data['count'], 0)
        self.assertEqual(_api(self.fa2).get(f'{INV}?client={self.cl.pk}').data['count'], 0)
        self.assertEqual(_api(self.fa2).get(f'{INV}pending_deliveries/').data, [])
        self.assertEqual(_api(self.fa2).get(f'{INV}bread_summary/?node={self.n1.pk}').status_code, 403)

    def test_daily_summary_ne_fuit_pas_vers_autre_noeud(self):
        r = self.post(payment_amount=3000)
        _api(self.lv1).post(f'{INV}{r.data["id"]}/deliver/', {}, format='json')
        res = _api(self.fa2).get(f'{INV}daily_summary/?node={self.n1.pk}').data
        self.assertEqual(res, [])
        res = _api(self.fa1).get(f'{INV}daily_summary/').data
        self.assertTrue(all(row['node__code'] == 'AV1' for row in res))

    def test_facturier_peut_facturer_client_autre_boulangerie(self):
        """remarque.md : facturier d'une boulangerie, client d'une autre : accepte, facture sur SA boulangerie."""
        c2 = make_client(self.n2)
        r = self.post(user=self.fa1, client=c2, payment_amount=500)
        self.assertEqual(r.status_code, 201, r.data)
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual((inv.node_id, inv.client_id), (self.n1.pk, c2.pk))
        self.assertEqual(self.debt(c2), D(2500))
        self.assertEqual(self.sent(self.n1), 10)
        self.assertEqual(self.sent(self.n2), 0)

    def test_compte_sans_boulangerie_non_siege(self):
        u = make_user('FACTURIER', node=None, username='av_nonode')
        r = self.post(user=u)
        self.assertNotEqual(r.status_code, 500)
        self.assertIn(r.status_code, (400, 403), r.data)
        self.assertEqual(_api(u).get(INV).data['count'], 0)

    def test_siege_doit_preciser_noeud(self):
        r = _api(self.adm).post(INV, {'payment_type': 'CASH', 'payment_amount': 3000,
                                      'lines': [{'bread_price': self.bp3.pk, 'quantity': 10}]}, format='json')
        self.assertEqual(r.status_code, 400)
        r = _api(self.adm).post(INV, {'node': self.n2.pk, 'payment_type': 'CASH', 'payment_amount': 3000,
                                      'lines': [{'bread_price': self.bp3.pk, 'quantity': 10}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Invoice.objects.get(pk=r.data['id']).node_id, self.n2.pk)

    def test_livraison_par_facturier_ou_livreur_meme_noeud(self):
        for u in (self.fa1, self.lv1, self.g1):
            iid = self.post(payment_amount=3000, client=False, payment_type='CASH').data['id']
            r = _api(u).post(f'{INV}{iid}/deliver/', {}, format='json')
            self.assertEqual(r.status_code, 200, f'{u.role} {r.data}')
            self.assertEqual(Invoice.objects.get(pk=iid).livreur_id, u.pk)

    def test_livreur_non_authentifie_par_role_inconnu(self):
        u = make_user('LIVREUR', node=self.n1, username='av_lv_x')
        User = type(u)
        User.objects.filter(pk=u.pk).update(role='HACKER')
        iid = self.post().data['id']
        r = _api(User.objects.get(pk=u.pk)).post(f'{INV}{iid}/deliver/', {}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_utilisateur_inactif_jwt_refuse(self):
        u = make_user('FACTURIER', node=self.n1, username='av_inact')
        type(u).objects.filter(pk=u.pk).update(is_active=False)
        from rest_framework_simplejwt.tokens import AccessToken
        tok = AccessToken.for_user(type(u).objects.get(pk=u.pk))
        a = APIClient()
        a.raise_request_exception = False
        a.credentials(HTTP_AUTHORIZATION=f'Bearer {tok}')
        self.assertEqual(a.get(INV).status_code, 401)


# =============================================================================== B
class BpPlafondEtTypes(Base):
    def _set_debt(self, v, cl=None):
        Client.objects.filter(pk=(cl or self.cl).pk).update(current_debt=D(v))

    def test_bp_cumulatif_sur_plusieurs_ventes_et_aucun_reset(self):
        expected = D(0)
        for pay in (0, 500, 3000, 100, 0):
            r = self.post(payment_amount=pay)
            self.assertEqual(r.status_code, 201, r.data)
            inv = Invoice.objects.get(pk=r.data['id'])
            self.assertEqual(inv.debt_before, expected)
            expected += D(3000) - D(pay)
            self.assertEqual(inv.debt_after, expected)
        self.assertEqual(self.debt(), expected)

    def test_bp_cumulatif_changement_de_mois_avec_horloge(self):
        """Dernier jour du mois puis 1er du mois suivant : la BP est reportee, jamais remise a zero."""
        t1 = timezone.make_aware(timezone.datetime(2026, 9, 30, 12, 0))
        t2 = timezone.make_aware(timezone.datetime(2026, 10, 1, 9, 0))
        with patch('django.utils.timezone.now', return_value=t1):
            r1 = self.post(payment_amount=1000)
        with patch('django.utils.timezone.now', return_value=t2):
            r2 = self.post(payment_amount=0)
        self.assertEqual(r1.status_code, 201, r1.data)
        self.assertEqual(r2.status_code, 201, r2.data)
        i2 = Invoice.objects.get(pk=r2.data['id'])
        self.assertEqual((i2.debt_before, i2.debt_after), (D(2000), D(5000)))
        self.assertEqual(self.debt(), D(5000))

    def test_plafond_bornes_exactes(self):
        for debt, pay, ok in [(50000, 2999, False), (50000, 3000, True), (50000, 3001, True),
                              (49999, 0, True), (50001, 2999, False), (50001, 3000, True),
                              (50000, 0, False), (120000, 0, False), (120000, 3000, True)]:
            self._set_debt(debt)
            n = Invoice.objects.count()
            r = self.post(payment_amount=pay)
            self.assertEqual(r.status_code, 201 if ok else 403, f'debt={debt} pay={pay}: {r.data}')
            self.assertEqual(Invoice.objects.count(), n + (1 if ok else 0))
            if not ok:
                self.assertEqual(self.debt(), D(debt), 'refus : BP inchangee')
                self.assertEqual(self.sent(), self.sent())  # pas de stock touche (verifie plus bas)

    def test_refus_ne_touche_ni_stock_ni_numero_et_notifie(self):
        self._set_debt(50000)
        n_notif = SystemNotification.objects.count()
        stock_before = self.sent()
        r = self.post(payment_amount=0)
        self.assertEqual(r.status_code, 403)
        self.assertIn('detail', r.data)
        self.assertEqual(self.sent(), stock_before)
        self.assertGreaterEqual(SystemNotification.objects.count(), n_notif + 1)
        ok = self.post(payment_amount=3000)
        self.assertTrue(ok.data['receipt_number'].endswith('-0001'), 'un refus ne consomme pas de numero de recu')

    def test_plafond_zero_client_sans_credit(self):
        cl = make_client(self.n1, credit_limit=D('0.00'))
        r = self.post(client=cl, payment_amount=0)
        self.assertEqual(r.status_code, 403, 'plafond 0 FC : BP 0 >= 0, paiement < commande')
        r = self.post(client=cl, payment_amount=3000)
        self.assertEqual(r.status_code, 201, r.data)

    def test_plafond_propre_au_client(self):
        cl = make_client(self.n1, credit_limit=D('10000.00'), current_debt=D('10000.00'))
        self.assertEqual(self.post(client=cl, payment_amount=0).status_code, 403)
        cl2 = make_client(self.n1, credit_limit=D('200000.00'), current_debt=D('60000.00'))
        self.assertEqual(self.post(client=cl2, payment_amount=0).status_code, 201)

    def test_bp_negative_epargne_permet_vente_et_reduit_credit(self):
        self._set_debt(-10000)
        r = self.post(payment_amount=0)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.debt(), D(-7000))
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual((inv.debt_before, inv.debt_after), (D(-10000), D(-7000)))

    def test_depot_epargne_commande_zero_bp_negative(self):
        r = self.post(lines=[], payment_amount=5000, is_debt_repayment=True)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.debt(), D(-5000))
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual((inv.order_total, inv.commission_rate, inv.status), (D(0), D('0.00'), 'DELIVERED'))
        self.assertEqual(self.sent(), 0)
        r = self.post(lines=[], payment_amount=5000, is_debt_repayment=True)
        self.assertEqual(self.debt(), D(-10000))

    def test_remboursement_nul_ou_sans_client_refuse(self):
        self.assertEqual(self.post(lines=[], payment_amount=0, is_debt_repayment=True).status_code, 400)
        self.assertEqual(self.post(lines=[], payment_amount=100, is_debt_repayment=True, client=False).status_code, 400)
        self.assertEqual(Invoice.objects.count(), 0)

    def test_remboursement_ignore_lignes_envoyees_et_soldee(self):
        self._set_debt(4000)
        r = self.post(payment_amount=1000, is_debt_repayment=True, is_soldee=True,
                      lines=[{'bread_price': self.bp5.pk, 'quantity': 50}], special_code='NS')
        self.assertEqual(r.status_code, 201, r.data)
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual(inv.lines.count(), 0)
        self.assertEqual(inv.order_total, D(0))
        self.assertEqual(self.debt(), D(3000))
        self.assertEqual(self.sent(bp=self.bp5), 0)

    def test_remboursement_ne_gonfle_pas_ventes_du_jour(self):
        r = self.post(lines=[], payment_amount=2000, is_debt_repayment=True)
        res = _api(self.g1).get(f'{INV}bread_summary/').data
        self.assertEqual(res['grand_total_qty'], 0)
        self.assertEqual(res['grand_total_fc'], 0)
        self.assertEqual(Invoice.objects.get(pk=r.data['id']).lines.count(), 0)

    def test_paiement_negatif_sortie_de_caisse_et_blocage(self):
        self._set_debt(1000)
        r = self.post(lines=[], payment_amount=-500, is_debt_repayment=True, motif='RETRAIT_EPARGNE')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.debt(), D(1500))
        self._set_debt(50000)
        r = self.post(lines=[], payment_amount=-1, is_debt_repayment=True)
        self.assertEqual(r.status_code, 403, 'une sortie de caisse ne contourne jamais le plafond')
        self._set_debt(49999)
        self.assertEqual(self.post(lines=[], payment_amount=-1, is_debt_repayment=True).status_code, 201)
        self.assertEqual(self.debt(), D(50000))

    def test_paiement_negatif_sur_vente_normale_ne_contourne_pas_plafond(self):
        self._set_debt(50000)
        r = self.post(payment_amount=-100000)
        self.assertEqual(r.status_code, 403)
        self._set_debt(0)
        r = self.post(payment_amount=-500)
        self.assertIn(r.status_code, (201, 400))
        if r.status_code == 201:
            self.assertEqual(self.debt(), D(3500))

    def test_paiement_excedentaire_reduit_bp_et_peut_la_rendre_negative(self):
        self._set_debt(50000)
        r = self.post(payment_amount=10000)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.debt(), D(43000))
        self._set_debt(0)
        r = self.post(payment_amount=9000)
        self.assertEqual(self.debt(), D(-6000))

    def test_vente_soldee_prix_75_cm_zero_bp_inchangee(self):
        r = self.post(is_soldee=True, payment_amount=1000, lines=[{'bread_price': self.bp3.pk, 'quantity': 10}])
        self.assertEqual(r.status_code, 201, r.data)
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual(inv.lines.get().unit_price, 225)
        self.assertEqual((inv.order_total, inv.commission_rate), (D(2250), D('0.00')))
        self.assertEqual(self.debt(), D(0), 'VENTE SOLDE : aucune creance')
        self.assertEqual(inv.debt_after, inv.debt_before)

    def test_vente_soldee_blocage_utilise_prix_75(self):
        self._set_debt(50000)
        self.assertEqual(self.post(is_soldee=True, payment_amount=2249).status_code, 403)
        self.assertEqual(self.post(is_soldee=True, payment_amount=2250).status_code, 201)

    def test_vente_soldee_arrondi_par_ligne_sur_prix_impairs(self):
        bp = make_bread_price('AV7', 'Pain 150', 150)       # 112,5 -> 113
        r = self.post(is_soldee=True, payment_amount=0, lines=[{'bread_price': bp.pk, 'quantity': 3}])
        self.assertEqual(r.status_code, 201, r.data)
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual((inv.lines.get().unit_price, inv.order_total), (113, D(339)))

    def test_commission_exempt_et_taux_ignores_du_payload(self):
        cl = make_client(self.n1, commission_rate=D('0.30'))
        r = self.post(client=cl, commission_rate='0.25', payment_amount=0)
        self.assertEqual(Invoice.objects.get(pk=r.data['id']).commission_rate, D('0.30'))
        r = self.post(client=cl, commission_exempt=True)
        self.assertEqual(Invoice.objects.get(pk=r.data['id']).commission_rate, D('0.00'))
        r = self.post(client=cl, commission_rate='0.00')
        self.assertEqual(Invoice.objects.get(pk=r.data['id']).commission_rate, D('0.30'))

    def test_prix_du_catalogue_jamais_du_client(self):
        r = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 2, 'unit_price': 1, 'line_total': 1,
                              'price': 1}], unit_price=1)
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual((inv.lines.get().unit_price, inv.order_total), (300, D(600)))

    def test_prix_fige_apres_changement_de_tarif(self):
        r = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 2}])
        self.bp3.unit_price = 999
        self.bp3.save()
        inv = Invoice.objects.get(pk=r.data['id'])
        inv.save()
        for ln in inv.lines.all():
            ln.save()
        inv.refresh_from_db()
        self.assertEqual(inv.lines.get().unit_price, 300)
        self.assertEqual(_api(self.g1).get(f'{INV}{inv.pk}/').data['lines'][0]['unit_price'], 300)
        self.bp3.unit_price = 300
        self.bp3.save()

    def test_pain_desactive_ne_peut_plus_etre_vendu(self):
        """BUG-646 : categorie de pain desactivee vendable (201)"""
        bp = make_bread_price('AV9', 'Pain retire', 100)
        type(bp).objects.filter(pk=bp.pk).update(is_active=False)
        r = self.post(lines=[{'bread_price': bp.pk, 'quantity': 1}])
        self.assertEqual(r.status_code, 400, 'catalogue desactive : vente refusee')

    def test_client_desactive_ne_peut_plus_etre_facture(self):
        """BUG-646 : client desactive facturable (201)"""
        Client.objects.filter(pk=self.cl.pk).update(is_active=False)
        r = self.post(payment_amount=3000)
        self.assertEqual(r.status_code, 400, 'client desactive : facturation refusee')

    def test_code_nv_vente_normale_client_neuf(self):
        cl = make_client(self.n1)
        r = self.post(client=cl, special_code='NV', payment_amount=1000)
        self.assertEqual(r.status_code, 201, r.data)
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual((inv.special_code, inv.order_total, inv.commission_rate), ('NV', D(3000), D('0.25')))
        self.assertEqual(self.debt(cl), D(2000))
        self.assertEqual(self.sent(), 10)

    def test_code_nv_sans_client_au_comptant_seulement(self):
        self.assertEqual(self.post(client=False, special_code='NV', payment_type='CREDIT', payment_amount=0).status_code, 400)
        r = self.post(client=False, special_code='NV', payment_type='CASH', payment_amount=3000)
        self.assertEqual(r.status_code, 201, r.data)

    def test_code_rg_ni_paiement_ni_dette_ni_blocage_stock_decremente(self):
        self._set_debt(60000)
        r = self.post(special_code='RG', payment_amount=999)
        self.assertEqual(r.status_code, 201, r.data)
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual((inv.payment_amount, inv.commission_rate), (D(0), D('0.00')))
        self.assertEqual(self.debt(), D(60000))
        self.assertEqual(inv.debt_after, D(60000))

    def test_code_ns_credit_garde_dette_comptant_aucune_et_stock_intact(self):
        r = self.post(special_code='NS', payment_type='CREDIT', payment_amount=1000)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.debt(), D(2000))
        self.assertEqual(self.sent(), 0, 'NS : aucun pain sorti')
        r = self.post(special_code='NS', payment_type='CASH', payment_amount=1000)
        self.assertEqual(self.debt(), D(2000))
        self.assertEqual(Invoice.objects.get(pk=r.data['id']).payment_amount, D(0))
        self.assertEqual(self.sent(), 0)

    def test_ns_non_livrable_et_absente_des_livraisons_en_attente(self):
        iid = self.post(special_code='NS').data['id']
        self.assertEqual(_api(self.lv1).post(f'{INV}{iid}/deliver/', {}, format='json').status_code, 400)
        self.assertEqual(_api(self.lv1).get(f'{INV}pending_deliveries/').data, [])

    def test_vente_occasionnelle_sans_client(self):
        r = self.post(client=False, payment_type='CASH', payment_amount=3000)
        self.assertEqual(r.status_code, 201, r.data)
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertIsNone(inv.client_id)
        self.assertEqual(inv.commission_rate, D('0.00'))
        self.assertEqual(r.data['client_display'], 'CLIENT DIVERS')
        self.assertEqual(self.post(client=False, payment_type='CASH', payment_amount=2999).status_code, 400)
        self.assertEqual(self.post(client=False, payment_type='CREDIT', payment_amount=3000).status_code, 400)

    def test_deficit_net_du_mois_bloque_avec_commission_deduite(self):
        """Commande 200 000 / verse 100 000 / CM 25 % = 50 000 : deficit net >= plafond -> 403."""
        cl = make_client(self.n1)
        for _ in range(2):
            i = Invoice.objects.create(node=self.n1, client=cl, facturier=self.fa1, team='A',
                                       status='DELIVERED', payment_type='CREDIT', order_total=D(100000),
                                       payment_amount=D(50000), commission_rate=D('0.25'), delivered_at=timezone.now())
        r = self.post(client=cl, payment_amount=0)
        self.assertEqual(r.status_code, 403, r.data)
        self.assertIn('Déficit', r.data['detail'])
        self.assertEqual(self.post(client=cl, payment_amount=3000).status_code, 201)

    def test_receipt_numbers_uniques_tous_types(self):
        self._set_debt(0)
        ids = []
        ids.append(self.post().data['id'])
        ids.append(self.post(lines=[], payment_amount=100, is_debt_repayment=True).data['id'])
        ids.append(self.post(client=False, payment_type='CASH', payment_amount=3000).data['id'])
        ids.append(self.post(special_code='NS').data['id'])
        ids.append(self.post(special_code='RG').data['id'])
        _api(self.lv1).post(f'{INV}{ids[0]}/deliver/', {}, format='json')
        adj = _api(self.g1).post(f'{INV}{ids[0]}/adjust/', {
            'adjustment_sign': 1, 'payment_amount': 0, 'lines': [{'bread_price': self.bp3.pk, 'quantity': 1}]}, format='json')
        self.assertEqual(adj.status_code, 201, adj.data)
        ids.append(adj.data['id'])
        _api(self.fa1).post(f'{INV}{self.post().data["id"]}/cancel/', {}, format='json')
        nums = list(Invoice.objects.values_list('receipt_number', flat=True))
        self.assertEqual(len(nums), len(set(nums)), nums)
        for n in nums:
            self.assertRegex(n, r'^AV1-\d{8}-\d{4}$')
        # compteur propre a chaque boulangerie
        n2 = self.post(user=self.fa2, client=make_client(self.n2), payment_amount=3000)
        self.assertTrue(n2.data['receipt_number'].startswith('AV2-'))
        self.assertTrue(n2.data['receipt_number'].endswith('-0001'))

    def test_recu_contient_toutes_les_mentions_en_api(self):
        r = self.post(payment_amount=500)
        d = _api(self.fa1).get(f'{INV}{r.data["id"]}/').data
        for k in ('receipt_number', 'node_display', 'created_at', 'team', 'client_display',
                  'client_code', 'lines', 'order_total', 'payment_amount', 'commission_rate', 'debt_before',
                  'debt_after', 'invoice_date'):
            self.assertIn(k, d, k)
            self.assertNotIn(d[k], (None, ''), k)
        self.assertEqual((d['team'], d['debt_before'], d['debt_after']), ('A', '0.00', '2500.00'))
        self.assertTrue(all({'bread_label', 'quantity', 'unit_price', 'line_total'} <= set(l) for l in d['lines']))

    def test_equipes_a_et_b_uniquement(self):
        u = make_user('FACTURIER', node=self.n1, team='B', username='av_teamb')
        r = self.post(user=u, payment_amount=3000)
        self.assertEqual(Invoice.objects.get(pk=r.data['id']).team, 'B')
        for t in ('C', 'N', 'J'):
            u2 = make_user('FACTURIER', node=self.n1, team='A', username=f'av_team_{t}')
            type(u2).objects.filter(pk=u2.pk).update(team=t)
            u2 = type(u2).objects.get(pk=u2.pk)
            rr = self.post(user=u2, payment_amount=3000)
            self.assertNotEqual(rr.status_code, 500)

    def test_journalisation_creation_livraison_annulation(self):
        iid = self.post(payment_amount=3000).data['id']
        _api(self.fa1).post(f'{INV}{iid}/cancel/', {}, format='json')
        titles = list(ActivityLog.objects.values_list('action', flat=True))
        self.assertTrue(any('Facturation' in t for t in titles), titles)
        self.assertTrue(any('Annulation' in t for t in titles), titles)


# =============================================================================== S
class SequencesAleatoires(Base):
    """Modele independant : current_debt et stock apres CHAQUE operation d'une longue sequence."""

    def _run(self, seed, steps=70):
        rnd = random.Random(seed)
        cl = make_client(self.n1, credit_limit=D('20000.00'))
        gerant, fa, lv = _api(self.g1), _api(self.fa1), _api(self.lv1)
        exp_debt = D(0)
        exp_sent = {self.bp3.pk: 0, self.bp5.pk: 0}
        pend = []        # factures en attente : dict(id, lines=[(line_id, bp, qty, unit)], pay, soldee)
        delivered = []   # factures livrees non soldees ajustables
        prices = {self.bp3.pk: 300, self.bp5.pk: 500}

        def delta(order, pay, soldee):
            return D(0) if soldee else D(order) - D(pay)

        for step in range(steps):
            op = rnd.choice(['create', 'create', 'create', 'refund', 'cancel', 'deliver', 'partial', 'ns',
                             'expire', 'adjust', 'list'])
            if op == 'create':
                qtys = {self.bp3.pk: rnd.randint(1, 6), self.bp5.pk: rnd.choice([0, 0, 1, 2])}
                soldee = rnd.random() < 0.15
                unit = {k: (_soldee_price(v) if soldee else v) for k, v in prices.items()}
                order = sum(qtys[k] * unit[k] for k in qtys if qtys[k])
                pay = rnd.choice([0, 0, order // 2, order, order + 700])
                lines = [{'bread_price': k, 'quantity': q} for k, q in qtys.items() if q]
                before = exp_debt
                r = fa.post(INV, {'client': str(cl.pk), 'payment_type': 'CREDIT', 'payment_amount': pay,
                                  'is_soldee': soldee, 'lines': lines}, format='json')
                if before >= D(20000) and pay < order:
                    self.assertEqual(r.status_code, 403, f'seed {seed} step {step}: {r.data}')
                    self.assertEqual(self.debt(cl), exp_debt)
                    continue
                if r.status_code == 403:     # deficit net du mois (regle complementaire) : etat inchange
                    self.assertIn('Déficit', r.data['detail'], f'seed {seed} step {step}')
                    self.assertEqual(self.debt(cl), exp_debt)
                    continue
                self.assertEqual(r.status_code, 201, f'seed {seed} step {step}: {r.data}')
                dl = delta(order, pay, soldee)
                exp_debt += dl
                for k, q in qtys.items():
                    exp_sent[k] += q
                self.assertEqual((D(r.data['debt_before']), D(r.data['debt_after']), D(r.data['order_total'])),
                                 (before, before + dl, D(order)), f'seed {seed} step {step}')
                pend.append({'id': r.data['id'], 'soldee': soldee, 'pay': D(pay), 'order': D(order),
                             'lines': [(l['id'], l['bread_price'], l['quantity'], l['unit_price']) for l in r.data['lines']],
                             'created': timezone.now()})
            elif op == 'refund':
                pay = rnd.choice([100, 2500, -400, 7000])
                before = exp_debt
                r = fa.post(INV, {'client': str(cl.pk), 'payment_type': 'CASH', 'payment_amount': pay,
                                  'is_debt_repayment': True, 'lines': []}, format='json')
                if pay < 0 and before >= D(20000):
                    self.assertEqual(r.status_code, 403, f'seed {seed} step {step}')
                else:
                    self.assertEqual(r.status_code, 201, f'seed {seed} step {step}: {r.data}')
                    exp_debt -= D(pay)
                    self.assertEqual(D(r.data['debt_after']), exp_debt)
            elif op == 'cancel' and pend:
                p = pend.pop(rnd.randrange(len(pend)))
                r = fa.post(f'{INV}{p["id"]}/cancel/', {}, format='json')
                self.assertEqual(r.status_code, 200, f'seed {seed} step {step}: {r.data}')
                exp_debt -= delta(p['order'], p['pay'], p['soldee'])
                for (_l, bp, q, _u) in p['lines']:
                    exp_sent[bp] -= q
            elif op == 'deliver' and pend:
                p = pend.pop(rnd.randrange(len(pend)))
                r = (lv if rnd.random() < 0.5 else fa).post(f'{INV}{p["id"]}/deliver/', {}, format='json')
                self.assertEqual(r.status_code, 200, f'seed {seed} step {step}: {r.data}')
                if not p['soldee']:
                    delivered.append(p)
                again = fa.post(f'{INV}{p["id"]}/deliver/', {}, format='json')
                self.assertEqual(again.status_code, 400, 'double livraison refusee')
            elif op == 'partial' and pend:
                p = pend[rnd.randrange(len(pend))]
                if sum(q for (_l, _b, q, _u) in p['lines']) < 2:
                    continue
                served = []
                for (lid, bp, q, u) in p['lines']:
                    served.append((lid, bp, rnd.randint(0, q), u, q))
                if sum(s[2] for s in served) == 0:
                    served[0] = (served[0][0], served[0][1], 1, served[0][3], served[0][4])
                new_order = sum(s[2] * s[3] for s in served)
                r = lv.post(f'{INV}{p["id"]}/deliver/', {'lines': [{'id': s[0], 'quantity': s[2]} for s in served]},
                            format='json')
                self.assertEqual(r.status_code, 200, f'seed {seed} step {step}: {r.data}')
                pend.remove(p)
                exp_debt += delta(new_order, p['pay'], p['soldee']) - delta(p['order'], p['pay'], p['soldee'])
                for s in served:
                    exp_sent[s[1]] -= s[4] - s[2]
                self.assertEqual(D(r.data['order_total']), D(new_order), f'seed {seed} step {step}')
            elif op == 'ns' and pend:
                p = pend.pop(rnd.randrange(len(pend)))
                r = fa.post(f'{INV}{p["id"]}/mark-not-served/', {'reason': 'test'}, format='json')
                self.assertEqual(r.status_code, 200, f'seed {seed} step {step}: {r.data}')
                exp_debt += delta(0, p['pay'], p['soldee']) - delta(p['order'], p['pay'], p['soldee'])
                for (_l, bp, q, _u) in p['lines']:
                    exp_sent[bp] -= q
                self.assertEqual(fa.post(f'{INV}{p["id"]}/mark-not-served/', {}, format='json').status_code, 409)
            elif op == 'expire' and pend:
                p = pend.pop(rnd.randrange(len(pend)))
                Invoice.objects.filter(pk=p['id']).update(created_at=timezone.now() - timedelta(hours=12, minutes=1))
                r = fa.get(f'{INV}pending_deliveries/')
                self.assertEqual(r.status_code, 200)
                self.assertEqual(Invoice.objects.get(pk=p['id']).status, 'NOT_SERVED')
                exp_debt += delta(0, p['pay'], p['soldee']) - delta(p['order'], p['pay'], p['soldee'])
                for (_l, bp, q, _u) in p['lines']:
                    exp_sent[bp] -= q
                fa.get(INV)
                gerant.post(f'{INV}cleanup_expired/', {}, format='json')
            elif op == 'adjust' and delivered:
                p = delivered[rnd.randrange(len(delivered))]
                sign = rnd.choice([1, -1])
                bp = p['lines'][0][1]
                remaining = p.setdefault('rem', {lb: q for (_l, lb, q, _u) in p['lines']})
                if sign == -1 and remaining.get(bp, 0) < 1:
                    sign = 1
                pay = rnd.choice([0, 100])
                r = gerant.post(f'{INV}{p["id"]}/adjust/', {
                    'adjustment_sign': sign, 'payment_amount': pay,
                    'lines': [{'bread_price': bp, 'quantity': 1}]}, format='json')
                if sign == 1 and exp_debt >= D(20000):
                    pass  # l'ajustement n'applique pas le plafond : comportement observe, pas asserte
                self.assertEqual(r.status_code, 201, f'seed {seed} step {step}: {r.data}')
                unit = p['lines'][0][3]
                exp_debt += sign * (D(unit) - D(pay))
                exp_sent[bp] += sign
                remaining[bp] = remaining.get(bp, 0) + sign
            elif op == 'list':
                fa.get(INV)
            # invariants apres CHAQUE operation
            self.assertEqual(self.debt(cl), exp_debt, f'seed {seed} step {step} op {op} : BP')
            for k in exp_sent:
                self.assertEqual(self.sent(bp=type(self.bp3).objects.get(pk=k)), exp_sent[k],
                                 f'seed {seed} step {step} op {op} : stock {k}')
        nums = list(Invoice.objects.values_list('receipt_number', flat=True))
        self.assertEqual(len(nums), len(set(nums)))

    def test_sequence_seed_1(self):
        self._run(1)

    def test_sequence_seed_2(self):
        self._run(2)

    def test_sequence_seed_3(self):
        self._run(3)

    def test_sequence_seed_4(self):
        self._run(4)

    def test_sequence_seed_5(self):
        self._run(5)


# =============================================================================== L
class LivraisonExpirationAnnulation(Base):
    def _deliver(self, iid, user=None, **body):
        return _api(user or self.lv1).post(f'{INV}{iid}/deliver/', body, format='json')

    def test_double_livraison_sequentielle_destocke_une_fois(self):
        iid = self.post().data['id']
        self.assertEqual(self._deliver(iid).status_code, 200)
        self.assertEqual(self._deliver(iid).status_code, 400)
        self.assertEqual(self._deliver(iid, self.fa1).status_code, 400)
        self.assertEqual(self.sent(), 10)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.total_breads_received, 10, 'pains recus comptes une seule fois')
        self.assertEqual(self.debt(), D(3000))
        self.assertEqual(Invoice.objects.get(pk=iid).livreur_id, self.lv1.pk)

    def test_livraison_ne_change_pas_la_bp_deja_appliquee(self):
        iid = self.post(payment_amount=1000).data['id']
        before = self.debt()
        self._deliver(iid)
        self.assertEqual(self.debt(), before)
        self.assertEqual(Invoice.objects.get(pk=iid).debt_after, before)

    def test_annulation_restaure_bp_stock_et_journalise(self):
        iid = self.post(payment_amount=1000).data['id']
        self.assertEqual(self.debt(), D(2000))
        self.assertEqual(self.sent(), 10)
        r = _api(self.fa1).post(f'{INV}{iid}/cancel/', {}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.debt(), D(0))
        self.assertEqual(self.sent(), 0)
        self.assertTrue(ActivityLog.objects.filter(action__icontains='Annulation').exists())
        again = _api(self.fa1).post(f'{INV}{iid}/cancel/', {}, format='json')
        self.assertEqual(self.debt(), D(0), 'seconde annulation : pas de double restitution')
        self.assertEqual(self.sent(), 0)
        self.__class__._again = again.status_code

    def test_BUG_647_annuler_deux_fois_refuse(self):
        """BUG-647 : seconde annulation -> 200 + nouvelle ligne de journal « stock et BP restitues »."""
        iid = self.post().data['id']
        _api(self.fa1).post(f'{INV}{iid}/cancel/', {}, format='json')
        again = _api(self.fa1).post(f'{INV}{iid}/cancel/', {}, format='json')
        self.assertEqual(again.status_code, 400)

    def test_annulation_refusee_si_livree_et_livraison_refusee_si_annulee(self):
        iid = self.post().data['id']
        self._deliver(iid)
        self.assertEqual(_api(self.fa1).post(f'{INV}{iid}/cancel/', {}, format='json').status_code, 400)
        iid2 = self.post().data['id']
        _api(self.fa1).post(f'{INV}{iid2}/cancel/', {}, format='json')
        self.assertEqual(self._deliver(iid2).status_code, 400)
        self.assertEqual(_api(self.fa1).post(f'{INV}{iid2}/mark-not-served/', {}, format='json').status_code, 409)
        self.assertEqual(self.debt(), D(3000))

    def test_annulation_facture_non_servie_refusee(self):
        """BUG-647 : cancel() reecrit NOT_SERVED en CANCELLED"""
        iid = self.post(payment_amount=1000).data['id']
        _api(self.fa1).post(f'{INV}{iid}/mark-not-served/', {}, format='json')
        r = _api(self.fa1).post(f'{INV}{iid}/cancel/', {}, format='json')
        self.assertEqual(r.status_code, 400, "une facture NOT_SERVED (statut terminal) ne doit pas passer a CANCELLED")
        self.assertEqual(Invoice.objects.get(pk=iid).status, 'NOT_SERVED')

    def test_annulation_remboursement_ou_ajustement_refusee(self):
        iid = self.post(lines=[], payment_amount=100, is_debt_repayment=True).data['id']
        r = _api(self.fa1).post(f'{INV}{iid}/cancel/', {}, format='json')
        self.assertEqual(r.status_code, 400)       # DELIVERED
        self.assertEqual(self.debt(), D(-100))

    def test_annulation_apres_ajustement_negatif_double_restitution(self):
        """BUG-648 : annulation apres ajustement -1 : BP -300 et stock -1"""
        """Ajustement -1 (1 pain repris) puis annulation de l'ORIGINALE en attente : BP/stock ne doivent pas etre restitues deux fois."""
        iid = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 2}], payment_amount=0).data['id']
        self.assertEqual((self.debt(), self.sent()), (D(600), 2))
        adj = _api(self.g1).post(f'{INV}{iid}/adjust/', {
            'adjustment_sign': -1, 'payment_amount': 0, 'lines': [{'bread_price': self.bp3.pk, 'quantity': 1}]}, format='json')
        self.assertEqual(adj.status_code, 201, adj.data)
        self.assertEqual((self.debt(), self.sent()), (D(300), 1))
        r = _api(self.fa1).post(f'{INV}{iid}/cancel/', {}, format='json')
        # soit refuse (400), soit restitue seulement le reste (BP 0, stock 0)
        if r.status_code == 200:
            self.assertEqual((self.debt(), self.sent()), (D(0), 0),
                             'annulation apres ajustement : restitution double (BP negative, stock excedentaire)')

    def test_ajustement_sur_originale_annulee_ou_non_servie(self):
        """BUG-649 : ajustement +1 accepte sur facture NOT_SERVED"""
        iid = self.post().data['id']
        _api(self.fa1).post(f'{INV}{iid}/mark-not-served/', {}, format='json')
        body = {'adjustment_sign': -1, 'payment_amount': 0, 'lines': [{'bread_price': self.bp3.pk, 'quantity': 1}]}
        r = _api(self.g1).post(f'{INV}{iid}/adjust/', body, format='json')
        self.assertEqual(r.status_code, 400)
        body['adjustment_sign'] = 1
        r = _api(self.g1).post(f'{INV}{iid}/adjust/', body, format='json')
        self.assertEqual(r.status_code, 400, "ajuster (+1) une facture NOT_SERVED (terminale) cree une vente fantome")

    def test_ajustement_negatif_plus_que_net_refuse_et_ne_touche_rien(self):
        iid = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 2}]).data['id']
        self._deliver(iid)
        body = {'adjustment_sign': -1, 'payment_amount': 0, 'lines': [{'bread_price': self.bp3.pk, 'quantity': 3}]}
        r = _api(self.g1).post(f'{INV}{iid}/adjust/', body, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual((self.debt(), self.sent()), (D(600), 2))
        ok = {'adjustment_sign': -1, 'payment_amount': 0, 'lines': [{'bread_price': self.bp3.pk, 'quantity': 1}]}
        self.assertEqual(_api(self.g1).post(f'{INV}{iid}/adjust/', ok, format='json').status_code, 201)
        self.assertEqual(_api(self.g1).post(f'{INV}{iid}/adjust/', ok, format='json').status_code, 201)
        self.assertEqual(_api(self.g1).post(f'{INV}{iid}/adjust/', ok, format='json').status_code, 400)
        self.assertEqual((self.debt(), self.sent()), (D(0), 0))

    def test_ajustement_meme_pain_deux_lignes_dans_une_requete(self):
        iid = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 2}]).data['id']
        self._deliver(iid)
        body = {'adjustment_sign': -1, 'payment_amount': 0, 'lines': [
            {'bread_price': self.bp3.pk, 'quantity': 2}, {'bread_price': self.bp3.pk, 'quantity': 2}]}
        r = _api(self.g1).post(f'{INV}{iid}/adjust/', body, format='json')
        self.assertEqual(r.status_code, 400, 'cumul des lignes d un meme pain : 4 > 2 restant')
        self.assertEqual(self.sent(), 2)

    def test_expiration_12h_bornes(self):
        iid = self.post(payment_amount=500).data['id']
        Invoice.objects.filter(pk=iid).update(created_at=timezone.now() - timedelta(hours=11, minutes=59))
        self.assertEqual(self._deliver(iid).status_code, 200, 'a 11 h 59 : encore livrable')
        iid2 = self.post(payment_amount=500).data['id']
        Invoice.objects.filter(pk=iid2).update(created_at=timezone.now() - timedelta(hours=12, minutes=1))
        before_debt, before_sent = self.debt(), self.sent()
        r = self._deliver(iid2)
        self.assertEqual(r.status_code, 409)
        inv = Invoice.objects.get(pk=iid2)
        self.assertEqual(inv.status, 'NOT_SERVED')
        self.assertEqual(self.sent(), before_sent - 10)
        self.assertEqual(inv.order_total, D(0))
        self.assertEqual(inv.initial_order_total, D(3000))
        # versement 500 conserve comme encaissement : BP = (apres 1re facture 2500) - 500
        self.assertEqual(self.debt(), D(2500) + D(-500))

    def test_expiration_idempotente_et_unique(self):
        iid = self.post(payment_amount=0).data['id']
        Invoice.objects.filter(pk=iid).update(created_at=timezone.now() - timedelta(hours=13))
        for _ in range(3):
            _api(self.fa1).get(INV)
            _api(self.g1).post(f'{INV}cleanup_expired/', {}, format='json')
            _api(self.lv1).get(f'{INV}pending_deliveries/')
        self.assertEqual((self.debt(), self.sent()), (D(0), 0))
        self.assertEqual(Invoice.objects.filter(pk=iid, status='NOT_SERVED').count(), 1)

    def test_expiration_ne_touche_ni_ns_ni_remboursement_ni_livree(self):
        ns = self.post(special_code='NS', payment_amount=0).data['id']
        rf = self.post(lines=[], payment_amount=100, is_debt_repayment=True).data['id']
        dl = self.post(payment_amount=3000).data['id']
        self._deliver(dl)
        old = timezone.now() - timedelta(hours=30)
        Invoice.objects.update(created_at=old)
        _api(self.g1).post(f'{INV}cleanup_expired/', {}, format='json')
        self.assertEqual(Invoice.objects.get(pk=ns).status, 'PENDING')
        self.assertEqual(Invoice.objects.get(pk=rf).status, 'DELIVERED')
        self.assertEqual(Invoice.objects.get(pk=dl).status, 'DELIVERED')

    def test_expiration_isolee_par_noeud(self):
        c2 = make_client(self.n2)
        a = self.post().data['id']
        b = self.post(user=self.fa2, client=c2).data['id']
        Invoice.objects.update(created_at=timezone.now() - timedelta(hours=20))
        r = _api(self.g1).post(f'{INV}cleanup_expired/', {}, format='json')
        self.assertEqual(r.data['expired'], 1)
        self.assertEqual(Invoice.objects.get(pk=a).status, 'NOT_SERVED')
        self.assertEqual(Invoice.objects.get(pk=b).status, 'PENDING')

    def test_livraison_partielle_soldee_et_sans_client(self):
        r = self.post(client=False, payment_type='CASH', payment_amount=3000)
        iid, lid = r.data['id'], r.data['lines'][0]['id']
        rr = self._deliver(iid, user=self.fa1, lines=[{'id': lid, 'quantity': 4}])
        self.assertEqual(rr.status_code, 200, rr.data)
        inv = Invoice.objects.get(pk=iid)
        self.assertEqual((inv.order_total, inv.payment_amount, inv.initial_order_total), (D(1200), D(1200), D(3000)))
        self.assertEqual(self.sent(), 4)

    def test_livraison_partielle_zero_partout_refusee_et_ligne_a_zero_acceptee(self):
        r = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 4}, {'bread_price': self.bp5.pk, 'quantity': 2}])
        iid = r.data['id']
        l0, l1 = r.data['lines'][0]['id'], r.data['lines'][1]['id']
        rr = self._deliver(iid, lines=[{'id': l0, 'quantity': 0}, {'id': l1, 'quantity': 0}])
        self.assertEqual(rr.status_code, 400)
        self.assertEqual((self.debt(), self.sent(), self.sent(bp=self.bp5)), (D(2200), 4, 2))
        rr = self._deliver(iid, lines=[{'id': l0, 'quantity': 0}])
        self.assertEqual(rr.status_code, 200, rr.data)
        self.assertEqual((self.debt(), self.sent(), self.sent(bp=self.bp5)), (D(1000), 0, 2))

    def test_livraison_liste_vide_equivaut_a_livraison_totale(self):
        iid = self.post().data['id']
        self.assertEqual(self._deliver(iid, lines=[]).status_code, 200)
        self.assertEqual((self.debt(), self.sent()), (D(3000), 10))

    def test_stock_insuffisant_comportement_documente(self):
        """Aucun stock initial : la facture est creee et le stock devient negatif (pas de refus). Comportement observe, pas de ticket."""
        r = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 100000}], payment_amount=30000000, client=False,
                      payment_type='CASH')
        self.assertIn(r.status_code, (201, 400))
        self.assertNotEqual(r.status_code, 500)

    def test_pending_deliveries_exclut_non_servi_et_livrees(self):
        a = self.post().data['id']
        b = self.post().data['id']
        c = self.post().data['id']
        _api(self.fa1).post(f'{INV}{b}/mark-not-served/', {}, format='json')
        self._deliver(c)
        ids = [x['id'] for x in _api(self.lv1).get(f'{INV}pending_deliveries/').data]
        self.assertEqual(ids, [a])


class LivraisonConcurrente(TransactionTestCase):
    """Double clic : N requetes simultanees de livraison de la MEME facture."""

    def setUp(self):
        self.n1 = make_node(code='CV1')
        self.fa = make_user('FACTURIER', node=self.n1, team='A', username='cv1_fa')
        self.lv = make_user('LIVREUR', node=self.n1, team='A', username='cv1_lv')
        self.bp = make_bread_price('CV3', 'Pain 300', 300)
        self.cl = make_client(self.n1)

    def test_BUG_650_n_livraisons_simultanees_une_seule_reussit(self):
        """BUG-650 : 5 livraisons simultanees de la meme facture (SQLite, noeud desktop) : OperationalError table locked, 5 x 500, aucune ne reussit (pas de retentative comme BUG-062)."""
        r = _api(self.fa).post(INV, {'client': str(self.cl.pk), 'payment_type': 'CREDIT', 'payment_amount': 0,
                                     'lines': [{'bread_price': self.bp.pk, 'quantity': 10}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        iid = r.data['id']
        codes, errs, errs_500 = [], [], []
        barrier = threading.Barrier(5)

        def work():
            try:
                barrier.wait()
                a = _api(self.lv)
                a.raise_request_exception = True
                try:
                    codes.append(a.post(f'{INV}{iid}/deliver/', {}, format='json').status_code)
                except Exception as exc:
                    codes.append(500)
                    errs_500.append(f'{type(exc).__name__}: {exc}'[:120])
            except Exception as exc:       # pragma: no cover
                errs.append(repr(exc))
            finally:
                connection.close()

        ts = [threading.Thread(target=work) for _ in range(5)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertFalse(errs, errs)
        self.assertEqual(codes.count(200), 1, f'{codes} {errs_500[:2]}')
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.total_breads_received, 10, 'double comptage des pains recus')
        self.assertEqual(Invoice.objects.get(pk=iid).status, 'DELIVERED')
        st = BreadStock.objects.get(node=self.n1, bread_price=self.bp)
        self.assertEqual(st.qty_sent, 10)

    def test_annulation_et_livraison_simultanees_etat_coherent(self):
        r = _api(self.fa).post(INV, {'client': str(self.cl.pk), 'payment_type': 'CREDIT', 'payment_amount': 0,
                                     'lines': [{'bread_price': self.bp.pk, 'quantity': 10}]}, format='json')
        iid = r.data['id']
        res = {}
        barrier = threading.Barrier(2)

        def deliver():
            barrier.wait()
            res['d'] = _api(self.lv).post(f'{INV}{iid}/deliver/', {}, format='json').status_code
            connection.close()

        def cancel():
            barrier.wait()
            res['c'] = _api(self.fa).post(f'{INV}{iid}/cancel/', {}, format='json').status_code
            connection.close()

        ts = [threading.Thread(target=deliver), threading.Thread(target=cancel)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        inv = Invoice.objects.get(pk=iid)
        self.cl.refresh_from_db()
        st = BreadStock.objects.get(node=self.n1, bread_price=self.bp)
        if inv.status == 'CANCELLED':
            self.assertEqual((self.cl.current_debt, st.qty_sent), (D(0), 0), f'annulee mais effets conserves {res}')
        else:
            self.assertEqual((self.cl.current_debt, st.qty_sent), (D(3000), 10), f'livree mais effets perdus {res}')


# =============================================================================== K
class VerrousCreationFacture(Base):
    """CLAUDE.md 4 : toute lecture d'un solde (current_debt) destinee a decider/ecrire est sous select_for_update."""

    def _locked_models(self, fn):
        seen = []
        orig = QuerySet.select_for_update

        def spy(qs, *a, **kw):
            seen.append(qs.model.__name__)
            return orig(qs, *a, **kw)

        with patch.object(QuerySet, 'select_for_update', spy):
            fn()
        return seen

    def test_BUG_640_creation_facture_verrouille_le_client(self):
        """BUG-640 : _create_once lit Client sans verrou (plafond contournable, debt_before/after faux en concurrence)."""
        seen = self._locked_models(lambda: self.post(payment_amount=500))
        self.assertIn('Client', seen)

    def test_BUG_640_remboursement_verrouille_le_client(self):
        """BUG-640 (volet remboursement)."""
        seen = self._locked_models(lambda: self.post(lines=[], payment_amount=500, is_debt_repayment=True))
        self.assertIn('Client', seen)

    def test_BUG_640_ajustement_verrouille_le_client(self):
        """BUG-640 (volet ajustement : debt_before lu sans verrou)."""
        iid = self.post().data['id']
        _api(self.lv1).post(f'{INV}{iid}/deliver/', {}, format='json')
        body = {'adjustment_sign': 1, 'payment_amount': 0, 'lines': [{'bread_price': self.bp3.pk, 'quantity': 1}]}
        seen = self._locked_models(lambda: _api(self.g1).post(f'{INV}{iid}/adjust/', body, format='json'))
        self.assertIn('Client', seen)

    def test_BUG_642_annulation_est_atomique_et_sous_verrou(self):
        """BUG-642 : cancel() lit le statut sans verrou ni transaction : deux annulations simultanees restituent deux fois."""
        iid = self.post().data['id']
        seen = self._locked_models(lambda: _api(self.fa1).post(f'{INV}{iid}/cancel/', {}, format='json'))
        self.assertIn('Invoice', seen)

    def test_BUG_641_verrou_livraison_sans_jointure_externe(self):
        """BUG-641 : _lock() = select_for_update + select_related('client') sur FK NULLABLE -> LEFT OUTER JOIN ;
        PostgreSQL : FOR UPDATE cannot be applied to the nullable side of an outer join."""
        captured = []
        orig_get = QuerySet.get

        def spy(qs, *a, **kw):
            if qs.query.select_for_update and qs.model is Invoice:
                captured.append(qs)
            return orig_get(qs, *a, **kw)

        iid = self.post().data['id']
        with patch.object(QuerySet, 'get', spy):
            _api(self.lv1).post(f'{INV}{iid}/deliver/', {}, format='json')
        self.assertTrue(captured, 'aucune requete verrouillee observee')
        for qs in captured:
            if qs.query.select_for_update_of:
                continue
            self.assertNotIn('LEFT OUTER JOIN', str(qs.query), 'FOR UPDATE sur la face nullable')
