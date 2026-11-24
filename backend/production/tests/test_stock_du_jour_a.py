"""
BUG-1070 (remarque.md l.510) : le stock de départ confirmé apparait dans « Stock Pains du Jour »
(`qty_opening`). BUG-1071 (l.514) : « Envoyés » = transferts émis seulement
(`qty_transfer_sent`, distinct de `qty_sent` qui mélange aussi les ventes livrées),
« Reçu » = transferts reçus (`qty_transfer_received`). Valeurs fictives.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price
from core.workday import work_date_for
from production.models import BreadStock, _adjust_bread_stock


def cl(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


class _Base(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.k2 = make_node(code='K2')
        self.k3 = make_node(code='K3')
        self.g1 = make_user('GERANT', node=self.k1)
        self.g2 = make_user('GERANT', node=self.k2)
        self.g3 = make_user('GERANT', node=self.k3)
        self.f1 = make_user('FACTURIER', node=self.k1)
        self.l1 = make_user('LIVREUR', node=self.k1)
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.bp2 = make_bread_price('GRAND', 'Pain 1000 FC', 1000)
        _adjust_bread_stock(self.k1, self.bp, produced=100)
        _adjust_bread_stock(self.k1, self.bp2, produced=50)

    def rows(self, user):
        r = cl(user).get('/api/production/bread-stocks/')
        self.assertEqual(r.status_code, 200, r.content)
        data = r.data['results'] if isinstance(r.data, dict) and 'results' in r.data else r.data
        return {(row['node'], row['bread_price']): row for row in data}

    def send(self, qty, bp=None, to=None):
        r = cl(self.g1).post('/api/production/transfers/send/', {
            'to_node': (to or self.k2).pk,
            'lines': [{'bread_price': (bp or self.bp).pk, 'quantity_sent': qty}],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return r.data['id']

    def confirm(self, user, tid, qty, bp=None):
        r = cl(user).post(f'/api/production/transfers/{tid}/confirm_reception/', {
            'lines': [{'bread_price': (bp or self.bp).pk, 'quantity_received': qty}],
        }, format='json')
        self.assertEqual(r.status_code, 200, r.content)


class OpeningTests(_Base):
    def test_stock_de_depart_confirme_visible(self):
        before = self.rows(self.g1)[(self.k1.pk, self.bp.pk)]
        self.assertIsNone(before['qty_opening'])
        r = cl(self.g1).post('/api/production/opening-confirmation/', {
            'team': 'A', 'lines': [{'bread_price': self.bp.pk, 'qty': 40}],
        }, format='json')
        self.assertEqual(r.status_code, 201 if r.status_code == 201 else 200, r.content)
        row = self.rows(self.g1)[(self.k1.pk, self.bp.pk)]
        self.assertEqual(row['qty_opening'], 40)
        self.assertEqual(row['qty_available'], 40)  # le disponible reflète le stock de départ confirmé
        # by-date (aujourd'hui) expose le même champ
        d = cl(self.g1).get('/api/production/bread-stocks/by-date/').data
        cat = next(c for c in d['categories'] if c['bread_price'] == self.bp.pk)
        self.assertEqual(cat['qty_opening'], 40)

    def test_isolation_boulangerie(self):
        cl(self.g1).post('/api/production/opening-confirmation/', {
            'team': 'A', 'lines': [{'bread_price': self.bp.pk, 'qty': 40}],
        }, format='json')
        for key, row in self.rows(self.g2).items():
            self.assertEqual(row['node'], self.k2.pk)
            self.assertIsNone(row['qty_opening'])


class TransferColumnsTests(_Base):
    def test_envoi_en_attente_puis_confirme_somme_nulle(self):
        tid = self.send(30)
        k1 = self.rows(self.g1)[(self.k1.pk, self.bp.pk)]
        self.assertEqual((k1['qty_transfer_sent'], k1['qty_transfer_received']), (30, 0))
        # en attente : rien de reçu côté réceptrice
        self.assertEqual(self.rows(self.g2).get((self.k2.pk, self.bp.pk), {'qty_transfer_received': 0})['qty_transfer_received'], 0)
        self.confirm(self.g2, tid, 30)
        k2 = self.rows(self.g2)[(self.k2.pk, self.bp.pk)]
        self.assertEqual((k2['qty_transfer_sent'], k2['qty_transfer_received']), (0, 30))
        k1 = self.rows(self.g1)[(self.k1.pk, self.bp.pk)]
        self.assertEqual(k1['qty_transfer_sent'] - k2['qty_transfer_received'], 0)
        total = sum(BreadStock.objects.get(node=n, bread_price=self.bp).qty_available for n in (self.k1, self.k2, self.k3) if BreadStock.objects.filter(node=n, bread_price=self.bp).exists())
        self.assertEqual(total, 100)  # somme nulle du groupe

    def test_envoye_ignore_les_ventes_livrees(self):
        # une sortie de vente alimente qty_sent (legacy) mais pas qty_transfer_sent
        _adjust_bread_stock(self.k1, self.bp, sent=25)
        row = self.rows(self.g1)[(self.k1.pk, self.bp.pk)]
        self.assertEqual(row['qty_sent'], 25)
        self.assertEqual(row['qty_transfer_sent'], 0)
        self.send(10)
        row = self.rows(self.g1)[(self.k1.pk, self.bp.pk)]
        self.assertEqual((row['qty_sent'], row['qty_transfer_sent']), (35, 10))

    def test_par_categorie(self):
        self.send(10, self.bp)
        self.send(5, self.bp2)
        rows = self.rows(self.g1)
        self.assertEqual(rows[(self.k1.pk, self.bp.pk)]['qty_transfer_sent'], 10)
        self.assertEqual(rows[(self.k1.pk, self.bp2.pk)]['qty_transfer_sent'], 5)

    def test_isolation_tiers_et_roles(self):
        self.send(10)
        for user in (self.g3,):
            for row in self.rows(user).values():
                self.assertEqual(row['qty_transfer_sent'], 0)
        for user in (self.f1, self.l1):  # lecture pour facturier / livreur de la boulangerie émettrice
            r = cl(user).get('/api/production/bread-stocks/')
            self.assertEqual(r.status_code, 200)
        self.assertEqual(self.rows(self.f1)[(self.k1.pk, self.bp.pk)]['qty_transfer_sent'], 10)
