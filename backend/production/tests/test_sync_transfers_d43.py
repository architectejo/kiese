"""Architecte-sync d43 : complements de BUG-989 a 992 (conflits de precedence tracés, marqueur de miroir)."""
from production.tests.test_verif_production_a14_v14 import A14Base
from sync.models import SyncConflictLog, TransferMirror


class D43Conflicts(A14Base):
    def test_992_conflit_trace_au_journal_et_poste_non_bloque(self):
        tid = self.request_from('K2', [self.L(self.b3, 10)], 'K1')
        self.cycles(2)
        r = self.post_rest('cloud', self.dir, tid, 'respond_to_request',
                           {'approved': True, 'lines': [self.L(self.b3, 10)]})
        self.assertEqual(r.status_code, 200, r.content)
        r = self.post_rest('K1', self.g1, tid, 'respond_to_request', {'approved': False})
        self.assertEqual(r.status_code, 200, r.content)
        self.cycles(3)
        self.go('cloud')
        conflits = SyncConflictLog.objects.filter(model_label='production.BreadTransfer', object_id=str(tid))
        self.assertEqual(conflits.count(), 1)
        self.assertEqual(conflits.first().conflict_type, 'TRANSFER_STATE_CONFLICT')
        self.assertEqual(self.own('K1', self.b3), 90)    # reponse du siege appliquee une seule fois

    def test_992_inverse_siege_refuse_pendant_que_k1_repond_stock_restitue(self):
        tid = self.request_from('K2', [self.L(self.b3, 10)], 'K1')
        self.cycles(2)
        self.respond_at('K1', tid, [self.L(self.b3, 10)])
        self.assertEqual(self.own('K1', self.b3), 90)
        r = self.post_rest('cloud', self.dir, tid, 'respond_to_request', {'approved': False})
        self.assertEqual(r.status_code, 200, r.content)
        self.cycles(4)
        for n in ('K1', 'K2'):
            self.assertEqual(self.view(n, tid)[0], 'CANCELLED', n)
        self.assertEqual(self.own('K1', self.b3), 100)   # stock restitue
        self.assertEqual(self.total(self.b3), 100)

    def test_989_marqueur_miroir_enregistre_puis_poste_reinstalle_ne_recredite_pas(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.sync('K1')
        r = self.post_rest('cloud', self.dir, tid, 'confirm_reception', {'lines': [self.RV(self.b3, 100)]})
        self.assertEqual(r.status_code, 200, r.content)
        self.cycles(3)
        self.assertEqual(self.own('K2', self.b3), 100)
        self.go('cloud')
        self.assertEqual(TransferMirror.objects.get(node=self.k2, transfer_id=tid).applied, {str(self.b3.pk): [0, 100]})
        self.states['K2'] = {'t': [], 'l': [], 's': [], 'n': []}     # poste reinstalle
        self.cycles(3)
        self.assertEqual(self.own('K2', self.b3), 0)

    def test_marqueur_forge_par_un_tiers_ignore(self):
        import uuid
        tid = self.send_from('K1', [self.L(self.b3, 10)], 'K2')
        self.sync('K1')
        self.go('K3')
        payload = __import__('sync.management.commands.sync_now', fromlist=['x']).build_outbound_payload('Q3')
        payload['mirrors'] = {str(tid): {str(self.b3.pk): [0, 10]}, 'pas-un-uuid': {}, str(uuid.uuid4()): 5}
        payload['batch_id'] = uuid.uuid4().hex
        self.go('cloud')
        r = self.api['K3'].post('/api/sync/push/', payload, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(TransferMirror.objects.filter(node=self.k3).count(), 0)
