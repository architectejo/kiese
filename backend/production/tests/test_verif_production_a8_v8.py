"""Testeur-production (Dev A, cycle 9 / a8) : push de synchronisation production/ventes face aux
regles REST (bornes, ASCII, dates futures, negatifs, portee noeud, factures terminales) et flux
legitime complet fournee -> stock -> facture -> livraison -> cloture journaliere (chiffres du
signe appro recu, BUG-675). Donnees fictives. Les `@expectedFailure` referencent leur ticket.
"""
import uuid
from datetime import date as ddate, timedelta
from decimal import Decimal as Dc

from rest_framework.test import APIClient

from core.models import BreadPrice
from core.testing import make_client, make_node
from production.models import (BreadDisposal, ConsumableMovement, ConsumableStock, ProductionSession,
                               ProductionSessionLine)
from production.tests.test_verif_a4_testeur_production import TBase, cl
from sales.models import Invoice, InvoiceLine
from sync.models import NodeAuthToken

PUSH = '/api/sync/push/'
S = '/api/production/sessions/'
AR = '٣'  # chiffre arabe-indien


def api_for(node):
    _, raw = NodeAuthToken.issue_for_node(node)
    a = APIClient(raise_request_exception=False)
    a.credentials(HTTP_AUTHORIZATION=f'Bearer {raw}')
    return a


def push(a, label, rec):
    r = a.post(PUSH, {'batch_id': str(uuid.uuid4()), 'records': {label: [rec]}}, format='json')
    assert r.status_code == 200, (r.status_code, r.content)
    x = r.data['results'][label][0]
    return x['status'], x.get('reason')


def uid():
    return str(uuid.uuid4())


class PushBase(TBase):
    """Deux noeuds de synchronisation Q1/Q2 (codes de TBase), jetons dedies."""

    def setUp(self):
        super().setUp()
        self.a1, self.a2 = api_for(self.k1), api_for(self.k2)
        self._n = 0

    def day(self):
        self._n += 1
        return str(ddate.today() - timedelta(days=self._n))

    def sess(self, **kw):
        d = {'id': uid(), 'node': self.k1.code, 'team': 'A', 'date': self.day(), 'flour_sacks_used': '2.00',
             'total_breads': 100, 'total_fc_produced': 50000, 'theoretical_yield': 400000,
             'yield_gap': -350000, 'sac_value_fc_used': 200000}
        d.update(kw)
        return d

    def push_sess(self, **kw):
        rec = self.sess(**kw)
        return rec, push(self.a1, 'production.ProductionSession', rec)

    def inv(self, **kw):
        d = {'id': uid(), 'node': self.k1.code, 'team': 'A', 'status': 'PENDING', 'payment_type': 'CASH',
             'order_total': '5000', 'payment_amount': '5000', 'debt_before': '0', 'debt_after': '0'}
        d.update(kw)
        return d


# ---------------------------------------------------------------- Session : garde-fous qui tiennent
class V8SessionGuards(PushBase):
    def test_scope_team_and_ownership_hold(self):
        _, res = self.push_sess(node=self.k2.code)
        self.assertEqual(res[0], 'REJECTED')
        _, res = self.push_sess(team='Z')
        self.assertEqual(res[0], 'REJECTED')
        rec, res = self.push_sess()
        self.assertEqual(res[0], 'ACCEPTED')
        # un autre noeud ne peut ni cloturer la session ni lui ajouter une ligne
        self.assertEqual(push(self.a2, 'production.ProductionSession', {'id': rec['id'], 'is_closed': True})[0], 'REJECTED')
        self.assertEqual(push(self.a2, 'production.ProductionSessionLine',
                              {'session': rec['id'], 'bread_price': self.b3.pk, 'quantity': 3})[0], 'REJECTED')
        self.assertFalse(ProductionSession.objects.get(pk=rec['id']).is_closed)

    def test_non_ascii_date_and_garbage_closed_at_rejected_without_500(self):
        for kw in ({'date': '٢٠٢٦-١١-٢٣'}, {'closed_at': 'garbage', 'is_closed': True}):
            _, res = self.push_sess(**kw)
            self.assertEqual(res[0], 'REJECTED', kw)

    def test_replay_idempotent_and_closed_never_reopens(self):
        rec, _ = self.push_sess()
        self.assertEqual(push(self.a1, 'production.ProductionSession', dict(rec, is_closed=True,
                                                                           closed_at='2026-11-23T20:00:00Z'))[0], 'ACCEPTED')
        self.assertEqual(push(self.a1, 'production.ProductionSession', dict(rec, is_closed=False))[0], 'ACCEPTED')
        self.assertTrue(ProductionSession.objects.get(pk=rec['id']).is_closed)
        self.assertEqual(ProductionSession.objects.filter(pk=rec['id']).count(), 1)


