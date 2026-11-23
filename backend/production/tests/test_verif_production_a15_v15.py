"""Testeur-production (cycle 16 / a15) : verification independante de BUG-989 a 992 (d43) sur le banc
K1/K2/K3 + cloud (A14Base). Mesure : somme des stocks propres du groupe (`total`) = 100 par categorie."""
import uuid
from unittest import expectedFailure

from production.tests.test_verif_production_a14_v14 import A14Base
from sync.management.commands.sync_now import apply_pull_response, build_outbound_payload
from sync.models import SyncConflictLog, TransferMirror


def blank():
    return {'t': [], 'l': [], 's': [], 'n': []}


class A15Base(A14Base):
    def reinstall(self, name):
        self.states[name] = blank()
        if self.cur == name:
            self._load(self.states[name])

    def forge(self, name, mirrors):
        self.go(name)
        p = build_outbound_payload(self.node[name].code)
        p['mirrors'] = mirrors
        p['batch_id'] = uuid.uuid4().hex
        self.go('cloud')
        return self.api[name].post('/api/sync/push/', p, format='json')

    def resolve(self, tid, how):
        r = self.post_rest('cloud', self.dir, tid, 'resolve_dispute', {'resolution': how, 'reason': 'x'})
        self.assertEqual(r.status_code, 200, r.content)


