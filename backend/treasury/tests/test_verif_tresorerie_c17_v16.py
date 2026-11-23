"""Cycle 17 partie C (testeur-tresorerie, 2026-11-23-c17) : verification independante de BUG-996
(resubmit_count seulement apres infirmation) et balayage final (finance, blockchain, livre,
verrou de vente BUG-973, journee 2 postes + cloud). Donnees fictives. Code applicatif non modifie.
"""
import datetime as dt
from datetime import timedelta
from decimal import Decimal as Dc

from core.models import Node
from core.testing import make_bread_price, make_client, make_user
from finance.models import FinancialYear
from sync.management.commands.sync_now import build_outbound_payload
from treasury.models import CashbookEntry, CashClosure, DisbursementVoucher
from treasury.tests.test_cycle1_tresorerie_c import BILLS, cl, today
from treasury.tests.test_verif_tresorerie_c10_v9 import CLO
from treasury.tests.test_verif_tresorerie_c13_v12 import Base13

INV = '/api/sales/invoices/'


class V996(Base13):
    def _reject(self, cid):
        r = cl(self.dirn).post(f"/api/treasury/closures/{cid}/reject/", {'reason': 'recompter'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def _put(self, cid, **bills):
        body = {'date': str(today()), **{b: 0 for b in BILLS}, 'bills_10000': 1, **bills}
        return cl(self.g1).put(f"/api/treasury/closures/{cid}/", body, format='json')

    def _count(self, cid):
        return CashClosure.objects.get(pk=cid).resubmit_count

    def _new(self):
        self.report(self.n1, 'A', '10000')
        return self.close(self.g1, {'bills_10000': 1}).json()['id']

    def test_editions_non_infirmees_n_incrementent_jamais(self):
        cid = self._new()
        for _ in range(3):
            self.assertEqual(self._put(cid).status_code, 200)
        self.assertEqual(self._count(cid), 0)

    def test_une_resoumission_par_infirmation_exactement(self):
        cid = self._new()
        for i in (1, 2, 3):
            self._reject(cid)
            self.assertEqual(self._put(cid).status_code, 200)
            self.assertEqual(self._count(cid), i)
            self.assertEqual(self._put(cid).status_code, 200)  # edition suivante, non infirmee
            self.assertEqual(self._count(cid), i)

    def test_resoumission_refusee_ne_touche_ni_compteur_ni_infirmation(self):
        cid = self._new()
        self._reject(cid)
        r = self._put(cid, bills_10000=-1)
        self.assertEqual(r.status_code, 400, r.content)
        c = CashClosure.objects.get(pk=cid)
        self.assertEqual((c.is_rejected, c.resubmit_count), (True, 0))

    def test_rejeu_lot_anterieur_apres_edition_puis_infirmation_reste_infirme(self):
        cid = self._new()
        self.assertEqual(self._put(cid).status_code, 200)
        rec = next(x for x in build_outbound_payload('C1')['records'][CLO] if x['id'] == cid)
        self.assertEqual(rec['resubmit_count'], 0)
        self._reject(cid)
        for _ in range(3):
            self.push(self.raw1, CLO, rec)
        self.assertTrue(CashClosure.objects.get(pk=cid).is_rejected)

    def test_cycle_complet_poste_cloud_resoumission_rejeu_versement(self):
        """Poste -> cloud (compteur 0) -> infirmation -> edition poste (compteur 1) -> push : levee ;
        rejeu du meme lot : rien ; confirmation puis versement ; chaine valide."""
        self.report(self.n1, 'A', '10000')
        rec = self.clo(total_entries='10000')
        self.push(self.raw1, CLO, rec)
        self._reject(rec['id'])
        self.push(self.raw1, CLO, dict(rec, resubmit_count=1))
        self.assertFalse(CashClosure.objects.get(pk=rec['id']).is_rejected)
        self._reject(rec['id'])
        self.push(self.raw1, CLO, dict(rec, resubmit_count=1))   # rejeu
        self.assertTrue(CashClosure.objects.get(pk=rec['id']).is_rejected)
        self.push(self.raw1, CLO, dict(rec, resubmit_count=2))   # 2e resoumission
        self.assertEqual(self.valider(rec['id']).status_code, 200)
        self.assertEqual(self.verser(rec['id']).status_code, 201)
        self.assertEqual(self.valider(rec['id']).status_code, 400)
        self.assertEqual(CashbookEntry.objects.count(), 1)
        self.assertTrue(self.chain_ok())


class Verrou(Base13):
    """BUG-973 avec clotures infirmees / resoumises / confirmees."""

    def setUp(self):
        self.bpx = make_bread_price('MOYEN', 'Pain 500', 500)
        self.cli = make_client(self.n1)
        Node.objects.filter(pk=self.n1.pk).update(block_sales_after_closure=True, handover_time=dt.time(0, 0))
        self.n1.refresh_from_db()

    def sale(self):
        return cl(self.fac).post(INV, {'payment_type': 'CREDIT', 'payment_amount': 0, 'client': str(self.cli.pk),
                                       'lines': [{'bread_price': self.bpx.pk, 'quantity': 1}]}, format='json')

    def test_bloque_jusqu_a_la_confirmation_meme_apres_infirmation_et_resoumission(self):
        self.report(self.n1, 'A', '10000')
        self.assertEqual(self.sale().status_code, 403)               # pas de cloture
        cid = self.close(self.g1, {'bills_10000': 1}).json()['id']
        self.assertEqual(self.sale().status_code, 403)               # en attente
        cl(self.dirn).post(f'/api/treasury/closures/{cid}/reject/', {'reason': 'x'}, format='json')
        self.assertEqual(self.sale().status_code, 403)               # infirmee
        body = {'date': str(today()), **{b: 0 for b in BILLS}, 'bills_10000': 1}
        self.assertEqual(cl(self.g1).put(f'/api/treasury/closures/{cid}/', body, format='json').status_code, 200)
        self.assertEqual(self.sale().status_code, 403)               # resoumise
        self.assertEqual(self.valider(cid).status_code, 200)
        self.assertEqual(self.sale().status_code, 201)               # confirmee (BUG-986 : a clarifier)

    def test_cloture_confirmee_d_un_autre_poste_ne_debloque_pas(self):
        CashClosure.objects.create(node=self.n2, date=today(), is_validated=True, node_origin='C2')
        self.assertEqual(self.sale().status_code, 403)


class Balayage(Base13):
    def test_finance_lecture_reservee_et_etats_n_n1_sans_500(self):
        self.report(self.n1, 'A', '10000')
        cid = self.close(self.g1, {'bills_10000': 1}).json()['id']
        self.assertEqual(self.valider(cid).status_code, 200)
        self.assertEqual(self.verser(cid).status_code, 201)
        y = today().year
        fy = FinancialYear.objects.create(year=y)
        urls = [f'/api/finance/years/{fy.pk}/{a}/' for a in
                ('income_statement', 'cashflow', 'balance_sheet', 'comparative')]
        urls += ['/api/finance/years/', '/api/finance/years/summary/']
        for u in urls:
            for who in (self.g1, self.fac, self.liv, self.g2):
                self.assertEqual(cl(who).get(u).status_code, 403, (who.role, u))
            self.assertEqual(cl().get(u).status_code, 401, u)
            for who in (self.dirn, self.compt, self.adm):
                self.assertLess(cl(who).get(u).status_code, 400, (who.role, u))
        for a in ('income_statement', 'cashflow', 'balance_sheet', 'comparative'):
            self.assertEqual(cl(self.dirn).post(f'/api/finance/years/{fy.pk}/{a}/', {}, format='json').status_code, 405)
        # annees hors plage refusees a la creation (400) ; annee ancienne valide : N-1 vide, pas de 500
        self.assertEqual(cl(self.dirn).post('/api/finance/years/', {'year': 1}, format='json').status_code, 400)
        old = cl(self.dirn).post('/api/finance/years/', {'year': 2000}, format='json')
        self.assertEqual(old.status_code, 201, old.content)
        self.assertEqual(cl(self.dirn).get(f"/api/finance/years/{old.json()['id']}/comparative/").status_code, 200)

    def test_blockchain_et_treasury_meme_verdict_apres_versements_et_bon(self):
        for node, g in ((self.n1, self.g1), (self.n2, self.g2)):
            self.report(node, 'A', '20000')
            cid = self.close(g, {'bills_20000': 1}).json()['id']
            self.assertEqual(self.valider(cid).status_code, 200)
            self.assertEqual(self.verser(cid).status_code, 201)
        r = cl(self.dirn).post('/api/treasury/vouchers/', {'date': str(today()), 'motif': 'Achat',
                                                           **{b: 0 for b in BILLS}, 'bills_5000': 2}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual([e.running_balance for e in CashbookEntry.chain_queryset()],
                         [Dc('20000'), Dc('40000'), Dc('30000')])
        self.assertTrue(self.chain_ok())
        rc = cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {}, format='json')
        self.assertEqual(rc.status_code, 200, rc.content)
        gs = cl(self.dirn).get('/api/blockchain/snapshots/global_status/').json()
        self.assertEqual(cl(self.dirn).get('/api/blockchain/alerts/').json().get('count', 0), 0)
        self.assertTrue(gs.get('is_intact', gs.get('chain_valid', True)), gs)
        # alteration directe : les deux endpoints crient
        e = CashbookEntry.objects.filter(node=self.n1).first()
        CashbookEntry.objects.filter(pk=e.pk).update(entry_amount=Dc('99999'))
        self.assertFalse(self.chain_ok())
        rc = cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {}, format='json')
        self.assertEqual(rc.status_code, 200, rc.content)
        self.assertGreaterEqual(cl(self.dirn).get('/api/blockchain/alerts/').json().get('count', 0), 1)

    def test_bon_de_decaissement_immuable_et_solde_jamais_negatif(self):
        self.report(self.n1, 'A', '10000')
        cid = self.close(self.g1, {'bills_10000': 1}).json()['id']
        self.valider(cid)
        self.verser(cid)
        b = {b_: 0 for b_ in BILLS}
        ok = cl(self.dirn).post('/api/treasury/vouchers/', {'date': str(today()), 'motif': 'x', **b, 'bills_10000': 1}, format='json')
        self.assertEqual(ok.status_code, 201, ok.content)
        ko = cl(self.dirn).post('/api/treasury/vouchers/', {'date': str(today()), 'motif': 'x', **b, 'bills_50': 1}, format='json')
        self.assertEqual(ko.status_code, 400, ko.content)
        self.assertEqual(DisbursementVoucher.objects.count(), 1)
        self.assertEqual(CashbookEntry.chain_queryset().last().running_balance, Dc('0'))
        self.assertTrue(self.chain_ok())