# ---------------------------------------------------------------- BUG-901/902 : session
class V8SessionBounds(PushBase):
    def _assert_refused(self, **kw):
        rec, res = self.push_sess(**kw)
        self.assertEqual(res[0], 'REJECTED', (kw, res))
        self.assertFalse(ProductionSession.objects.filter(pk=rec['id']).exists())

    def test_BUG_901_future_date_refused(self):
        self._assert_refused(date=str(ddate.today() + timedelta(days=30)))

    def test_BUG_902_negative_flour_refused(self):
        self._assert_refused(flour_sacks_used='-3')

    def test_BUG_902_non_ascii_flour_refused(self):
        self._assert_refused(flour_sacks_used=AR)

    def test_BUG_902_flour_above_100000_refused(self):
        self._assert_refused(flour_sacks_used='999999')


# ---------------------------------------------------------------- BUG-903/904/905 : lignes
class V8LinePush(PushBase):
    def setUp(self):
        super().setUp()
        self.rec, _ = self.push_sess()

    def _line(self, **kw):
        d = {'session': self.rec['id'], 'bread_price': self.b3.pk, 'quantity': 10}
        d.update(kw)
        return push(self.a1, 'production.ProductionSessionLine', d)

    def _count(self):
        return ProductionSessionLine.objects.filter(session_id=self.rec['id']).count()

    def test_valid_line_and_hostile_types_hold(self):
        self.assertEqual(self._line()[0], 'ACCEPTED')
        self.assertEqual(self._count(), 1)
        for q in (-5, 2.5, True, 'abc'):
            self.assertEqual(self._line(bread_price=self.b5.pk, quantity=q)[0], 'REJECTED', q)
        self.assertEqual(self._count(), 1)

    def test_BUG_903_huge_quantity_refused(self):
        self.assertEqual(self._line(quantity=10 ** 12)[0], 'REJECTED')
        self.assertEqual(self._count(), 0)

    def test_BUG_903_non_ascii_quantity_refused(self):
        self.assertEqual(self._line(quantity=AR + '0')[0], 'REJECTED')
        self.assertEqual(self._count(), 0)

    def test_BUG_904_null_quantity_not_silently_accepted(self):
        st = self._line(quantity=None)[0]
        # soit REJECTED, soit une ligne creee ; jamais ACCEPTED sans aucune ligne (perte silencieuse)
        self.assertTrue(st == 'REJECTED' or self._count() == 1, (st, self._count()))

    def test_BUG_905_line_on_closed_session_refused(self):
        push(self.a1, 'production.ProductionSession', dict(self.rec, is_closed=True, closed_at='2026-11-23T20:00:00Z'))
        self.assertTrue(ProductionSession.objects.get(pk=self.rec['id']).is_closed)
        self.assertEqual(self._line(source='CARRYOVER')[0], 'REJECTED')
        self.assertEqual(self._count(), 0)


# ---------------------------------------------------------------- BUG-906 : dispositions
class V8DisposalPush(PushBase):
    def setUp(self):
        super().setUp()
        self.rec, _ = self.push_sess()

    def _d(self, **kw):
        d = {'id': uid(), 'session': self.rec['id'], 'bread_price': self.b3.pk, 'disposal_type': 'UNSOLD',
             'quantity': 5, 'unit_price_sold': 0}
        d.update(kw)
        return d, push(self.a1, 'production.BreadDisposal', d)

    def test_guards_hold(self):
        d, res = self._d(quantity=7, disposal_type='SOLD_DISCOUNT', unit_price_sold=225)
        self.assertEqual(res[0], 'ACCEPTED')
        self.assertEqual(BreadDisposal.objects.get(pk=d['id']).total_value, Dc('1575'))
        for kw in ({'disposal_type': 'FOO'}, {'unit_price_sold': -1}, {'quantity': -5}, {'node': self.k2.code}):
            d, res = self._d(**kw)
            self.assertEqual(res[0], 'REJECTED', kw)
            self.assertFalse(BreadDisposal.objects.filter(pk=d['id']).exists())
        d, res = self._d(quantity=-5, disposal_type='REMAINING')  # reste du jour negatif autorise (BUG-158)
        self.assertEqual(res[0], 'ACCEPTED')

    def test_BUG_906_quantity_above_rest_bound_refused(self):
        d, res = self._d(quantity=3_000_000_000)
        self.assertEqual(res[0], 'REJECTED')
        self.assertFalse(BreadDisposal.objects.filter(pk=d['id']).exists())

    def test_BUG_906_blank_disposal_type_refused(self):
        d, res = self._d(disposal_type='')
        self.assertEqual(res[0], 'REJECTED')
        self.assertFalse(BreadDisposal.objects.filter(pk=d['id']).exists())


