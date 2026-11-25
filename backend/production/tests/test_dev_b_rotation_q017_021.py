"""
Q-021 (reponse client 2026-11-24) : si personne n'est connecte a l'heure de cloture, la
direction ET le comptable recoivent UNE notification par boulangerie et par periode,
declenchee par la commande `auto_close_sessions` et par `shift-end-status`. Donnees fictives.
"""
from datetime import date, time, timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import ActivityLog, Node, SystemNotification, User
from core.testing import make_node, make_user
from production.services import UNATTENDED_CLOSURE_TITLE, notify_direction_if_unattended_closure
from production.tests.test_restes_journee_cloture_auto_a import D, SHIFT, _at, _now
from treasury.models import CashClosure


def _alerts(code=None):
    qs = SystemNotification.objects.filter(title__startswith=UNATTENDED_CLOSURE_TITLE)
    return qs.filter(node_origin=code) if code else qs


class UnattendedClosureAlertTests(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1', rotation=True)
        self.k2 = make_node(code='K2', rotation=True)
        self.gerant = make_user('GERANT', node=self.k1, team='A')
        self.dirn = make_user('DIRECTION', node=None)
        self.compta = make_user('COMPTABLE', node=None)
        self.k2_gerant = make_user('GERANT', node=self.k2, team='A')

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def test_avant_l_heure_pas_d_alerte_pour_la_cloture_du_jour(self):
        with _now(11, 59):
            notify_direction_if_unattended_closure(self.k1)
        # seule la cloture PRECEDENTE (veille 12:00) peut etre signalee, jamais celle de 12:00 du jour
        self.assertEqual(_alerts().filter(title__contains=f'{D} 12:00').count(), 0)

    def test_a_l_heure_personne_connecte_une_notification(self):
        with _now(12, 0):
            n = notify_direction_if_unattended_closure(self.k1)
        self.assertIsNotNone(n)
        self.assertEqual(n.node_origin, 'K1')
        self.assertEqual(n.severity, 'WARNING')
        self.assertEqual(_alerts('K1').count(), 1)
        self.assertTrue(ActivityLog.objects.filter(action__startswith='Alerte clôture', node_origin='K1').exists())

    def test_endpoint_shift_end_status_declenche_sans_doublon(self):
        with _now(12, 5):
            r1 = self.api(self.gerant).get(SHIFT)
            r2 = self.api(self.gerant).get(SHIFT)
            r3 = self.api(self.dirn).get(SHIFT, {'node': 'K1'})
        self.assertEqual((r1.status_code, r2.status_code, r3.status_code), (200, 200, 200))
        self.assertEqual(_alerts('K1').count(), 1)

    def test_commande_declenche_sans_doublon_et_partage_avec_l_endpoint(self):
        with _now(12, 10):
            call_command('auto_close_sessions', stdout=StringIO())
            call_command('auto_close_sessions', stdout=StringIO())
            self.api(self.gerant).get(SHIFT)
        self.assertEqual(_alerts('K1').count(), 1)
        self.assertEqual(_alerts('K2').count(), 1)  # une par boulangerie

    def test_direction_et_comptable_la_voient_pas_les_autres_boulangeries(self):
        with _now(12, 10):
            notify_direction_if_unattended_closure(self.k1)
        for user in (self.dirn, self.compta):
            data = self.api(user).get('/api/core/notifications/').json()
            rows = data['results'] if isinstance(data, dict) else data
            self.assertTrue(any(n['title'].startswith(UNATTENDED_CLOSURE_TITLE) for n in rows), user.role)
        data = self.api(self.k2_gerant).get('/api/core/notifications/').json()
        rows = data['results'] if isinstance(data, dict) else data
        self.assertFalse(any(n['title'].startswith(UNATTENDED_CLOSURE_TITLE) for n in rows))

    def test_quelqu_un_actif_apres_l_heure_pas_de_notification(self):
        with _now(12, 1):
            ActivityLog.objects.create(user=self.gerant, action='x', node_origin='K1')
        with _now(12, 5):
            self.assertIsNone(notify_direction_if_unattended_closure(self.k1))
        self.assertEqual(_alerts().count(), 0)

    def test_connexion_apres_l_heure_pas_de_notification(self):
        User.objects.filter(pk=self.gerant.pk).update(last_login=_at(D, 12, 2))
        with _now(12, 5):
            self.assertIsNone(notify_direction_if_unattended_closure(self.k1))

    def test_activite_avant_l_heure_ne_compte_pas(self):
        with _now(11, 0):
            ActivityLog.objects.create(user=self.gerant, action='x', node_origin='K1')
        with _now(12, 5):
            self.assertIsNotNone(notify_direction_if_unattended_closure(self.k1))

    def test_cloture_deja_validee_pas_de_notification(self):
        from treasury.closure_lock import closure_status
        ended = closure_status(self.k1, _at(D, 12, 5))['closure_date']
        CashClosure.objects.create(node=self.k1, date=date.fromisoformat(ended), is_validated=True, node_origin='K1')
        with _now(12, 5):
            self.assertIsNone(notify_direction_if_unattended_closure(self.k1))

    def test_lue_ne_recree_pas_et_periode_suivante_en_cree_une_autre(self):
        with _now(12, 5):
            notify_direction_if_unattended_closure(self.k1)
        SystemNotification.objects.update(is_read=True)
        with _now(13, 0):
            self.assertIsNone(notify_direction_if_unattended_closure(self.k1))
        self.assertEqual(_alerts('K1').filter(title__contains=f'{D} 12:00').count(), 1)
        with _now(12, 5, D + timedelta(days=1)):
            self.assertIsNotNone(notify_direction_if_unattended_closure(self.k1))
        self.assertEqual(_alerts('K1').filter(title__contains=f'{D + timedelta(days=1)} 12:00').count(), 1)

    def test_heure_personnalisee_respectee(self):
        self.k1.handover_time = time(18, 0)
        self.k1.save()
        with _now(17, 0):
            notify_direction_if_unattended_closure(self.k1)
        self.assertEqual(_alerts('K1').filter(title__contains=f'{D} 18:00').count(), 0)
        with _now(18, 1):
            self.assertIsNotNone(notify_direction_if_unattended_closure(self.k1))
        self.assertEqual(_alerts('K1').filter(title__contains=f'{D} 18:00').count(), 1)

    def test_hors_rotation_et_siege_exclus(self):
        self.k1.team_rotation_enabled = False
        self.k1.save()
        siege = Node.objects.get(code='SIEGE')
        Node.objects.filter(pk=siege.pk).update(team_rotation_enabled=True)
        siege.refresh_from_db()
        with _now(12, 5):
            self.assertIsNone(notify_direction_if_unattended_closure(self.k1))
            self.assertIsNone(notify_direction_if_unattended_closure(siege))
