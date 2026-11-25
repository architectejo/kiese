"""Cycle 18 partie C (testeur-tresorerie, 2026-11-23-c18) : balayage final independant.
(1) clotures / livre inchanges par les transferts et les marqueurs de miroir (BUG-1000 a 1003) ;
(2) journee de 2 jours sur 2 postes + cloud ; (3) permissions de closure-status ?node=, du journal
SyncConflictLog par role, volumetrie TransferMirror / SyncConflictLog, exports (final_report,
period_summary). Donnees fictives. Code applicatif non modifie.
"""
import datetime as dt
import uuid
from datetime import timedelta
from decimal import Decimal as Dc

from core.models import Config, Node
from core.testing import make_user
from finance.models import FinancialYear
from production.models import BreadTransfer
from sync.models import SyncConflictLog, TransferMirror
from sync.services import _log_conflict
from treasury.models import CashbookEntry, CashClosure, DisbursementVoucher
from treasury.tests.test_cycle1_tresorerie_c import BILLS, cl, today
from treasury.tests.test_verif_tresorerie_c10_v9 import CLO, RAP
from treasury.tests.test_verif_tresorerie_c13_v12 import Base13
from treasury.tests.test_verif_tresorerie_c8_v7 import PUSH, push_client

CS = '/api/treasury/closure-status/'
TYPES = ('TRANSFER_STATE_CONFLICT', 'MIRROR_OUT_OF_BOUNDS', 'IDENTITE_OBSOLETE',
         'HORLOGE_POSTE_EN_AVANCE', 'CODE_CLIENT_EN_CONFLIT')


