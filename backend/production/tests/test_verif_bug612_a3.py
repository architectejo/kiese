"""Verification testeur-production (Dev A, a3) de BUG-612 (+ revalidation BUG-540/541 : ne pas
toucher le ticket, seulement les cas voisins) : identifiants booleens / flottants / geants /
`1_0` sur transferts, envoi direct, rapprochement. Donnees fictives uniquement."""
from unittest import expectedFailure

from core.models import Node
from production.tests.test_production_v2_a3 import Base, cl
from production.models import _adjust_bread_stock

BAD_IDS = [True, False, 1.5, 10 ** 30, -1, 0, '1_0', '१', [1], {'a': 1}, '9' * 40]


class Bug612Verif(Base):
    def setUp(self):
        _adjust_bread_stock(self.k1, self.b3, produced=100)

    def _request(self):
        r = cl(self.g2).post('/api/production/transfers/', {'from_node': self.k1.pk, 'lines': [
            {'bread_price': self.b3.pk, 'quantity_sent': 10}]}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return r.data['id']

    def test_request_from_node_bad_ids(self):
        for bad in [b for b in BAD_IDS if b not in (1.5, '१')]:  # 1.5 : voir BUG-612 (rouvert) ci-dessous
            r = cl(self.g2).post('/api/production/transfers/', {
                'from_node': bad, 'lines': [{'bread_price': self.b3.pk, 'quantity_sent': 1}]}, format='json')
            self.assertEqual(r.status_code, 400, bad)

    def test_request_line_bread_price_bad_ids(self):
        for bad in BAD_IDS:
            r = cl(self.g2).post('/api/production/transfers/', {
                'from_node': self.k1.pk, 'lines': [{'bread_price': bad, 'quantity_sent': 1}]}, format='json')
            self.assertEqual(r.status_code, 400, bad)

    def test_respond_and_confirm_line_bad_ids_no_stock_effect(self):
        t = self._request()
        for bad in BAD_IDS:
            r = cl(self.g1).post(f'/api/production/transfers/{t}/respond_to_request/', {
                'approved': True, 'lines': [{'bread_price': bad, 'quantity_sent': 10}]}, format='json')
            self.assertEqual(r.status_code, 400, bad)
        self.assertEqual(self.stock(self.k1, self.b3), 100)
        r = cl(self.g1).post(f'/api/production/transfers/{t}/respond_to_request/', {
            'approved': True, 'lines': [{'bread_price': str(self.b3.pk), 'quantity_sent': 10}]}, format='json')
        self.assertEqual(r.status_code, 200, r.content)  # id en chaine de chiffres : accepte
        self.assertEqual(self.stock(self.k1, self.b3), 90)
        for bad in BAD_IDS:
            r = cl(self.g2).post(f'/api/production/transfers/{t}/confirm_reception/', {
                'lines': [{'bread_price': bad, 'quantity_received': 10}]}, format='json')
            self.assertEqual(r.status_code, 400, bad)
        self.assertEqual(self.stock(self.k2, self.b3), 0)

    def test_send_direct_destination_and_line_bad_ids(self):
        for bad in BAD_IDS:
            r = cl(self.g1).post('/api/production/transfers/send/', {
                'to_node': bad, 'lines': [{'bread_price': self.b3.pk, 'quantity_sent': 1}]}, format='json')
            self.assertEqual(r.status_code, 400, bad)
            r = cl(self.g1).post('/api/production/transfers/send/', {
                'to_node': self.k2.pk, 'lines': [{'bread_price': bad, 'quantity_sent': 1}]}, format='json')
            self.assertEqual(r.status_code, 400, bad)
        self.assertEqual(self.stock(self.k1, self.b3), 100)
        r = cl(self.g1).post('/api/production/transfers/send/', {
            'to_node': ' q2 ', 'lines': [{'bread_price': self.b3.pk, 'quantity_sent': 1}]}, format='json')
        self.assertEqual(r.status_code, 201, r.content)  # code insensible a la casse / aux espaces

    def test_siege_and_filters_with_bad_node_param(self):
        for bad in ('True', '1.5', '1_0', '9' * 40, '-1', 'ZZZ'):
            for url in ('/api/production/sessions/reconciliation/', '/api/production/movements/flour_history/'):
                r = cl(self.dir).get(url, {'node': bad})
                self.assertEqual(r.status_code, 400, (url, bad))
        r = cl(self.dir).get('/api/production/sessions/reconciliation/', {'node': 'q1'})
        self.assertEqual(r.status_code, 200)
        # gerant : `?node=` ignore (BUG-505), jamais d'erreur ni de fuite
        r = cl(self.g1).get('/api/production/sessions/reconciliation/', {'node': 'ZZZ'})
        self.assertEqual(r.status_code, 200)

    def test_dispatch_bad_node_ids(self):
        for bad in BAD_IDS:
            r = cl(self.dir).post('/api/production/consumables/dispatch/', {
                'consumable_type': 'YEAST', 'allocations': [{'node': bad, 'quantity': '1'}]}, format='json')
            self.assertEqual(r.status_code, 400, bad)

    def test_BUG_612_reopened_request_from_node_float_is_refused(self):
        for bad in (1.5, '१'):  # flottant et chiffre Unicode (int('१') == 1)
            r = cl(self.g2).post('/api/production/transfers/', {
                'from_node': bad, 'lines': [{'bread_price': self.b3.pk, 'quantity_sent': 1}]}, format='json')
            self.assertEqual(r.status_code, 400, (bad, r.content))

    def test_BUG_627_request_to_siege_is_refused(self):
        siege = Node.objects.get(code='SIEGE')
        r = cl(self.g2).post('/api/production/transfers/', {
            'from_node': siege.pk, 'lines': [{'bread_price': self.b3.pk, 'quantity_sent': 1}]}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_BUG_627_request_to_inactive_bakery_is_refused(self):
        k = Node.objects.create(code='QI', name='Fermee', is_active=False)
        r = cl(self.g2).post('/api/production/transfers/', {
            'from_node': k.pk, 'lines': [{'bread_price': self.b3.pk, 'quantity_sent': 1}]}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