class A15Verif(A15Base):
    def test_989_envoi_confirme_par_le_siege_inconnu_de_k2(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.sync('K1')
        r = self.post_rest('cloud', self.dir, tid, 'confirm_reception', {'lines': [self.RV(self.b3, 100)]})
        self.assertEqual(r.status_code, 200, r.content)
        self.cycles(3)
        self.assertEqual((self.own('K1', self.b3), self.own('K2', self.b3)), (0, 100))
        self.assertEqual(self.total(self.b3), 100)

    def test_990_reponse_du_siege_demande_pending_debit_unique(self):
        tid = self.request_from('K2', [self.L(self.b3, 100)], 'K1')
        self.cycles(2)
        r = self.post_rest('cloud', self.dir, tid, 'respond_to_request',
                           {'approved': True, 'lines': [self.L(self.b3, 100)]})
        self.assertEqual(r.status_code, 200, r.content)
        self.cycles(4)
        self.assertEqual(self.own('K1', self.b3), 0)
        self.confirm_at('K2', tid, [self.RV(self.b3, 100)])
        self.cycles(4)
        self.assertEqual(self.total(self.b3), 100)

    def test_991_quantite_ajustee_puis_litige_puis_resolution_siege(self):
        tid = self.request_from('K2', [self.L(self.b3, 100)], 'K1')
        self.cycles(2)
        self.respond_at('K1', tid, [self.L(self.b3, 80)])
        self.cycles(3)
        self.assertEqual(self.view('cloud', tid), ('RESPONDED', {self.b3.pk: (80, None)}))
        self.assertEqual(self.confirm_at('K2', tid, [self.RV(self.b3, 78)]), 'DISPUTED')
        self.cycles(3)
        self.assertEqual(self.total(self.b3), 98)
        self.resolve(tid, 'ALIGN_ON_SENT')
        self.cycles(4)
        self.assertEqual((self.own('K1', self.b3), self.own('K2', self.b3)), (20, 80))
        self.assertEqual(self.total(self.b3), 100)

    def test_991_ajuste_puis_align_on_received_somme_nulle(self):
        tid = self.request_from('K2', [self.L(self.b3, 100)], 'K1')
        self.cycles(2)
        self.respond_at('K1', tid, [self.L(self.b3, 80)])
        self.cycles(2)
        self.confirm_at('K2', tid, [self.RV(self.b3, 78)])
        self.cycles(2)
        self.resolve(tid, 'ALIGN_ON_RECEIVED')
        self.cycles(4)
        self.assertEqual((self.own('K1', self.b3), self.own('K2', self.b3)), (22, 78))
        self.assertEqual(self.total(self.b3), 100)

    def test_992_annulation_apres_reponse_ordre_inverse_des_cycles(self):
        tid = self.request_from('K2', [self.L(self.b3, 10)], 'K1')
        self.cycles(2)
        r = self.post_rest('cloud', self.dir, tid, 'respond_to_request',
                           {'approved': True, 'lines': [self.L(self.b3, 10)]})
        self.assertEqual(r.status_code, 200)
        self.post_rest('K1', self.g1, tid, 'respond_to_request', {'approved': False})
        self.cycles(4, ('K3', 'K2', 'K1'))
        if self.view('K2', tid)[0] == 'RESPONDED':
            self.confirm_at('K2', tid, [self.RV(self.b3, 10)])
        self.cycles(4)
        self.assertEqual(self.total(self.b3), 100)
        self.go('cloud')
        self.assertEqual(SyncConflictLog.objects.filter(conflict_type='TRANSFER_STATE_CONFLICT').count(), 1)

    def test_combo_poste_k2_reinstalle_en_cours_de_transfert_puis_valide(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(3)
        self.reinstall('K2')
        self.cycles(3)
        self.assertEqual(self.own('K2', self.b3), 0)
        self.assertEqual(self.confirm_at('K2', tid, [self.RV(self.b3, 100)]), 'CONFIRMED')
        self.cycles(4)
        self.assertEqual((self.own('K1', self.b3), self.own('K2', self.b3)), (0, 100))
        self.assertEqual(self.total(self.b3), 100)

    def test_combo_poste_k1_reinstalle_apres_reponse_ajustee(self):
        tid = self.request_from('K2', [self.L(self.b3, 100)], 'K1')
        self.cycles(2)
        self.respond_at('K1', tid, [self.L(self.b3, 80)])
        self.cycles(3)
        self.reinstall('K1')
        self.cycles(3)
        self.assertEqual(self.own('K1', self.b3), 0)       # pas de re-debit fantome
        self.confirm_at('K2', tid, [self.RV(self.b3, 80)])
        self.cycles(4)
        self.assertEqual((self.own('K1', self.b3), self.own('K2', self.b3)), (0, 80))

    def test_combo_transferts_croises_k1_k2_et_k2_k1(self):
        a = self.send_from('K1', [self.L(self.b3, 30)], 'K2')
        self.cycles(2)
        self.confirm_at('K2', a, [self.RV(self.b3, 30)])
        self.cycles(2)
        b = self.send_from('K2', [self.L(self.b3, 10)], 'K1')
        self.cycles(2)
        self.confirm_at('K1', b, [self.RV(self.b3, 9)])
        self.cycles(4)
        self.assertEqual(self.total(self.b3), 99)
        self.resolve(b, 'ALIGN_ON_SENT')
        self.cycles(4)
        self.assertEqual(self.total(self.b3), 100)

    def test_combo_rejeu_reponses_perdues_dans_les_deux_sens(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.go('K1')
        p = build_outbound_payload('Q1')
        self.go('cloud')
        self.post(self.api['K1'], dict(p, batch_id=uuid.uuid4().hex))      # reponse de push perdue
        self.api['K1'].get('/api/sync/pull/')                              # pull perdu
        self.cycles(2)
        self.confirm_at('K2', tid, [self.RV(self.b3, 98)])
        self.go('K2')
        p = build_outbound_payload('Q2')
        self.go('cloud')
        self.post(self.api['K2'], dict(p, batch_id=uuid.uuid4().hex))
        self.post(self.api['K2'], dict(p, batch_id=uuid.uuid4().hex))      # rejeu, nouveau lot
        self.api['K2'].get('/api/sync/pull/')                              # pull perdu
        self.cycles(4)
        self.assertEqual(self.total(self.b3), 98)
        self.resolve(tid, 'ALIGN_ON_SENT')
        self.cycles(4)
        self.assertEqual(self.total(self.b3), 100)

    def test_cloud_ancien_sans_mirrors_envoi_en_cours_reste_coherent(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.sync('K1')
        p = self.pulled('K2')
        p.pop('mirrors')
        self.go('K2')
        apply_pull_response(p)
        self.assertEqual(self.view('K2', tid)[0], 'RESPONDED')
        self.assertEqual(self.own('K2', self.b3), 0)
        self.confirm_at('K2', tid, [self.RV(self.b3, 100)])
        self.cycles(4)
        self.assertEqual(self.total(self.b3), 100)

    def test_cloud_ancien_envoi_deja_confirme_inconnu_de_k2_limite_documentee(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.sync('K1')
        self.post_rest('cloud', self.dir, tid, 'confirm_reception', {'lines': [self.RV(self.b3, 100)]})
        p = self.pulled('K2')
        p.pop('mirrors')
        self.go('K2')
        apply_pull_response(p)
        self.assertEqual(self.total(self.b3), 0)      # limite annoncee : 100 pains perdus (cloud ancien)

    def test_mirrors_hostiles_aucune_erreur_et_aucun_marqueur_parasite(self):
        tid = self.send_from('K1', [self.L(self.b3, 10)], 'K2')
        self.sync('K1')
        bp = str(self.b3.pk)
        big = {str(uuid.uuid4()): {bp: [0, 1]} for _ in range(700)}
        for raw in ('x', 5, None, [], {'a': 1}, big, {str(tid): 'x'}, {str(tid): {'x': [1, 2]}},
                    {str(tid): {bp: [1.5, 2]}}, {str(tid): {bp: [True, 2]}}, {str(tid): {bp: [-1, 0]}},
                    {str(tid): {bp: [10 ** 30, 0]}}, {str(tid): {bp: [1, 2, 3]}}, {str(tid): {'9' * 400: [0, 0]}},
                    {str(tid): {'٣': [0, 0]}}):
            r = self.forge('K3', raw)
            self.assertEqual(r.status_code, 200, (str(raw)[:60], r.content[:200]))
        self.go('cloud')
        self.assertEqual(TransferMirror.objects.filter(node=self.k3).count(), 0)
        for raw in ('x', 5, {str(tid): {bp: [10 ** 30, 0]}}, {str(tid): {bp: [1.5, 2]}}):
            self.assertEqual(self.forge('K2', raw).status_code, 200)
        self.cycles(2)
        self.assertEqual(self.total(self.b3), 90)    # 10 en transit
        self.confirm_at('K2', tid, [self.RV(self.b3, 10)])
        self.cycles(3)
        self.assertEqual(self.total(self.b3), 100)

    @expectedFailure  # BUG-997
    def test_mirror_forge_par_k2_plus_grand_que_la_quantite_puis_reinstallation(self):
        """Marqueur K2 [0, 1000] pour un envoi de 100 : un poste reinstalle ne doit pas etre debite de 900."""
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        self.assertEqual(self.forge('K2', {str(tid): {str(self.b3.pk): [0, 1000]}}).status_code, 200)
        self.reinstall('K2')
        self.cycles(3)
        self.assertGreaterEqual(self.own('K2', self.b3), 0)

    def test_stock_negatif_apres_resolution_recu_superieur_a_l_envoye_somme_nulle(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.cycles(2)
        self.confirm_at('K2', tid, [self.RV(self.b3, 105)])
        self.cycles(3)
        self.resolve(tid, 'ALIGN_ON_RECEIVED')
        self.cycles(4)
        self.assertEqual((self.own('K1', self.b3), self.own('K2', self.b3)), (-5, 105))
        self.assertEqual(self.total(self.b3), 100)