class Permissions18(Base13):
    def test_closure_status_node_param_par_role(self):
        Node.objects.filter(pk=self.n2.pk).update(block_sales_after_closure=True)
        for who in (self.g1, self.fac, self.liv):
            for p in (self.n2.code, str(self.n2.pk), self.n1.code):
                self.assertEqual(cl(who).get(CS, {'node': p}).status_code, 403, (who.role, p))
            self.assertEqual(cl(who).get(CS).status_code, 200, who.role)
        for who in (self.dirn, self.compt, self.adm):
            r = cl(who).get(CS, {'node': self.n2.code})
            self.assertEqual(r.status_code, 200, (who.role, r.content))
            self.assertTrue(r.json()['enabled'])
            self.assertEqual(cl(who).get(CS, {'node': str(self.n2.pk)}).json(), r.json())
        self.assertEqual(cl().get(CS).status_code, 401)
        self.assertEqual(cl().get(CS, {'node': self.n1.code}).status_code, 401)

    def test_closure_status_param_hostile_ou_inconnu_jamais_500(self):
        for p in ("'; DROP TABLE core_node;--", 'ZZ9', str(uuid.uuid4()), 'not-a-uuid', 'é' * 300, '\x00', '%'):
            r = cl(self.dirn).get(CS, {'node': p})
            self.assertEqual(r.status_code, 404, (p[:20], r.status_code))
        # un gerant ne devine pas l'existence d'un code : 403 avant 404
        self.assertEqual(cl(self.g1).get(CS, {'node': 'ZZ9'}).status_code, 403)
        # direction sans noeud et sans parametre : desactive, pas d'erreur
        r = cl(self.dirn).get(CS)
        self.assertEqual((r.status_code, r.json()['enabled'], r.json()['blocked']), (200, False, False))
        # SIEGE : jamais bloque
        self.assertFalse(cl(self.dirn).get(CS, {'node': 'SIEGE'}).json()['blocked'])

    def test_closure_status_lecture_seule_et_pas_de_fuite_de_champs(self):
        for m in ('post', 'put', 'patch', 'delete'):
            self.assertEqual(getattr(cl(self.dirn), m)(CS, {}, format='json').status_code, 405, m)
        keys = set(cl(self.g1).get(CS).json())
        self.assertEqual(keys, {'closure_hour', 'blocked', 'reason', 'closure_date', 'validated', 'enabled'})

    def test_journal_conflits_par_role_et_5_types(self):
        for t in TYPES:
            _log_conflict(self.n1, 'x.Model', uuid.uuid4(), t, 'detail ' + t)
        for who in (self.adm, self.dirn, self.compt):
            r = cl(who).get('/api/sync/conflicts/')
            self.assertEqual(r.status_code, 200, (who.role, r.content))
            body = r.json()
            rows = body['results'] if isinstance(body, dict) else body
            self.assertEqual({x['conflict_type'] for x in rows}, set(TYPES))
            self.assertTrue(all(x['node_display'] == 'C1' for x in rows))
        for who in (self.g1, self.g2, self.fac, self.liv):
            self.assertEqual(cl(who).get('/api/sync/conflicts/').status_code, 403, who.role)
        self.assertEqual(cl().get('/api/sync/conflicts/').status_code, 401)
        # jeton de noeud : route humaine, refuse
        self.assertIn(push_client(self.raw1).get('/api/sync/conflicts/').status_code, (401, 403))

    def test_journal_conflits_lecture_seule(self):
        c = _log_conflict(self.n1, 'x.Model', 'o1', TYPES[0], 'd')
        for who in (self.adm, self.dirn):
            for m in ('post', 'put', 'patch', 'delete'):
                r = getattr(cl(who), m)('/api/sync/conflicts/', {'conflict_type': 'X'}, format='json')
                self.assertEqual(r.status_code, 405, (who.role, m))
            r = cl(who).patch(f'/api/sync/conflicts/{c.pk}/', {'resolution_note': 'x'}, format='json')
            self.assertIn(r.status_code, (404, 405))
        self.assertEqual(SyncConflictLog.objects.count(), 1)

    def test_exports_direction_seulement_et_coherents_avec_le_livre(self):
        self.report(self.n1, 'A', '30000')
        cid = self.close(self.g1, {'bills_20000': 1, 'bills_10000': 1}).json()['id']
        self.valider(cid)
        self.verser(cid)
        v = cl(self.dirn).post('/api/treasury/vouchers/', {'date': str(today()), 'motif': 'x',
                                                           **{b: 0 for b in BILLS}, 'bills_10000': 1}, format='json')
        self.assertEqual(v.status_code, 201, v.content)
        for u in ('/api/treasury/vouchers/final_report/', '/api/treasury/cashbook/period_summary/',
                  '/api/treasury/cashbook/'):
            for who in (self.g1, self.fac, self.liv):
                self.assertEqual(cl(who).get(u).status_code, 403, (who.role, u))
            self.assertEqual(cl().get(u).status_code, 401, u)
        fr = cl(self.compt).get('/api/treasury/vouchers/final_report/').json()
        self.assertEqual((Dc(fr['total_disbursed']), Dc(fr['remaining_balance'])), (Dc('10000'), Dc('20000')))
        ps = cl(self.dirn).get('/api/treasury/cashbook/period_summary/').json()
        self.assertEqual([(x['node__code'], Dc(x['total_entries'])) for x in ps if x['node__code'] == 'C1'],
                         [('C1', Dc('30000'))])
        self.assertEqual(sum(Dc(x['total_exits']) for x in ps), Dc('10000'))


