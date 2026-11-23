"""Testeur-production (cycle 18 / a17) : verification independante de BUG-1000 a 1003 (d48) sur le banc
K1/K2/K3 + cloud (A16Base) : pic historique des marqueurs (migration sync 0005), marqueur descendu borne,
borne d'envoi 0 tant que PENDING, date de comptage `updated_at` partagee. Balayage push vs REST.
Donnees fictives. Les `@expectedFailure` referencent leur ticket.
"""
import json
import uuid
from datetime import date as ddate, timedelta
from unittest import expectedFailure

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from core.models import Node
from production.models import BreadTransfer, ConsumableMovement, ConsumableStock
from production.tests.test_verif_a4_testeur_production import cl
from production.tests.test_verif_production_a16_v16 import A16Base, OOB
from production.tests.test_verif_production_a8_v8 import PushBase, push, uid
from sync.management.commands.sync_now import apply_pull_response
from sync.models import SyncConflictLog, TransferMirror

SITES = ('cloud', 'K1', 'K2', 'K3')


class A17Base(A16Base):
    def age_all(self, tid, days=1):
        """Le transfert est « date d'hier » partout (cloud + 3 postes) : la suite se passe le lendemain."""
        at = timezone.now() - timedelta(days=days)
        for s in SITES:
            self.go(s)
            BreadTransfer.objects.filter(pk=tid).update(updated_at=at)

    def appro(self, name, day):
        self.go(name)
        r = cl(self.ger[name]).get('/api/production/daily-closure/', {'date': str(day)})
        self.assertEqual(r.status_code, 200, r.content)
        row = {c['bread_price']: c for c in r.data['categories']}[self.b3.pk]
        return row['appro_effectue']['quantity'], row['appro_recu']['quantity']

    def day_sums(self, day):
        eff = rec = 0
        for n in ('K1', 'K2', 'K3'):
            e, r = self.appro(n, day)
            eff += e
            rec += r
        return eff, rec

    def assert_group_days(self, expected_today, expected_yesterday=(0, 0)):
        today = ddate.today()
        self.assertEqual(self.day_sums(today), expected_today)
        self.assertEqual(self.day_sums(today - timedelta(days=1)), expected_yesterday)
        self.assertEqual(self.total(self.b3), 100)


