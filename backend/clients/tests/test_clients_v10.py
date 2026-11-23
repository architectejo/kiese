"""
Ronde b13 (testeur clients/commissions) : verification independante de BUG-951/952/954
(identity_updated_at, push d'identite, pull sans ecrasement, journal des cotisations)
et recherche de defauts voisins. Donnees fictives uniquement.
"""
import os
import tempfile
import unittest
from datetime import timedelta
from decimal import Decimal as D
from unittest import expectedFailure

from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from clients.models import Client, SocialContribution
from clients.tests.test_clients_v2 import CL, CONTRIB, Base, api
from clients.tests.test_clients_v6 import node_api, push
from clients.tests.test_clients_v9 import n_logs
from core.models import ActivityLog
from sync.management.commands.sync_now import apply_pull_response, build_outbound_payload
from sync.models import DebtMovement, SyncConflictLog


class IdentiteDeuxPostes(Base):
    def setUp(self):
        super().setUp()
        self.n1 = node_api(self.k1)
        self.n3 = node_api(self.k3)
        self.own = self.mk(self.k1, 'Own', 'Own', credit_limit=D('50000.00'), current_debt=D('1000.00'))

    def cur(self):
        return Client.objects.get(pk=self.own.pk)

    def rec(self, **kw):
        r = {'id': str(self.own.id), 'node': 'K1', 'node_origin': 'K1', 'first_name': 'Own', 'last_name': 'Own'}
        r.update(kw)
        return r

    def mouvement(self, amount='500'):
        mv = {'id': str(__import__('uuid').uuid4()), 'client': str(self.own.id), 'amount': amount, 'kind': 'ORDER'}
        self.assertEqual(push(self.n3, 'sync.DebtMovement', mv)['status'], 'ACCEPTED')

    def test_rest_pose_identity_updated_at_et_pas_le_mouvement_de_dette(self):
        self.assertIsNone(self.cur().identity_updated_at)
        self.mouvement()
        self.assertIsNone(self.cur().identity_updated_at, "un mouvement de dette ne doit pas marquer l'identite")
        r = api(self.g1).patch(f'{CL}{self.own.pk}/', {'phone': '0811000111'}, format='json')
        self.assertEqual(r.status_code, 200)
        t1 = self.cur().identity_updated_at
        self.assertIsNotNone(t1)
        self.mouvement()
        self.assertEqual(self.cur().identity_updated_at, t1)
        # un PATCH vide ne marque pas
        api(self.g1).patch(f'{CL}{self.own.pk}/', {}, format='json')
        self.assertEqual(self.cur().identity_updated_at, t1)

    def test_edition_poste_apres_mouvements_intercales_acceptee(self):
        Client.objects.filter(pk=self.own.pk).update(identity_updated_at=timezone.now() - timedelta(hours=1))
        self.mouvement('300')
        sent = (timezone.now() - timedelta(minutes=30)).isoformat()
        self.mouvement('200')
        r = push(self.n1, 'clients.Client', self.rec(phone='0899', credit_limit='65000', updated_at=sent))
        self.assertEqual(r['status'], 'ACCEPTED')
        c = self.cur()
        self.assertEqual((c.phone, c.credit_limit, c.current_debt), ('0899', D('65000.00'), D('1500.00')))

    def test_edition_plus_ancienne_que_la_version_d_identite_ignoree(self):
        Client.objects.filter(pk=self.own.pk).update(identity_updated_at=timezone.now(), phone='CLOUD')
        old = (timezone.now() - timedelta(hours=2)).isoformat()
        r = push(self.n1, 'clients.Client', self.rec(phone='POSTE', updated_at=old))
        self.assertEqual(r['status'], 'ACCEPTED')
        self.assertEqual(self.cur().phone, 'CLOUD')

    @expectedFailure
    def test_BUG_969_push_d_identite_obsolete_ignore_sans_aucune_trace(self):
        # conflit simultane : le Cloud a une edition plus recente ; le push du poste est ignore et renvoie
        # ACCEPTED (le poste le marque is_synced) sans SyncConflictLog ni notification : perte silencieuse.
        Client.objects.filter(pk=self.own.pk).update(identity_updated_at=timezone.now(), phone='CLOUD')
        old = (timezone.now() - timedelta(hours=2)).isoformat()
        before = SyncConflictLog.objects.count()
        push(self.n1, 'clients.Client', self.rec(phone='POSTE', plafond='x', updated_at=old))
        self.assertEqual(self.cur().phone, 'CLOUD')
        self.assertGreater(SyncConflictLog.objects.count(), before,
                           "edition du poste ecartee sans conflit journalise")

    def test_identity_NULL_sans_mouvement_garde_sur_updated_at(self):
        old = (self.cur().updated_at - timedelta(hours=1)).isoformat()
        push(self.n1, 'clients.Client', self.rec(phone='OLD', updated_at=old))
        self.assertEqual(self.cur().phone, '')
        new = (self.cur().updated_at + timedelta(hours=1)).isoformat()
        push(self.n1, 'clients.Client', self.rec(phone='NEW', updated_at=new))
        self.assertEqual(self.cur().phone, 'NEW')

    def test_identity_NULL_avec_mouvement_le_proprietaire_fait_autorite(self):
        # cas documente en risque : un push date d'avant le dernier mouvement est applique.
        DebtMovement.objects.create(client=self.own, amount=D('10'), kind='ORDER', node_origin='K3')
        old = (timezone.now() - timedelta(days=30)).isoformat()
        r = push(self.n1, 'clients.Client', self.rec(phone='AUTORITE', updated_at=old))
        self.assertEqual(r['status'], 'ACCEPTED')
        self.assertEqual(self.cur().phone, 'AUTORITE')
        self.assertIsNotNone(self.cur().identity_updated_at)

    def test_push_applique_pose_identity_updated_at_et_ne_touche_pas_la_dette(self):
        self.mouvement('250')
        push(self.n1, 'clients.Client', self.rec(credit_limit='1000'))
        c = self.cur()
        self.assertEqual(c.current_debt, D('1250.00'))
        self.assertEqual(c.category, 'RISK')
        self.assertIsNotNone(c.identity_updated_at)

    @expectedFailure
    def test_BUG_970_le_lot_sortant_ne_porte_aucune_version_d_identite(self):
        # build_outbound_payload n'envoie ni updated_at ni identity_updated_at : la garde du push
        # (sent_at) est morte en flux reel, le dernier push gagne meme s'il date d'avant une edition du Cloud.
        api(self.g1).patch(f'{CL}{self.own.pk}/', {'credit_limit': '60000'}, format='json')
        snapshot = [c for c in build_outbound_payload('K1')['records']['clients.Client']
                    if c['id'] == str(self.own.id)][0]
        # la direction (siege) edite ensuite le plafond : edition plus recente
        api(self.direction).patch(f'{CL}{self.own.pk}/', {'credit_limit': '90000'}, format='json')
        push(self.n1, 'clients.Client', snapshot)
        self.assertEqual(self.cur().credit_limit, D('90000.00'),
                         "le push du poste (60 000, plus ancien) ecrase l'edition plus recente du siege")


