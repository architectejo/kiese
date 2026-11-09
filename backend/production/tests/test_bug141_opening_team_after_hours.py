"""
Vérification indépendante BUG-141 (testeur-production, 2026-11-09).

Ne relit pas simplement le test déjà écrit par dev-backend : reproduit le
scénario RÉEL signalé par le client en direct sur K1, à 21h00, soit APRÈS la
fermeture des DEUX créneaux configurés (06:00-11:30 pour A, 14:30-20:00 pour
B). remarque.md l.398 exige que la boîte modale de confirmation du stock de
départ cible toujours l'équipe du PREMIER créneau de la journée (ici A),
quelle que soit l'heure à laquelle le gérant/facturier se connecte — y compris
pour rattraper une confirmation oubliée le soir, bien après la fermeture.

Avant BUG-141, `opening_team` était dérivé de `Node.active_team_at()` (« qui
travaille EN CE MOMENT ? »), qui renvoie `None` à 21h puisqu'aucun créneau
n'est actif à cette heure — la boîte modale ne présélectionnait alors plus
aucune équipe. Ce test reproduit exactement cette plage horaire pour prouver
que la régression ne réapparaît pas : la réponse de l'API doit porter
`opening_team == 'A'`, pas `None` et pas un sélecteur neutre.
"""
import datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone as dj_timezone
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price
from production.models import _adjust_bread_stock


TODAY = '2026-11-09'


class Bug141AfterHoursOpeningTeamTests(TestCase):
    """Scénario réel signalé par le client : connexion à 21h, hors des deux
    créneaux K1 (A 06:00-11:30, B 14:30-20:00)."""

    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.node.team_a_start_time = datetime.time(6, 0)
        self.node.team_a_end_time = datetime.time(11, 30)
        self.node.team_b_start_time = datetime.time(14, 30)
        self.node.team_b_end_time = datetime.time(20, 0)
        self.node.save()
        self.bp500 = make_bread_price(category='MOYEN', label='Pain 500 FC', unit_price=500)
        _adjust_bread_stock(self.node, self.bp500, produced=100)

    def _frozen_localtime(self, hour, minute=0):
        fixed = dj_timezone.make_aware(
            datetime.datetime.combine(dj_timezone.localdate(), datetime.time(hour, minute)),
        )
        return lambda *args, **kwargs: fixed

    def test_connection_at_21h_after_both_slots_still_preselects_opening_team_a(self):
        """Preuve du correctif : à 21h (après fermeture de A et de B),
        `active_team_at()` est bien `None` (ce qui causait le bug), mais la
        réponse de l'API expose quand même `opening_team == 'A'` — pas
        `None`, pas un sélecteur neutre côté frontend."""
        gerant = make_user(role='GERANT', node=self.node)
        api = APIClient()
        api.force_authenticate(gerant)

        with patch.object(dj_timezone, 'localtime', side_effect=self._frozen_localtime(21)):
            # Contrôle : la méthode "équipe active maintenant" ne voit
            # effectivement aucune équipe active à cette heure (preuve
            # indépendante de la cause du bug signalé par le client).
            self.assertIsNone(self.node.active_team_at())

            resp = api.get(f'/api/production/opening-confirmation/?date={TODAY}')
            self.assertEqual(resp.status_code, 200, resp.data)
            self.assertEqual(resp.data['opening_team'], 'A')
            self.assertTrue(resp.data['needs_confirmation'])

        # Confirmation de A (équipe d'ouverture) à 21h : doit être acceptée
        # et suffire à lever `needs_confirmation`, exactement comme si elle
        # avait eu lieu le matin au créneau réel.
        with patch.object(dj_timezone, 'localtime', side_effect=self._frozen_localtime(21)):
            post_resp = api.post('/api/production/opening-confirmation/', {
                'team': 'A', 'date': TODAY,
                'lines': [{'bread_price': self.bp500.pk, 'qty': 100}],
            }, format='json')
            self.assertEqual(post_resp.status_code, 200, post_resp.data)

            after = api.get(f'/api/production/opening-confirmation/?date={TODAY}')
            self.assertFalse(after.data['needs_confirmation'])
            self.assertEqual(after.data['opening_team'], 'A')

    def test_facturier_also_sees_opening_team_a_after_hours_at_22h(self):
        """Même garantie pour un FACTURIER (remarque.md l.398 : « le
        facturier peut aussi faire ça »), à une heure encore plus tardive
        (22h), pour couvrir une plage distincte de celle déjà testée par
        dev-backend (21h) et éviter un faux-positif lié à une valeur d'heure
        particulière."""
        facturier = make_user(role='FACTURIER', node=self.node, team='B')
        api = APIClient()
        api.force_authenticate(facturier)

        with patch.object(dj_timezone, 'localtime', side_effect=self._frozen_localtime(22)):
            self.assertIsNone(self.node.active_team_at())
            resp = api.get(f'/api/production/opening-confirmation/?date={TODAY}')
            self.assertEqual(resp.status_code, 200, resp.data)
            self.assertEqual(resp.data['opening_team'], 'A')
