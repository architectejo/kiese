"""
BUG-1300 : l'agent de la boulangerie qui interroge `shift-end-status` est connecte ; il ne doit
pas declencher l'alerte « Cloture sans personne connectee » (Q-021). Un appel siege (DIRECTION
avec ?node=) dans les memes conditions declenche toujours l'alerte. Donnees fictives.
"""
from datetime import timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import ActivityLog, Node, SystemNotification, User
from core.testing import make_user
from production.services import UNATTENDED_CLOSURE_TITLE
from production.tests.test_restes_journee_cloture_auto_a import D, SHIFT, _at, _now
from treasury.models import CashClosure


def _alerts(code):
    return SystemNotification.objects.filter(
        title__startswith=UNATTENDED_CLOSURE_TITLE, node_origin=code,
    )


class AppelantPresentPasDAlerteTests(TestCase):
    def setUp(self):
        self.k1 = Node.objects.create(code='K1', name='Boulangerie fictive K1', team_rotation_enabled=True)
        self.facturier = make_user('FACTURIER', node=self.k1, team='A')
        self.dirn = make_user('DIRECTION', node=None)
        # Connecte depuis la veille (JWT encore valide) : last_login anterieur a 12:00.
        User.objects.filter(pk=self.facturier.pk).update(last_login=_at(D - timedelta(days=1), 8, 0))
        ActivityLog.objects.all().delete()
        # Cloture de la veille presente mais non validee.
        CashClosure.objects.create(node=self.k1, date=D - timedelta(days=1), is_validated=False, node_origin='K1')

    def _get(self, user, params=None):
        c = APIClient()
        c.force_authenticate(user)
        return c.get(SHIFT, params or {})

    def test_facturier_de_la_boulangerie_compte_comme_present(self):
        with _now(12, 30):
            r = self._get(self.facturier)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(_alerts('K1').count(), 0)

    def test_direction_avec_node_declenche_toujours_l_alerte(self):
        with _now(12, 30):
            r = self._get(self.dirn, {'node': 'K1'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(_alerts('K1').count(), 1)

    def test_agent_d_une_autre_boulangerie_ne_compte_pas(self):
        from production.services import notify_direction_if_unattended_closure
        k2 = Node.objects.create(code='K2', name='Boulangerie fictive K2', team_rotation_enabled=True)
        autre = make_user('FACTURIER', node=k2, team='A')
        with _now(12, 30):
            self.assertIsNotNone(notify_direction_if_unattended_closure(self.k1, present_user=autre))
        self.assertEqual(_alerts('K1').count(), 1)
