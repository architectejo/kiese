"""
B-3 (Q-025 / BUG-507 / BUG-1106 / BUG-1203) : le livreur voit les clients des autres boulangeries
seulement en ligne ; creation de client par le livreur dans SA boulangerie. Donnees FICTIVES.
"""
import time
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from clients.models import Client
from clients.tests.test_clients_v2 import Base, api, results
from core.models import Node
from sync import connectivity, desktop_client

CL = '/api/clients/clients/'
LOCAL = dict(KIESE_CLOUD_URL='https://etskiese.example')


def ids(resp):
    return {str(c['id']) for c in results(resp)}


class Etat(Base):
    def setUp(self):
        super().setUp()
        self.k2 = Node.objects.get_or_create(code='K2', defaults={'name': 'K2 COQ'})[0]
        self.c1 = self.mk(self.k1, 'Aline', 'Mavungu')
        self.c2 = self.mk(self.k2, 'Bruno', 'Kasongo')
        saved = dict(desktop_client._STATE)
        self.addCleanup(lambda: (desktop_client._STATE.clear(), desktop_client._STATE.update(saved)))
        desktop_client._STATE.update(last_push_at=None, last_pull_at=None)

    def go_online(self, minutes_ago=1):
        desktop_client._STATE['last_pull_at'] = time.time() - minutes_ago * 60


class Helper(Etat):
    def test_cloud_toujours_en_ligne(self):
        self.assertTrue(connectivity.node_is_online(self.k1))
        self.assertTrue(connectivity.node_is_online(None))

    @override_settings(**LOCAL)
    def test_poste_local_jamais_synchronise_hors_ligne(self):
        self.assertFalse(connectivity.node_is_online(self.k1))

    @override_settings(**LOCAL)
    def test_poste_local_recent_en_ligne(self):
        self.go_online(2)
        self.assertTrue(connectivity.node_is_online(self.k1))

    @override_settings(**LOCAL)
    def test_poste_local_perime_hors_ligne(self):
        self.go_online(16)
        self.assertFalse(connectivity.node_is_online(self.k1))

    @override_settings(**LOCAL, KIESE_ONLINE_WINDOW_MINUTES='30')
    def test_fenetre_configurable(self):
        self.go_online(20)
        self.assertTrue(connectivity.node_is_online(self.k1))

    @override_settings(**LOCAL, KIESE_ONLINE_WINDOW_MINUTES='abc')
    def test_fenetre_invalide_defaut_15(self):
        self.go_online(10)
        self.assertTrue(connectivity.node_is_online(self.k1))
        self.go_online(20)
        self.assertFalse(connectivity.node_is_online(self.k1))

    @override_settings(**LOCAL)
    def test_node_last_sync_recent_compte(self):
        Node.objects.filter(pk=self.k1.pk).update(last_sync=timezone.now() - timedelta(minutes=3))
        self.k1.refresh_from_db()
        self.assertTrue(connectivity.node_is_online(self.k1))
        Node.objects.filter(pk=self.k1.pk).update(last_sync=timezone.now() - timedelta(hours=2))
        self.k1.refresh_from_db()
        self.assertFalse(connectivity.node_is_online(self.k1))


class Liste(Etat):
    def test_cloud_livreur_voit_k2(self):
        r = api(self.l1).get(CL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ids(r), {str(self.c1.pk), str(self.c2.pk)})

    @override_settings(**LOCAL)
    def test_livreur_hors_ligne_ne_voit_pas_k2(self):
        r = api(self.l1).get(CL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ids(r), {str(self.c1.pk)})

    @override_settings(**LOCAL)
    def test_livreur_en_ligne_voit_k2(self):
        self.go_online()
        self.assertEqual(ids(api(self.l1).get(CL)), {str(self.c1.pk), str(self.c2.pk)})

    @override_settings(**LOCAL)
    def test_recherche_code_et_nom(self):
        for term, other in ((self.c2.code, True), ('kasongo', True), ('mavungu', False)):
            desktop_client._STATE['last_pull_at'] = None
            off = ids(api(self.l1).get(CL, {'search': term}))
            self.go_online()
            on = ids(api(self.l1).get(CL, {'search': term}))
            if other:
                self.assertEqual(off, set(), term)
                self.assertEqual(on, {str(self.c2.pk)}, term)
            else:
                self.assertEqual(off, on, term)

    @override_settings(**LOCAL)
    def test_detail_hors_ligne_404_pas_500(self):
        r = api(self.l1).get(f'{CL}{self.c2.pk}/')
        self.assertEqual(r.status_code, 404)

    @override_settings(**LOCAL)
    def test_facturier_inchange_hors_ligne(self):
        self.assertEqual(ids(api(self.f1).get(CL)), {str(self.c1.pk), str(self.c2.pk)})

    @override_settings(**LOCAL)
    def test_gerant_direction_comptable_inchanges(self):
        self.assertEqual(ids(api(self.g1).get(CL)), {str(self.c1.pk)})
        for u in (self.direction, self.comptable):
            self.assertEqual(ids(api(u).get(CL)), {str(self.c1.pk), str(self.c2.pk)})
        self.go_online()
        self.assertEqual(ids(api(self.g1).get(CL)), {str(self.c1.pk)})

    def test_aucun_500_etat_corrompu(self):
        desktop_client._STATE['last_pull_at'] = 'x'
        with override_settings(**LOCAL):
            self.assertEqual(api(self.l1).get(CL).status_code, 200)


class Creation(Etat):
    def post(self, user, **extra):
        return api(user).post(CL, {'first_name': 'Nadia', 'last_name': 'Tsimba', 'phone': '0810000000', **extra},
                              format='json')

    def test_livreur_cree_dans_sa_boulangerie(self):
        r = self.post(self.l1)
        self.assertEqual(r.status_code, 201, getattr(r, 'data', None))
        self.assertEqual(Client.objects.get(pk=r.data['id']).node, self.k1)

    def test_livreur_ne_peut_pas_creer_dans_une_autre(self):
        r = self.post(self.l1, node=self.k2.pk)
        self.assertIn(r.status_code, (201, 400, 403))
        self.assertFalse(Client.objects.filter(node=self.k2, last_name='Tsimba').exists())

    def test_livreur_creation_ne_fixe_pas_plafond_ni_taux(self):
        r = self.post(self.l1, credit_limit='900000', commission_rate='0.30')
        self.assertEqual(r.status_code, 201)
        c = Client.objects.get(pk=r.data['id'])
        self.assertEqual(str(c.credit_limit), '50000.00')
        self.assertEqual(str(c.commission_rate), '0.25')

    def test_autres_actions_restent_fermees_au_livreur(self):
        u = api(self.l1)
        self.assertEqual(u.patch(f'{CL}{self.c1.pk}/', {'phone': '1'}, format='json').status_code, 403)
        self.assertEqual(u.delete(f'{CL}{self.c1.pk}/').status_code, 403)
        for action in ('bulk_move', 'bulk_delete', 'import_excel'):
            self.assertEqual(u.post(f'{CL}{action}/', {}, format='json').status_code, 403, action)
