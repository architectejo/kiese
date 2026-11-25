"""
Q-019 (blocage des ventes TOUT DE SUITE a l'heure de cloture) et Q-020 (direction ET comptable
valident la cloture / le versement ; gerant, facturier, livreur non). Donnees fictives.
"""
import datetime as dt

from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user
from production.tests.test_restes_journee_cloture_auto_a import D, _at, _now
from treasury.closure_lock import closure_status, sales_blocked_for
from treasury.models import CashClosure


def api(user):
    c = APIClient()
    c.raise_request_exception = False
    c.force_authenticate(user)
    return c


class Q019BlocageImmediatTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1', rotation=True)
        self.node.block_sales_after_closure = True
        self.node.handover_time = dt.time(12, 0)
        self.node.save()

    def _validate_ended_day(self, instant):
        ended = closure_status(self.node, instant)['closure_date']
        CashClosure.objects.create(node=self.node, date=dt.date.fromisoformat(ended), is_validated=True,
                                   node_origin='K1')

    def test_pas_de_delai_de_grace_a_12h00_pile(self):
        # Journee precedente validee : la veille est en regle, rien ne bloque avant 12:00.
        self._validate_ended_day(_at(D, 11, 59))
        self.assertFalse(sales_blocked_for(self.node, _at(D, 11, 59)))
        # A 12:00 pile la journee qui s'acheve doit etre validee : blocage IMMEDIAT (Q-019),
        # sans attendre les 30 minutes de la cloture automatique, et il persiste ensuite.
        self.assertTrue(sales_blocked_for(self.node, _at(D, 12, 0)))
        self.assertTrue(sales_blocked_for(self.node, _at(D, 12, 1)))

    def test_apres_validation_direction_debloque(self):
        self.assertTrue(sales_blocked_for(self.node, _at(D, 12, 1)))
        self._validate_ended_day(_at(D, 12, 1))
        self.assertFalse(closure_status(self.node, _at(D, 12, 1))['blocked'])

    def test_delai_de_30_min_de_la_cloture_automatique_inchange(self):
        from production.views import SHIFT_END_GRACE_MINUTES
        self.assertEqual(SHIFT_END_GRACE_MINUTES, 30)  # Q-053 en attente : ne pas toucher


class Q020ValidationDirectionEtComptableTests(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1', rotation=True)
        self.k2 = make_node(code='K2', rotation=True)
        self.users = {
            'DIRECTION': make_user('DIRECTION', node=None),
            'ADMIN': make_user('ADMIN', node=None),
            'COMPTABLE': make_user('COMPTABLE', node=None),
            'GERANT': make_user('GERANT', node=self.k1, team='A'),
            'FACTURIER': make_user('FACTURIER', node=self.k1, team='A'),
            'LIVREUR': make_user('LIVREUR', node=self.k1, team='A'),
            'GERANT_K2': make_user('GERANT', node=self.k2, team='A'),
        }
        self._n = 0

    def closure(self, node=None):
        self._n += 1
        node = node or self.k1
        return CashClosure.objects.create(node=node, date=D - dt.timedelta(days=self._n), node_origin=node.code)

    def test_direction_admin_comptable_valident(self):
        for role in ('DIRECTION', 'ADMIN', 'COMPTABLE'):
            c = self.closure()
            r = api(self.users[role]).post(f'/api/treasury/closures/{c.pk}/validate/', {}, format='json')
            self.assertEqual(r.status_code, 200, (role, r.data))
            c.refresh_from_db()
            self.assertTrue(c.is_validated, role)

    def test_gerant_facturier_livreur_ne_valident_pas(self):
        c = self.closure()
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            r = api(self.users[role]).post(f'/api/treasury/closures/{c.pk}/validate/', {}, format='json')
            self.assertEqual(r.status_code, 403, role)
        c.refresh_from_db()
        self.assertFalse(c.is_validated)

    def test_gerant_d_une_autre_boulangerie_ne_voit_ni_ne_valide(self):
        c = self.closure()
        r = api(self.users['GERANT_K2']).post(f'/api/treasury/closures/{c.pk}/validate/', {}, format='json')
        self.assertIn(r.status_code, (403, 404))
        c.refresh_from_db()
        self.assertFalse(c.is_validated)
        listing = api(self.users['GERANT_K2']).get('/api/treasury/closures/').json()
        self.assertEqual(listing['results'] if isinstance(listing, dict) else listing, [])

    def test_comptable_et_direction_infirment_gerant_non(self):
        for role, expected in (('COMPTABLE', 200), ('DIRECTION', 200), ('GERANT', 403)):
            c = self.closure()
            r = api(self.users[role]).post(f'/api/treasury/closures/{c.pk}/reject/', {'reason': 'x'}, format='json')
            self.assertEqual(r.status_code, expected, role)

    def test_validation_par_comptable_debloque_les_ventes(self):
        self.k1.block_sales_after_closure = True
        self.k1.save()
        now = _at(D, 12, 30)
        self.assertTrue(sales_blocked_for(self.k1, now))
        ended = dt.date.fromisoformat(closure_status(self.k1, now)['closure_date'])
        c = CashClosure.objects.create(node=self.k1, date=ended, node_origin='K1')
        with _now(12, 30):
            r = api(self.users['COMPTABLE']).post(f'/api/treasury/closures/{c.pk}/validate/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(sales_blocked_for(self.k1, now))