# ---------------------------------------------------------------- BUG-907 : consommables
class V8MovementPush(PushBase):
    def _m(self, **kw):
        d = {'id': uid(), 'node': self.k1.code, 'consumable_type': 'SALT', 'movement_type': 'ENTRY',
             'quantity': '5', 'unit_price': '10'}
        d.update(kw)
        return d, push(self.a1, 'production.ConsumableMovement', d)

    def _qty(self):
        s = ConsumableStock.objects.filter(node=self.k1, consumable_type='SALT').first()
        return s.quantity if s else Dc('0')

    def test_valid_decimal_movements_and_guards(self):
        self.assertEqual(self._m(quantity='0.25', consumable_type='YEAST')[1][0], 'ACCEPTED')
        self.assertEqual(self._m(quantity='0.33', consumable_type='OIL', unit='litre')[1][0], 'ACCEPTED')
        self.assertEqual(self._m(movement_type='XX')[1][0], 'REJECTED')
        self.assertEqual(self._m(quantity='99999999999')[1][0], 'REJECTED')
        self.assertEqual(self._m(node=self.k2.code)[1][0], 'REJECTED')

    def test_BUG_907_negative_entry_refused_and_stock_untouched(self):
        self._m(quantity='10')
        d, res = self._m(quantity='-5')
        self.assertEqual(res[0], 'REJECTED')
        self.assertEqual(self._qty(), Dc('10'))
        self.assertFalse(ConsumableMovement.objects.filter(pk=d['id']).exists())

    def test_BUG_907_non_ascii_quantity_refused(self):
        d, res = self._m(quantity=AR)
        self.assertEqual(res[0], 'REJECTED')
        self.assertEqual(self._qty(), 0)

    def test_BUG_907_negative_unit_price_refused(self):
        d, res = self._m(unit_price='-3')
        self.assertEqual(res[0], 'REJECTED')

    def test_BUG_907_more_than_three_decimals_refused_not_rounded(self):
        d, res = self._m(quantity='0.3333')
        self.assertEqual(res[0], 'REJECTED')
        self.assertEqual(self._qty(), 0)


# ---------------------------------------------------------------- BUG-908/909 : factures
class V8InvoicePush(PushBase):
    def _assert_refused(self, **kw):
        rec = self.inv(**kw)
        res = push(self.a1, 'sales.Invoice', rec)
        self.assertEqual(res[0], 'REJECTED', (kw, res))
        self.assertFalse(Invoice.objects.filter(pk=rec['id']).exists())

    def test_guards_hold(self):
        rec = self.inv()
        self.assertEqual(push(self.a1, 'sales.Invoice', rec)[0], 'ACCEPTED')
        self.assertEqual(push(self.a2, 'sales.Invoice', dict(rec, status='CANCELLED'))[0], 'REJECTED')
        self.assertEqual(Invoice.objects.get(pk=rec['id']).status, 'PENDING')
        for kw in ({'status': 'XX'}, {'special_code': 'ZZ'}, {'order_total': '-1'}, {'payment_amount': '-1'}):
            self._assert_refused(**kw)

    def test_terminal_invoice_not_modified_by_replay(self):
        for term in ('DELIVERED', 'CANCELLED'):
            rec = self.inv(status=term)
            self.assertEqual(push(self.a1, 'sales.Invoice', rec)[0], 'ACCEPTED')
            for kw in ({'status': 'PENDING'}, {'status': 'DELIVERED' if term == 'CANCELLED' else 'CANCELLED'},
                       {'order_total': '1', 'payment_amount': '1'}):
                push(self.a1, 'sales.Invoice', dict(rec, **kw))
                inv = Invoice.objects.get(pk=rec['id'])
                self.assertEqual((inv.status, inv.order_total, inv.payment_amount), (term, Dc('5000'), Dc('5000')), (term, kw))

    def test_BUG_908_commission_rate_out_of_range_refused(self):
        self._assert_refused(commission_rate='5')
        self._assert_refused(commission_rate='-1')

    def test_BUG_908_future_delivered_at_refused(self):
        self._assert_refused(status='DELIVERED', delivered_at='2099-01-01T00:00:00Z')

    def test_BUG_908_non_ascii_receipt_number_refused(self):
        self._assert_refused(receipt_number=AR * 3)

    def test_BUG_909_new_line_on_delivered_or_cancelled_invoice_refused(self):
        for term in ('DELIVERED', 'CANCELLED'):
            rec = self.inv(status=term)
            push(self.a1, 'sales.Invoice', rec)
            res = push(self.a1, 'sales.InvoiceLine', {'invoice': rec['id'],
                                                      'bread_price': self.b5.pk, 'quantity': 50})
            self.assertEqual(res[0], 'REJECTED', term)
            self.assertEqual(InvoiceLine.objects.filter(invoice_id=rec['id']).count(), 0, term)


