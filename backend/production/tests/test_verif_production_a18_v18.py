"""Testeur-production (cycle 19 / a18) : verification independante de BUG-1007 (d50, table sync.TransferPull,
migration 0006). Donnees fictives."""
import uuid

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from core.models import Node
from production.tests.test_verif_production_a17_v17 import A17Base
from sync.models import TransferMirror, TransferPull


class A18Pull(A17Base):
    def _lag_setup(self):
        tid, _ = self.to_dispute_direct()
        self.resolve(tid, 'ALIGN_ON_RECEIVED')          # ligne cloud 100 -> 98 apres le dernier pull de K1
        return tid

    def test_1007_honnete_sans_pull_rejoue_son_marqueur_sans_alerte(self):
        tid = self._lag_setup()
        for _ in range(3):
            self.assertEqual(self.forge('K1', {str(tid): {str(self.b3.pk): [100, 0]}}).status_code, 200)
        self.assertEqual(self.oob().count(), 0)

    def test_1007_apres_pull_poste_a_jour_marqueur_gonfle_signale(self):
        tid = self._lag_setup()
        self.pulled('K1')
        self.forge('K1', {str(tid): {str(self.b3.pk): [100, 0]}})
        self.assertEqual(self.oob().count(), 1)

    def test_1007_pull_poserait_pulled_at_et_le_push_ne_le_modifie_pas(self):
        tid = self._lag_setup()
        self.go('cloud')
        before = TransferPull.objects.get(node=self.k1, transfer_id=tid).pulled_at
        self.forge('K1', {str(tid): {str(self.b3.pk): [100, 0]}})
        self.go('cloud')
        self.assertEqual(TransferPull.objects.get(node=self.k1, transfer_id=tid).pulled_at, before)

    def test_1007_un_pull_par_transfert_pas_de_croissance_au_rejeu(self):
        self._lag_setup()
        self.cycles(1)
        self.go('cloud')
        n = TransferPull.objects.count()
        self.cycles(10)
        self.go('cloud')
        self.assertEqual(TransferPull.objects.count(), n)

    def test_1007_poste_hostile_ne_fausse_pas_la_somme_apres_reinstallation(self):
        tid = self._lag_setup()
        for _ in range(3):
            self.forge('K1', {str(tid): {str(self.b3.pk): [100, 0]}})
        self.forge('K1', {str(tid): {str(self.b3.pk): [100, 0]}})
        self.reinstall('K1')
        self.cycles(4)
        self.assertEqual(self.total(self.b3), 98)

    def test_1007_poste_hostile_au_dela_du_pic_refuse_meme_sans_pull(self):
        tid = self._lag_setup()
        self.forge('K1', {str(tid): {str(self.b3.pk): [500, 0]}})
        self.assertEqual(self.oob().count(), 1)
        self.assertNotEqual(self.marker('K1', tid), [500, 0])

    def test_1007_hostile_k2_receptrice_recu_gonfle_sans_pull_apres_align_sent(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        self.confirm_at('K2', tid, [self.RV(self.b3, 105)])
        self.cycles(3)
        self.resolve(tid, 'ALIGN_ON_SENT')
        self.forge('K2', {str(tid): {str(self.b3.pk): [0, 105]}})
        self.forge('K2', {str(tid): {str(self.b3.pk): [0, 105]}})
        self.reinstall('K2')
        self.cycles(4)
        self.assertLessEqual(self.total(self.b3), 100)   # reinstallation : perte du stock du poste (limite connue), jamais de credit fantome

    def test_1007_reinstalle_sans_pull_antecedent_jamais_livre_donc_en_retard(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        self.go('cloud')
        TransferPull.objects.filter(node=self.k1).delete()   # poste reinstalle / ligne jamais livree
        self.forge('K1', {str(tid): {str(self.b3.pk): [100, 0]}})
        self.assertEqual(self.oob().count(), 0)

    def test_1007_pic_vide_initialise_par_le_push_meme_sans_pull(self):
        tid = self._lag_setup()
        self.go('cloud')
        TransferMirror.objects.filter(node=self.k1, transfer_id=tid).update(peak={})
        self.forge('K1', {str(tid): {str(self.b3.pk): [100, 0]}})
        self.go('cloud')
        self.assertEqual(TransferMirror.objects.get(node=self.k1, transfer_id=tid).peak[str(self.b3.pk)], [98, 98])


class A18Migration0006(TransactionTestCase):
    def test_migration_0006_additive_et_retour_arriere(self):
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        node = Node.objects.create(code='ZZ9', name='Z9')
        tid = uuid.uuid4()
        try:
            MigrationExecutor(connection).migrate([('sync', '0005_transfermirror_peak')])
            self.assertNotIn('sync_transferpull', connection.introspection.table_names())
            old_apps = MigrationExecutor(connection).loader.project_state(
                [('sync', '0005_transfermirror_peak')]).apps
            old_apps.get_model('sync', 'TransferMirror').objects.create(
                node=old_apps.get_model('core', 'Node').objects.get(pk=node.pk), transfer_id=tid,
                applied={'1': [100, 0]}, peak={})
            MigrationExecutor(connection).migrate(latest)
            self.assertIn('sync_transferpull', connection.introspection.table_names())
            self.assertEqual(TransferMirror.objects.get(node=node, transfer_id=tid).applied, {'1': [100, 0]})
            self.assertEqual(TransferPull.objects.count(), 0)   # absence de ligne = jamais livre
            TransferPull.objects.create(node=node, transfer_id=tid, pulled_at=timezone.now())
            MigrationExecutor(connection).migrate([('sync', '0005_transfermirror_peak')])
            MigrationExecutor(connection).migrate(latest)
        finally:
            MigrationExecutor(connection).migrate(latest)
            Node.objects.filter(pk=node.pk).delete()
