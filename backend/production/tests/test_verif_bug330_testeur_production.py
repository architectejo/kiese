"""
Vérification indépendante (testeur-production, 2026-11-21) de BUG-330 :
`GET /api/production/opening-confirmation/` ne propose jamais de quantité
négative (règle « plus de négatifs », BUG-317), le BreadStock réel n'est pas
modifié. Données fictives (`core.testing`).
"""
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price
from production.models import (
    BreadStock, DailyBreadStockSnapshot, DailyOpeningConfirmation,
)

OPENING = '/api/production/opening-confirmation/'
D1 = date(2026, 10, 14)
D2 = date(2026, 10, 15)


def _api(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


class Bug330Tests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1')
        self.other = make_node(code='K2')
        self.g = _api(make_user('GERANT', node=self.node))
        self.f = _api(make_user('FACTURIER', node=self.node))
        self.bp = make_bread_price('V330T_500', 'Pain 500 V330T', 500)
        self.bp2 = make_bread_price('V330T_200', 'Pain 200 V330T', 200)
        self.bp3 = make_bread_price('V330T_100', 'Pain 100 V330T', 100)

    # -- helpers
    def rotation(self, on=True):
        self.node.team_rotation_enabled = on
        self.node.save()

    def stock(self, bp, qty, node=None):
        return BreadStock.objects.create(node=node or self.node, bread_price=bp, qty_adjusted=qty)

    def snap(self, bp, d, qty, team='A', node=None):
        return DailyBreadStockSnapshot.objects.create(
            node=node or self.node, bread_price=bp, date=d, team=team, qty_at_close=qty)

    def props(self, api=None, d=D2):
        r = (api or self.g).get(OPENING, {'date': str(d)})
        self.assertEqual(r.status_code, 200, r.data)
        return {c['bread_price']: c['qty_proposed'] for c in r.data['categories']}

    def real(self, bp, node=None):
        return BreadStock.objects.get(node=node or self.node, bread_price=bp).qty_available

    def post(self, lines, team='A', api=None):
        return (api or self.f).post(
            OPENING, {'team': team, 'date': str(D2), 'lines': lines}, format='json')

    # -- sans instantané : négatif / zéro / positif, hors rotation puis rotation
    def _matrix_sans_snapshot(self):
        self.stock(self.bp, -20)
        self.stock(self.bp2, 0)
        self.stock(self.bp3, 15)
        p = self.props()
        self.assertEqual(p[self.bp.pk], 0)
        self.assertEqual(p[self.bp2.pk], 0)
        self.assertEqual(p[self.bp3.pk], 15)
        # stock réel inchangé après le GET
        self.assertEqual(self.real(self.bp), -20)
        self.assertEqual(self.real(self.bp2), 0)
        self.assertEqual(self.real(self.bp3), 15)

    def test_hors_rotation_sans_snapshot_negatif_zero_positif(self):
        self.assertFalse(self.node.team_rotation_enabled)
        self._matrix_sans_snapshot()

    def test_rotation_sans_snapshot_negatif_zero_positif(self):
        self.rotation()
        self._matrix_sans_snapshot()

    # -- avec instantané
    def _matrix_avec_snapshot(self):
        self.stock(self.bp, -500)  # le stock courant est ignoré au profit de l'instantané
        self.snap(self.bp, D1, -20)
        self.snap(self.bp2, D1, 0)
        self.snap(self.bp3, D1, 9)
        p = self.props()
        self.assertEqual(p[self.bp.pk], 0)
        self.assertEqual(p[self.bp2.pk], 0)
        self.assertEqual(p[self.bp3.pk], 9)
        self.assertEqual(self.real(self.bp), -500)
        # l'instantané n'est pas réécrit
        self.assertEqual(
            DailyBreadStockSnapshot.objects.get(node=self.node, bread_price=self.bp, date=D1).qty_at_close, -20)

    def test_hors_rotation_avec_snapshot_negatif_zero_positif(self):
        self._matrix_avec_snapshot()

    def test_rotation_avec_snapshot_negatif_zero_positif(self):
        self.rotation()
        self._matrix_avec_snapshot()

    def test_instantane_positif_avec_stock_courant_negatif_et_inversement(self):
        for rot in (False, True):
            with self.subTest(rotation=rot):
                self.rotation(rot)
                BreadStock.objects.all().delete()
                DailyBreadStockSnapshot.objects.all().delete()
                self.stock(self.bp, -40)
                self.snap(self.bp, D1, 25)
                self.stock(self.bp2, 40)
                self.snap(self.bp2, D1, -5)
                p = self.props()
                self.assertEqual(p[self.bp.pk], 25)
                self.assertEqual(p[self.bp2.pk], 0)

    def test_plusieurs_categories_aucune_negative(self):
        for rot in (False, True):
            with self.subTest(rotation=rot):
                self.rotation(rot)
                BreadStock.objects.all().delete()
                self.stock(self.bp, -1)
                self.stock(self.bp2, -1000)
                self.stock(self.bp3, 3)
                p = self.props()
                self.assertTrue(all(v >= 0 for v in p.values()), p)
                self.assertEqual(p[self.bp3.pk], 3)

    def test_sans_aucun_stock_ni_instantane(self):
        p = self.props()
        self.assertTrue(all(v == 0 for v in p.values()))

    def test_get_n_ecrit_rien(self):
        self.stock(self.bp, -20)
        self.snap(self.bp, D1, -3)
        self.props()
        self.props()
        self.assertEqual(self.real(self.bp), -20)
        self.assertFalse(DailyOpeningConfirmation.objects.exists())
        self.assertEqual(BreadStock.objects.count(), 1)

    def test_type_entier_de_la_proposition(self):
        self.stock(self.bp, -20)
        v = self.props()[self.bp.pk]
        self.assertIsInstance(v, int)

    # -- POST
    def test_post_negatif_refuse(self):
        self.stock(self.bp, -20)
        r = self.post([{'bread_price': self.bp.pk, 'qty': -20}])
        self.assertEqual(r.status_code, 400, r.data)
        self.assertFalse(DailyOpeningConfirmation.objects.exists())
        self.assertEqual(self.real(self.bp), -20)

    def test_post_proposition_bornee_acceptee_et_ramene_le_stock_a_zero(self):
        self.stock(self.bp, -20)
        q = self.props()[self.bp.pk]
        self.assertEqual(q, 0)
        r = self.post([{'bread_price': self.bp.pk, 'qty': q}])
        self.assertIn(r.status_code, (200, 201), r.data)
        self.assertEqual(self.real(self.bp), 0)

    def test_post_proposition_bornee_acceptee_en_rotation(self):
        self.rotation()
        self.snap(self.bp, D1, -8)
        q = self.props()[self.bp.pk]
        self.assertEqual(q, 0)
        # En rotation : désignation de l'équipe requise, puis journée courante seule.
        a = self.g.post('/api/production/team-assignment/', {'team': 'A'}, format='json')
        self.assertIn(a.status_code, (200, 201), a.data)
        r = self.f.post(OPENING, {'team': 'A', 'lines': [{'bread_price': self.bp.pk, 'qty': q}]},
                        format='json')
        self.assertIn(r.status_code, (200, 201), r.data)

    # -- isolation
    def test_isolation_entre_noeuds(self):
        self.stock(self.bp, -20)
        self.stock(self.bp, 50, node=self.other)
        self.snap(self.bp2, D1, 77, node=self.other)
        p = self.props()
        self.assertEqual(p[self.bp.pk], 0)
        self.assertEqual(p[self.bp2.pk], 0)
        g2 = _api(make_user('GERANT', node=self.other))
        p2 = self.props(api=g2)
        self.assertEqual(p2[self.bp.pk], 50)
        self.assertEqual(p2[self.bp2.pk], 77)
        self.assertEqual(self.real(self.bp), -20)
        self.assertEqual(self.real(self.bp, node=self.other), 50)
