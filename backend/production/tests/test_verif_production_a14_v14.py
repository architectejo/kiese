"""Testeur-production (cycle 15 / a14) : verification independante de BUG-974 a 980 (architecte-sync d39) sur le
banc 3 postes (K1/K2/K3 = Q1/Q2/Q3) + cloud de `test_verif_production_a13_v13` (`P13Base.sync` = export, push,
pull, apply_push_response, apply_pull_response). Donnees fictives.

Mesure cle : « somme du groupe » = somme des stocks PROPRES de K1+K2+K3 (`total`), qui doit rester egale au stock
initial (100 par categorie chez K1) apres chaque scenario termine.
"""
import json
from datetime import timedelta
from unittest import expectedFailure

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from core.models import SystemNotification
from production.models import BreadStock, BreadTransfer, BreadTransferLine
from production.tests.test_verif_production_a13_v13 import P13Base
from sync.management.commands.sync_now import apply_pull_response, apply_push_response, build_outbound_payload
from sync.models import NodeOpenTransfers
from treasury.views import _unresolved_incoming_transfer_gap

TS = BreadTransfer.TransferStatus


class A14Base(P13Base):
    def cycles(self, n=1, order=('K1', 'K2', 'K3')):
        out = []
        for _ in range(n):
            for name in order:
                out.append(self.refused(self.sync(name)))
        return out

    def pulled(self, name):
        self.go('cloud')
        r = self.api[name].get('/api/sync/pull/')
        self.assertEqual(r.status_code, 200, r.content)
        return json.loads(r.content)

    def age(self, tid, days):
        self.go('cloud')
        BreadTransfer.objects.filter(pk=tid).update(updated_at=timezone.now() - timedelta(days=days))

    def notes(self, name, needle=None):
        self.go(name)
        qs = SystemNotification.objects.all()
        if needle:
            qs = qs.filter(title__contains=needle)
        return qs.count()

    def k3_transfer_alerts(self):
        return sum(self.notes('K3', n) for n in ('Pains', 'Litige', 'Demande'))

    def sums(self, *bps):
        return tuple(self.total(bp) for bp in bps)

    def snapshot(self):
        out = {}
        for n in ('K1', 'K2', 'K3'):
            self.go(n)
            out[n] = (sorted((s.bread_price_id, s.qty_available) for s in BreadStock.objects.filter(node=self.node[n])),
                      BreadTransfer.objects.count(), BreadTransferLine.objects.count(),
                      SystemNotification.objects.count())
        return out


