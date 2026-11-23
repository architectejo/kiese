"""Testeur-production (cycle 13 / a12) : verification independante de BUG-955/956/957/958 (d34) et flux
de transfert complet par REST + sync_now (export) + push sur plusieurs postes simules.
Donnees fictives. Les `@expectedFailure` referencent leur ticket.

Simulation de postes : une seule base de test sert de « cloud » ; un poste est simule en exportant son
etat (`build_outbound_payload`) puis en effacant ses lignes locales avant de pousser avec son jeton.
"""
import itertools
import uuid
from decimal import Decimal as Dc
from unittest import expectedFailure

from production.models import (BreadDisposal, BreadStock, BreadTransfer, BreadTransferLine, ProductionSession,
                               _adjust_bread_stock)
from production.tests.test_verif_a4_testeur_production import T, cl
from production.tests.test_verif_production_a11_v11 import V11Base
from production.tests.test_verif_production_a8_v8 import PUSH, push, uid
from production.tests.test_verif_production_a9_v9 import LBL_IL, LBL_S, LBL_T, LBL_TL, lot
from sales.models import InvoiceLine
from sync.management.commands.sync_now import apply_push_response, build_outbound_payload
from treasury.views import _unresolved_incoming_transfer_gap

TS = BreadTransfer.TransferStatus


def reasons(res):
    return [x[1] or '' for v in res.values() for x in v if x[0] != 'ACCEPTED']


