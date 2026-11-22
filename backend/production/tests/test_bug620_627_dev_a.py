"""BUG-620/621/622/623/624/627 : complements de non-regression (Dev A). Donnees fictives."""
from production.models import BreadTransfer, _adjust_bread_stock
from production.tests.test_production_v2_a3 import Base, cl


class TransfersDevA(Base):
    def setUp(self):
        _adjust_bread_stock(self.k1, self.b3, produced=100)
        _adjust_bread_stock(self.k1, self.b5, produced=100)

    def request(self, lines):
        r = cl(self.g2).post('/api/production/transfers/', {'from_node': self.k1.pk, 'lines': lines}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return r.data['id']

    def respond(self, t, lines):
        return cl(self.g1).post(f'/api/production/transfers/{t}/respond_to_request/',
                                {'approved': True, 'lines': lines}, format='json')

    def confirm(self, t, lines):
        return cl(self.g2).post(f'/api/production/transfers/{t}/confirm_reception/', {'lines': lines}, format='json')

    def test_620_partial_confirm_is_400_and_no_stock_effect(self):
        t = self.request([{'bread_price': self.b3.pk, 'quantity_sent': 10}, {'bread_price': self.b5.pk, 'quantity_sent': 7}])
        self.respond(t, [{'bread_price': self.b3.pk, 'quantity_sent': 10}, {'bread_price': self.b5.pk, 'quantity_sent': 7}])
        r = self.confirm(t, [{'bread_price': self.b3.pk, 'quantity_received': 10}])
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(BreadTransfer.objects.get(pk=t).transfer_status, 'RESPONDED')
        self.assertEqual(self.stock(self.k2, self.b3), 0)
        # toutes les lignes (0 accepte pour « rien recu ») -> litige, somme du groupe nulle
        r = self.confirm(t, [{'bread_price': self.b3.pk, 'quantity_received': 10}, {'bread_price': self.b5.pk, 'quantity_received': 0}])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['transfer_status'], 'DISPUTED')
        self.assertEqual(self.group(self.b3), 100)

    def test_621_ambiguous_booleans_refused(self):
        t = self.request([{'bread_price': self.b3.pk, 'quantity_sent': 10}])
        for bad in ('0', 'non', 1, 0, [], 'oui'):
            r = cl(self.g1).post(f'/api/production/transfers/{t}/respond_to_request/', {'approved': bad}, format='json')
            self.assertEqual(r.status_code, 400, bad)
        self.assertEqual(BreadTransfer.objects.get(pk=t).transfer_status, 'PENDING')
        r = cl(self.g1).post(f'/api/production/transfers/{t}/respond_to_request/', {'approved': 'false'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['transfer_status'], 'CANCELLED')

    def test_624_requester_can_still_edit_and_delete(self):
        t = self.request([{'bread_price': self.b3.pk, 'quantity_sent': 10}])
        self.assertEqual(cl(self.g2).patch(f'/api/production/transfers/{t}/', {'notes': 'ok'}, format='json').status_code, 200)
        self.assertEqual(cl(self.g2).delete(f'/api/production/transfers/{t}/').status_code, 204)

    def test_612_627_float_unicode_siege_refused(self):
        from core.models import Node
        siege = Node.objects.get(code='SIEGE')
        for bad in (1.5, '१', siege.pk):
            r = cl(self.g2).post('/api/production/transfers/', {
                'from_node': bad, 'lines': [{'bread_price': self.b3.pk, 'quantity_sent': 1}]}, format='json')
            self.assertEqual(r.status_code, 400, bad)