class Volumetrie18(Base13):
    def _push_mirrors(self, raw, mirrors):
        r = push_client(raw).post(PUSH, {'batch_id': str(uuid.uuid4()), 'records': {}, 'mirrors': mirrors},
                                  format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_rejeux_de_marqueur_hors_borne_une_ligne_de_conflit_une_ligne_miroir(self):
        t = self.transfer(100, 100, status='CONFIRMED')
        bp = str(self.bp.pk)
        for _ in range(40):
            self._push_mirrors(self.raw1, {str(t.pk): {bp: [0, 500]}})
        rows = SyncConflictLog.objects.filter(conflict_type='MIRROR_OUT_OF_BOUNDS')
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().occurrences, 40)
        self.assertEqual(TransferMirror.objects.filter(node=self.n1, transfer_id=t.pk).count(), 1)
        self.assertEqual(TransferMirror.objects.filter(node=self.n1).first().applied, {})

    def test_identifiants_forges_ou_etrangers_ne_creent_aucune_ligne(self):
        t = self.transfer(10, 10, status='CONFIRMED', frm=self.n2, to=self.siege)  # C1 n'est pas partie
        forged = {str(uuid.uuid4()): {str(self.bp.pk): [1, 1]} for _ in range(700)}
        forged[str(t.pk)] = {str(self.bp.pk): [1, 1]}
        self._push_mirrors(self.raw1, forged)
        self.assertEqual(TransferMirror.objects.count(), 0)
        self.assertEqual(SyncConflictLog.objects.count(), 0)

    def test_marqueur_valide_ne_change_ni_cloture_ni_livre(self):
        self.report(self.n1, 'A', '10000')
        t = self.transfer(100, 100, status='CONFIRMED')
        d = self.close(self.g1, {'bills_10000': 1}).json()
        before = (d['total_entries'], d['net_cash'], d['cash_gap'])
        self._push_mirrors(self.raw1, {str(t.pk): {str(self.bp.pk): [0, 100]}})
        self._push_mirrors(self.raw1, {str(t.pk): {str(self.bp.pk): [0, 9999]}})  # hors borne
        c = CashClosure.objects.get(pk=d['id'])
        self.assertEqual((str(c.total_entries), str(c.net_cash), str(c.cash_gap)), before)
        self.assertEqual(self.valider(d['id']).status_code, 200)
        self.assertEqual(self.verser(d['id']).status_code, 201)
        self.assertEqual(CashbookEntry.chain_queryset().last().running_balance, Dc('10000'))
        self.assertTrue(self.chain_ok())

    def test_litige_entrant_bloque_puis_libere_apres_resolution_au_cloud(self):
        self.report(self.n1, 'A', '10000')
        t = self.transfer(100, 98)  # DISPUTED entrant
        self.assertEqual(self.close(self.g1, {'bills_10000': 1}).status_code, 400)
        self._push_mirrors(self.raw1, {str(t.pk): {str(self.bp.pk): [0, 98]}})
        self.assertEqual(self.close(self.g1, {'bills_10000': 1}).status_code, 400)  # un marqueur ne leve rien
        BreadTransfer.objects.filter(pk=t.pk).update(transfer_status='CONFIRMED')
        t.lines.update(quantity_received=100)
        r = self.close(self.g1, {'bills_10000': 1})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Dc(r.json()['net_cash']), Dc('10000'))  # les transferts n'entrent pas dans la caisse