class V12Base(V11Base):
    """k1/k2/k3 (codes Q1/Q2/Q3), jetons a1/a2/a3, stock initial K1 = 100 par categorie (TBase)."""

    def setUp(self):
        super().setUp()
        _adjust_bread_stock(self.k1, self.b4, produced=100)

    def rest_send(self, lines, user=None, to=None):
        r = cl(user or self.g1).post(f'{T}send/', {'to_node': (to or self.k2).pk, 'lines': lines}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return BreadTransfer.objects.get(pk=r.data['id'])

    def export_forget(self, node, transfer):
        """Exporte l'etat du poste puis oublie le transfert localement (le « cloud » ne le connait pas)."""
        payload = build_outbound_payload(node.code)
        recs = [x for x in payload['records']['production.BreadTransfer'] if x['id'] == str(transfer.pk)]
        lines = [x for x in payload['records']['production.BreadTransferLine'] if x['transfer'] == str(transfer.pk)]
        BreadTransfer.objects.filter(pk=transfer.pk).delete()
        return payload, recs, lines

    def tpush(self, api, tid, status, frm=None, to=None, **kw):
        rec = {'id': str(tid), 'from_node': (frm or self.k1).code, 'to_node': (to or self.k2).code,
               'transfer_status': status}
        rec.update(kw)
        return push(api, LBL_T, rec)

    def tline(self, api, tid, bp, sent, recv=None):
        rec = {'transfer': str(tid), 'bread_price': bp.pk, 'quantity_sent': sent}
        if recv is not None:
            rec['quantity_received'] = recv
        return push(api, LBL_TL, rec)

    def tstate(self, tid):
        t = BreadTransfer.objects.get(pk=tid)
        return t.transfer_status, {l.bread_price_id: (l.quantity_sent, l.quantity_received) for l in t.lines.all()}


# --------------------------------------------------------------------------- BUG-955 / 956 / 957
class V12Corrections(V12Base):
    def test_955_reference_facture_malformee_ne_modifie_pas_une_ligne(self):
        i1 = self.inv(node=self.k1.code)
        self.assertEqual(push(self.a1, 'sales.Invoice', i1)[0], 'ACCEPTED')
        lot(self.a1, sales__InvoiceLine=[self.il(i1, self.b3, 3, 1)])
        pk1 = InvoiceLine.objects.get(invoice_id=i1['id']).pk
        for garbage in ('pas-un-uuid', 12345, '', ['x'], None, {'a': 1}, True, 1.5, '٣', ' ', 'X' * 64):
            st = push(self.a1, LBL_IL, {'id': str(pk1), 'invoice': garbage, 'bread_price': self.b3.pk, 'quantity': 1})
            self.assertEqual(st[0], 'REJECTED', garbage)
            self.assertIn('invoice', st[1], garbage)
            self.assertEqual(InvoiceLine.objects.get(pk=pk1).quantity, 3, garbage)
        # ancien payload SANS cle invoice : repli par l'id toujours accepte (compatibilite)
        self.assertEqual(push(self.a1, LBL_IL, {'id': str(pk1), 'bread_price': self.b3.pk, 'quantity': 4})[0],
                         'ACCEPTED')
        self.assertEqual(InvoiceLine.objects.get(pk=pk1).quantity, 4)

    def test_955_id_inconnu_avec_invoice_malformee_ne_cree_rien(self):
        i1 = self.inv(node=self.k1.code)
        push(self.a1, 'sales.Invoice', i1)
        for garbage in ('pas-un-uuid', 12345, ''):
            st = push(self.a1, LBL_IL, {'id': '987', 'invoice': garbage, 'bread_price': self.b3.pk, 'quantity': 1})
            self.assertEqual(st[0], 'REJECTED', garbage)
        self.assertEqual(InvoiceLine.objects.count(), 0)

    def _session(self, **kw):
        s = self.sess(**kw)
        return s

    def test_956_valeur_sac_decimale_creation_et_mise_a_jour(self):
        s = self.sess(sac_value_fc_used='150000.0')
        self.assertEqual(push(self.a1, LBL_S, s)[0], 'ACCEPTED')
        self.assertEqual(ProductionSession.objects.get(pk=s['id']).sac_value_fc_used, 150000)
        for val, exp in (('120000.0', 120000), (130000.0, 130000), ('110000.00', 110000), (' 90000 ', 90000),
                         ('9.0E4', None), ('1e3', None), ('150000.5', None), (150000.5, None), ('--1', None),
                         ('+80000', 80000), ('٩٠٠٠٠', None), (None, None)):
            st = push(self.a1, LBL_S, dict(s, sac_value_fc_used=val))
            if exp is None and val is not None:
                self.assertEqual(st[0], 'REJECTED', val)
                self.assertNotIn('erreur serveur', st[1], val)
            elif val is not None:
                self.assertEqual(st[0], 'ACCEPTED', (val, st))
                self.assertEqual(ProductionSession.objects.get(pk=s['id']).sac_value_fc_used, exp, val)
        # type exact : entier
        self.assertIsInstance(ProductionSession.objects.get(pk=s['id']).sac_value_fc_used, int)

    def test_956_creation_valeur_sac_en_chaine_rejetee_avec_motif_clair(self):
        for val in ('1e3', 'abc', '1.5', '٣'):
            st = push(self.a1, LBL_S, self.sess(sac_value_fc_used=val))
            self.assertEqual(st[0], 'REJECTED', val)
            self.assertNotIn('erreur serveur', st[1] or '', val)

    def test_957_valeur_sac_zero_meme_regle_creation_et_mise_a_jour(self):
        a = self.sess(sac_value_fc_used=0)
        push(self.a1, LBL_S, a)
        b = self.sess(sac_value_fc_used=200000)
        push(self.a1, LBL_S, b)
        push(self.a1, LBL_S, dict(b, sac_value_fc_used=0))
        ca = ProductionSession.objects.get(pk=a['id'])
        cb = ProductionSession.objects.get(pk=b['id'])
        self.assertEqual((ca.sac_value_fc_used, cb.sac_value_fc_used), (0, 0))
        self.assertEqual(ca.theoretical_yield, 0)
        # absent / vide / null : valeur par defaut 200000
        for k, val in (('absent', None), ('vide', ''), ('null', None)):
            r = self.sess()
            if k == 'absent':
                r.pop('sac_value_fc_used')
            else:
                r['sac_value_fc_used'] = val
            self.assertEqual(push(self.a1, LBL_S, r)[0], 'ACCEPTED', k)
            self.assertEqual(ProductionSession.objects.get(pk=r['id']).sac_value_fc_used, 200000, k)


# --------------------------------------------------------------------------- BUG-958 : envoi direct
class V12DirectSend(V12Base):
    def test_envoi_direct_rest_export_push_accepte_avec_lignes(self):
        t = self.rest_send([self.L(self.b3, 30), self.L(self.b5, 20)])
        self.assertEqual(t.transfer_status, TS.RESPONDED)
        stock_k1 = (self.stock(self.k1, self.b3), self.stock(self.k1, self.b5))
        self.assertEqual(stock_k1, (70, 80))
        payload, recs, lines = self.export_forget(self.k1, t)
        self.assertEqual(len(recs), 1)
        self.assertEqual((recs[0]['transfer_status'], recs[0]['from_node'], recs[0]['to_node']),
                         ('RESPONDED', 'Q1', 'Q2'))
        self.assertEqual(sorted((l['bread_price'], l['quantity_sent']) for l in lines),
                         sorted([(self.b3.pk, 30), (self.b5.pk, 20)]))
        data = self.post(self.a1, dict(payload, batch_id=uid()))
        for label in ('production.BreadTransfer', 'production.BreadTransferLine'):
            for r in data['results'][label]:
                self.assertEqual(r['status'], 'ACCEPTED', (label, r))
        st, ls = self.tstate(t.pk)
        self.assertEqual(st, 'RESPONDED')
        self.assertEqual(ls, {self.b3.pk: (30, None), self.b5.pk: (20, None)})
        # le push ne rejoue jamais l'effet de stock
        self.assertEqual((self.stock(self.k1, self.b3), self.stock(self.k1, self.b5)), stock_k1)
        self.assertEqual(self.stock(self.k2, self.b3), 0)
        self.assertEqual(self.group(self.b3), 70)         # K2 n'a encore rien recu : en transit

    def test_envoi_direct_rejeu_idempotent(self):
        t = self.rest_send([self.L(self.b3, 30)])
        payload, _, _ = self.export_forget(self.k1, t)
        for _ in range(3):
            data = self.post(self.a1, dict(payload, batch_id=uid()))
            for rows in data['results'].values():
                for r in rows:
                    self.assertEqual(r['status'], 'ACCEPTED', r)
        self.assertEqual(BreadTransfer.objects.filter(pk=t.pk).count(), 1)
        self.assertEqual(BreadTransferLine.objects.filter(transfer_id=t.pk).count(), 1)

    def test_envoi_direct_multi_lignes_trois_categories(self):
        t = self.rest_send([self.L(self.b3, 10), self.L(self.b5, 20), self.L(self.b4, 0 + 5)])
        payload, _, _ = self.export_forget(self.k1, t)
        res = lot(self.a1, production__BreadTransfer=payload['records']['production.BreadTransfer'],
                  production__BreadTransferLine=payload['records']['production.BreadTransferLine'])
        self.assertEqual(reasons(res), [])
        self.assertEqual(self.tstate(t.pk)[1], {self.b3.pk: (10, None), self.b5.pk: (20, None),
                                                self.b4.pk: (5, None)})

    def test_creation_par_reception_ou_tiers_refusee(self):
        for api, who in ((self.a2, 'receptrice'), (self.a3, 'tiers')):
            tid = uid()
            st = self.tpush(api, tid, 'RESPONDED')
            self.assertEqual(st[0], 'REJECTED', who)
            self.assertFalse(BreadTransfer.objects.filter(pk=tid).exists())

    def test_creation_par_emettrice_etats_interdits(self):
        for status, extra in (('CONFIRMED', {}), ('DISPUTED', {}), ('CANCELLED', {}), ('BIDON', {}),
                              ('RESPONDED', {'quantity_received': 5}), ('RESPONDED', {'quantity_received': 0}),
                              ('CONFIRMED', {'quantity_received': 5}), ('DISPUTED', {'quantity_received': 3})):
            tid = uid()
            st = self.tpush(self.a1, tid, status, **extra)
            self.assertEqual(st[0], 'REJECTED', (status, extra, st))
            self.assertFalse(BreadTransfer.objects.filter(pk=tid).exists(), (status, extra))

    def test_creation_par_receptrice_demande_pending_ok_autres_refuses(self):
        tid = uid()
        self.assertEqual(self.tpush(self.a2, tid, 'PENDING', node_origin='Q2')[0], 'ACCEPTED')
        for status in ('RESPONDED', 'CONFIRMED', 'DISPUTED', 'CANCELLED'):
            self.assertEqual(self.tpush(self.a2, uid(), status)[0], 'REJECTED', status)
            self.assertEqual(self.tpush(self.a2, uid(), status, quantity_received=4)[0], 'REJECTED', status)

    def test_transfert_a_soi_meme_et_noeud_inconnu(self):
        self.assertEqual(self.tpush(self.a1, uid(), 'RESPONDED', to=self.k1)[0], 'REJECTED')
        st = self.tpush(self.a1, uid(), 'RESPONDED', to=type('N', (), {'code': 'ZZZ'}))
        self.assertEqual(st[0], 'REJECTED')
        self.assertEqual(BreadTransfer.objects.count(), 0)

    def test_lignes_d_un_transfert_refuse_ne_laissent_aucun_orphelin(self):
        tid = uid()
        res = lot(self.a1, production__BreadTransfer=[{'id': tid, 'from_node': 'Q1', 'to_node': 'Q2',
                                                      'transfer_status': 'CONFIRMED', 'quantity_received': 5}],
                  production__BreadTransferLine=[{'transfer': tid, 'bread_price': self.b3.pk, 'quantity_sent': 5}])
        self.assertEqual([x[0] for x in res[LBL_T]], ['REJECTED'])
        self.assertEqual([x[0] for x in res[LBL_TL]], ['REJECTED'])
        self.assertEqual(BreadTransferLine.objects.count(), 0)

    def test_receptrice_ne_peut_pas_ajouter_de_quantite_envoyee_apres_coup(self):
        t = self.rest_send([self.L(self.b3, 30)])
        # K2 tente de modifier quantity_sent d'une ligne existante, puis d'ajouter une ligne
        self.assertIn(self.tline(self.a2, t.pk, self.b3, 99)[0], ('ACCEPTED', 'REJECTED'))
        self.assertEqual(self.tstate(t.pk)[1][self.b3.pk][0], 30)
        self.tline(self.a2, t.pk, self.b5, 40)

    def test_emettrice_ne_pose_pas_quantite_recue(self):
        t = self.rest_send([self.L(self.b3, 30)])
        self.tline(self.a1, t.pk, self.b3, 30, recv=30)
        self.assertEqual(self.tstate(t.pk)[1][self.b3.pk], (30, None))
        self.tpush(self.a1, t.pk, 'RESPONDED', quantity_received=30)
        self.assertIsNone(BreadTransfer.objects.get(pk=t.pk).quantity_received)


# --------------------------------------------------------------------------- machine d'etats par role
class V12StateMachine(V12Base):
    ALL = ('PENDING', 'RESPONDED', 'CONFIRMED', 'DISPUTED', 'CANCELLED')
    # transitions legales : (statut courant, nouveau statut) -> role qui peut l'appliquer
    LEGAL = {('PENDING', 'RESPONDED'): 'from', ('PENDING', 'CANCELLED'): 'from',
             ('RESPONDED', 'CONFIRMED'): 'to', ('RESPONDED', 'DISPUTED'): 'to'}

    def _mk(self, status):
        t = BreadTransfer.objects.create(from_node=self.k1, to_node=self.k2, transfer_status=status,
                                         node_origin=self.k1.code)
        BreadTransferLine.objects.create(transfer=t, bread_price=self.b3, quantity_sent=10)
        return t

    def test_matrice_complete_statut_courant_x_role_x_nouveau_statut(self):
        roles = {'from': self.a1, 'to': self.a2, 'tiers': self.a3}
        for cur, role, new in itertools.product(self.ALL, roles, self.ALL):
            t = self._mk(cur)
            st = self.tpush(roles[role], t.pk, new, quantity_received=10 if role == 'to' else None)
            got = BreadTransfer.objects.get(pk=t.pk).transfer_status
            legal = self.LEGAL.get((cur, new)) == role
            expected = new if legal else cur
            self.assertEqual(got, expected, (cur, role, new, st))
            if role == 'tiers':
                self.assertEqual(st[0], 'REJECTED', (cur, new))
            BreadTransfer.objects.filter(pk=t.pk).delete()

    def test_quantite_recue_seulement_par_la_receptrice(self):
        t = self._mk('RESPONDED')
        self.tpush(self.a1, t.pk, 'DISPUTED', quantity_received=3)
        self.assertEqual(self.tstate(t.pk)[0], 'RESPONDED')
        self.assertIsNone(BreadTransfer.objects.get(pk=t.pk).quantity_received)
        self.tpush(self.a2, t.pk, 'DISPUTED', quantity_received=3)
        self.assertEqual(BreadTransfer.objects.get(pk=t.pk).quantity_received, 3)

    def test_transfert_confirme_ou_annule_est_immuable_pour_les_lignes(self):
        for cur in ('CONFIRMED', 'CANCELLED'):
            t = self._mk(cur)
            self.assertEqual(self.tline(self.a1, t.pk, self.b5, 7)[0], 'REJECTED', cur)
            self.assertEqual(self.tline(self.a2, t.pk, self.b5, 7, recv=7)[0], 'REJECTED', cur)
            self.assertEqual(t.lines.count(), 1)

    def test_double_validation_par_push_un_seul_effet(self):
        t = self._mk('RESPONDED')
        for _ in range(3):
            self.tpush(self.a2, t.pk, 'CONFIRMED', quantity_received=10)
            self.tline(self.a2, t.pk, self.b3, 10, recv=10)
        self.assertEqual(self.tstate(t.pk), ('CONFIRMED', {self.b3.pk: (10, 10)}))
        self.assertEqual(self.stock(self.k2, self.b3), 0)     # jamais d'effet de stock au cloud

    def test_regression_de_statut_jamais_appliquee(self):
        t = self._mk('RESPONDED')
        self.tpush(self.a2, t.pk, 'CONFIRMED', quantity_received=10)
        for api in (self.a1, self.a2):
            for old in ('PENDING', 'RESPONDED', 'DISPUTED', 'CANCELLED'):
                self.tpush(api, t.pk, old)
        self.assertEqual(self.tstate(t.pk)[0], 'CONFIRMED')

    def test_transfert_connu_d_un_tiers_refuse(self):
        t = self._mk('RESPONDED')
        self.assertEqual(self.tpush(self.a3, t.pk, 'CONFIRMED')[0], 'REJECTED')
        self.assertEqual(self.tline(self.a3, t.pk, self.b3, 1, recv=1)[0], 'REJECTED')
        self.assertEqual(self.tstate(t.pk), ('RESPONDED', {self.b3.pk: (10, None)}))


# --------------------------------------------------------------------------- flux complet
class V12FullFlow(V12Base):
    def _bake(self, node, k):
        pass

    def test_flux_demande_reponse_confirmation_ecart_et_resolution_rest_apres_push(self):
        """K2 demande 100 (REST) -> export + push ; K1 repond (push) ; K2 confirme 98 (push) : litige, cloture K2
        bloquee ; resolution REST par la direction : cloture debloquee, transfert confirme, lignes alignees."""
        r = cl(self.g2).post(T, {'from_node': self.k1.pk, 'lines': [self.L(self.b3, 100)]}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        t = BreadTransfer.objects.get(pk=r.data['id'])
        payload, recs, lines = self.export_forget(self.k2, t)
        self.assertEqual((recs[0]['transfer_status'], recs[0]['node_origin']), ('PENDING', 'Q2'))
        data = self.post(self.a2, dict(payload, batch_id=uid()))
        self.assertTrue(all(x['status'] == 'ACCEPTED' for rows in data['results'].values() for x in rows), data)
        self.assertEqual(self.tstate(t.pk), ('PENDING', {self.b3.pk: (100, None)}))
        # K1 repond
        self.assertEqual(self.tpush(self.a1, t.pk, 'RESPONDED')[0], 'ACCEPTED')
        self.assertEqual(self.tstate(t.pk)[0], 'RESPONDED')
        # K2 ne peut pas se confirmer elle-meme avant d'avoir recu... mais peut confirmer apres envoi : 98 recus
        self.assertEqual(self.tline(self.a2, t.pk, self.b3, 100, recv=98)[0], 'ACCEPTED')
        self.assertEqual(self.tpush(self.a2, t.pk, 'DISPUTED', quantity_received=98)[0], 'ACCEPTED')
        self.assertEqual(self.tstate(t.pk), ('DISPUTED', {self.b3.pk: (100, 98)}))
        self.assertTrue(_unresolved_incoming_transfer_gap(self.k2))
        self.assertFalse(_unresolved_incoming_transfer_gap(self.k1))
        # resolution REST (siege) : le recu fait foi
        r = cl(self.dir).post(f'{T}{t.pk}/resolve_dispute/',
                              {'resolution': 'ALIGN_ON_RECEIVED', 'reason': 'sacs perdus'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.tstate(t.pk), ('CONFIRMED', {self.b3.pk: (98, 98)}))
        self.assertFalse(_unresolved_incoming_transfer_gap(self.k2))
        # un rejeu perime du litige ne reouvre rien (pas de regression)
        self.tpush(self.a2, t.pk, 'DISPUTED', quantity_received=98)
        self.assertEqual(self.tstate(t.pk)[0], 'CONFIRMED')
        self.assertFalse(_unresolved_incoming_transfer_gap(self.k2))

    def test_flux_direct_100_validation_exacte_somme_groupe_et_cloture_libre(self):
        t = self.rest_send([self.L(self.b3, 100)])
        self.assertEqual((self.stock(self.k1, self.b3), self.group(self.b3)), (0, 0))
        payload, _, _ = self.export_forget(self.k1, t)
        data = self.post(self.a1, dict(payload, batch_id=uid()))
        self.assertTrue(all(x['status'] == 'ACCEPTED' for rows in data['results'].values() for x in rows))
        self.assertEqual(self.tpush(self.a1, t.pk, 'CONFIRMED', quantity_received=100)[0], 'REJECTED')
        self.assertEqual(self.tpush(self.a2, t.pk, 'CONFIRMED', quantity_received=100)[0], 'ACCEPTED')
        self.assertEqual(self.tline(self.a2, t.pk, self.b3, 100, recv=100)[0], 'ACCEPTED')
        self.assertEqual(self.tstate(t.pk), ('CONFIRMED', {self.b3.pk: (100, 100)}))
        self.assertFalse(_unresolved_incoming_transfer_gap(self.k2))
        # Effet de stock REST de la reception (poste K2) : somme du groupe inchangee
        # (le push n'a jamais touche aux stocks : on rejoue la reception REST sur un transfert frais)
        t2 = self.rest_send([self.L(self.b5, 100)])
        self.assertEqual(cl(self.g2).post(f'{T}{t2.pk}/confirm_reception/',
                                          {'lines': [self.L(self.b5, 100, 'quantity_received')]},
                                          format='json').status_code, 200)
        self.assertEqual((self.stock(self.k1, self.b5), self.stock(self.k2, self.b5), self.group(self.b5)),
                         (0, 100, 100))

    def test_envoi_direct_ecart_98_push_confirme_la_receptrice_seule_puis_blocage(self):
        t = self.rest_send([self.L(self.b3, 100)])
        payload, _, _ = self.export_forget(self.k1, t)
        self.post(self.a1, dict(payload, batch_id=uid()))
        self.assertEqual(self.tline(self.a2, t.pk, self.b3, 100, recv=98)[0], 'ACCEPTED')
        self.assertEqual(self.tpush(self.a2, t.pk, 'DISPUTED', quantity_received=98)[0], 'ACCEPTED')
        self.assertTrue(_unresolved_incoming_transfer_gap(self.k2))
        self.assertFalse(_unresolved_incoming_transfer_gap(self.k3))

    # ----- nouveaux defauts : le poste recepteur n'est jamais au courant, ses transitions ne sont pas exportees
    @expectedFailure
    def test_BUG_964_pull_descend_les_transferts_entrants_au_poste_receptrice(self):
        """BUG-964 : SYNC.md §5.3 prevoit que le cloud redescende vers `to_node` tout transfert le concernant
        (alerte + validation par la receptrice). `PullView` ne renvoie ni transfert ni ligne : un poste K2
        hors du cloud n'a aucun moyen de connaitre ni de valider un envoi de K1."""
        t = self.rest_send([self.L(self.b3, 30)])
        payload, _, _ = self.export_forget(self.k1, t)
        self.post(self.a1, dict(payload, batch_id=uid()))
        r = self.a2.get('/api/sync/pull/')
        self.assertEqual(r.status_code, 200)
        blob = str(r.data)
        self.assertIn(str(t.pk), blob)

    @expectedFailure
    def test_BUG_965_validation_de_la_receptrice_est_exportee_par_son_poste(self):
        """BUG-965 : `build_outbound_payload` filtre les transferts par `node_origin == code du poste`. Un transfert
        cree par K1 (node_origin K1) puis confirme par K2 n'est JAMAIS exporte par K2 (sa validation, ses
        quantites recues et l'ecart n'atteignent pas le cloud) ; K1 l'exporte avec un statut qu'il n'a pas le
        droit de pousser (REJECTED a chaque cycle). Attendu : le poste exporte aussi les transferts dont il est
        partie et qu'il a modifies."""
        t = self.rest_send([self.L(self.b3, 30)])
        r = cl(self.g2).post(f'{T}{t.pk}/confirm_reception/', {'lines': [self.L(self.b3, 28, 'quantity_received')]},
                             format='json')
        self.assertEqual(r.status_code, 200, r.content)
        ids_k2 = [x['id'] for x in build_outbound_payload(self.k2.code)['records']['production.BreadTransfer']]
        self.assertIn(str(t.pk), ids_k2)

    @expectedFailure
    def test_BUG_966_resolution_ou_recomptage_du_litige_atteint_le_cloud(self):
        """BUG-966 : `DISPUTED -> CONFIRMED` (re-validation de la receptrice apres recomptage, ou resolution par
        l'emettrice/le siege, REST) n'existe pas dans la machine d'etats de sync : le push est ACCEPTED (donc
        marque synchronise) mais sans aucun effet ; le cloud reste DISPUTED et la cloture de la receptrice reste
        bloquee a vie. Attendu : transition acceptee (receptrice : recomptage egal a l'envoye ; resolution
        documentee) ou rejet motive."""
        t = self.rest_send([self.L(self.b3, 100)])
        payload, _, _ = self.export_forget(self.k1, t)
        self.post(self.a1, dict(payload, batch_id=uid()))
        self.tline(self.a2, t.pk, self.b3, 100, recv=98)
        self.tpush(self.a2, t.pk, 'DISPUTED', quantity_received=98)
        self.assertTrue(_unresolved_incoming_transfer_gap(self.k2))
        # recomptage : 100 recus
        st = self.tline(self.a2, t.pk, self.b3, 100, recv=100)
        self.assertEqual(st[0], 'ACCEPTED')
        st = self.tpush(self.a2, t.pk, 'CONFIRMED', quantity_received=100)
        applied = self.tstate(t.pk)[0] == 'CONFIRMED'
        self.assertTrue(applied or st[0] == 'REJECTED', ('ACCEPTED sans effet', st, self.tstate(t.pk)))
        self.assertTrue(applied)
        self.assertFalse(_unresolved_incoming_transfer_gap(self.k2))


# --------------------------------------------------------------------------- champs decimaux en chaine
class V12DecimalStrings(V12Base):
    """Voisinage de BUG-956 : champs entiers acceptes en '5.0' / '1e1' par `_sync_decimal` mais ecrits bruts."""

    def _no_generic(self, res, ctx):
        for r in reasons(res):
            self.assertNotIn('erreur serveur', r, ctx)

    @expectedFailure
    def test_BUG_967_transfert_entete_quantites_en_chaine_decimale(self):
        """BUG-967 : creation d'un `BreadTransfer` avec `quantity_sent`/`quantity_received` = '5.0' (ou '1e1',
        5.0) : le controle strict l'accepte (entier valide) mais la valeur brute est ecrite telle quelle dans le
        PositiveIntegerField : ValueError -> « erreur serveur ». Attendu : normalise en entier ou rejet motive."""
        for field in ('quantity_sent', 'quantity_received'):
            for val in ('5.0', '1e1', ' 7 ', 5.0, '+3'):
                tid = uid()
                st = self.tpush(self.a2, tid, 'PENDING', node_origin='Q2', **{field: val})
                self.assertNotIn('erreur serveur', st[1] or '', (field, val))
                if st[0] == 'ACCEPTED':
                    got = getattr(BreadTransfer.objects.get(pk=tid), field)
                    self.assertEqual(got, int(Dc(str(val).strip())), (field, val))

    def test_ligne_de_transfert_quantites_en_chaine_decimale(self):
        t = self.rest_send([self.L(self.b3, 10)])
        for val in ('5.0', '1e1', ' 7 ', 8.0):
            st = self.tline(self.a1, t.pk, self.b5, val)
            self.assertNotIn('erreur serveur', st[1] or '', val)
            BreadTransferLine.objects.filter(transfer_id=t.pk, bread_price=self.b5).delete()

    def test_reception_en_chaine_decimale_sur_ligne_et_entete(self):
        t = self.rest_send([self.L(self.b3, 10)])
        for val in ('10.0', '1e1', 10.0):
            st = self.tline(self.a2, t.pk, self.b3, 10, recv=val)
            self.assertNotIn('erreur serveur', st[1] or '', val)
        st = self.tpush(self.a2, t.pk, 'CONFIRMED', quantity_received='10.0')
        self.assertEqual(st[0], 'ACCEPTED')
        self.assertEqual(BreadTransfer.objects.get(pk=t.pk).quantity_received, 10)
        self.assertEqual(self.tstate(t.pk)[1][self.b3.pk], (10, 10))

    @expectedFailure
    def test_BUG_968_dispositions_quantites_en_chaine_decimale(self):
        """BUG-968 : `BreadDisposal` avec `quantity='3.0'`/`unit_price_sold='100.0'` (ou '1e1', 3.0) : controle
        strict OK, mais valeurs brutes -> `quantity * unit_price_sold` (str * str) TypeError -> « erreur serveur ».
        Attendu : normalise en entier (comme `_push_production_session_line`) ou rejet motive."""
        s = self.sess()
        push(self.a1, LBL_S, s)
        for qf, pf in (('3.0', '100.0'), ('1e1', '50'), (' 4 ', '25'), (3.0, 100.0)):
            did = uid()
            st = push(self.a1, 'production.BreadDisposal', {
                'id': did, 'session': s['id'], 'bread_price': self.b3.pk, 'disposal_type': 'UNSOLD',
                'quantity': qf, 'unit_price_sold': pf})
            self.assertNotIn('erreur serveur', st[1] or '', (qf, pf))
            if st[0] == 'ACCEPTED':
                d = BreadDisposal.objects.get(pk=did)
                self.assertEqual((d.quantity, d.unit_price_sold), (int(Dc(str(qf).strip())), int(Dc(str(pf).strip()))))

    def test_ligne_de_fournee_quantite_en_chaine(self):
        s = self.sess()
        push(self.a1, LBL_S, s)
        for val in ('5.0', 7.0, ' 3 '):
            st = push(self.a1, 'production.ProductionSessionLine',
                      {'session': s['id'], 'bread_price': self.b3.pk, 'quantity': val})
            self.assertNotIn('erreur serveur', st[1] or '', val)
            self.assertEqual(st[0], 'ACCEPTED', val)
        st = push(self.a1, 'production.ProductionSessionLine',
                  {'session': s['id'], 'bread_price': self.b5.pk, 'quantity': '1e1'})
        self.assertNotIn('erreur serveur', st[1] or '')

    def test_mouvement_consommable_quantites_decimales(self):
        for qty, price in (('0.25', '12.5'), ('1e1', '0'), ('0.33', '1e2'), (0.5, 3.25)):
            st = push(self.a1, 'production.ConsumableMovement', {
                'id': uid(), 'node': self.k1.code, 'consumable_type': 'YEAST', 'movement_type': 'ENTRY',
                'quantity': qty, 'unit_price': price, 'unit': 'paquet'})
            self.assertNotIn('erreur serveur', st[1] or '', (qty, price))

    def test_motif_clair_sur_valeurs_hostiles_de_transfert(self):
        t = self.rest_send([self.L(self.b3, 10)])
        for val in ('abc', '1.5', '-1', 3_000_000_000, '٣', [1], {'a': 1}, True):
            for api, rec in ((self.a1, {'id': uid(), 'from_node': 'Q1', 'to_node': 'Q2',
                                        'transfer_status': 'PENDING', 'quantity_sent': val}),
                             (self.a2, {'id': str(t.pk), 'from_node': 'Q1', 'to_node': 'Q2',
                                        'transfer_status': 'CONFIRMED', 'quantity_received': val})):
                st = push(api, LBL_T, rec)
                self.assertEqual(st[0], 'REJECTED', (val, st))
                self.assertNotIn('erreur serveur', st[1] or '', val)
        self.assertEqual(self.tstate(t.pk)[0], 'RESPONDED')
