"""Testeur-production (cycle 14 / a13) : verification independante de BUG-964 a 968 (d35) et cycles de
synchronisation de transferts sur trois postes simules K1/K2/K3 (Q1/Q2/Q3) + un cloud, par `sync_now`
(export `build_outbound_payload`, push, pull, `apply_push_response`, `apply_pull_response`).
Donnees fictives. Les `@expectedFailure` referencent leur ticket.

Simulation : une seule base de test ; l'etat (transferts, lignes, stocks de pains, notifications) de chaque
poste et du cloud est sauvegarde puis recharge a chaque changement de « site » (`go`). Un poste n'a donc
jamais connaissance de l'etat du cloud sauf par push/pull, et ses actions REST n'ont d'effet de stock que
chez lui.
"""
import json
from datetime import timedelta
from unittest import expectedFailure

from django.utils import timezone

from core.models import BreadPrice, SystemNotification
from production.models import BreadDisposal, BreadStock, BreadTransfer, BreadTransferLine, ProductionSession
from production.tests.test_verif_a4_testeur_production import T, cl
from production.tests.test_verif_production_a12_v12 import V12Base
from production.tests.test_verif_production_a8_v8 import push, uid
from production.tests.test_verif_production_a9_v9 import LBL_S, LBL_T, LBL_TL
from sync.management.commands.sync_now import (apply_pull_response, apply_push_response,
                                               build_outbound_payload)
from treasury.views import _unresolved_incoming_transfer_gap

TS = BreadTransfer.TransferStatus


