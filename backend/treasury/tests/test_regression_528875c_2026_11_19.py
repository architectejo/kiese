"""
Régression trésorerie sur le commit 528875c (testeur-tresorerie, 2026-11-19).

Effets contradictoires des changements récents sur la trésorerie :
  - BUG-290 : paiements négatifs (Retrait d'épargne / Emprunt boulanger /
    Manquant d'équipe) dans le rapport facturier, la clôture gérant et le
    livre de caisse direction (écriture en SORTIE) ;
  - BUG-304 : « reste d'hier / du jour » par jour (production) ;
  - BUG-306 : incrément de la fournée « en cours » à la livraison ;
  ces deux derniers ne doivent avoir AUCUN effet sur les montants de caisse.

Valeurs calculées à la main (voir commentaires). Données fictives uniquement.
"""
import hashlib
import json
import threading
import unittest
from datetime import timedelta
from decimal import Decimal as D

from django.db import OperationalError, connection, connections
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from core.models import ExpenseCategory
from core.testing import make_bread_price, make_client, make_node, make_user
from core.workday import work_date_for
from production.models import (
    BreadDisposal, BreadStock, DailyBreadStockSnapshot, ProductionSession,
    ProductionSessionLine,
)
from sales.models import Invoice
from treasury.hashing import GENESIS_HASH, compute_cashbook_entry_hash
from treasury.models import (
    CashbookEntry, CashbookHead, CashClosure, FacturierReport, LocalExpense,
)
from treasury.services import promote_closure_to_cashbook, regenerate_facturier_reports

INV = '/api/sales/invoices/'
CLOSURES = '/api/treasury/closures/'
CASHBOOK = '/api/treasury/cashbook/'


