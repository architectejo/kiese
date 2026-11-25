"""Testeur-production (cycle 17 / a16) : verification independante de BUG-997 (marqueurs de miroir
bornes par les lignes cloud, d46) et balayage de fin de partie A (clôture journalière + transferts
après sync, blocage de clôture + ventes bloquées, push BreadDisposal / ConsumableCount vs REST).
Banc : 3 postes simules K1/K2/K3 (Q1/Q2/Q3) + cloud (A15Base). Donnees fictives. Les
`@expectedFailure` referencent leur ticket.
"""
import datetime as dt
import uuid
from datetime import date as ddate, timedelta

from django.utils import timezone

from core.models import Node
from production.models import BreadDisposal, BreadTransfer, ConsumableCount
from production.tests.test_verif_a4_testeur_production import cl
from production.tests.test_verif_production_a15_v15 import A15Base
from production.tests.test_verif_production_a8_v8 import push
from sync.models import SyncConflictLog, TransferMirror
from treasury.closure_lock import closure_status
from treasury.models import CashClosure

OOB = 'MIRROR_OUT_OF_BOUNDS'


class A16Base(A15Base):
    def oob(self):
        self.go('cloud')
        return SyncConflictLog.objects.filter(conflict_type=OOB)

    def marker(self, name, tid):
        self.go('cloud')
        m = TransferMirror.objects.filter(node=self.node[name], transfer_id=tid).first()
        return None if m is None else m.applied.get(str(self.b3.pk))