class P13Base(V12Base):
    SITES = ('cloud', 'K1', 'K2', 'K3')

    def setUp(self):
        super().setUp()
        self.cur = 'cloud'
        self.states = {n: self._dump() for n in self.SITES}
        self.api = {'K1': self.a1, 'K2': self.a2, 'K3': self.a3}
        self.node = {'K1': self.k1, 'K2': self.k2, 'K3': self.k3}
        self.ger = {'K1': self.g1, 'K2': self.g2, 'K3': self.g3}

    # ---- etat des sites
    def _dump(self):
        return {'t': list(BreadTransfer.objects.values()), 'l': list(BreadTransferLine.objects.values()),
                's': list(BreadStock.objects.values()), 'n': list(SystemNotification.objects.values())}

    def _load(self, st):
        BreadTransfer.objects.all().delete()
        BreadStock.objects.all().delete()
        SystemNotification.objects.all().delete()
        BreadTransfer.objects.bulk_create([BreadTransfer(**r) for r in st['t']])
        for r in st['t']:
            BreadTransfer.objects.filter(pk=r['id']).update(updated_at=r['updated_at'], created_at=r['created_at'])
        BreadTransferLine.objects.bulk_create([BreadTransferLine(**r) for r in st['l']])
        BreadStock.objects.bulk_create([BreadStock(**r) for r in st['s']])
        SystemNotification.objects.bulk_create([SystemNotification(**r) for r in st['n']])

    def go(self, name):
        if name != self.cur:
            self.states[self.cur] = self._dump()
            self._load(self.states[name])
            self.cur = name

    # ---- actions
    def sync(self, name):
        """Un cycle sync_now : export, push au cloud, pull du cloud, application locale."""
        self.go(name)
        payload = build_outbound_payload(self.node[name].code)
        self.go('cloud')
        data = self.post(self.api[name], dict(payload, batch_id=uid()))
        pr = self.api[name].get('/api/sync/pull/')
        self.assertEqual(pr.status_code, 200, pr.content)
        pulled = json.loads(pr.content)
        self.go(name)
        apply_push_response(data)
        apply_pull_response(pulled)
        return data

    def refused(self, data):
        return [(lbl, r.get('reason')) for lbl, rows in data['results'].items() for r in rows
                if r['status'] != 'ACCEPTED']

    def send_from(self, name, lines, to):
        self.go(name)
        r = cl(self.ger[name]).post(f'{T}send/', {'to_node': self.node[to].pk, 'lines': lines}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return r.data['id']

    def request_from(self, name, lines, frm):
        self.go(name)
        r = cl(self.ger[name]).post(T, {'from_node': self.node[frm].pk, 'lines': lines}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return r.data['id']

    def post_rest(self, name, user, tid, action, body):
        self.go(name)
        return cl(user).post(f'{T}{tid}/{action}/', body, format='json')

    def confirm_at(self, name, tid, lines):
        r = self.post_rest(name, self.ger[name], tid, 'confirm_reception', {'lines': lines})
        self.assertEqual(r.status_code, 200, r.content)
        return r.data['transfer_status']

    def respond_at(self, name, tid, lines):
        r = self.post_rest(name, self.ger[name], tid, 'respond_to_request', {'approved': True, 'lines': lines})
        self.assertEqual(r.status_code, 200, r.content)

    def RV(self, bp, q):
        return self.L(bp, q, 'quantity_received')

    # ---- lecture
    def view(self, name, tid):
        self.go(name)
        t = BreadTransfer.objects.filter(pk=tid).first()
        if t is None:
            return None
        return t.transfer_status, {l.bread_price_id: (l.quantity_sent, l.quantity_received) for l in t.lines.all()}

    def own(self, name, bp):
        self.go(name)
        return self.stock(self.node[name], bp)

    def total(self, bp):
        """Somme des stocks PROPRES de chaque poste (chaque poste ne voit/ne modifie que le sien)."""
        return sum(self.own(n, bp) for n in ('K1', 'K2', 'K3'))

    def gap(self, name):
        self.go(name)
        return bool(_unresolved_incoming_transfer_gap(self.node[name]))

    def to_dispute_direct(self, recv=98, sent=100):
        """K1 envoie `sent` (envoi direct) ; K2 recoit `recv` : litige. Tous les cycles joues."""
        tid = self.send_from('K1', [self.L(self.b3, sent)], 'K2')
        self.sync('K1')
        self.sync('K2')
        st = self.confirm_at('K2', tid, [self.RV(self.b3, recv)])
        self.sync('K2')
        self.sync('K1')
        return tid, st


# --------------------------------------------------------------------------- BUG-964 / 965 : verification
class A13Verif964965(P13Base):
    def test_964_pull_contient_transferts_et_lignes_pour_emettrice_et_receptrice_pas_pour_un_tiers(self):
        tid = self.send_from('K1', [self.L(self.b3, 30), self.L(self.b5, 20)], 'K2')
        self.sync('K1')
        self.go('cloud')
        for name, expected in (('K1', 1), ('K2', 1), ('K3', 0)):
            r = self.api[name].get('/api/sync/pull/')
            self.assertEqual(r.status_code, 200)
            ids = [t['id'] for t in r.data['transfers']]
            self.assertEqual(ids.count(str(tid)), expected, name)
            lines = [l for l in r.data['transfer_lines'] if l['transfer'] == str(tid)]
            self.assertEqual(len(lines), 2 * expected, name)
            if expected:
                tr = [t for t in r.data['transfers'] if t['id'] == str(tid)][0]
                self.assertEqual((tr['from_node'], tr['to_node'], tr['transfer_status']), ('Q1', 'Q2', 'RESPONDED'))

    def test_964_pull_recree_le_transfert_chez_la_receptrice_sans_mouvement_de_stock(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.assertEqual(self.own('K1', self.b3), 0)
        self.sync('K1')
        self.assertEqual(self.sync('K2') is not None, True)
        self.assertEqual(self.view('K2', tid), ('RESPONDED', {self.b3.pk: (100, None)}))
        self.assertEqual(self.own('K2', self.b3), 0)          # rien recu physiquement : pas de credit
        self.assertEqual(self.total(self.b3), 0)              # 100 en transit
        self.assertIsNone(self.view('K3', tid))
        self.sync('K3')
        self.assertIsNone(self.view('K3', tid))
        self.assertFalse(self.gap('K3'))

    def test_965_export_receptrice_apres_validation_et_pas_de_reexport_apres_succes(self):
        tid = self.send_from('K1', [self.L(self.b3, 30)], 'K2')
        self.sync('K1')
        self.sync('K2')
        self.go('K2')
        self.assertEqual(build_outbound_payload('Q2')['records']['production.BreadTransfer'], [])
        self.confirm_at('K2', tid, [self.RV(self.b3, 28)])
        ids = [x['id'] for x in build_outbound_payload('Q2')['records']['production.BreadTransfer']]
        self.assertEqual(ids, [str(tid)])
        lines = [x for x in build_outbound_payload('Q2')['records']['production.BreadTransferLine']]
        self.assertEqual([(l['quantity_sent'], l['quantity_received']) for l in lines], [(30, 28)])
        self.assertEqual(self.refused(self.sync('K2')), [])
        self.go('K2')
        self.assertEqual(build_outbound_payload('Q2')['records']['production.BreadTransfer'], [])
        self.assertEqual(self.view('cloud', tid), ('DISPUTED', {self.b3.pk: (30, 28)}))
        # K3 n'exporte jamais le transfert des autres
        self.go('K3')
        self.assertEqual(build_outbound_payload('Q3')['records']['production.BreadTransfer'], [])

    def test_965_emettrice_exporte_un_transfert_modifie_localement_apres_pull(self):
        tid = self.request_from('K2', [self.L(self.b3, 100)], 'K1')
        self.sync('K2')
        self.sync('K1')
        self.assertEqual(self.view('K1', tid)[0], 'PENDING')
        self.respond_at('K1', tid, [self.L(self.b3, 100)])
        self.go('K1')
        self.assertEqual([x['transfer_status'] for x in build_outbound_payload('Q1')['records']['production.BreadTransfer']],
                         ['RESPONDED'])
        self.assertEqual(self.refused(self.sync('K1')), [])
        self.assertEqual(self.view('cloud', tid)[0], 'RESPONDED')


# --------------------------------------------------------------------------- flux de bout en bout
class A13Flows(P13Base):
    def test_direct_100_valide_100_somme_groupe_inchangee_et_aucun_double_mouvement(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.assertEqual((self.own('K1', self.b3), self.own('K2', self.b3)), (0, 0))
        self.assertEqual(self.refused(self.sync('K1')), [])
        self.assertEqual(self.refused(self.sync('K2')), [])
        self.assertEqual(self.confirm_at('K2', tid, [self.RV(self.b3, 100)]), 'CONFIRMED')
        self.assertEqual(self.refused(self.sync('K2')), [])
        self.assertEqual(self.refused(self.sync('K1')), [])
        self.sync('K3')
        self.assertEqual((self.own('K1', self.b3), self.own('K2', self.b3), self.own('K3', self.b3)), (0, 100, 0))
        # le stock initial du groupe etait 100 (K1) : somme inchangee
        self.assertEqual(self.total(self.b3), 100)
        for st in ('K1', 'K2'):
            self.assertEqual(self.view(st, tid), ('CONFIRMED', {self.b3.pk: (100, 100)}))
        self.assertEqual(self.view('cloud', tid), ('CONFIRMED', {self.b3.pk: (100, 100)}))
        self.assertFalse(self.gap('K2'))
        # rejeux : aucun mouvement, aucune ligne, aucun transfert de plus
        for _ in range(3):
            for n in ('K1', 'K2', 'K3', 'K1', 'K2'):
                self.assertEqual(self.refused(self.sync(n)), [], n)
        self.assertEqual((self.own('K1', self.b3), self.own('K2', self.b3), self.own('K3', self.b3)), (0, 100, 0))
        for n in ('K1', 'K2'):
            self.go(n)
            self.assertEqual((BreadTransfer.objects.count(), BreadTransferLine.objects.count()), (1, 1), n)
        self.go('K3')
        self.assertEqual(BreadTransfer.objects.count(), 0)

    def test_demande_puis_reponse_puis_ecart_98_blocage_de_la_cloture_de_k2(self):
        tid = self.request_from('K2', [self.L(self.b3, 100)], 'K1')
        self.sync('K2')
        self.sync('K1')
        self.assertEqual(self.view('K1', tid), ('PENDING', {self.b3.pk: (100, None)}))
        self.respond_at('K1', tid, [self.L(self.b3, 100)])
        self.assertEqual(self.refused(self.sync('K1')), [])
        self.sync('K2')
        self.assertEqual(self.view('K2', tid)[0], 'RESPONDED')
        self.assertFalse(self.gap('K2'))
        self.assertEqual(self.confirm_at('K2', tid, [self.RV(self.b3, 98)]), 'DISPUTED')
        self.assertTrue(self.gap('K2'))                       # blocage immediat chez K2
        self.assertEqual(self.refused(self.sync('K2')), [])
        self.assertEqual(self.view('cloud', tid), ('DISPUTED', {self.b3.pk: (100, 98)}))
        self.sync('K1')
        self.assertEqual(self.view('K1', tid), ('DISPUTED', {self.b3.pk: (100, 98)}))
        self.assertFalse(self.gap('K1'))                      # K1 est emettrice : pas bloquee
        self.assertFalse(self.gap('K3'))
        self.assertEqual(self.total(self.b3), 98)             # 2 pains manquants au groupe, ecart visible

    def test_multi_lignes_ecart_sur_une_seule_ligne(self):
        tid = self.send_from('K1', [self.L(self.b3, 10), self.L(self.b5, 50), self.L(self.b4, 5)], 'K2')
        self.sync('K1')
        self.sync('K2')
        self.assertEqual(self.view('K2', tid)[1], {self.b3.pk: (10, None), self.b5.pk: (50, None), self.b4.pk: (5, None)})
        self.assertEqual(self.confirm_at('K2', tid, [self.RV(self.b3, 10), self.RV(self.b5, 47), self.RV(self.b4, 5)]),
                         'DISPUTED')
        self.assertEqual(self.refused(self.sync('K2')), [])
        self.sync('K1')
        self.assertEqual(self.view('K1', tid)[1], {self.b3.pk: (10, 10), self.b5.pk: (50, 47), self.b4.pk: (5, 5)})
        for bp, exp in ((self.b3, 100), (self.b5, 97), (self.b4, 100)):
            self.assertEqual(self.total(bp), exp, bp.label)
        self.assertTrue(self.gap('K2'))

    def test_double_validation_un_seul_mouvement(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.sync('K1')
        self.sync('K2')
        self.assertEqual(self.confirm_at('K2', tid, [self.RV(self.b3, 100)]), 'CONFIRMED')
        r = self.post_rest('K2', self.g2, tid, 'confirm_reception', {'lines': [self.RV(self.b3, 100)]})
        self.assertEqual(r.status_code, 400)
        self.sync('K2')
        # la copie « en retard » de K2 : on rejoue le pull ancien (RESPONDED) apres la validation locale
        self.go('cloud')
        old = json.loads(self.a2.get('/api/sync/pull/').content)
        self.go('K2')
        for t in old['transfers']:
            t['transfer_status'] = 'RESPONDED'
        apply_pull_response(old)
        self.assertEqual(self.view('K2', tid)[0], 'CONFIRMED')
        self.assertEqual(self.own('K2', self.b3), 100)

    def test_emettrice_et_tiers_ne_valident_pas_la_reception_par_le_push(self):
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.sync('K1')
        self.go('cloud')
        self.assertEqual(self.tpush(self.a1, tid, 'CONFIRMED', quantity_received=100)[0], 'REJECTED')
        self.assertEqual(self.tpush(self.a3, tid, 'CONFIRMED', quantity_received=100)[0], 'REJECTED')
        self.assertEqual(self.view('cloud', tid)[0], 'RESPONDED')
        # REST local : K1 ne peut pas valider son propre envoi (poste K1), ni K3
        r = self.post_rest('K1', self.g1, tid, 'confirm_reception', {'lines': [self.RV(self.b3, 100)]})
        self.assertIn(r.status_code, (403, 404))
        self.assertEqual(self.own('K2', self.b3), 0)

    # ----- recomptage de K2 : l'ordre « transfert avant lignes » du lot
    def test_recomptage_k2_litige_converge_en_au_plus_deux_cycles_et_debloque_la_cloture(self):
        tid, st = self.to_dispute_direct()
        self.assertEqual(st, 'DISPUTED')
        self.assertTrue(self.gap('K2'))
        self.assertEqual(self.confirm_at('K2', tid, [self.RV(self.b3, 100)]), 'CONFIRMED')
        self.assertFalse(self.gap('K2'))
        self.assertEqual(self.own('K2', self.b3), 100)
        d1 = self.sync('K2')
        rejected_first = self.refused(d1)
        cloud_after_1 = self.view('cloud', tid)
        d2 = self.sync('K2')
        self.assertEqual(self.refused(d2), [], ('deuxieme cycle', rejected_first))
        self.assertEqual(self.view('cloud', tid), ('CONFIRMED', {self.b3.pk: (100, 100)}))
        # comportement documente : premiere tentative eventuellement rejetee, etat intermediaire coherent
        self.assertIn(cloud_after_1[0], ('DISPUTED', 'CONFIRMED'))
        self.assertEqual(cloud_after_1[1], {self.b3.pk: (100, 100)})
        self.sync('K1')
        self.assertEqual(self.view('K1', tid), ('CONFIRMED', {self.b3.pk: (100, 100)}))
        self.assertEqual(self.total(self.b3), 100)
        self.assertFalse(self.gap('K2'))

    def test_recomptage_k2_le_premier_cycle_ne_laisse_pas_un_etat_local_non_exporte(self):
        """Pendant le cycle ou le transfert est rejete, K2 local reste en attente d'envoi (is_synced=False) et le
        pull du meme cycle n'ecrase pas son statut local."""
        tid, _ = self.to_dispute_direct()
        self.confirm_at('K2', tid, [self.RV(self.b3, 100)])
        self.sync('K2')
        self.go('K2')
        self.assertEqual(self.view('K2', tid)[0], 'CONFIRMED')
        self.assertEqual(self.own('K2', self.b3), 100)

    # ----- transitions de litige par le push (BUG-966)
    def test_966_matrice_sortie_de_litige_par_le_push(self):
        tid, _ = self.to_dispute_direct()
        self.go('cloud')
        # lignes non alignees : tout le monde est refuse avec motif
        for api in (self.a1, self.a2, self.a3):
            st = self.tpush(api, tid, 'CONFIRMED', quantity_received=100)
            self.assertEqual(st[0], 'REJECTED')
        self.assertEqual(self.view('cloud', tid)[0], 'DISPUTED')
        # tiers : refuse meme si les lignes sont alignees
        self.assertEqual(self.tline(self.a2, tid, self.b3, 100, recv=100)[0], 'ACCEPTED')
        self.assertEqual(self.tpush(self.a3, tid, 'CONFIRMED')[0], 'REJECTED')
        self.assertEqual(self.view('cloud', tid)[0], 'DISPUTED')
        # emettrice : acceptee quand les lignes sont alignees (resolution)
        self.assertEqual(self.tpush(self.a1, tid, 'CONFIRMED')[0], 'ACCEPTED')
        self.assertEqual(self.view('cloud', tid)[0], 'CONFIRMED')

    def test_966_sortie_de_litige_refusee_si_une_ligne_sans_quantite_recue(self):
        tid = self.send_from('K1', [self.L(self.b3, 10), self.L(self.b5, 10)], 'K2')
        self.sync('K1')
        self.go('cloud')
        self.tline(self.a2, tid, self.b3, 10, recv=10)
        self.tline(self.a2, tid, self.b5, 10, recv=4)
        self.assertEqual(self.tpush(self.a2, tid, 'DISPUTED', quantity_received=14)[0], 'ACCEPTED')
        self.tline(self.a2, tid, self.b5, 10, recv=10)
        self.assertEqual(self.tpush(self.a2, tid, 'CONFIRMED', quantity_received=20)[0], 'ACCEPTED')
        self.assertEqual(self.view('cloud', tid), ('CONFIRMED', {self.b3.pk: (10, 10), self.b5.pk: (10, 10)}))
        # un confirme ne revient plus en litige
        self.assertEqual(self.tpush(self.a2, tid, 'DISPUTED', quantity_received=1)[0], 'ACCEPTED')
        self.assertEqual(self.view('cloud', tid)[0], 'CONFIRMED')

    # ----- BUG-967 / 968 : quantites normalisees
    def test_967_quantites_creation_normalisees_ou_rejet_motive(self):
        self.go('cloud')
        for val, exp in (('5.0', 5), (5.0, 5), (' 7 ', 7), ('+3', 3), (0, 0), ('0.0', 0)):
            tid = uid()
            st = self.tpush(self.a1, tid, 'RESPONDED', quantity_sent=val)
            self.assertEqual(st[0], 'ACCEPTED', (val, st))
            t = BreadTransfer.objects.get(pk=tid)
            self.assertEqual(t.quantity_sent, exp, val)
            self.assertIsInstance(t.quantity_sent, int)
        st = self.tpush(self.a1, uid(), 'RESPONDED', quantity_sent='1e1')
        self.assertNotIn('erreur serveur', st[1] or '')   # notation scientifique : rejet motive documente
        for val in ('1.5', 'abc', -1, '-1', True, [1], {'a': 1}, 3_000_000_000, '٣', '1e400', float('1e30')):
            tid = uid()
            st = self.tpush(self.a1, tid, 'RESPONDED', quantity_sent=val)
            self.assertEqual(st[0], 'REJECTED', (val, st))
            self.assertNotIn('erreur serveur', st[1] or '', val)
            self.assertFalse(BreadTransfer.objects.filter(pk=tid).exists(), val)

    def test_967_ligne_avec_quantites_en_decimal_chaine(self):
        tid = self.send_from('K1', [self.L(self.b3, 10)], 'K2')
        self.sync('K1')
        self.go('cloud')
        for val in ('10.0', 10.0, ' 10 '):
            st = self.tline(self.a2, tid, self.b3, 10, recv=val)
            self.assertEqual(st[0], 'ACCEPTED', (val, st))
            self.assertEqual(self.view('cloud', tid)[1][self.b3.pk], (10, 10), val)

    def test_968_disposition_quantites_normalisees_ou_rejet_motive(self):
        self.go('cloud')
        s = self.sess()
        push(self.a1, LBL_S, s)
        for q, p, eq, ep in (('3.0', '100.0', 3, 100), (' 4 ', '25', 4, 25), (3.0, 100.0, 3, 100)):
            did = uid()
            st = push(self.a1, 'production.BreadDisposal', {'id': did, 'session': s['id'], 'bread_price': self.b3.pk,
                                                            'disposal_type': 'UNSOLD', 'quantity': q,
                                                            'unit_price_sold': p})
            self.assertEqual(st[0], 'ACCEPTED', (q, p, st))
            d = BreadDisposal.objects.get(pk=did)
            self.assertEqual((d.quantity, d.unit_price_sold), (eq, ep))
        for q, p in (('3.5', '100'), ('abc', '1'), ('3', '1.5'), (-1, 10), (True, 1), ([1], 1), ('1e400', '1')):
            st = push(self.a1, 'production.BreadDisposal', {'id': uid(), 'session': s['id'], 'bread_price': self.b3.pk,
                                                            'disposal_type': 'UNSOLD', 'quantity': q,
                                                            'unit_price_sold': p})
            self.assertEqual(st[0], 'REJECTED', (q, p, st))
            self.assertNotIn('erreur serveur', st[1] or '', (q, p))

    # ----- anciens transferts
    def test_transferts_termines_de_plus_de_30_jours_exclus_du_pull_les_autres_restent(self):
        done = self.send_from('K1', [self.L(self.b3, 5)], 'K2')
        old_pending = self.request_from('K2', [self.L(self.b5, 5)], 'K1')
        old_resp = self.send_from('K1', [self.L(self.b4, 5)], 'K2')
        self.sync('K1')
        self.sync('K2')
        self.confirm_at('K2', done, [self.RV(self.b3, 5)])
        self.sync('K2')
        self.sync('K1')
        self.go('cloud')
        past = timezone.now() - timedelta(days=31)
        near = timezone.now() - timedelta(days=29)
        BreadTransfer.objects.filter(pk=done).update(updated_at=past)
        BreadTransfer.objects.filter(pk=old_pending).update(updated_at=past)
        BreadTransfer.objects.filter(pk=old_resp).update(updated_at=past)
        for api in (self.a1, self.a2):
            ids = {t['id'] for t in api.get('/api/sync/pull/').data['transfers']}
            self.assertNotIn(str(done), ids)                  # CONFIRMED > 30 j : exclu
            self.assertIn(str(old_pending), ids)              # PENDING ancien : toujours present
            self.assertIn(str(old_resp), ids)                 # RESPONDED ancien : toujours present
        BreadTransfer.objects.filter(pk=done).update(updated_at=near)
        ids = {t['id'] for t in self.a2.get('/api/sync/pull/').data['transfers']}
        self.assertIn(str(done), ids)                         # 29 j : encore present
        # un poste neuf (pas de copie) ne recree pas l'ancien confirme
        self.go('K3')
        self.assertIsNone(self.view('K3', done))

    def test_litige_ancien_reste_dans_le_pull_tant_qu_il_n_est_pas_resolu(self):
        tid, _ = self.to_dispute_direct()
        self.go('cloud')
        BreadTransfer.objects.filter(pk=tid).update(updated_at=timezone.now() - timedelta(days=90))
        for api in (self.a1, self.a2):
            self.assertIn(str(tid), {t['id'] for t in api.get('/api/sync/pull/').data['transfers']})

    # ----- defauts voisins ----------------------------------------------------------------------
    @expectedFailure
    def test_BUG_974_resolution_de_l_emettrice_atteint_le_cloud_et_debloque_k2(self):
        """BUG-974 : K1 (poste) resout le litige localement (ALIGN_ON_RECEIVED) : K1 est credite de 2, transfert
        CONFIRMED localement. Le push est rejete a chaque cycle (« litige non resolu » + « ligne en double ») : le
        cloud reste DISPUTED, K2 ne voit jamais la resolution et sa cloture reste bloquee a vie."""
        tid, _ = self.to_dispute_direct()
        r = self.post_rest('K1', self.g1, tid, 'resolve_dispute', {'resolution': 'ALIGN_ON_RECEIVED', 'reason': 'perte'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.total(self.b3), 100)            # localement, somme du groupe rétablie
        for _ in range(3):
            self.sync('K1')
            self.sync('K2')
        self.assertEqual(self.view('cloud', tid)[0], 'CONFIRMED', self.view('cloud', tid))
        self.assertFalse(self.gap('K2'))

    def test_resolution_emettrice_locale_n_est_pas_ecrasee_par_le_pull(self):
        tid, _ = self.to_dispute_direct()
        self.post_rest('K1', self.g1, tid, 'resolve_dispute', {'resolution': 'ALIGN_ON_RECEIVED', 'reason': 'perte'})
        self.sync('K1')
        self.assertEqual(self.view('K1', tid), ('CONFIRMED', {self.b3.pk: (98, 98)}))
        self.assertEqual(self.own('K1', self.b3), 2)

    @expectedFailure
    def test_BUG_975_resolution_siege_received_leve_le_blocage_de_k2_apres_pull(self):
        """BUG-975 : le siege resout au cloud ALIGN_ON_RECEIVED (quantity_sent <- recu). Le pull applique le
        statut CONFIRMED mais ne reporte pas la nouvelle quantity_sent sur les copies locales : la ligne reste
        (100 envoye, 98 recu) et `_unresolved_incoming_transfer_gap` bloque toujours la cloture de K2."""
        tid, _ = self.to_dispute_direct()
        r = self.post_rest('cloud', self.dir, tid, 'resolve_dispute', {'resolution': 'ALIGN_ON_RECEIVED', 'reason': 'perte'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.view('cloud', tid), ('CONFIRMED', {self.b3.pk: (98, 98)}))
        self.sync('K2')
        self.sync('K1')
        self.assertEqual(self.view('K2', tid)[0], 'CONFIRMED')
        self.assertEqual(self.view('K2', tid)[1], {self.b3.pk: (98, 98)})
        self.assertFalse(self.gap('K2'))

    def test_resolution_siege_sent_leve_le_blocage_de_k2_apres_pull(self):
        tid, _ = self.to_dispute_direct()
        r = self.post_rest('cloud', self.dir, tid, 'resolve_dispute', {'resolution': 'ALIGN_ON_SENT', 'reason': 'recompte'})
        self.assertEqual(r.status_code, 200, r.content)
        self.sync('K2')
        self.sync('K1')
        self.assertEqual(self.view('K2', tid), ('CONFIRMED', {self.b3.pk: (100, 100)}))
        self.assertFalse(self.gap('K2'))

    def _resolve_stock(self, resolution):
        tid, _ = self.to_dispute_direct()
        self.assertEqual(self.total(self.b3), 98)
        r = self.post_rest('cloud', self.dir, tid, 'resolve_dispute', {'resolution': resolution, 'reason': 'x'})
        self.assertEqual(r.status_code, 200, r.content)
        self.sync('K2')
        self.sync('K1')
        self.assertEqual(self.total(self.b3), 100, (resolution, self.own('K1', self.b3), self.own('K2', self.b3)))

    @expectedFailure
    def test_BUG_976_resolution_siege_received_regularise_le_stock_de_k1(self):
        """BUG-976 : la resolution du siege (cloud) n'ajuste que les stocks du cloud ; le pull ne cree aucun
        mouvement chez K1 (ALIGN_ON_RECEIVED : +2 attendu) ni chez K2 (ALIGN_ON_SENT : +2 attendu) : la somme
        des stocks du groupe reste a 98 alors que le litige est « resolu » (« somme nulle au niveau du groupe »)."""
        self._resolve_stock('ALIGN_ON_RECEIVED')

    @expectedFailure
    def test_BUG_976_resolution_siege_sent_regularise_le_stock_de_k2(self):
        self._resolve_stock('ALIGN_ON_SENT')

    @expectedFailure
    def test_BUG_976_confirmation_de_la_reception_par_le_siege_credite_le_stock_de_k2(self):
        """Copie locale en retard (limite annoncee d35) : le siege confirme la reception au cloud ; le pull
        passe la copie de K2 de RESPONDED a CONFIRMED sans créditer le stock de K2 : 100 pains disparaissent
        du groupe, et K2 ne peut plus rien valider (statut deja CONFIRMED)."""
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.sync('K1')
        self.sync('K2')
        r = self.post_rest('cloud', self.dir, tid, 'confirm_reception', {'lines': [self.RV(self.b3, 100)]})
        self.assertEqual(r.status_code, 200, r.content)
        self.sync('K2')
        self.sync('K1')
        self.assertEqual(self.view('K2', tid)[0], 'CONFIRMED')
        self.assertEqual(self.own('K2', self.b3), 100)
        self.assertEqual(self.total(self.b3), 100)

    @expectedFailure
    def test_BUG_977_envoi_direct_garde_son_flux_direct_au_cloud_et_chez_la_receptrice(self):
        """BUG-977 : `flow` n'est ni exporte par le poste ni pose a la creation cloud : un envoi direct (K1) devient
        « Demande puis reponse » au cloud et chez K2 (libelle, regles d'initiateur BUG-624)."""
        tid = self.send_from('K1', [self.L(self.b3, 30)], 'K2')
        self.assertEqual(BreadTransfer.objects.get(pk=tid).flow, 'DIRECT')
        self.sync('K1')
        self.go('cloud')
        self.assertEqual(BreadTransfer.objects.get(pk=tid).flow, 'DIRECT')
        self.sync('K2')
        self.go('K2')
        self.assertEqual(BreadTransfer.objects.get(pk=tid).flow, 'DIRECT')

    @expectedFailure
    def test_BUG_978_la_receptrice_est_alertee_d_un_envoi_recu_par_pull(self):
        """BUG-978 : les alertes (SystemNotification) sont creees dans la base du poste qui agit et ne sont pas
        synchronisees : « Pains Envoyes » / « Demande de Pains » / litige n'apparaissent jamais chez K2 (ou K1) en
        multi-postes. CLAUDE.md 5.4 : bon de sortie K1 -> K2 => alerte chez K2."""
        tid = self.send_from('K1', [self.L(self.b3, 100)], 'K2')
        self.sync('K1')
        self.sync('K2')
        self.go('K2')
        self.assertTrue(SystemNotification.objects.filter(node_origin='Q2').exists()
                        or SystemNotification.objects.filter(message__contains='Q1').exists())

    @expectedFailure
    def test_BUG_979_lignes_manquantes_completees_au_pull_suivant(self):
        """BUG-979 : le pull n'applique les lignes que lorsque le statut avance ; un transfert cree localement
        avec une ligne ignoree (categorie de pain inconnue du poste a ce moment) ne la recoit jamais, meme quand la
        categorie est disponible au cycle suivant : confirm_reception impossible (lignes incompletes)."""
        tid = self.send_from('K1', [self.L(self.b3, 10)], 'K2')
        self.sync('K1')
        self.go('cloud')
        pulled = json.loads(self.a2.get('/api/sync/pull/').content)
        ghost = BreadPrice.objects.order_by('-pk').first().pk + 50
        pulled['transfer_lines'].append({'transfer': str(tid), 'bread_price': ghost, 'quantity_sent': 7,
                                         'quantity_received': None})
        self.go('K2')
        apply_pull_response(pulled)
        self.assertEqual(BreadTransferLine.objects.filter(transfer_id=tid).count(), 1)  # fantome ignore
        BreadPrice.objects.create(pk=ghost, category='GHOST', label='G', unit_price=1000)
        apply_pull_response(pulled)
        self.assertEqual(BreadTransferLine.objects.filter(transfer_id=tid).count(), 2)

    @expectedFailure
    def test_BUG_980_poste_hors_ligne_plus_de_30_jours_apprend_la_resolution(self):
        """BUG-980 : un transfert CONFIRME depuis plus de 30 jours n'est plus descendu ; un poste qui reste
        hors ligne plus longtemps garde a vie sa copie DISPUTED et sa cloture bloquee (aucun moyen de rattrapage)."""
        tid, _ = self.to_dispute_direct()
        r = self.post_rest('cloud', self.dir, tid, 'resolve_dispute', {'resolution': 'ALIGN_ON_SENT', 'reason': 'x'})
        self.assertEqual(r.status_code, 200)
        BreadTransfer.objects.filter(pk=tid).update(updated_at=timezone.now() - timedelta(days=45))
        self.sync('K2')
        self.assertEqual(self.view('K2', tid)[0], 'CONFIRMED')
        self.assertFalse(self.gap('K2'))