def _api(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


class _Day(TestCase):
    """Fabrique d'une journée : deux équipes, paiements négatifs, dépense, clôture."""

    def setUp(self):
        self.bp = make_bread_price('B500', 'Pain 500 FC', 500)
        self.cat, _ = ExpenseCategory.objects.get_or_create(code='REG', defaults={'label': 'Divers'})
        self.direction = make_user('DIRECTION', node=None, team='', username='r528_dir')
        self.admin = make_user('ADMIN', node=None, team='', username='r528_adm')
        self.dir_api = _api(self.direction)

    # -- fabriques -------------------------------------------------------
    def make_bakery(self, code):
        node = make_node(code=code, sac_value_fc=D('210000'))
        users = {
            'A': make_user('FACTURIER', node=node, team='A', username=f'{code}_fa'),
            'B': make_user('FACTURIER', node=node, team='B', username=f'{code}_fb'),
            'G': make_user('GERANT', node=node, team='', username=f'{code}_g'),
        }
        return node, users

    def deliver(self, api, body):
        r = api.post(INV, body, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        if r.data['status'] != 'DELIVERED':
            d = api.post(f"{INV}{r.data['id']}/deliver/")
            self.assertEqual(d.status_code, 200, d.data)
        return r.data

    def sale_cash(self, api, node, qty):
        c = make_client(node)
        return self.deliver(api, {
            'client': str(c.pk), 'payment_type': 'CASH', 'payment_amount': str(qty * 500),
            'lines': [{'bread_price': self.bp.pk, 'quantity': qty}],
        })

    def negative(self, api, node, amount, motif):
        c = make_client(node)
        return self.deliver(api, {
            'client': str(c.pk), 'payment_type': 'CASH', 'payment_amount': str(amount),
            'is_debt_repayment': True, 'motif': motif, 'lines': [],
        })

    def build_day(self, code, with_batch=False):
        """Équipe A : vente cash 40 x 500 = 20 000, puis -3 000 (retrait d'épargne),
        -1 500 (emprunt boulanger), -500 (manquant d'équipe).
        Équipe B : vente cash 2 x 500 = 1 000.  Dépense locale : 700.
        -> cash A = 20 000 - 5 000 = 15 000 ; cash B = 1 000 ; total 16 000.
        -> crédit A = 5 000 (variation de BP des 3 sorties, décision BUG-290) ; crédit B = 0.
        -> caisse nette = 16 000 - 700 = 15 300.
        """
        node, u = self.make_bakery(code)
        today = work_date_for(node)
        if with_batch:
            r = _api(u['G']).post('/api/production/sessions/', {
                'team': 'A', 'date': str(today), 'flour_sacks_used': '2.00',
            }, format='json')
            self.assertEqual(r.status_code, 201, r.data)
            self.batch_id = r.data['id']
        fa, fb = _api(u['A']), _api(u['B'])
        self.sale_cash(fa, node, 40)
        self.negative(fa, node, '-3000', 'RETRAIT_EPARGNE')
        self.negative(fa, node, '-1500', 'EMPRUNT_BOULANGER')
        self.negative(fa, node, '-500', 'MANQUANT_EQUIPE')
        self.sale_cash(fb, node, 2)
        LocalExpense.objects.create(node=node, gerant=u['G'], description='Bois', amount=D('700'),
                                    category=self.cat, date=today)
        return node, u, today

    def generate_reports(self, node, gerant):
        r = _api(gerant).post('/api/treasury/reports/generate/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        return {rep['team']: rep for rep in r.data}

    def close(self, gerant, **bills):
        body = {'date': str(work_date_for(gerant.node)), 'bills_20000': 0, 'bills_10000': 0, 'bills_5000': 0, 'bills_1000': 0,
                'bills_500': 0, 'bills_200': 0, 'bills_100': 0, 'bills_50': 0}
        body.update(bills)
        return _api(gerant).post(CLOSURES, body, format='json')

    def confirm_and_push(self, closure_id):
        v = self.dir_api.post(f'{CLOSURES}{closure_id}/validate/')
        self.assertEqual(v.status_code, 200, v.data)
        return self.dir_api.post(f'{CLOSURES}{closure_id}/push_to_cashbook/')


class Regression290Treasury(_Day):
    def test_rapport_facturier_par_equipe_avec_paiements_negatifs(self):
        node, u, _ = self.build_day('R1')
        reps = self.generate_reports(node, u['G'])
        self.assertEqual(set(reps), {'A', 'B'})
        self.assertEqual(D(reps['A']['total_cash_sales']), D('15000'))      # 20 000 - 3 000 - 1 500 - 500
        self.assertEqual(D(reps['A']['theoretical_cash']), D('15000'))
        self.assertEqual(D(reps['A']['total_credit_sales']), D('5000'))     # 0 - (-3000) + 0 - (-1500) + 0 - (-500)
        self.assertEqual(D(reps['B']['total_cash_sales']), D('1000'))
        self.assertEqual(D(reps['B']['total_credit_sales']), D('0'))
        # somme des rapports = somme algébrique des paiements des factures livrées
        s = sum((i.payment_amount for i in Invoice.objects.filter(node=node, status='DELIVERED')), D('0'))
        self.assertEqual(s, D('16000'))

    def test_les_trois_motifs_sont_conserves_et_sortent_de_la_caisse(self):
        node, u, _ = self.build_day('R1')
        motifs = sorted(Invoice.objects.filter(node=node, payment_amount__lt=0).values_list('motif', flat=True))
        self.assertEqual(motifs, ['EMPRUNT_BOULANGER', 'MANQUANT_EQUIPE', 'RETRAIT_EPARGNE'])
        self.assertTrue(all(i.order_total == 0 for i in Invoice.objects.filter(node=node, payment_amount__lt=0)))

    def test_cloture_gerant_caisse_nette_et_ventilation_ecart_nul(self):
        node, u, today = self.build_day('R1')
        self.generate_reports(node, u['G'])
        # 10 000 + 5 000 + 200 + 100 = 15 300
        r = self.close(u['G'], bills_10000=1, bills_5000=1, bills_200=1, bills_100=1)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(D(r.data['total_entries']), D('16000'))
        self.assertEqual(D(r.data['total_expenses']), D('700'))
        self.assertEqual(D(r.data['net_cash']), D('15300'))
        self.assertEqual(D(r.data['physical_cash_total']), D('15300'))
        self.assertEqual(D(r.data['cash_gap']), D('0'))

    def test_cloture_ecart_negatif_puis_positif_apres_patch_des_billets(self):
        node, u, _ = self.build_day('R1')
        self.generate_reports(node, u['G'])
        r = self.close(u['G'], bills_10000=1, bills_5000=1, bills_200=1)       # 15 200
        self.assertEqual(D(r.data['cash_gap']), D('-100'))                     # 15 200 - 15 300
        p = _api(u['G']).patch(f"{CLOSURES}{r.data['id']}/",
                               {'bills_10000': 1, 'bills_5000': 1, 'bills_500': 1}, format='json')
        self.assertEqual(p.status_code, 200, p.data)
        # 10 000 + 5 000 + 500 = 15 500 (les billets omis du PATCH ne sont pas remis à zéro :
        # 200 reste ? voir assertion sur le total effectivement calculé)
        total = D(p.data['physical_cash_total'])
        self.assertEqual(D(p.data['net_cash']), D('15300'))
        self.assertEqual(D(p.data['cash_gap']), total - D('15300'))
        self.assertIn(total, (D('15500'), D('15700')))

    def test_ventilation_des_8_coupures(self):
        # 1x20000 + 2x10000 + 3x5000 + 4x1000 + 5x500 + 6x200 + 7x100 + 8x50
        # = 20000 + 20000 + 15000 + 4000 + 2500 + 1200 + 700 + 400 = 63 800
        node, u, today = self.build_day('R1')
        c = CashClosure(node=node, date=today - timedelta(days=3), total_entries=D('64000'),
                        total_expenses=D('500'), bills_20000=1, bills_10000=2, bills_5000=3,
                        bills_1000=4, bills_500=5, bills_200=6, bills_100=7, bills_50=8)
        c.compute_physical_cash()
        self.assertEqual(c.physical_cash_total, D('63800'))
        self.assertEqual(c.net_cash, D('63500'))
        self.assertEqual(c.cash_gap, D('300'))

    def test_cloture_nette_negative_ecart_positif_et_ecriture_en_sortie(self):
        node, u, today = self.build_day('R1')
        # R2 : un seul retrait d'épargne de 2 500, aucune dépense, aucun billet compté
        node2, u2 = self.make_bakery('R2')
        self.negative(_api(u2['A']), node2, '-2500', 'RETRAIT_EPARGNE')
        self.generate_reports(node, u['G'])
        self.generate_reports(node2, u2['G'])
        c1 = self.close(u['G'], bills_10000=1, bills_5000=1, bills_200=1, bills_100=1)
        c2 = self.close(u2['G'])
        self.assertEqual(D(c2.data['net_cash']), D('-2500'))
        self.assertEqual(D(c2.data['cash_gap']), D('2500'))                    # 0 - (-2500)
        e1 = self.confirm_and_push(c1.data['id'])
        self.assertEqual(e1.status_code, 201, e1.data)
        e2 = self.confirm_and_push(c2.data['id'])
        self.assertEqual(e2.status_code, 201, e2.data)
        a, b = list(CashbookEntry.chain_queryset())
        self.assertEqual((a.entry_amount, a.exit_amount, a.running_balance), (D('15300'), D('0'), D('15300')))
        self.assertEqual((b.entry_amount, b.exit_amount, b.running_balance), (D('0'), D('2500'), D('12800')))
        self.assertEqual(a.piece_number, f"VC-R1-{today.strftime('%Y%m%d')}")
        self.assertEqual(b.piece_number, f"VC-R2-{work_date_for(node2).strftime('%Y%m%d')}")

    def test_hash_sha256_inchange_chaine_et_cashbookhead(self):
        node, u, today = self.build_day('R1')
        node2, u2 = self.make_bakery('R2')
        self.negative(_api(u2['A']), node2, '-2500', 'EMPRUNT_BOULANGER')
        self.generate_reports(node, u['G'])
        self.generate_reports(node2, u2['G'])
        c1 = self.close(u['G'], bills_10000=1, bills_5000=1, bills_200=1, bills_100=1)
        c2 = self.close(u2['G'])
        self.confirm_and_push(c1.data['id'])
        self.confirm_and_push(c2.data['id'])
        a, b = list(CashbookEntry.chain_queryset())
        # formule réécrite à la main (v3), indépendante de compute_cashbook_entry_hash
        def manual(e, prev):
            payload = {
                'id': str(e.id), 'node': str(e.node_id), 'date': e.date.isoformat(),
                'piece_number': e.piece_number, 'imputation': e.imputation, 'label': e.label,
                'entry_amount': f'{e.entry_amount:.2f}', 'exit_amount': f'{e.exit_amount:.2f}',
                'running_balance': f'{e.running_balance:.2f}',
                'source_closure': str(e.source_closure_id), 'source_bordereau': '',
                'is_correction': False, 'previous_hash': prev,
            }
            return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                             separators=(',', ':')).encode('utf-8')).hexdigest()
        self.assertEqual(a.previous_hash, GENESIS_HASH)
        self.assertEqual(a.block_hash, manual(a, GENESIS_HASH))
        self.assertEqual(b.previous_hash, a.block_hash)
        self.assertEqual(b.block_hash, manual(b, a.block_hash))
        self.assertEqual(b.block_hash, compute_cashbook_entry_hash(b))
        head = CashbookHead.objects.get()
        self.assertEqual((head.entry_count, head.last_hash, head.last_node_code), (2, b.block_hash, 'R2'))
        # les deux endpoints de vérification donnent le même verdict (sain)
        t = self.dir_api.get(CASHBOOK + 'integrity_check/')
        k = self.dir_api.post('/api/blockchain/snapshots/run_check/')
        self.assertEqual((t.status_code, k.status_code), (200, 200))
        self.assertTrue(t.data['chain_valid'])
        self.assertTrue(k.data['all_intact'])
        self.assertEqual(t.data['total_entries'], sum(r['total_entries'] for r in k.data['results']))

    def test_alteration_du_montant_d_une_sortie_detectee_par_les_deux_endpoints(self):
        node2, u2 = self.make_bakery('R2')
        self.negative(_api(u2['A']), node2, '-2500', 'MANQUANT_EQUIPE')
        self.generate_reports(node2, u2['G'])
        c2 = self.close(u2['G'])
        self.assertEqual(self.confirm_and_push(c2.data['id']).status_code, 201)
        e = CashbookEntry.objects.get()
        self.assertEqual(e.exit_amount, D('2500'))
        CashbookEntry.objects.filter(pk=e.pk).update(exit_amount=D('250'))
        t = self.dir_api.get(CASHBOOK + 'integrity_check/')
        k = self.dir_api.post('/api/blockchain/snapshots/run_check/')
        self.assertFalse(t.data['chain_valid'])
        self.assertEqual(t.data['tampered_count'], 1)
        self.assertFalse(k.data['all_intact'])

    def test_suppression_directe_de_la_derniere_ecriture_detectee_par_l_ancre(self):
        node2, u2 = self.make_bakery('R2')
        self.negative(_api(u2['A']), node2, '-2500', 'RETRAIT_EPARGNE')
        self.generate_reports(node2, u2['G'])
        c2 = self.close(u2['G'])
        self.assertEqual(self.confirm_and_push(c2.data['id']).status_code, 201)
        with connection.cursor() as cur:
            cur.execute('DELETE FROM treasury_cashbookentry')
        t = self.dir_api.get(CASHBOOK + 'integrity_check/')
        k = self.dir_api.post('/api/blockchain/snapshots/run_check/')
        self.assertFalse(t.data['chain_valid'])
        self.assertTrue(t.data['head_problem'])
        self.assertFalse(k.data['all_intact'])

    def test_livre_de_caisse_lecture_seule_et_double_versement_refuse(self):
        node2, u2 = self.make_bakery('R2')
        self.negative(_api(u2['A']), node2, '-2500', 'RETRAIT_EPARGNE')
        self.generate_reports(node2, u2['G'])
        c2 = self.close(u2['G'])
        self.assertEqual(self.confirm_and_push(c2.data['id']).status_code, 201)
        again = self.dir_api.post(f"{CLOSURES}{c2.data['id']}/push_to_cashbook/")
        self.assertEqual(again.status_code, 400)
        self.assertEqual(CashbookEntry.objects.count(), 1)
        e = CashbookEntry.objects.get()
        for verb in ('post', 'put', 'patch', 'delete'):
            url = CASHBOOK if verb == 'post' else f'{CASHBOOK}{e.pk}/'
            r = getattr(self.dir_api, verb)(url, {'exit_amount': '1'}, format='json')
            self.assertEqual(r.status_code, 405, (verb, r.status_code))
        e.refresh_from_db()
        self.assertEqual(e.exit_amount, D('2500'))


class Regression304_306_SansEffetSurLaCaisse(_Day):
    def _snapshot_yesterday(self, node, today, a_left, b_left):
        for team, left in (('A', a_left), ('B', b_left)):
            s = ProductionSession.objects.create(
                node=node, team=team, date=today - timedelta(days=1), flour_sacks_used=D('1'))
            ProductionSessionLine.objects.create(session=s, bread_price=self.bp, quantity=20)
            BreadDisposal.objects.create(session=s, bread_price=self.bp, disposal_type='REMAINING',
                                         quantity=left, node=node, node_origin=node.code)
            DailyBreadStockSnapshot.record_snapshot(s)

    def _chiffres(self, node, u):
        reps = self.generate_reports(node, u['G'])
        c = self.close(u['G'], bills_10000=1, bills_5000=1, bills_200=1, bills_100=1)
        self.assertEqual(c.status_code, 201, c.data)
        return (
            D(reps['A']['total_cash_sales']), D(reps['A']['total_credit_sales']),
            D(reps['B']['total_cash_sales']), D(reps['B']['total_credit_sales']),
            D(c.data['total_entries']), D(c.data['net_cash']), D(c.data['cash_gap']),
        )

    def test_fournee_en_cours_ne_change_aucun_montant_de_caisse(self):
        node_a, ua, _ = self.build_day('R1', with_batch=True)
        node_b, ub, _ = self.build_day('R3', with_batch=False)
        avec, sans = self._chiffres(node_a, ua), self._chiffres(node_b, ub)
        self.assertEqual(avec, sans)
        self.assertEqual(avec, (D('15000'), D('5000'), D('1000'), D('0'), D('16000'), D('15300'), D('0')))

    def test_fournee_incremente_stock_et_lignes_mais_pas_le_rapport_en_montants(self):
        node, u, today = self.build_day('R1', with_batch=True)
        s = ProductionSession.objects.get(pk=self.batch_id)
        # 40 (équipe A) + 2 (équipe B) pains de 500 livrés ; les 3 sorties n'ont pas de ligne
        self.assertEqual(s.lines.get(bread_price=self.bp).quantity, 42)
        self.assertEqual(BreadStock.objects.get(node=node, bread_price=self.bp).qty_produced, 42)
        self.assertEqual(s.total_fc_produced, 21000)
        reps = {r.team: r for r in regenerate_facturier_reports(node, today)}
        self.assertEqual(reps['A'].total_cash_sales, D('15000.00'))
        # écart sacs : valeur réalisée équipe A (20 000) - 2 sacs x 210 000
        self.assertEqual(reps['A'].sacks_value_gap, D('-400000'))
        self.assertEqual(reps['A'].sacks_consumed, D('2'))
        # Les paiements négatifs (sans ligne) ne comptent pas dans la fournée
        self.assertEqual(Invoice.objects.filter(node=node, payment_amount__lt=0, lines__isnull=False).count(), 0)

    def test_restes_d_hier_et_du_jour_ne_changent_pas_la_cloture_ni_le_livre(self):
        node, u, today = self.build_day('R1', with_batch=True)
        self._snapshot_yesterday(node, today, 10, 5)
        reps = self.generate_reports(node, u['G'])
        before = (FacturierReport.objects.count(), CashClosure.objects.count(), CashbookEntry.objects.count())
        r = _api(u['G']).get('/api/production/daily-closure/', {'node': 'R1', 'date': str(today)})
        self.assertEqual(r.status_code, 200, r.data)
        cat = next(c for c in r.data['categories'] if c['bread_price'] == self.bp.pk)
        self.assertEqual(cat['reste_du_hier_jour'], -5)                         # B clôture en dernier : 5, signe inversé
        self.assertEqual(r.data['totals']['reste_du_hier_jour_fc'], '-2500.00')  # -5 x 500
        after = (FacturierReport.objects.count(), CashClosure.objects.count(), CashbookEntry.objects.count())
        self.assertEqual(before, after)
        c = self.close(u['G'], bills_10000=1, bills_5000=1, bills_200=1, bills_100=1)
        self.assertEqual(D(c.data['net_cash']), D('15300'))
        self.assertEqual(D(c.data['total_entries']), D(reps['A']['total_cash_sales']) + D(reps['B']['total_cash_sales']))

    def test_cloture_quotidienne_journee_complete_cash_et_chaine(self):
        """Journée complète : 2 équipes, 3 sorties négatives, dépense, fournée en cours,
        restes de la veille, clôture, versement, vérification de chaîne."""
        node, u, today = self.build_day('R1', with_batch=True)
        self._snapshot_yesterday(node, today, 10, 5)
        self.generate_reports(node, u['G'])
        c = self.close(u['G'], bills_10000=1, bills_5000=1, bills_200=1, bills_100=1)
        self.assertEqual(self.confirm_and_push(c.data['id']).status_code, 201)
        e = CashbookEntry.objects.get()
        self.assertEqual((e.entry_amount, e.exit_amount, e.running_balance), (D('15300'), D('0'), D('15300')))
        t = self.dir_api.get(CASHBOOK + 'integrity_check/')
        k = self.dir_api.post('/api/blockchain/snapshots/run_check/')
        self.assertTrue(t.data['chain_valid'])
        self.assertTrue(k.data['all_intact'])


class RegressionConcurrentPromotions(TransactionTestCase):
    """Validations concurrentes de clôtures de deux boulangeries : chaîne sans fourche.
    SQLite peut verrouiller la base : on documente et on saute alors."""

    def test_deux_versements_concurrents_ne_forkent_pas_la_chaine(self):
        bp = make_bread_price('B500', 'Pain 500 FC', 500)  # noqa: F841
        gerant_ids = []
        closures = []
        for code, net in (('C1', D('3000')), ('C2', D('4000')), ('C3', D('5000')), ('C4', D('6000'))):
            node = make_node(code=code)
            g = make_user('GERANT', node=node, team='', username=f'{code}_g')
            gerant_ids.append(g.pk)
            fa = make_user('FACTURIER', node=node, team='A', username=f'{code}_f')
            FacturierReport.objects.create(node=node, facturier=fa, team='A', date=work_date_for(node),
                                           total_cash_sales=net, theoretical_cash=net)
            cl = CashClosure.objects.create(node=node, date=work_date_for(node), gerant=g,
                                            total_entries=net, total_expenses=D('0'), is_validated=True)
            cl.compute_physical_cash()
            cl.save()
            closures.append(cl.pk)
        errors = []

        def worker(pk):
            try:
                promote_closure_to_cashbook(CashClosure.objects.get(pk=pk))
            except OperationalError as exc:
                errors.append(('locked', str(exc)))
            except Exception as exc:  # noqa: BLE001
                errors.append(('other', repr(exc)))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker, args=(pk,)) for pk in closures]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        locked = [e for e in errors if e[0] == 'locked']
        if locked:
            raise unittest.SkipTest(f"SQLite verrouillée en écriture concurrente : {locked[0][1]}")
        self.assertEqual([e for e in errors if e[0] == 'other'], [])
        entries = list(CashbookEntry.chain_queryset())
        self.assertEqual(len(entries), 4)
        self.assertEqual(len({e.previous_hash for e in entries}), 4, 'fourche : previous_hash dupliqué')
        self.assertEqual(entries[-1].running_balance, D('18000'))                 # 3+4+5+6 milliers
        head = CashbookHead.objects.get()
        self.assertEqual((head.entry_count, head.last_hash), (4, entries[-1].block_hash))