# --------------------------------------------------------------------------- BUG-1003 : jour J / J+1
class A17Dates(A17Base):
    def test_1003_trois_postes_envoi_hier_reception_aujourd_hui(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        self.age_all(tid)
        self.confirm_at('K2', tid, [self.RV(self.b3, 100)])
        self.cycles(3)
        today = ddate.today()
        k2_today = self.appro('K2', today)[1]
        k1_today, k1_yest = self.appro('K1', today)[0], self.appro('K1', today - timedelta(days=1))[0]
        self.assertEqual((k2_today, k1_today, k1_yest), (100, 100, 0))
        self.assertEqual(self.appro('K3', today), (0, 0))
        self.assert_group_days((100, 100))

    def test_1003_envoi_direct_meme_jour_tout_aujourd_hui(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        self.confirm_at('K2', tid, [self.RV(self.b3, 100)])
        self.cycles(3)
        self.assert_group_days((100, 100))

    def test_1003_demande_reponse_hier_reception_aujourd_hui(self):
        tid = self.request_from('K2', [self.L(self.b3, 100)], 'K1')
        self.cycles(2)
        self.respond_at('K1', tid, [self.L(self.b3, 100)])
        self.cycles(3)
        self.age_all(tid)
        self.confirm_at('K2', tid, [self.RV(self.b3, 100)])
        self.cycles(3)
        self.assert_group_days((100, 100))

    def test_1003_demande_reponse_du_siege_hier_reception_aujourd_hui(self):
        tid = self.request_from('K2', [self.L(self.b3, 100)], 'K1')
        self.cycles(2)
        self.post_rest('cloud', self.dir, tid, 'respond_to_request',
                       {'approved': True, 'lines': [self.L(self.b3, 100)]})
        self.cycles(3)
        self.age_all(tid)
        self.confirm_at('K2', tid, [self.RV(self.b3, 100)])
        self.cycles(3)
        self.assert_group_days((100, 100))

    def test_1003_litige_hier_resolution_siege_received_aujourd_hui(self):
        tid, _ = self.to_dispute_direct()
        self.cycles(3)
        self.age_all(tid)
        self.resolve(tid, 'ALIGN_ON_RECEIVED')
        self.cycles(4)
        today = ddate.today()
        self.assertEqual(self.day_sums(today), (98, 98))
        self.assertEqual(self.day_sums(today - timedelta(days=1)), (0, 0))
        self.assertEqual(self.total(self.b3), 100)

    def test_1003_litige_hier_resolution_siege_sent_aujourd_hui(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        self.confirm_at('K2', tid, [self.RV(self.b3, 105)])
        self.cycles(3)
        self.age_all(tid)
        self.resolve(tid, 'ALIGN_ON_SENT')
        self.cycles(4)
        self.assert_group_days((100, 100))

    def test_1003_litige_hier_recomptage_k2_aujourd_hui(self):
        tid, _ = self.to_dispute_direct()
        self.cycles(3)
        self.age_all(tid)
        self.assertEqual(self.confirm_at('K2', tid, [self.RV(self.b3, 100)]), 'CONFIRMED')
        self.cycles(4)
        self.assert_group_days((100, 100))

    def test_1003_annulation_aucun_appro_nulle_part_somme_stock_intacte(self):
        tid = self.request_from('K2', [self.L(self.b3, 100)], 'K1')
        self.cycles(2)
        self.age_all(tid)
        self.post_rest('K1', self.g1, tid, 'respond_to_request', {'approved': False})
        self.cycles(4)
        self.assert_group_days((0, 0))
        self.assertEqual(self.view('K2', tid)[0], 'CANCELLED')

    def test_1003_deux_transferts_croises_sur_deux_jours(self):
        t1 = self.send_from('K1', [self.L(self.b3, 40)], 'K2')
        self.cycles(2)
        self.age_all(t1)
        self.confirm_at('K2', t1, [self.RV(self.b3, 40)])
        self.cycles(2)
        t2 = self.send_from('K2', [self.L(self.b3, 10)], 'K1')
        self.cycles(2)
        self.confirm_at('K1', t2, [self.RV(self.b3, 10)])
        self.cycles(4)
        self.assert_group_days((50, 50))

    def test_1003_updated_at_identique_sur_les_trois_copies_apres_confirmation(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        self.age_all(tid)
        self.confirm_at('K2', tid, [self.RV(self.b3, 100)])
        self.cycles(4)
        stamps = {}
        for s in SITES:
            self.go(s)
            t = BreadTransfer.objects.filter(pk=tid).first()
            if t is not None:
                stamps[s] = timezone.localtime(t.updated_at).date()
        self.assertEqual(set(stamps), {'cloud', 'K1', 'K2'})
        self.assertEqual(len(set(stamps.values())), 1, stamps)

    @expectedFailure   # BUG-1006
    def test_BUG_1006_confirmation_hors_ligne_la_veille_poussee_le_lendemain_somme_par_jour(self):
        """K2 confirme la reception HIER hors ligne (copie locale datee d'hier) et se synchronise AUJOURD'HUI :
        le cloud date le statut d'aujourd'hui (push) et K1 le recopie ; la copie de K2 reste a hier. La somme du
        groupe par jour est faussee : hier recu 100 / effectue 0, aujourd'hui effectue 100 / recu 0."""
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        self.age_all(tid)
        self.confirm_at('K2', tid, [self.RV(self.b3, 100)])
        self.go('K2')
        BreadTransfer.objects.filter(pk=tid).update(updated_at=timezone.now() - timedelta(days=1))
        self.cycles(4)
        self.assert_group_days((100, 100))


# --------------------------------------------------------------------------- BUG-1000 / 1001 / 1002 : pic et bornes
class A17Peak(A17Base):
    def test_1000_poste_perime_k1_pousse_marqueur_honnete_apres_resolution_received_aucune_alerte(self):
        tid, _ = self.to_dispute_direct()
        self.resolve(tid, 'ALIGN_ON_RECEIVED')
        self.assertEqual(self.forge('K1', {str(tid): {str(self.b3.pk): [100, 0]}}).status_code, 200)
        self.assertEqual(self.oob().count(), 0)

    def test_1000_pic_enregistre_au_pull_et_au_push(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        self.go('cloud')
        self.assertEqual(TransferMirror.objects.get(node=self.k1, transfer_id=tid).peak[str(self.b3.pk)], [100, 0])
        self.assertEqual(TransferMirror.objects.get(node=self.k2, transfer_id=tid).peak[str(self.b3.pk)], [100, 0])
        self.confirm_at('K2', tid, [self.RV(self.b3, 98)])
        self.cycles(3)
        self.go('cloud')
        self.assertEqual(TransferMirror.objects.get(node=self.k2, transfer_id=tid).peak[str(self.b3.pk)], [100, 98])

    def test_1000_pic_d_une_demande_pending_reste_zero(self):
        tid = self.request_from('K2', [self.L(self.b3, 100)], 'K1')
        self.cycles(2)
        self.go('cloud')
        for n in (self.k1, self.k2):
            self.assertEqual(TransferMirror.objects.get(node=n, transfer_id=tid).peak[str(self.b3.pk)], [0, 0])

    def test_1000_abus_marqueur_gonfle_poste_non_perime_est_refuse(self):
        """Apres un pull recent (poste a jour), le pic ne sert plus : [100, 0] au-dessus de la ligne cloud (98)
        est ignore et journalise."""
        tid, _ = self.to_dispute_direct()
        self.resolve(tid, 'ALIGN_ON_RECEIVED')
        self.cycles(2)            # K1 a pull (last_sync > updated_at)
        self.forge('K1', {str(tid): {str(self.b3.pk): [100, 0]}})
        self.assertEqual(self.oob().count(), 1)

    def test_1000_abus_pic_ne_fausse_pas_la_somme_apres_reinstallation(self):
        """Un poste perime pousse [100, 0] (accepte grace au pic) alors que la ligne cloud vaut 98 ; reinstalle,
        le marqueur descendu est borne a 98 (BUG-1001) : aucun credit/debit fantome, somme du groupe = 98 + 0."""
        tid, _ = self.to_dispute_direct()
        self.resolve(tid, 'ALIGN_ON_RECEIVED')
        self.forge('K1', {str(tid): {str(self.b3.pk): [100, 0]}})
        self.reinstall('K1')
        self.cycles(4)
        self.assertEqual(self.own('K1', self.b3), 0)
        self.assertEqual(self.own('K2', self.b3), 98)
        self.assertEqual(self.total(self.b3), 98)    # K1 reinstalle perd son stock (limite connue), pas de fantome

    def test_1000_abus_pic_marqueur_recu_gonfle_k2_apres_align_on_sent(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        self.confirm_at('K2', tid, [self.RV(self.b3, 105)])
        self.cycles(3)
        self.resolve(tid, 'ALIGN_ON_SENT')            # ligne cloud : recu 105 -> 100, pic recu 105
        self.forge('K2', {str(tid): {str(self.b3.pk): [0, 105]}})   # perime : accepte (limite annoncee)
        self.reinstall('K2')
        self.cycles(4)
        self.assertLessEqual(self.own('K2', self.b3), 100)
        self.assertEqual(self.own('K1', self.b3), 0)

    def test_1000_abus_pic_n_ouvre_pas_au_dela_du_pic(self):
        tid, _ = self.to_dispute_direct()
        self.resolve(tid, 'ALIGN_ON_RECEIVED')
        self.forge('K1', {str(tid): {str(self.b3.pk): [101, 0]}})    # > pic 100
        self.assertEqual(self.oob().count(), 1)
        self.assertNotEqual(self.marker('K1', tid), [101, 0])

    def test_1000_abus_pic_d_un_autre_poste_sans_effet(self):
        """K3 (tiers) ne peut pas pousser de marqueur sur un transfert K1->K2, pic ou non."""
        tid, _ = self.to_dispute_direct()
        self.resolve(tid, 'ALIGN_ON_RECEIVED')
        self.forge('K3', {str(tid): {str(self.b3.pk): [100, 0]}})
        self.go('cloud')
        self.assertFalse(TransferMirror.objects.filter(node=self.k3, transfer_id=tid).exists())

    def test_1000_abus_k2_emetteur_fictif_marqueur_envoye_ne_change_pas_la_somme(self):
        """K2 (receptrice) pousse un marqueur « envoye 100 » : accepte (borne = ligne), mais sans effet sur les
        stocks de K2 apres reinstallation (seul le recu compte pour une receptrice)."""
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        self.forge('K2', {str(tid): {str(self.b3.pk): [100, 0]}})
        self.confirm_at('K2', tid, [self.RV(self.b3, 100)])
        self.cycles(3)
        self.assertEqual((self.own('K1', self.b3), self.own('K2', self.b3)), (0, 100))
        self.assertEqual(self.total(self.b3), 100)

    def test_1000_pic_pas_de_regression_marqueur_honnete_apres_pic_eleve(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        self.confirm_at('K2', tid, [self.RV(self.b3, 105)])
        self.cycles(3)
        self.resolve(tid, 'ALIGN_ON_SENT')
        self.cycles(5)
        self.assertEqual(self.total(self.b3), 100)
        self.assertEqual(self.oob().count(), 0)

    def test_BUG_1007_poste_perime_qui_repousse_sans_pull_est_signale_a_tort(self):
        """Poste honnete dont le pull a echoue : le 1er push (perime) passe grace au pic mais pose `last_sync`
        a maintenant ; le rejeu du MEME marqueur honnete [100, 0] (nouveau lot, pull toujours echoue) n'est
        plus « perime » : hors borne, MIRROR_OUT_OF_BOUNDS leve contre un poste honnete."""
        tid, _ = self.to_dispute_direct()
        self.resolve(tid, 'ALIGN_ON_RECEIVED')
        self.forge('K1', {str(tid): {str(self.b3.pk): [100, 0]}})
        self.forge('K1', {str(tid): {str(self.b3.pk): [100, 0]}})
        self.assertEqual(self.oob().count(), 0)

    def test_1001_marqueur_descendu_borne_et_lignes_inconnues_non_descendues(self):
        tid, _ = self.to_dispute_direct()
        self.resolve(tid, 'ALIGN_ON_RECEIVED')
        self.go('cloud')
        TransferMirror.objects.filter(node=self.k1, transfer_id=tid).update(
            applied={str(self.b3.pk): [100, 0], '99999': [5, 5], str(self.b5.pk): [3, 0]})
        data = self.pulled('K1')
        m = data['mirrors'][str(tid)]
        self.assertEqual(m, {str(self.b3.pk): [98, 0]})

    def test_1001_marqueur_vide_non_descendu(self):
        tid = self.send_from('K1', [self.L(self.b3, 10)], 'K2')
        self.cycles(2)
        self.go('cloud')
        TransferMirror.objects.filter(node=self.k2, transfer_id=tid).update(applied={})
        self.assertNotIn(str(tid), self.pulled('K2')['mirrors'])

    def test_1002_borne_envoi_zero_demande_pending_et_annulee(self):
        tid = self.request_from('K2', [self.L(self.b3, 100)], 'K1')
        self.cycles(2)
        self.assertEqual(self.forge('K1', {str(tid): {str(self.b3.pk): [1, 0]}}).status_code, 200)
        self.assertEqual(self.oob().count(), 1)
        self.post_rest('K1', self.g1, tid, 'respond_to_request', {'approved': False})
        self.cycles(3)
        self.forge('K1', {str(tid): {str(self.b3.pk): [100, 0]}})
        self.assertGreaterEqual(self.oob().first().occurrences, 2)
        self.assertEqual(self.total(self.b3), 100)

    def test_1002_reponse_apres_marqueur_forge_somme_100(self):
        tid = self.request_from('K2', [self.L(self.b3, 100)], 'K1')
        self.cycles(2)
        self.forge('K1', {str(tid): {str(self.b3.pk): [100, 0]}})
        self.respond_at('K1', tid, [self.L(self.b3, 100)])
        self.cycles(3)
        self.confirm_at('K2', tid, [self.RV(self.b3, 100)])
        self.cycles(3)
        self.assertEqual(self.total(self.b3), 100)

    def test_1002_marqueur_honnete_apres_reponse_accepte(self):
        tid = self.request_from('K2', [self.L(self.b3, 60)], 'K1')
        self.cycles(2)
        self.respond_at('K1', tid, [self.L(self.b3, 60)])
        self.cycles(3)
        self.assertEqual(self.marker('K1', tid), [60, 0])
        self.assertEqual(self.oob().count(), 0)


# --------------------------------------------------------------------------- somme du groupe, tous les scenarios x 2 jours
class A17Sum(A17Base):
    def test_somme_envoi_direct_multi_lignes_deux_jours(self):
        tid = self.send_from('K1', [self.L(self.b3, 30), self.L(self.b5, 20)], 'K2')
        self.cycles(2)
        self.age_all(tid)
        self.confirm_at('K2', tid, [self.RV(self.b3, 30), self.RV(self.b5, 20)])
        self.cycles(4)
        self.assertEqual((self.total(self.b3), self.total(self.b5)), (100, 100))
        self.assertEqual(self.own('K2', self.b3), 30)

    def test_somme_litige_puis_resolution_received_k3_spectateur(self):
        tid, _ = self.to_dispute_direct()
        self.cycles(3)
        self.age_all(tid)
        self.resolve(tid, 'ALIGN_ON_RECEIVED')
        self.cycles(5)
        self.assertEqual((self.own('K1', self.b3), self.own('K2', self.b3), self.own('K3', self.b3)), (2, 98, 0))
        self.assertEqual(self.total(self.b3), 100)
        self.assertEqual(self.k3_transfer_alerts(), 0)


# --------------------------------------------------------------------------- idempotence du pull x5
class A17Replay(A17Base):
    def _replay5(self, name):
        data = self.pulled(name)
        self.go(name)
        for _ in range(5):
            apply_pull_response(json.loads(json.dumps(data)))

    def _stamps(self):
        out = {}
        for s in ('K1', 'K2'):
            self.go(s)
            out[s] = [(str(t.pk), t.transfer_status, t.updated_at) for t in BreadTransfer.objects.order_by('pk')]
        return out

    def test_pull_x5_a_chaque_etape_envoi_direct_aucun_changement(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        steps = [lambda: None, lambda: self.cycles(2),
                 lambda: self.confirm_at('K2', tid, [self.RV(self.b3, 100)]), lambda: self.cycles(3)]
        for step in steps:
            step()
            before_stock = (self.total(self.b3), self.snapshot())
            before_stamps = self._stamps()
            for n in ('K1', 'K2', 'K3'):
                self._replay5(n)
            self.assertEqual((self.total(self.b3), self.snapshot()), before_stock)
            self.assertEqual(self._stamps(), before_stamps)
        self.assertEqual(self.total(self.b3), 100)

    def test_pull_x5_apres_resolution_siege_updated_at_stable(self):
        tid, _ = self.to_dispute_direct()
        self.resolve(tid, 'ALIGN_ON_RECEIVED')
        self.cycles(4)
        before = (self.total(self.b3), self.snapshot(), self._stamps())
        for n in ('K1', 'K2', 'K3'):
            self._replay5(n)
        self.assertEqual((self.total(self.b3), self.snapshot(), self._stamps()), before)
        self.assertEqual(self.total(self.b3), 100)

    def test_pull_x5_demande_puis_annulation_aucun_double_effet(self):
        tid = self.request_from('K2', [self.L(self.b3, 10)], 'K1')
        self.cycles(2)
        self.post_rest('K1', self.g1, tid, 'respond_to_request', {'approved': False})
        self.cycles(3)
        before = (self.total(self.b3), self.snapshot(), self._stamps())
        for n in ('K1', 'K2'):
            self._replay5(n)
        self.assertEqual((self.total(self.b3), self.snapshot(), self._stamps()), before)

    def test_push_rejoue_meme_lot_n_avance_pas_updated_at_cloud(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        self.confirm_at('K2', tid, [self.RV(self.b3, 100)])
        self.cycles(3)
        self.go('cloud')
        at = BreadTransfer.objects.get(pk=tid).updated_at
        self.cycles(4)
        self.go('cloud')
        self.assertEqual(BreadTransfer.objects.get(pk=tid).updated_at, at)


# --------------------------------------------------------------------------- migration 0005 sur base existante
class A17Migration0005(TransactionTestCase):
    def test_migration_0005_additive_peak_vide_et_ligne_existante_conservee(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        node = Node.objects.create(code='ZZ8', name='Z8')
        tid = uuid.uuid4()
        try:
            executor.migrate([('sync', '0004_transfermirror')])
            cols = {c.name for c in connection.introspection.get_table_description(
                connection.cursor(), 'sync_transfermirror')}
            self.assertNotIn('peak', cols)
            old_apps = MigrationExecutor(connection).loader.project_state(
                [('sync', '0004_transfermirror')]).apps
            OldMirror = old_apps.get_model('sync', 'TransferMirror')
            OldNode = old_apps.get_model('core', 'Node')
            OldMirror.objects.create(node=OldNode.objects.get(pk=node.pk), transfer_id=tid,
                                     applied={'1': [100, 0]})
            MigrationExecutor(connection).migrate([('sync', '0005_transfermirror_peak')])
            cols = {c.name for c in connection.introspection.get_table_description(
                connection.cursor(), 'sync_transfermirror')}
            self.assertIn('peak', cols)
            row = TransferMirror.objects.get(node=node, transfer_id=tid)
            self.assertEqual(row.applied, {'1': [100, 0]})
            self.assertEqual(row.peak, {})
            MigrationExecutor(connection).migrate(latest)
            # retour arriere puis avant : la colonne est supprimee puis recreee proprement
            MigrationExecutor(connection).migrate([('sync', '0004_transfermirror')])
            MigrationExecutor(connection).migrate(latest)
            self.assertEqual(TransferMirror.objects.get(node=node, transfer_id=tid).peak, {})
        finally:
            MigrationExecutor(connection).migrate(latest)
            Node.objects.filter(pk=node.pk).delete()


class A17LegacyPeak(A17Base):
    def test_ligne_ancienne_sans_pic_le_pull_le_complete_et_le_push_perime_reste_signale_limite_documentee(self):
        tid, _ = self.to_dispute_direct()
        self.go('cloud')
        TransferMirror.objects.filter(node=self.k1, transfer_id=tid).update(peak={})
        self.resolve(tid, 'ALIGN_ON_RECEIVED')
        # push perime d'un poste dont la ligne a ete migree (pic vide) : sans pic connu, [100, 0] > 98
        r = self.forge('K1', {str(tid): {str(self.b3.pk): [100, 0]}})
        self.assertEqual(r.status_code, 200, r.content)
        # observation (meme famille que BUG-1007) : le pic n'a pu etre reconstruit qu'a la borne actuelle (98)
        self.assertEqual(self.oob().count(), 1)


# --------------------------------------------------------------------------- balayage push vs REST
class A17Sweep(PushBase):
    def setUp(self):
        super().setUp()
        self.rec, _ = self.push_sess()

    def _d(self, **kw):
        d = {'id': uid(), 'session': self.rec['id'], 'bread_price': self.b3.pk, 'disposal_type': 'UNSOLD',
             'quantity': 5, 'unit_price_sold': 0}
        d.update(kw)
        return d, push(self.a1, 'production.BreadDisposal', d)

    def test_observation_sold_discount_au_push_accepte_total_recalcule(self):
        """Tranche coordinateur : SOLD_DISCOUNT accepte au push (donnees hors ligne anciennes). Verifie : valeur
        recalculee, aucune creation REST possible, et l'historique reste modifiable."""
        d, res = self._d(disposal_type='SOLD_DISCOUNT', quantity=4, unit_price_sold=225)
        self.assertEqual(res[0], 'ACCEPTED')
        from production.models import BreadDisposal
        self.assertEqual(BreadDisposal.objects.get(pk=d['id']).total_value, 900)
        r = cl(self.g1).post('/api/production/disposals/', {
            'session': self.rec['id'], 'bread_price': self.b3.pk, 'disposal_type': 'SOLD_DISCOUNT',
            'quantity': 1, 'unit_price_sold': 225}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_disposal_notes_au_dela_de_255_refusees_comme_en_rest(self):
        d, res = self._d(notes='x' * 300)
        r = cl(self.g1).post('/api/production/disposals/', {
            'session': self.rec['id'], 'bread_price': self.b3.pk, 'disposal_type': 'UNSOLD',
            'quantity': 1, 'notes': 'x' * 300}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(res[0], 'REJECTED', res)

    def test_consumable_movement_type_inconnu_refuse_comme_en_rest(self):
        rec = {'id': uid(), 'node': self.k1.code, 'consumable_type': 'SALT', 'movement_type': 'FOO',
               'quantity': '5.000', 'unit': 'g'}
        res = push(self.a1, 'production.ConsumableMovement', rec)
        self.assertEqual(res[0], 'REJECTED', res)
        self.assertFalse(ConsumableMovement.objects.filter(pk=rec['id']).exists())
        self.assertEqual(ConsumableStock.objects.filter(node=self.k1, consumable_type='SALT').count(), 0)