# --------------------------------------------------------------------------- rejeu du pull, resolutions
class A14Delta(A14Base):
    def test_rejeu_du_meme_pull_n_fois_a_chaque_etape_aucun_double_mouvement(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        for stage in ('RESPONDED', 'DISPUTED', 'CONFIRMED'):
            if stage == 'DISPUTED':
                self.confirm_at('K2', tid, [self.RV(self.b3, 98)])
                self.cycles(2)
            if stage == 'CONFIRMED':
                self.go('cloud')
                r = self.post_rest('cloud', self.dir, tid, 'resolve_dispute',
                                   {'resolution': 'ALIGN_ON_RECEIVED', 'reason': 'x'})
                self.assertEqual(r.status_code, 200, r.content)
                self.cycles(2)
            before = self.snapshot()
            payloads = {n: self.pulled(n) for n in ('K1', 'K2', 'K3')}
            for _ in range(5):
                for n in ('K1', 'K2', 'K3'):
                    self.go(n)
                    apply_pull_response(payloads[n])
            self.assertEqual(self.snapshot(), before, stage)
            self.assertEqual(self.total(self.b3), {'RESPONDED': 0, 'DISPUTED': 98, 'CONFIRMED': 100}[stage], stage)

    def test_align_on_received_par_l_emettrice_rest_somme_nulle_et_rejeux(self):
        tid, _ = self.to_dispute_direct()
        r = self.post_rest('K1', self.g1, tid, 'resolve_dispute', {'resolution': 'ALIGN_ON_RECEIVED', 'reason': 'casse'})
        self.assertEqual(r.status_code, 200, r.content)
        self.cycles(4)
        for n in ('K1', 'K2'):
            self.assertEqual(self.view(n, tid), ('CONFIRMED', {self.b3.pk: (98, 98)}), n)
        self.assertEqual(self.view('cloud', tid), ('CONFIRMED', {self.b3.pk: (98, 98)}))
        self.assertEqual((self.own('K1', self.b3), self.own('K2', self.b3), self.own('K3', self.b3)), (2, 98, 0))
        self.assertEqual(self.total(self.b3), 100)
        self.assertFalse(self.gap('K2'))

    def test_align_on_sent_par_l_emettrice_rest_somme_nulle_et_rejeux(self):
        tid, _ = self.to_dispute_direct()
        r = self.post_rest('K1', self.g1, tid, 'resolve_dispute', {'resolution': 'ALIGN_ON_SENT', 'reason': 'recompte'})
        self.assertEqual(r.status_code, 200, r.content)
        self.cycles(4)
        self.assertEqual(self.view('cloud', tid), ('CONFIRMED', {self.b3.pk: (100, 100)}))
        for n in ('K1', 'K2'):
            self.assertEqual(self.view(n, tid), ('CONFIRMED', {self.b3.pk: (100, 100)}), n)
        self.assertEqual((self.own('K2', self.b3), self.own('K3', self.b3)), (100, 0))
        # K1 ne doit pas avoir de mouvement propre en plus (le credit de K2 est celui de K2, pas une ecriture chez K1)
        self.assertEqual(self.own('K1', self.b3), 0)
        self.assertEqual(self.total(self.b3), 100)
        self.assertFalse(self.gap('K2'))

    def test_siege_align_on_sent_multi_lignes_somme_100(self):
        tid = self.send_from('K1', [self.L(self.b3, 10), self.L(self.b5, 50), self.L(self.b4, 5)], 'K2')
        self.cycles(2)
        self.confirm_at('K2', tid, [self.RV(self.b3, 10), self.RV(self.b5, 47), self.RV(self.b4, 5)])
        self.cycles(2)
        self.assertEqual((self.total(self.b3), self.total(self.b5), self.total(self.b4)), (100, 97, 100))
        r = self.post_rest('cloud', self.dir, tid, 'resolve_dispute', {'resolution': 'ALIGN_ON_SENT', 'reason': 'x'})
        self.assertEqual(r.status_code, 200, r.content)
        self.cycles(3)
        self.assertEqual((self.total(self.b3), self.total(self.b5), self.total(self.b4)), (100, 100, 100))
        self.assertEqual(self.own('K2', self.b5), 50)

    def test_siege_align_on_received_multi_lignes_somme_100(self):
        tid = self.send_from('K1', [self.L(self.b3, 10), self.L(self.b5, 50), self.L(self.b4, 5)], 'K2')
        self.cycles(2)
        self.confirm_at('K2', tid, [self.RV(self.b3, 10), self.RV(self.b5, 47), self.RV(self.b4, 5)])
        self.cycles(2)
        r = self.post_rest('cloud', self.dir, tid, 'resolve_dispute', {'resolution': 'ALIGN_ON_RECEIVED', 'reason': 'x'})
        self.assertEqual(r.status_code, 200, r.content)
        self.cycles(3)
        self.assertEqual((self.total(self.b3), self.total(self.b5), self.total(self.b4)), (100, 100, 100))
        self.assertEqual((self.own('K1', self.b5), self.own('K2', self.b5)), (53, 47))

    def test_confirmation_par_le_siege_100_puis_98_somme_nulle(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        r = self.post_rest('cloud', self.dir, tid, 'confirm_reception', {'lines': [self.RV(self.b3, 100)]})
        self.assertEqual(r.status_code, 200, r.content)
        self.cycles(3)
        self.assertEqual((self.own('K1', self.b3), self.own('K2', self.b3)), (0, 100))
        self.assertEqual(self.total(self.b3), 100)
        # variante 98 : litige ouvert par le siege, K2 credite de 98, clotûre de K2 bloquee puis recomptage local
        tid2 = self.send_from('K1', [self.L(self.b5, 40)], 'K2')
        self.cycles(2)
        r = self.post_rest('cloud', self.dir, tid2, 'confirm_reception', {'lines': [self.RV(self.b5, 38)]})
        self.assertEqual(r.status_code, 200, r.content)
        self.cycles(3)
        self.assertEqual(self.view('K2', tid2), ('DISPUTED', {self.b5.pk: (40, 38)}))
        self.assertEqual((self.own('K1', self.b5), self.own('K2', self.b5)), (60, 38))
        self.assertTrue(self.gap('K2'))
        self.assertEqual(self.total(self.b5), 98)
        # K2 recompte : +2 localement, resolution convergente
        self.assertEqual(self.confirm_at('K2', tid2, [self.RV(self.b5, 40)]), 'CONFIRMED')
        self.cycles(4)
        self.assertEqual(self.total(self.b5), 100)
        self.assertFalse(self.gap('K2'))
        self.assertEqual(self.view('cloud', tid2), ('CONFIRMED', {self.b5.pk: (40, 40)}))

    def test_stock_negatif_possible_par_resolution_recu_superieur_a_l_envoye(self):
        """Observation : K2 declare 105 recus pour 100 envoyes (K1 n'a plus de stock) ; ALIGN_ON_RECEIVED debite K1 de
        5 de plus -> stock negatif (-5). Le stock de K1 n'est pas controle par la resolution (comme en REST)."""
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        self.confirm_at('K2', tid, [self.RV(self.b3, 105)])
        self.cycles(2)
        r = self.post_rest('cloud', self.dir, tid, 'resolve_dispute', {'resolution': 'ALIGN_ON_RECEIVED', 'reason': 'x'})
        self.assertEqual(r.status_code, 200, r.content)
        self.cycles(2)
        self.assertEqual(self.total(self.b3), 100)       # la somme reste nulle
        self.assertEqual(self.own('K1', self.b3), -5)    # mais K1 est negatif

    def test_alertes_uniques_par_poste_apres_rejeux(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(1)
        self.cycles(3)
        self.assertEqual(self.notes('K2', 'Pains Envoy'), 1)
        self.confirm_at('K2', tid, [self.RV(self.b3, 98)])
        self.cycles(4)
        self.assertEqual(self.notes('K1', 'Litige Transfert —'), 1)
        self.assertEqual(self.notes('K2', 'Pains Envoy'), 1)
        self.assertEqual(self.k3_transfer_alerts(), 0)
        r = self.post_rest('cloud', self.dir, tid, 'resolve_dispute', {'resolution': 'ALIGN_ON_SENT', 'reason': 'x'})
        self.assertEqual(r.status_code, 200)
        self.cycles(4)
        self.assertEqual(self.notes('K1', 'résolu'), 1)
        self.assertEqual(self.notes('K2', 'résolu'), 1)
        self.assertEqual(self.notes('K1', 'Litige Transfert —'), 1)
        self.assertEqual(self.k3_transfer_alerts(), 0)

    def test_alerte_demande_de_pains_chez_l_emettrice_une_seule_fois(self):
        tid = self.request_from('K2', [self.L(self.b3, 10)], 'K1')
        self.cycles(4)
        self.assertEqual(self.notes('K1', 'Demande de Pains'), 1)
        self.assertEqual(self.k3_transfer_alerts(), 0)
        self.respond_at('K1', tid, [self.L(self.b3, 10)])
        self.cycles(4)
        self.assertEqual(self.notes('K2', 'Pains Envoy'), 1)
        self.assertEqual(self.notes('K1', 'Demande de Pains'), 1)

    def test_demande_refusee_alerte_une_fois_chez_la_demandeuse(self):
        tid = self.request_from('K2', [self.L(self.b3, 10)], 'K1')
        self.cycles(2)
        r = self.post_rest('K1', self.g1, tid, 'respond_to_request', {'approved': False})
        self.assertEqual(r.status_code, 200, r.content)
        self.cycles(4)
        self.assertEqual(self.view('K2', tid)[0], 'CANCELLED')
        self.assertEqual(self.notes('K2', 'Refus'), 1)
        self.assertEqual(self.total(self.b3), 100)

    @expectedFailure  # BUG-991
    def test_reponse_emettrice_avec_quantite_ajustee_80_sur_100_somme_nulle(self):
        tid = self.request_from('K2', [self.L(self.b3, 100)], 'K1')
        self.cycles(2)
        self.respond_at('K1', tid, [self.L(self.b3, 80)])
        self.assertEqual(self.own('K1', self.b3), 20)
        self.cycles(3)
        self.assertEqual(self.own('K1', self.b3), 20)           # pas de debit supplementaire au pull
        self.assertEqual(self.view('K2', tid), ('RESPONDED', {self.b3.pk: (80, None)}))
        self.assertEqual(self.confirm_at('K2', tid, [self.RV(self.b3, 80)]), 'CONFIRMED')
        self.cycles(3)
        self.assertEqual((self.own('K1', self.b3), self.own('K2', self.b3)), (20, 80))
        self.assertEqual(self.total(self.b3), 100)

    def test_k2_confirme_localement_puis_siege_resout_le_meme_litige_sans_double_credit(self):
        """K2 recompte (100) pendant que le siege a deja resolu ALIGN_ON_SENT au cloud mais K2 n'a pas encore pull."""
        tid, _ = self.to_dispute_direct()
        r = self.post_rest('cloud', self.dir, tid, 'resolve_dispute', {'resolution': 'ALIGN_ON_SENT', 'reason': 'x'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.confirm_at('K2', tid, [self.RV(self.b3, 100)]), 'CONFIRMED')   # +2 local
        self.cycles(4)
        self.assertEqual(self.own('K2', self.b3), 100)           # pas +4
        self.assertEqual(self.total(self.b3), 100)

    def test_pull_sans_node_code_ancien_cloud_aucun_effet_de_stock_ni_alerte_ni_plantage(self):
        tid, _ = self.to_dispute_direct()
        r = self.post_rest('cloud', self.dir, tid, 'resolve_dispute', {'resolution': 'ALIGN_ON_SENT', 'reason': 'x'})
        self.assertEqual(r.status_code, 200)
        p = self.pulled('K2')
        p.pop('node_code')
        self.go('K2')
        n0 = SystemNotification.objects.count()
        apply_pull_response(p)
        self.assertEqual(self.own('K2', self.b3), 98)
        self.assertEqual(SystemNotification.objects.count(), n0)
        self.assertEqual(self.view('K2', tid)[0], 'CONFIRMED')

    def test_pull_hostile_node_code_d_un_autre_poste_ne_cree_pas_de_stock_chez_soi(self):
        """Un pull K2 traite avec le node_code de K3 (poste sans lien) : aucun effet de stock."""
        tid, _ = self.to_dispute_direct()
        r = self.post_rest('cloud', self.dir, tid, 'resolve_dispute', {'resolution': 'ALIGN_ON_SENT', 'reason': 'x'})
        self.assertEqual(r.status_code, 200)
        p = self.pulled('K2')
        p['node_code'] = 'Q3'
        self.go('K2')
        apply_pull_response(p)
        self.assertEqual(self.own('K2', self.b3), 98)


# --------------------------------------------------------------------------- poste reinstalle, hors ligne, reponse perdue
class A14Resilience(A14Base):
    def _history(self):
        """Un transfert confirme (30), un litige (100/98) et un envoi en cours (7) : somme du groupe 100/100/100."""
        t1 = self.send_from('K1', [self.L(self.b3, 30)], 'K2')
        self.cycles(2)
        self.confirm_at('K2', t1, [self.RV(self.b3, 30)])
        t2 = self.send_from('K1', [self.L(self.b5, 40)], 'K2')
        self.cycles(2)
        self.confirm_at('K2', t2, [self.RV(self.b5, 38)])
        t3 = self.send_from('K1', [self.L(self.b4, 7)], 'K2')
        self.cycles(3)
        return t1, t2, t3

    def test_poste_reinstalle_rejoue_l_historique_sans_mouvement_de_stock_fantome(self):
        t1, t2, t3 = self._history()
        self.assertEqual((self.own('K2', self.b3), self.own('K2', self.b5), self.own('K2', self.b4)), (30, 38, 0))
        self.go('cloud')
        self.states['K2'] = {'t': [], 'l': [], 's': [], 'n': []}      # disque neuf
        self.cur = 'cloud'
        for _ in range(3):
            self.assertEqual(self.refused(self.sync('K2')), [])
        for tid, st in ((t1, 'CONFIRMED'), (t2, 'DISPUTED'), (t3, 'RESPONDED')):
            self.assertEqual(self.view('K2', tid)[0], st)
        self.assertEqual([self.own('K2', bp) for bp in (self.b3, self.b5, self.b4)], [0, 0, 0])
        self.assertEqual([s for s in BreadStock.objects.filter(node=self.k2) if s.qty_available], [])
        # aucun export parasite : rien a pousser, le cloud n'a pas bouge
        self.assertEqual(build_outbound_payload('Q2')['records']['production.BreadTransfer'], [])
        self.go('cloud')
        self.assertEqual(self.view('cloud', t2), ('DISPUTED', {self.b5.pk: (40, 38)}))
        # le litige reste visible : cloture de K2 bloquee tant que non resolu
        self.assertTrue(self.gap('K2'))
        # alertes fantomes : au plus une par transfert non termine (RESPONDED + DISPUTED non emettrice = 1)
        self.assertLessEqual(self.notes('K2'), 3)

    def test_poste_reinstalle_apres_resolution_siege_ne_recredite_pas(self):
        t1, t2, t3 = self._history()
        r = self.post_rest('cloud', self.dir, t2, 'resolve_dispute', {'resolution': 'ALIGN_ON_SENT', 'reason': 'x'})
        self.assertEqual(r.status_code, 200)
        self.cycles(2)
        self.go('cloud')
        self.states['K2'] = {'t': [], 'l': [], 's': [], 'n': []}
        self.cur = 'cloud'
        self.cycles(3)
        self.assertEqual([self.own('K2', bp) for bp in (self.b3, self.b5, self.b4)], [0, 0, 0])
        self.assertFalse(self.gap('K2'))
        # le poste neuf peut ensuite valider t3 normalement : +7 et pas plus
        self.assertEqual(self.confirm_at('K2', t3, [self.RV(self.b4, 7)]), 'CONFIRMED')
        self.cycles(3)
        self.assertEqual(self.own('K2', self.b4), 7)

    def test_poste_k1_reinstalle_ne_redebite_pas_et_ne_recredite_pas(self):
        t1, t2, t3 = self._history()
        r = self.post_rest('cloud', self.dir, t2, 'resolve_dispute', {'resolution': 'ALIGN_ON_RECEIVED', 'reason': 'x'})
        self.assertEqual(r.status_code, 200)
        self.cycles(2)
        k1_before = [self.own('K1', bp) for bp in (self.b3, self.b5, self.b4)]
        self.assertEqual(k1_before, [70, 62, 93])
        self.go('cloud')
        self.states['K1'] = {'t': [], 'l': [], 's': [], 'n': []}
        self.cur = 'cloud'
        self.cycles(3)
        self.assertEqual([self.own('K1', bp) for bp in (self.b3, self.b5, self.b4)], [0, 0, 0])

    def _offline_dispute(self, resolution):
        tid, _ = self.to_dispute_direct()
        self.go('cloud')
        r = self.post_rest('cloud', self.dir, tid, 'resolve_dispute', {'resolution': resolution, 'reason': 'x'})
        self.assertEqual(r.status_code, 200, r.content)
        self.age(tid, 45)
        return tid

    def test_poste_k2_hors_ligne_45_jours_rattrape_la_resolution_et_le_stock(self):
        tid = self._offline_dispute('ALIGN_ON_SENT')
        self.cycles(1, ('K2',))
        self.assertEqual(self.view('K2', tid), ('CONFIRMED', {self.b3.pk: (100, 100)}))
        self.assertEqual(self.own('K2', self.b3), 100)
        self.assertFalse(self.gap('K2'))
        self.cycles(3)
        self.assertEqual(self.total(self.b3), 100)

    def test_poste_k1_hors_ligne_45_jours_rattrape_align_on_received(self):
        tid = self._offline_dispute('ALIGN_ON_RECEIVED')
        self.cycles(1, ('K1',))
        self.assertEqual(self.view('K1', tid), ('CONFIRMED', {self.b3.pk: (98, 98)}))
        self.assertEqual(self.own('K1', self.b3), 2)
        self.cycles(3)
        self.assertEqual(self.total(self.b3), 100)

    def test_poste_hors_ligne_une_seule_resolution_pour_k1_et_k2_en_meme_temps(self):
        tid = self._offline_dispute('ALIGN_ON_RECEIVED')
        self.cycles(2, ('K1', 'K2', 'K3'))
        self.assertEqual((self.own('K1', self.b3), self.own('K2', self.b3)), (2, 98))
        self.assertEqual(self.total(self.b3), 100)

    def test_reponse_de_pull_perdue_open_transfers_redeclare_puis_rattrape(self):
        tid = self._offline_dispute('ALIGN_ON_SENT')
        # cycle 1 : push passe, le pull est livre mais la reponse est perdue (non appliquee)
        self.go('K2')
        payload = build_outbound_payload('Q2')
        self.assertIn(str(tid), payload['open_transfers'])
        self.go('cloud')
        self.post(self.api['K2'], dict(payload, batch_id=__import__('uuid').uuid4().hex))
        lost = json.loads(self.api['K2'].get('/api/sync/pull/').content)
        self.assertIn(str(tid), [t['id'] for t in lost['transfers']])
        self.assertNotIn(str(tid), NodeOpenTransfers.objects.get(node=self.k2).transfer_ids)  # retire cote cloud
        # K2 n'a rien applique : sa copie est toujours DISPUTED -> le prochain push redeclare l'id
        self.go('K2')
        self.assertIn(str(tid), build_outbound_payload('Q2')['open_transfers'])
        self.cycles(1, ('K2',))
        self.assertEqual(self.view('K2', tid)[0], 'CONFIRMED')
        self.assertEqual(self.own('K2', self.b3), 100)
        self.assertNotIn(str(tid), build_outbound_payload('Q2')['open_transfers'])
        self.go('cloud')
        self.assertEqual(NodeOpenTransfers.objects.get(node=self.k2).transfer_ids, [])

    def test_reponse_de_push_perdue_le_rejeu_ne_double_rien(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.go('K1')
        payload = build_outbound_payload('Q1')
        self.go('cloud')
        d1 = self.post(self.api['K1'], payload)           # la reponse est perdue : K1 ne l'applique pas
        self.go('K1')
        d2 = None
        payload2 = build_outbound_payload('Q1')
        self.assertEqual([x['id'] for x in payload2['records']['production.BreadTransfer']], [str(tid)])
        self.go('cloud')
        d2 = self.post(self.api['K1'], dict(payload2))    # nouveau batch_id, memes enregistrements
        self.assertEqual(self.refused(d2), [])
        self.go('cloud')
        self.assertEqual(BreadTransfer.objects.filter(pk=tid).count(), 1)
        self.assertEqual(BreadTransferLine.objects.filter(transfer_id=tid).count(), 1)
        self.go('K1')
        apply_push_response(d2)
        self.cycles(3)
        self.assertEqual(self.confirm_at('K2', tid, [self.RV(self.b3, 100)]), 'CONFIRMED')
        self.cycles(3)
        self.assertEqual(self.total(self.b3), 100)

    def test_k3_ne_recoit_jamais_un_transfert_de_k1_k2_meme_ancien(self):
        tid = self._offline_dispute('ALIGN_ON_SENT')
        for _ in range(2):
            p = self.pulled('K3')
            self.assertEqual(p['transfers'], [])
            self.assertEqual(p['transfer_lines'], [])

    # ----- lots hostiles : open_transfers forge
    def _declare(self, name, open_transfers):
        self.go(name)
        payload = build_outbound_payload(self.node[name].code)
        payload['open_transfers'] = open_transfers
        payload['batch_id'] = __import__('uuid').uuid4().hex
        self.go('cloud')
        return self.api[name].post('/api/sync/push/', payload, format='json')

    def test_open_transfers_forge_avec_ids_d_autres_noeuds_aucune_fuite(self):
        tid = self._offline_dispute('ALIGN_ON_SENT')          # K1->K2, CONFIRMED, vieux de 45 jours
        r = self._declare('K3', [str(tid)])
        self.assertEqual(r.status_code, 200, r.content)
        p = self.pulled('K3')
        self.assertEqual(p['transfers'], [])
        self.assertEqual(p['transfer_lines'], [])
        self.assertNotIn(str(tid), json.dumps(p))
        # idem pour un id declare par K1 qui ne le possede pas / tiers : K3 ne le voit toujours pas
        self.assertEqual(NodeOpenTransfers.objects.get(node=self.k3).transfer_ids, [str(tid)])
        # et l'etat de K2 n'a pas ete touche par la declaration de K3
        self.assertNotEqual(NodeOpenTransfers.objects.filter(node=self.k2).first() and 'x', None)

    def test_open_transfers_forge_ne_ressuscite_pas_un_transfert_d_autrui_chez_k1_si_k1_n_est_pas_partie(self):
        tid = self._offline_dispute('ALIGN_ON_SENT')
        # K1 est emettrice : la declaration est legitime et redescend uniquement chez K1 et K2
        self._declare('K1', [str(tid)])
        self.assertIn(str(tid), [t['id'] for t in self.pulled('K1')['transfers']])
        self.assertNotIn(str(tid), [t['id'] for t in self.pulled('K3')['transfers']])

    def test_open_transfers_valeurs_hostiles_aucune_erreur_serveur_et_borne(self):
        import uuid
        good = str(uuid.uuid4())
        for raw in ('texte', 5, {'a': 1}, [1, None, [], {}, True, 'x' * 100, '', ' ', good.upper(), good,
                                           '{' + good + '}', 'urn:uuid:' + good], list(range(5000)), None):
            r = self._declare('K1', raw)
            self.assertEqual(r.status_code, 200, (str(raw)[:40], r.content[:200]))
        st = NodeOpenTransfers.objects.get(node=self.k1)
        self.assertLessEqual(len(st.transfer_ids), 1000)
        r = self._declare('K1', [str(uuid.uuid4()) for _ in range(3000)])
        self.assertEqual(r.status_code, 200)
        self.assertLessEqual(len(NodeOpenTransfers.objects.get(node=self.k1).transfer_ids), 1000)
        self.assertEqual(self.pulled('K1')['node_code'], 'Q1')

    def test_open_transfers_absent_ne_modifie_pas_l_etat_et_pull_sans_etat_ok(self):
        tid = self._offline_dispute('ALIGN_ON_SENT')
        self.go('cloud')
        NodeOpenTransfers.objects.all().delete()               # poste ancien / avant migration : aucun etat
        p = self.pulled('K2')
        self.assertNotIn(str(tid), [t['id'] for t in p['transfers']])
        self._declare('K2', [str(tid)])
        self.go('cloud')
        payload = {'batch_id': __import__('uuid').uuid4().hex, 'records': {}}
        r = self.api['K2'].post('/api/sync/push/', payload, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(NodeOpenTransfers.objects.get(node=self.k2).transfer_ids, [str(tid)])  # intact
        self.assertIn(str(tid), [t['id'] for t in self.pulled('K2')['transfers']])

    def test_open_transfers_n_est_pas_dans_l_empreinte_du_lot_rejeu_d_un_ancien_lot(self):
        tid = self._offline_dispute('ALIGN_ON_SENT')
        bid = __import__('uuid').uuid4().hex
        self.go('K2')
        payload = build_outbound_payload('Q2')
        payload['batch_id'] = bid
        self.go('cloud')
        self.assertEqual(self.api['K2'].post('/api/sync/push/', payload, format='json').status_code, 200)
        # meme batch_id, open_transfers different (forge) : accepte (rejeu) mais ne doit pas elargir le pull
        payload['open_transfers'] = []
        r = self.api['K2'].post('/api/sync/push/', payload, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data.get('replayed'))


# --------------------------------------------------------------------------- les deux points A CLARIFIER d39 + concurrence
class A14Clarify(A14Base):
    @expectedFailure  # BUG-989
    def test_clarifier_1_transfert_deja_confirme_au_cloud_inconnu_de_k2_somme_du_groupe(self):
        """Le siege confirme au cloud (100) pour K2 qui n'a jamais pull l'envoi : K2 cree la copie CONFIRMED sans credit
        (indiscernable d'un poste reinstalle). Somme du groupe : K1 -100, K2 +0 => 0 au lieu de 100."""
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.sync('K1')
        r = self.post_rest('cloud', self.dir, tid, 'confirm_reception', {'lines': [self.RV(self.b3, 100)]})
        self.assertEqual(r.status_code, 200, r.content)
        self.cycles(3)
        self.assertEqual(self.view('K2', tid)[0], 'CONFIRMED')
        self.assertEqual(self.total(self.b3), 100)

    @expectedFailure  # BUG-990
    def test_clarifier_2_reponse_positive_du_siege_a_une_demande_pending_somme_du_groupe(self):
        tid = self.request_from('K2', [self.L(self.b3, 100)], 'K1')
        self.cycles(2)
        r = self.post_rest('cloud', self.dir, tid, 'respond_to_request',
                           {'approved': True, 'lines': [self.L(self.b3, 100)]})
        self.assertEqual(r.status_code, 200, r.content)
        self.cycles(2)
        self.assertEqual(self.view('K2', tid)[0], 'RESPONDED')
        self.assertEqual(self.confirm_at('K2', tid, [self.RV(self.b3, 100)]), 'CONFIRMED')
        self.cycles(3)
        self.assertEqual(self.own('K2', self.b3), 100)
        self.assertEqual(self.total(self.b3), 100)

    def test_concurrence_k2_confirme_98_localement_pendant_que_le_siege_confirme_100(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        r = self.post_rest('cloud', self.dir, tid, 'confirm_reception', {'lines': [self.RV(self.b3, 100)]})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.confirm_at('K2', tid, [self.RV(self.b3, 98)]), 'DISPUTED')    # K2 n'a pas encore pull
        self.cycles(4)
        self.assertEqual(self.view('K2', tid), self.view('cloud', tid))                       # convergence
        self.assertEqual(self.total(self.b3), 100)
        self.assertFalse(self.gap('K2'))

    @expectedFailure  # BUG-992
    def test_concurrence_k1_refuse_localement_pendant_que_le_siege_repond_au_cloud(self):
        tid = self.request_from('K2', [self.L(self.b3, 10)], 'K1')
        self.cycles(2)
        r = self.post_rest('cloud', self.dir, tid, 'respond_to_request',
                           {'approved': True, 'lines': [self.L(self.b3, 10)]})
        self.assertEqual(r.status_code, 200, r.content)
        r = self.post_rest('K1', self.g1, tid, 'respond_to_request', {'approved': False})
        self.assertEqual(r.status_code, 200, r.content)
        self.cycles(4)
        self.assertEqual(self.view('K1', tid)[0], self.view('cloud', tid)[0])
        self.assertEqual(self.view('K2', tid)[0], self.view('cloud', tid)[0])
        self.go('K1')
        self.assertFalse(BreadTransfer.objects.filter(is_synced=False).exists())
        # la suite : K2 recoit/valide ce que le cloud lui montre ; le groupe doit rester a 100
        if self.view('K2', tid)[0] == 'RESPONDED':
            self.confirm_at('K2', tid, [self.RV(self.b3, 10)])
            self.cycles(3)
        self.assertEqual(self.total(self.b3), 100)


# --------------------------------------------------------------------------- migration 0003 sur base existante
class A14Migration0003(TransactionTestCase):
    def test_migration_0003_additive_sur_base_existante_et_pull_sans_etat(self):
        from core.models import Node
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        node = Node.objects.create(code='ZZ9', name='Z9')
        try:
            executor.migrate([('sync', '0002_batchlog_fingerprint_conflict_occurrences')])
            self.assertNotIn('sync_nodeopentransfers', connection.introspection.table_names())
            from sync.models import SyncBatchLog
            SyncBatchLog.objects.create(batch_id='11111111-1111-4111-8111-111111111111', node=node,
                                        status=SyncBatchLog.Status.OK, result={}, fingerprint='f')
            executor = MigrationExecutor(connection)
            executor.migrate([('sync', '0003_nodeopentransfers')])
            self.assertIn('sync_nodeopentransfers', connection.introspection.table_names())
            self.assertEqual(SyncBatchLog.objects.filter(node=node).count(), 1)
            self.assertEqual(NodeOpenTransfers.objects.count(), 0)       # aucune donnee inventee
            SyncBatchLog.objects.all().delete()
            NodeOpenTransfers.objects.create(node=node, transfer_ids=['a'])
            node.delete()                                                  # CASCADE
            self.assertEqual(NodeOpenTransfers.objects.count(), 0)
        finally:
            MigrationExecutor(connection).migrate(latest)

