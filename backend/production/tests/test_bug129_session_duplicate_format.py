"""
BUG-129 : le refus de doublon de session (course sur unique_together) doit
renvoyer `{"detail": "..."}` et non un tableau JSON nu. Le doublon « normal »
s'ajoute à la session existante (BUG-142) et n'est plus une erreur.
"""
from decimal import Decimal
from unittest import mock

from django.db import IntegrityError
from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price
from core.workday import work_date_for
from production.models import ProductionSession


class Bug129DuplicateSessionFormatTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1', sac_value_fc=Decimal('200000'))
        self.gerant = make_user('GERANT', node=self.node)
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.api = APIClient()
        self.api.force_authenticate(self.gerant)
        self.today = work_date_for(self.node)
        self.payload = {'team': 'A', 'date': str(self.today), 'flour_sacks_used': '1.00'}

    def test_second_declaration_adds_to_session_no_error(self):
        r1 = self.api.post('/api/production/sessions/', self.payload, format='json')
        r2 = self.api.post('/api/production/sessions/', self.payload, format='json')
        self.assertEqual(r1.status_code, 201, r1.data)
        self.assertEqual(r2.status_code, 201, r2.data)
        self.assertEqual(r1.data['id'], r2.data['id'])

    def test_integrity_error_race_returns_detail_dict(self):
        with mock.patch.object(ProductionSession.objects, 'create', side_effect=IntegrityError('unique')):
            r = self.api.post('/api/production/sessions/', self.payload, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIsInstance(r.data, dict)
        self.assertIn('Une session existe déjà', r.data['detail'])