class Journee18(Base13):
    def _status(self, who, node):
        return cl(who).get(CS, {'node': node.code}).json()

    def test_deux_jours_deux_postes_et_cloud(self):
        d1, d2 = today() - timedelta(days=1), today()
        Node.objects.filter(pk=self.n1.pk).update(block_sales_after_closure=True, handover_time=dt.time(0, 0))
        Config.objects.filter(pk=Config.get_instance().pk).update(allow_backdated_sales=True)
        # ---- jour 1 ----
        self.report(self.n1, 'A', '50000', date=d1)
        self.report(self.n1, 'B', '30000', credit='9000', date=d1)
        self.report(self.n2, 'A', '40000', date=d1)
        self.assertEqual(self.expense(self.g1, '12500', date=d1).status_code, 201)
        self.assertEqual(self.expense(self.g2, '5000', date=d1).status_code, 201)
        t = self.transfer(100, 100, status='CONFIRMED')  # n2 -> n1, sans ecart
        c1 = self.close(self.g1, {'bills_20000': 3, 'bills_5000': 1, 'bills_1000': 2, 'bills_500': 1}, date=str(d1))
        self.assertEqual(c1.status_code, 201, c1.content)
        c1 = c1.json()
        self.assertEqual((Dc(c1['net_cash']), Dc(c1['cash_gap'])), (Dc('67500'), Dc('0')))
        c2 = self.close(self.g2, {'bills_20000': 1, 'bills_10000': 1, 'bills_5000': 1, 'bills_500': 1}, date=str(d1))
        self.assertEqual(c2.status_code, 201, c2.content)
        c2 = c2.json()
        self.assertEqual((Dc(c2['net_cash']), Dc(c2['cash_gap'])), (Dc('35000'), Dc('500')))
        # infirmation puis resoumission exacte de n2
        r = cl(self.dirn).post(f"/api/treasury/closures/{c2['id']}/reject/", {'reason': 'recompter'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        body = {'date': str(d1), **{b: 0 for b in BILLS}, 'bills_20000': 1, 'bills_10000': 1, 'bills_5000': 1}
        self.assertEqual(cl(self.g2).put(f"/api/treasury/closures/{c2['id']}/", body, format='json').status_code, 200)
        c2b = CashClosure.objects.get(pk=c2['id'])
        self.assertEqual((c2b.resubmit_count, c2b.cash_gap), (1, Dc('0')))
        for c in (c1, c2):
            self.assertEqual(self.valider(c['id']).status_code, 200)
            self.assertEqual(self.verser(c['id']).status_code, 201)
        entries = list(CashbookEntry.chain_queryset())
        self.assertEqual([e.running_balance for e in entries], [Dc('67500'), Dc('102500')])
        self.assertEqual({e.piece_number for e in entries},
                         {f"VC-C1-{d1:%Y%m%d}", f"VC-C2-{d1:%Y%m%d}"})
        # BUG-1130 (midi a midi) : closure-status porte sur la journee TERMINEE (ici le jour 1,
        # heure de cloture 00:00) : validee -> ventes debloquees ; le jour 2 sera exige a sa fin.
        st = self._status(self.dirn, self.n1)
        self.assertEqual((st['blocked'], st['validated'], st['closure_date']), (False, True, str(d1)))
        # ---- jour 2 ----
        self.report(self.n1, 'A', '20000', date=d2)
        disputed = self.transfer(50, 48, frm=self.n2, to=self.n1)
        r = self.close(self.g1, {'bills_20000': 1})
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('detail', r.json())
        BreadTransfer.objects.filter(pk=disputed.pk).update(transfer_status='CONFIRMED')
        disputed.lines.update(quantity_received=50)
        c3 = self.close(self.g1, {'bills_20000': 1})
        self.assertEqual(c3.status_code, 201, c3.content)
        # n2, jour 2 : poste -> cloud (push)
        raw2 = self.raw2
        rec = {'id': str(uuid.uuid4()), 'node': 'C2', 'team': 'B', 'date': str(d2), 'total_cash_sales': '25000',
               'total_credit_sales': '0', 'theoretical_cash': '25000'}
        r = push_client(raw2).post(PUSH, {'batch_id': str(uuid.uuid4()), 'records': {RAP: [rec]}}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        clo = {'id': str(uuid.uuid4()), 'node': 'C2', 'date': str(d2), 'total_entries': '25000',
               'total_expenses': '0', **{b: 0 for b in BILLS}, 'bills_20000': 1, 'bills_5000': 1}
        r = push_client(raw2).post(PUSH, {'batch_id': str(uuid.uuid4()), 'records': {CLO: [clo]}}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(CashClosure.objects.filter(pk=clo['id']).exists(), r.content)
        # validation + versements (BUG-1130 : la journee 1 validee ne bloque plus les ventes du jour 2)
        self.assertFalse(self._status(self.dirn, self.n1)['blocked'])
        for cid in (c3.json()['id'], clo['id']):
            self.assertEqual(self.valider(cid).status_code, 200)
            self.assertEqual(self.verser(cid).status_code, 201)
            self.assertEqual(self.verser(cid).status_code, 400)  # double versement
        st = self._status(self.dirn, self.n1)
        self.assertEqual((st['blocked'], st['validated']), (False, True))
        v = cl(self.dirn).post('/api/treasury/vouchers/', {'date': str(d2), 'motif': 'Achat', **{b: 0 for b in BILLS},
                                                           'bills_20000': 2}, format='json')
        self.assertEqual(v.status_code, 201, v.content)
        # ---- soldes, chaine, etats ----
        bal = [e.running_balance for e in CashbookEntry.chain_queryset()]
        self.assertEqual(bal, [Dc('67500'), Dc('102500'), Dc('122500'), Dc('147500'), Dc('107500')])
        self.assertTrue(self.chain_ok())
        self.assertEqual(DisbursementVoucher.objects.count(), 1)
        rc = cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {}, format='json')
        self.assertEqual(rc.status_code, 200, rc.content)
        self.assertEqual(cl(self.dirn).get('/api/blockchain/alerts/').json().get('count', 0), 0)
        fy = FinancialYear.objects.create(year=d2.year)
        FinancialYear.objects.create(year=d2.year - 1)
        for a in ('income_statement', 'cashflow', 'balance_sheet', 'comparative'):
            r = cl(self.compt).get(f'/api/finance/years/{fy.pk}/{a}/')
            self.assertEqual(r.status_code, 200, (a, r.content))
        # la caisse du livre egale la somme des clotures versees moins les bons
        self.assertEqual(bal[-1], Dc('67500') + Dc('35000') + Dc('20000') + Dc('25000') - Dc('40000'))