class PullSansEcrasement(Base):
    def setUp(self):
        super().setUp()
        self.own = self.mk(self.k1, 'Own', 'Own', credit_limit=D('50000.00'))

    def pull(self, **kw):
        row = {'id': str(self.own.id), 'code': self.own.code, 'current_debt': '0.00',
               'credit_limit': '50000.00', 'category': 'NORMAL', 'first_name': 'Own', 'last_name': 'Own'}
        row.update(kw)
        apply_pull_response({'clients': [row]})
        return Client.objects.get(pk=self.own.pk)

    def edit_local(self, **body):
        r = api(self.g1).patch(f'{CL}{self.own.pk}/', body, format='json')
        self.assertEqual(r.status_code, 200, r.data)

    def test_edition_locale_non_poussee_survit_au_pull_et_la_dette_cloud_s_applique(self):
        self.edit_local(credit_limit='20000', first_name='Local', phone='0822')
        c = self.pull(current_debt='25000.00', credit_limit='50000.00', first_name='Cloud', phone='X',
                      address='AdCloud')
        self.assertEqual((c.credit_limit, c.first_name, c.phone, c.address),
                         (D('20000.00'), 'Local', '0822', ''))
        self.assertEqual(c.current_debt, D('25000.00'))
        self.assertEqual(c.category, 'RISK', "categorie recalculee sur le plafond local")

    def test_apres_push_accepte_le_pull_reapplique_le_cloud(self):
        self.edit_local(first_name='Local')
        Client.objects.filter(pk=self.own.pk).update(is_synced=True)
        c = self.pull(first_name='Cloud', credit_limit='70000.00')
        self.assertEqual((c.first_name, c.credit_limit), ('Cloud', D('70000.00')))

    def test_client_cree_localement_sans_edition_recoit_l_identite_du_cloud(self):
        Client.objects.filter(pk=self.own.pk).update(is_synced=False, identity_updated_at=None)
        c = self.pull(first_name='Cloud')
        self.assertEqual(c.first_name, 'Cloud')

    def test_pull_ne_marque_pas_l_edition_locale_comme_synchronisee(self):
        self.edit_local(first_name='Local')
        self.pull(first_name='Cloud')
        c = Client.objects.get(pk=self.own.pk)
        self.assertFalse(c.is_synced)
        payload = build_outbound_payload('K1')['records']['clients.Client']
        self.assertEqual([x['first_name'] for x in payload if x['id'] == str(self.own.id)], ['Local'])

    def test_mouvement_local_non_pousse_prime_toujours_sur_la_dette(self):
        self.edit_local(first_name='Local')
        DebtMovement.objects.create(client=self.own, amount=D('100'), kind='ORDER', node_origin='K1',
                                    is_synced=False)
        c = self.pull(current_debt='0.00')
        self.assertEqual(c.current_debt, D('0.00'))
        self.assertEqual(c.first_name, 'Local')