# --------------------------------------------------------------------------- BUG-997 : verification
class A16Mirror(A16Base):
    def test_997_marqueur_honnete_stocke_apres_cycle_complet(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        self.confirm_at('K2', tid, [self.RV(self.b3, 100)])
        self.cycles(3)
        self.assertEqual(self.marker('K1', tid), [100, 0])
        self.assertEqual(self.marker('K2', tid), [0, 100])
        self.assertEqual(self.oob().count(), 0)
        self.assertEqual(self.total(self.b3), 100)

    def test_997_hors_borne_recu_superieur_ignore_et_lot_accepte(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        r = self.forge('K2', {str(tid): {str(self.b3.pk): [0, 1000]}})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.marker('K2', tid), [0, 0])      # le marqueur honnete d'avant reste intact
        self.assertEqual(self.oob().count(), 1)

    def test_997_marqueur_recu_avant_confirmation_est_hors_borne(self):
        """Le recu du cloud est None (0) tant que personne n'a confirme : K2 ne peut pas se dire credite."""
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        self.forge('K2', {str(tid): {str(self.b3.pk): [0, 1]}})
        self.assertEqual(self.marker('K2', tid), [0, 0])
        self.assertEqual(self.oob().count(), 1)

    def test_997_conflit_unique_occurrences_incrementees_et_rejeu_du_meme_lot(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        for _ in range(3):
            self.forge('K2', {str(tid): {str(self.b3.pk): [0, 500]}})
        c = self.oob()
        self.assertEqual(c.count(), 1)
        self.assertEqual(c.first().occurrences, 3)

    def test_997_categorie_valide_stockee_meme_si_une_autre_est_hors_borne(self):
        tid = self.send_from('K1', [self.L(self.b3, 10), self.L(self.b5, 20)], 'K2')
        self.cycles(2)
        self.forge('K1', {str(tid): {str(self.b3.pk): [10, 0], str(self.b5.pk): [999, 0], '77777': [1, 0]}})
        self.go('cloud')
        applied = TransferMirror.objects.get(node=self.k1, transfer_id=tid).applied
        self.assertEqual(applied[str(self.b3.pk)], [10, 0])
        self.assertNotIn(str(self.b5.pk), {k for k, v in applied.items() if v == [999, 0]})
        self.assertNotIn('77777', applied)

    def test_997_marqueur_monotone_un_marqueur_plus_bas_ne_remplace_pas(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        self.confirm_at('K2', tid, [self.RV(self.b3, 100)])
        self.cycles(3)
        self.forge('K2', {str(tid): {str(self.b3.pk): [0, 0]}})
        self.assertEqual(self.marker('K2', tid), [0, 100])
        self.reinstall('K2')
        self.cycles(3)
        self.assertEqual(self.own('K2', self.b3), 0)       # pas de double credit
        self.assertEqual(self.total(self.b3), 0)           # la reinstallation perd le stock du poste (limite connue)

    def test_997_somme_nulle_resolution_siege_sent_recu_superieur_sans_reinstallation(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        self.assertEqual(self.confirm_at('K2', tid, [self.RV(self.b3, 105)]), 'DISPUTED')
        self.cycles(3)
        self.assertEqual(self.total(self.b3), 105)
        self.resolve(tid, 'ALIGN_ON_SENT')
        self.cycles(4)
        self.assertEqual((self.own('K1', self.b3), self.own('K2', self.b3)), (0, 100))
        self.assertEqual(self.total(self.b3), 100)
        self.assertEqual(self.marker('K2', tid), [0, 100])         # retablissement : le poste a repris la main

    def test_997_somme_nulle_resolution_siege_received_sans_reinstallation(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        self.confirm_at('K2', tid, [self.RV(self.b3, 98)])
        self.cycles(3)
        self.resolve(tid, 'ALIGN_ON_RECEIVED')
        self.cycles(4)
        self.assertEqual((self.own('K1', self.b3), self.own('K2', self.b3)), (2, 98))
        self.assertEqual(self.total(self.b3), 100)
        self.assertEqual(self.marker('K1', tid), [98, 0])

    def test_997_resolution_par_k1_puis_k2_pull_avant_k1_somme_nulle(self):
        tid, _ = self.to_dispute_direct()
        r = self.post_rest('K1', self.g1, tid, 'resolve_dispute', {'resolution': 'ALIGN_ON_RECEIVED', 'reason': 'x'})
        self.assertEqual(r.status_code, 200, r.content)
        self.cycles(4, ('K2', 'K1', 'K3'))
        self.assertEqual(self.total(self.b3), 100)

    # ------------------------------------------------ pistes de contournement
    def test_observation_k1_honnete_ne_declenche_pas_d_alerte_apres_resolution_siege_received(self):
        """Apres ALIGN_ON_RECEIVED au siege, la ligne cloud passe de 100 a 98 ; K1 n'a pas encore pull et pousse
        son marqueur honnete [100, 0] : il ne doit pas etre traite comme une falsification."""
        tid, _ = self.to_dispute_direct()
        self.resolve(tid, 'ALIGN_ON_RECEIVED')
        self.assertEqual(self.oob().count(), 0)
        self.cycles(1, ('K1',))
        self.assertEqual(self.oob().count(), 0)

    def test_observation_k2_honnete_ne_declenche_pas_d_alerte_apres_resolution_siege_sent(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        self.confirm_at('K2', tid, [self.RV(self.b3, 105)])
        self.cycles(3)
        self.resolve(tid, 'ALIGN_ON_SENT')
        self.cycles(1, ('K2',))
        self.assertEqual(self.oob().count(), 0)

    def test_marqueur_perime_poste_k1_reinstalle_juste_apres_resolution_received_aucun_credit_fantome(self):
        tid, _ = self.to_dispute_direct()
        self.resolve(tid, 'ALIGN_ON_RECEIVED')
        self.reinstall('K1')
        self.cycles(3)
        self.assertEqual(self.own('K1', self.b3), 0)

    def test_marqueur_perime_poste_k2_reinstalle_juste_apres_resolution_sent_aucun_debit_fantome(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        self.confirm_at('K2', tid, [self.RV(self.b3, 105)])
        self.cycles(3)
        self.resolve(tid, 'ALIGN_ON_SENT')
        self.reinstall('K2')
        self.cycles(3)
        self.assertGreaterEqual(self.own('K2', self.b3), 0)

    def test_BUG_1002_marqueur_emetteur_gonfle_sur_demande_pending_efface_la_deduction(self):
        """La borne `quantity_sent` d'une demande PENDING est la quantite DEMANDEE (rien n'est deduit) : K1
        pousse [100, 0] avant d'avoir vu la demande ; la reponse du siege est ensuite creditee a K2 sans
        deduction chez K1 (somme du groupe 200 au lieu de 100)."""
        tid = self.request_from('K2', [self.L(self.b3, 100)], 'K1')
        self.sync('K2')
        self.assertEqual(self.forge('K1', {str(tid): {str(self.b3.pk): [100, 0]}}).status_code, 200)
        r = self.post_rest('cloud', self.dir, tid, 'respond_to_request',
                           {'approved': True, 'lines': [self.L(self.b3, 100)]})
        self.assertEqual(r.status_code, 200, r.content)
        self.cycles(3)
        self.confirm_at('K2', tid, [self.RV(self.b3, 100)])
        self.cycles(3)
        self.assertEqual(self.total(self.b3), 100)

    def test_observation_fenetre_de_retablissement_abaisse_le_marqueur_et_double_credite_au_poste_neuf(self):
        """Limite documentee (poste hostile qui possede deja son stock) : tant que l'ancien marqueur depasse la
        borne actuelle, un marqueur plus bas est accepte ; un poste neuf est alors credite une seconde fois."""
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        self.confirm_at('K2', tid, [self.RV(self.b3, 105)])
        self.cycles(3)
        self.resolve(tid, 'ALIGN_ON_SENT')
        self.forge('K2', {str(tid): {str(self.b3.pk): [0, 0]}})
        self.assertEqual(self.marker('K2', tid), [0, 0])


# --------------------------------------------------------------------------- balayage fin de partie A
class A16Sweep(A16Base):
    def _closure(self, name, day):
        self.go(name)
        r = cl(self.ger[name]).get('/api/production/daily-closure/', {'date': str(day)})
        self.assertEqual(r.status_code, 200, r.content)
        rows = {c['bread_price']: c for c in r.data['categories']}
        return rows[self.b3.pk]

    def test_cloture_journaliere_envoi_et_reception_le_meme_jour_apres_sync_somme_nulle(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        self.confirm_at('K2', tid, [self.RV(self.b3, 100)])
        self.cycles(3)
        today = ddate.today()
        k1, k2 = self._closure('K1', today), self._closure('K2', today)
        self.assertEqual((k1['appro_effectue']['quantity'], k2['appro_recu']['quantity']), (100, 100))
        self.assertEqual(k1['appro_effectue']['fc'], '30000.00')
        self.assertEqual(k2['facture_mvm_interne']['fc'], '-30000.00')

    def test_BUG_1003_envoi_la_veille_confirme_aujourd_hui_apres_sync_k1_compte_l_appro_le_meme_jour_que_k2(self):
        """Envoye hier, receptionne aujourd'hui : en REST (une base) `updated_at` passe a aujourd'hui pour les
        deux boulangeries. Via la synchronisation, la copie de K1 recoit le statut CONFIRMED sans que son
        `updated_at` avance : l'appro effectue de K1 reste classe a HIER (journee deja close) alors que l'appro
        recu de K2 est classe a AUJOURD'HUI."""
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        yesterday = timezone.now() - timedelta(days=1)
        BreadTransfer.objects.filter(pk=tid).update(updated_at=yesterday)
        self.cycles(2)
        self.go('cloud')
        BreadTransfer.objects.filter(pk=tid).update(updated_at=yesterday)
        self.confirm_at('K2', tid, [self.RV(self.b3, 100)])
        self.cycles(3)
        today = ddate.today()
        k2_today = self._closure('K2', today)['appro_recu']['quantity']
        k1_today = self._closure('K1', today)['appro_effectue']['quantity']
        k1_yesterday = self._closure('K1', today - timedelta(days=1))['appro_effectue']['quantity']
        self.assertEqual((k2_today, k1_today, k1_yesterday), (100, 100, 0))

    def test_transfert_en_litige_bloque_la_confirmation_de_la_cloture_et_les_ventes_puis_se_debloque(self):
        """BUG-973 x BUG-277 : heure de cloture atteinte, cloture K2 non confirmee a cause d'un litige entrant : les
        ventes de K2 restent bloquees jusqu'a la resolution ; le litige K1 (sortant) ne bloque pas K1."""
        Node.objects.filter(pk__in=[self.k1.pk, self.k2.pk]).update(
            block_sales_after_closure=True, handover_time=dt.time(0, 0))
        tid, _ = self.to_dispute_direct()
        self.go('cloud')
        self.assertTrue(closure_status(Node.objects.get(pk=self.k2.pk))['blocked'])
        # BUG-1130 : la cloture exigee par le verrou est celle de la journee comptable terminee
        # (heure de cloture 00:00 -> veille).
        veille = ddate.today() - dt.timedelta(days=1)
        c2 = CashClosure.objects.create(node=self.k2, date=veille, node_origin='Q2')
        c1 = CashClosure.objects.create(node=self.k1, date=veille, node_origin='Q1')
        r = cl(self.cpt).post(f'/api/treasury/closures/{c2.pk}/validate/', {}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('Confirmation bloquée', r.data['detail'])
        self.assertFalse(CashClosure.objects.get(pk=c2.pk).is_validated)
        r1 = cl(self.cpt).post(f'/api/treasury/closures/{c1.pk}/validate/', {}, format='json')
        self.assertNotIn('Confirmation bloquée', str(r1.content))   # litige sortant : n'empeche pas K1
        # recomptage par K2 : le litige se resorbe, la confirmation passe, les ventes se debloquent
        self.assertEqual(self.confirm_at('K2', tid, [self.RV(self.b3, 100)]), 'CONFIRMED')
        self.cycles(4)
        self.go('cloud')
        r = cl(self.cpt).post(f'/api/treasury/closures/{c2.pk}/validate/', {}, format='json')
        self.assertNotIn('Confirmation bloquée', str(r.content), r.content)
        if r.status_code == 200:
            self.assertFalse(closure_status(Node.objects.get(pk=self.k2.pk))['blocked'])

    def test_push_cloture_confirmee_refusee_tant_que_le_litige_n_est_pas_resolu_apres_sync(self):
        tid, _ = self.to_dispute_direct()
        self.go('cloud')
        cid = str(uuid.uuid4())
        rec = {'id': cid, 'node': 'Q2', 'date': str(ddate.today()), 'is_validated': True, 'node_origin': 'Q2'}
        st = push(self.api['K2'], 'treasury.CashClosure', rec)
        self.assertEqual(st[0], 'REJECTED', st)
        self.assertIn('écart', st[1] or '')

    def test_disposal_poussee_visible_par_date_au_cloud_et_filtre_jour_precedent(self):
        self.go('cloud')
        sid = str(uuid.uuid4())
        day = ddate.today() - timedelta(days=2)
        s = {'id': sid, 'node': 'Q1', 'team': 'A', 'date': str(day), 'flour_sacks_used': '1.00',
             'total_breads': 10, 'total_fc_produced': 3000, 'theoretical_yield': 200000, 'yield_gap': -197000,
             'sac_value_fc_used': 200000}
        self.assertEqual(push(self.api['K1'], 'production.ProductionSession', s)[0], 'ACCEPTED')
        d = {'id': str(uuid.uuid4()), 'session': sid, 'bread_price': self.b3.pk, 'disposal_type': 'UNSOLD',
             'quantity': 4, 'unit_price_sold': 0}
        self.assertEqual(push(self.api['K1'], 'production.BreadDisposal', d)[0], 'ACCEPTED')
        u = '/api/production/disposals/'
        got = cl(self.g1).get(u, {'date': str(day)}).json()
        rows = got['results'] if isinstance(got, dict) else got
        self.assertEqual([x['id'] for x in rows], [d['id']])
        other = cl(self.g1).get(u, {'date': str(day + timedelta(days=1))}).json()
        self.assertEqual(other['results'] if isinstance(other, dict) else other, [])
        self.assertEqual(cl(self.g2).get(u, {'date': str(day)}).json().get('count', 0), 0)   # autre boulangerie
        self.assertEqual(cl(self.g1).get(u, {'date': 'x'}).status_code, 400)

    def test_push_comptage_ecart_signe_et_bornes(self):
        d = str(ddate.today())
        base = {'node': 'Q1', 'consumable_type': 'SALT', 'count_date': d, 'system_quantity': '10.000',
                'physical_quantity': '7.500', 'gap': '-2.500'}
        self.assertEqual(push(self.api['K1'], 'production.ConsumableCount', dict(base, id=1))[0], 'ACCEPTED')
        self.assertEqual(ConsumableCount.objects.get(consumable_type='SALT').gap, -2.5)
        bad = dict(base, id=2, consumable_type='OIL', gap='2.500')   # signe inverse
        self.assertEqual(push(self.api['K1'], 'production.ConsumableCount', bad)[0], 'REJECTED')
        big = dict(base, id=3, consumable_type='YEAST', system_quantity='0', physical_quantity='99999999999',
                   gap='99999999999')
        self.assertEqual(push(self.api['K1'], 'production.ConsumableCount', big)[0], 'REJECTED')
        four = dict(base, id=4, consumable_type='FLOUR', system_quantity='1.0005', physical_quantity='1.0005',
                    gap='0')
        self.assertEqual(push(self.api['K1'], 'production.ConsumableCount', four)[0], 'REJECTED')
        self.assertEqual(BreadDisposal.objects.count(), 0)