# ---------------------------------------------------------------- flux legitime complet
class V8FullFlow(TBase):
    """TBase : K1 demarre a 100 pains MINI (300 FC) et 100 MOYEN (500 FC)."""

    def _close(self, user, d=None):
        r = cl(user).get('/api/production/daily-closure/', {'date': str(d or ddate.today())})
        self.assertEqual(r.status_code, 200, r.content)
        return r.data, {c['bread_price']: c for c in r.data['categories']}

    def test_fournee_stock_facture_livraison_cloture_et_appro_recu(self):
        # fournee : 2 sacs x 200 000 = 400 000 theorique ; 700 x 300 + 400 x 500 = 410 000 declare
        r = cl(self.g1).post(S, {'team': 'A', 'date': str(ddate.today()), 'flour_sacks_used': '2.00',
                                 'lines': [{'bread_price': self.b3.pk, 'quantity': 700},
                                           {'bread_price': self.b5.pk, 'quantity': 400}]}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((self.stock(self.k1, self.b3), self.stock(self.k1, self.b5)), (800, 500))
        s = ProductionSession.objects.get(pk=r.data['id'])
        self.assertEqual((s.total_fc_produced, s.theoretical_yield, s.yield_gap), (410000, 400000, 10000))  # excedent

        # facture : 400 x 300 + 100 x 500 = 170 000, payee cash, livree par le livreur
        client = make_client(self.k1, credit_limit=Dc('9000000'))
        inv = cl(self.fac).post('/api/sales/invoices/', {
            'payment_type': 'CASH', 'payment_amount': '170000', 'client': str(client.pk),
            'lines': [{'bread_price': self.b3.pk, 'quantity': 400}, {'bread_price': self.b5.pk, 'quantity': 100}]},
            format='json')
        self.assertEqual(inv.status_code, 201, inv.content)
        # observation : le stock est decremente des la creation de la facture (sales/views.py), pas a la livraison
        self.assertEqual((self.stock(self.k1, self.b3), self.stock(self.k1, self.b5)), (400, 400))
        self.assertEqual(cl(self.liv).post(f"/api/sales/invoices/{inv.data['id']}/deliver/").status_code, 200)
        self.assertEqual((self.stock(self.k1, self.b3), self.stock(self.k1, self.b5)), (400, 400))
        self.assertEqual(Invoice.objects.get(pk=inv.data['id']).order_total, Dc('170000'))

        a1 = Dc(self._close(self.g1)[0]['totals']['total_du_jour_fc'])
        a2 = Dc(self._close(self.g2)[0]['totals']['total_du_jour_fc'])
        _, rows1 = self._close(self.g1)
        self.assertEqual(rows1[self.b3.pk]['vendu_jour']['quantity'], 400)
        self.assertEqual(rows1[self.b5.pk]['vendu_jour']['quantity'], 100)

        # appro 100 MINI vers K2 : -100 K1, +100 K2, somme du groupe inchangee
        grp = self.group(self.b3)
        t = cl(self.g1).post('/api/production/transfers/send/',
                             {'to_node': self.k2.pk, 'lines': [{'bread_price': self.b3.pk, 'quantity_sent': 100}]}, format='json')
        self.assertEqual(t.status_code, 201, t.content)
        c = cl(self.g2).post(f"/api/production/transfers/{t.data['id']}/confirm_reception/",
                             {'lines': [{'bread_price': self.b3.pk, 'quantity_received': 100}]}, format='json')
        self.assertEqual(c.status_code, 200, c.content)
        self.assertEqual((self.stock(self.k1, self.b3), self.stock(self.k2, self.b3)), (300, 100))
        self.assertEqual(self.group(self.b3), grp)
        d1, rows1 = self._close(self.g1)
        d2, rows2 = self._close(self.g2)
        self.assertEqual(Dc(d1['totals']['total_du_jour_fc']) - a1, Dc('30000'))   # envoye = +100 x 300
        self.assertEqual(Dc(d2['totals']['total_du_jour_fc']) - a2, Dc('-30000'))  # recu retranche
        self.assertEqual(rows1[self.b3.pk]['appro_effectue']['fc'], '30000.00')
        self.assertEqual(rows2[self.b3.pk]['appro_recu']['fc'], '30000.00')
        self.assertEqual(rows2[self.b3.pk]['facture_mvm_interne']['fc'], '-30000.00')