class Journal_cotisations(Base):
    def setUp(self):
        super().setUp()
        self.c1 = self.mk(self.k1, 'Alice', 'Zola')
        self.contrib = SocialContribution.objects.create(client=self.c1, node=self.k1, month=4, year=2026,
                                                         amount=D('2000'))

    def last(self):
        return ActivityLog.objects.filter(action__icontains='Cotisation').order_by('-created_at').first()

    def test_patch_is_paid_journalise_une_fois_en_francais_avec_noeud(self):
        b = n_logs()
        r = api(self.g1).patch(f'{CONTRIB}{self.contrib.pk}/', {'is_paid': True}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(n_logs(), b + 1)
        log = self.last()
        self.assertIn('payée', log.action)
        self.assertEqual(log.node_origin, 'K1')

    def test_patch_sans_changement_de_is_paid_ne_journalise_pas(self):
        b = n_logs()
        api(self.g1).patch(f'{CONTRIB}{self.contrib.pk}/', {'is_paid': False}, format='json')
        api(self.g1).patch(f'{CONTRIB}{self.contrib.pk}/', {'amount': '2500'}, format='json')
        self.assertEqual(n_logs(), b)

    def test_annulation_du_paiement_journalisee(self):
        SocialContribution.objects.filter(pk=self.contrib.pk).update(is_paid=True, paid_at=timezone.now())
        b = n_logs()
        api(self.g1).patch(f'{CONTRIB}{self.contrib.pk}/', {'is_paid': False}, format='json')
        self.assertEqual(n_logs(), b + 1)
        self.assertIn('annulée', self.last().action)

    def test_suppression_journalisee(self):
        SocialContribution.objects.filter(pk=self.contrib.pk).update(is_paid=True)
        b = n_logs()
        r = api(self.g1).delete(f'{CONTRIB}{self.contrib.pk}/')
        self.assertEqual(r.status_code, 204)
        self.assertEqual(n_logs(), b + 1)
        self.assertEqual(self.last().action, 'Suppression Cotisation Sociale')
        self.assertFalse(SocialContribution.objects.filter(pk=self.contrib.pk).exists())

    def test_gerant_k3_ne_peut_ni_modifier_ni_supprimer_et_rien_n_est_journalise(self):
        b = n_logs()
        self.assertEqual(api(self.g3).patch(f'{CONTRIB}{self.contrib.pk}/', {'is_paid': True},
                                            format='json').status_code, 404)
        self.assertEqual(api(self.g3).delete(f'{CONTRIB}{self.contrib.pk}/').status_code, 404)
        self.assertEqual(n_logs(), b)
        self.assertTrue(SocialContribution.objects.filter(pk=self.contrib.pk).exists())

    def test_facturier_ne_supprime_pas_de_cotisation(self):
        r = api(self.f1).delete(f'{CONTRIB}{self.contrib.pk}/')
        self.assertIn(r.status_code, (403, 404))
        self.assertTrue(SocialContribution.objects.filter(pk=self.contrib.pk).exists())


class Migration0011(unittest.TestCase):
    """Base SQLite jetable : clients existants a 0010, puis application de 0011."""
    ALIAS = 'clients_0011'

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.sqlite3')
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(self.db_path) and os.remove(self.db_path))
        connections.databases[self.ALIAS] = {
            'ENGINE': 'django.db.backends.sqlite3', 'NAME': self.db_path, 'ATOMIC_REQUESTS': False,
            'TIME_ZONE': None, 'CONN_HEALTH_CHECKS': False, 'CONN_MAX_AGE': 0, 'AUTOCOMMIT': True, 'OPTIONS': {},
        }
        self.addCleanup(connections[self.ALIAS].close)
        self.addCleanup(lambda: connections.databases.pop(self.ALIAS, None))
        self.executor = MigrationExecutor(connections[self.ALIAS])

    def test_clients_existants_conserves_identity_NULL_et_dette_intacte(self):
        core_leaf = next(n for n in self.executor.loader.graph.leaf_nodes() if n[0] == 'core')
        self.executor.migrate([core_leaf, ('clients', '0010_bug289')])
        old = self.executor.loader.project_state([('clients', '0010_bug289')]).apps
        Node, OldClient = old.get_model('core', 'Node'), old.get_model('clients', 'Client')
        node = Node.objects.using(self.ALIAS).create(code='ZZ', name='Noeud fictif')
        ids = []
        for i in range(3):
            c = OldClient.objects.using(self.ALIAS).create(
                code=f'ZZ-{i:04d}', first_name=f'Prenom{i}', last_name=f'Nom{i}', node=node, node_origin='ZZ',
                current_debt=D('1234.50') * i, credit_limit=D('50000.00'), phone=f'081000000{i}')
            ids.append(c.pk)
        self.executor.loader.build_graph()
        self.executor.migrate([('clients', '0011_client_identity_updated_at')])
        new = self.executor.loader.project_state([('clients', '0011_client_identity_updated_at')]).apps
        NewClient = new.get_model('clients', 'Client')
        rows = list(NewClient.objects.using(self.ALIAS).order_by('code'))
        self.assertEqual(len(rows), 3)
        for i, c in enumerate(rows):
            self.assertIsNone(c.identity_updated_at)
            self.assertEqual((c.current_debt, c.credit_limit, c.phone, c.first_name),
                             (D('1234.50') * i, D('50000.00'), f'081000000{i}', f'Prenom{i}'))
        self.assertEqual({c.pk for c in rows}, set(ids))
        NewClient.objects.using(self.ALIAS).filter(pk=ids[0]).update(identity_updated_at=timezone.now())
        self.assertIsNotNone(NewClient.objects.using(self.ALIAS).get(pk=ids[0]).identity_updated_at)
