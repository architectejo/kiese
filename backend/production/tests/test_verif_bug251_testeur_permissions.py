"""Verification BUG-251 (testeur-permissions, 2026-11-20b). Donnees fictives."""
from decimal import Decimal as Dc

from core.tests.test_permissions_regression_2026_11_19 import Base, cl
from production.models import ConsumableStock

U = '/api/production/stocks/'


class Bug251(Base):
    def setUp(self):
        self.s1 = ConsumableStock.objects.create(node=self.k1, consumable_type='SEL', quantity=Dc('5'),
                                                 node_origin='P1')
        self.s2 = ConsumableStock.objects.create(node=self.k2, consumable_type='SEL', quantity=Dc('7'),
                                                 node_origin='P2')

    def test_facturier_livreur_read_only(self):
        for role in ('FACTURIER', 'LIVREUR'):
            c = cl(self.u[role])
            self.assertEqual(c.get(U).status_code, 200)
            self.assertEqual(c.get(f'{U}{self.s1.pk}/').status_code, 200)
            self.assertEqual(c.patch(f'{U}{self.s1.pk}/', {'quantity': '99'}, format='json').status_code, 403)
            self.assertEqual(c.put(f'{U}{self.s1.pk}/', {'quantity': '99', 'node': str(self.k1.pk),
                             'consumable_type': 'SEL'}, format='json').status_code, 403)
            self.assertEqual(c.delete(f'{U}{self.s1.pk}/').status_code, 403)
            self.assertEqual(c.post(U, {'node': str(self.k1.pk), 'consumable_type': 'LEV'},
                                    format='json').status_code, 403)
        self.s1.refresh_from_db()
        self.assertEqual(self.s1.quantity, Dc('5'))

    def test_anonymous(self):
        self.assertEqual(cl().get(U).status_code, 401)
        self.assertEqual(cl().patch(f'{U}{self.s1.pk}/', {}, format='json').status_code, 401)

    def test_gerant_quantity_readonly_and_node_forced(self):
        g = cl(self.u['GERANT'])
        g.patch(f'{U}{self.s1.pk}/', {'quantity': '99'}, format='json')
        g.put(f'{U}{self.s1.pk}/', {'quantity': '99', 'node': str(self.k2.pk), 'consumable_type': 'SEL'},
              format='json')
        self.s1.refresh_from_db()
        self.assertEqual((self.s1.quantity, self.s1.node_id), (Dc('5'), self.k1.pk))
        r = g.post(U, {'node': str(self.k2.pk), 'consumable_type': 'LEV', 'quantity': '50'}, format='json')
        self.assertIn(r.status_code, (201, 400), r.content)
        self.assertFalse(ConsumableStock.objects.filter(node=self.k2, consumable_type='LEV').exists())
        if r.status_code == 201:
            n = ConsumableStock.objects.get(pk=r.data['id'])
            self.assertEqual((n.node_id, n.quantity), (self.k1.pk, Dc('0')))

    def test_cross_node_detail(self):
        g = cl(self.u['GERANT'])
        self.assertEqual(g.get(f'{U}{self.s2.pk}/').status_code, 404)
        self.assertEqual(g.delete(f'{U}{self.s2.pk}/').status_code, 404)
        self.assertEqual(g.patch(f'{U}{self.s2.pk}/', {'quantity': '1'}, format='json').status_code, 404)
        self.assertEqual(cl(self.u['FACTURIER']).get(f'{U}{self.s2.pk}/').status_code, 404)
        self.s2.refresh_from_db()
        self.assertEqual(self.s2.quantity, Dc('7'))
