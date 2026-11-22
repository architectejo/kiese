"""Verification independante (testeur-tresorerie, Dev C, 2026-11-22-c) :
BUG-381 (Versement direction en lecture), BUG-526 a 529 (500 -> 400, helpers
kiese/node_guard.py), BUG-516 (PROTECT), chaine de hash du livre de caisse.
Donnees fictives uniquement.
"""
from decimal import Decimal as Dc

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from blockchain.models import BlockchainSnapshot, TamperAlert
from core.models import ActivityLog, Node
from core.testing import make_node, make_user
from kiese.node_guard import month_year_error, parse_date_param, resolve_node_param
from treasury.models import CashbookEntry, CashClosure
from treasury.views import append_cashbook_entry

D = '2026-11-18'
URL = '/api/treasury/closures/versements/'


def cl(user=None):
    c = APIClient()
    if user is not None:
        c.force_authenticate(user)
    return c


class VersementAttaques(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.n1 = make_node('V1', 'Verif V1')
        cls.n2 = make_node('V2', 'Verif V2')
        cls.n3 = make_node('V3', 'Verif V3')
        cls.adm = make_user('ADMIN')
        cls.dirn = make_user('DIRECTION')
        cls.compt = make_user('COMPTABLE')
        cls.g1 = make_user('GERANT', cls.n1)
        cls.fac = make_user('FACTURIER', cls.n1)
        mk = lambda n, **kw: CashClosure.objects.create(node=n, date=D, node_origin=n.code, **kw)
        cls.c1 = mk(cls.n1, total_entries=Dc('100000.50'), total_expenses=Dc('10000.25'),
                    net_cash=Dc('90000.25'), physical_cash_total=Dc('89000.25'), cash_gap=Dc('-1000.00'),
                    bills_20000=4, bills_10000=1, bills_50=7)
        cls.c2 = mk(cls.n2, total_entries=Dc('50000.00'), total_expenses=Dc('0'),
                    net_cash=Dc('50000.00'), physical_cash_total=Dc('50500.00'), cash_gap=Dc('500.00'),
                    bills_20000=2, bills_10000=1, bills_500=1, is_validated=True)

    def rows(self, r):
        return {x['node_code']: x for x in r.data['results'] if x['node_code'] in ('V1', 'V2', 'V3')}

    def test_totals_signed_gaps_decimal_exact(self):
        r = cl(self.dirn).get(URL, {'date': D})
        self.assertEqual(r.status_code, 200, r.content)
        t = r.data['totals']
        self.assertEqual(t['cash_gap'], '-500.00')            # -1000 + 500
        self.assertEqual(t['total_entries'], '150000.50')
        self.assertEqual(t['net_cash'], '140000.25')
        self.assertEqual(t['physical_cash_total'], '139500.25')
        self.assertEqual(t['bills']['bills_20000'], 6)
        self.assertEqual(t['bills']['bills_50'], 7)
        self.assertEqual(t['bills']['bills_500'], 1)
        rows = self.rows(r)
        self.assertEqual(rows['V3']['status'], 'NON_VERSE')
        self.assertEqual(rows['V3']['net_cash'], '0.00')
        # chaque montant est une chaine decimale, jamais un flottant JSON
        for x in r.data['results']:
            for f in ('total_entries', 'net_cash', 'cash_gap'):
                self.assertIsInstance(x[f], str)

    def test_row_sums_equal_totals(self):
        r = cl(self.adm).get(URL, {'date': D})
        s = sum(Dc(x['net_cash']) for x in r.data['results'])
        self.assertEqual(str(s.quantize(Dc('0.01'))), r.data['totals']['net_cash'])
        c = r.data['totals']['counts']
        self.assertEqual(sum(c.values()), r.data['count'])

    def test_gerant_totals_exclude_other_bakeries(self):
        r = cl(self.g1).get(URL, {'date': D})
        self.assertEqual([x['node_code'] for x in r.data['results']], ['V1'])
        self.assertEqual(r.data['totals']['net_cash'], '90000.25')
        self.assertNotIn('50000', r.content.decode().replace('100000.50', ''))
        # parametre node vide ou espaces = ignore, pas d'ouverture
        self.assertEqual(cl(self.g1).get(URL, {'date': D, 'node': ''}).status_code, 200)

    def test_bad_params_never_500(self):
        for q in ({'date': '2026-02-30'}, {'date': "2026-11-18'; DROP"}, {'date': D, 'node': '0'},
                  {'date': D, 'node': '-1'}, {'date': D, 'node': '1.5'}, {'date': D, 'node': '%00'},
                  {'date': D, 'node': 'é' * 50}):
            for u in (self.dirn, self.g1):
                r = cl(u).get(URL, q)
                self.assertLess(r.status_code, 500, (q, u.role, r.content))
                self.assertIn(r.status_code, (400, 403), (q, u.role))

    def test_methods_and_no_side_effects(self):
        n_log = ActivityLog.objects.count()
        n_cl = CashClosure.objects.count()
        before = list(CashClosure.objects.values_list('pk', 'is_validated', 'net_cash'))
        self.assertEqual(cl(self.dirn).get(URL, {'date': D}).status_code, 200)
        n_log = ActivityLog.objects.count()  # apres creation paresseuse eventuelle de Config
        self.assertEqual(cl(self.dirn).get(URL, {'date': D}).status_code, 200)
        self.assertEqual(ActivityLog.objects.count(), n_log, 'un GET ecrit dans le journal')
        self.assertEqual(cl(self.dirn).options(URL).status_code, 200)
        self.assertEqual(cl(self.dirn).head(URL, {'date': D}).status_code, 200)
        for m in ('post', 'put', 'patch', 'delete'):
            self.assertEqual(getattr(cl(self.adm), m)(URL, {}, format='json').status_code, 405, m)
        self.assertEqual(ActivityLog.objects.count(), n_log)
        self.assertEqual(CashClosure.objects.count(), n_cl)
        self.assertEqual(before, list(CashClosure.objects.values_list('pk', 'is_validated', 'net_cash')))

    def test_roles_without_access(self):
        for u in (self.fac, make_user('LIVREUR', self.n1)):
            self.assertEqual(cl(u).get(URL, {'date': D}).status_code, 403)
        self.assertIn(cl().get(URL).status_code, (401, 403))

    def test_route_does_not_shadow_detail(self):
        r = cl(self.dirn).get(f'/api/treasury/closures/{self.c1.pk}/')
        self.assertEqual(r.status_code, 200)
        r = cl(self.dirn).get('/api/treasury/closures/')
        self.assertEqual(r.status_code, 200)

    def test_query_count_does_not_grow_with_bakeries(self):
        def n_queries():
            with CaptureQueriesContext(connection) as ctx:
                cl(self.dirn).get(URL, {'date': D})
            return len(ctx)
        base = n_queries()
        for i in range(6):
            n = make_node(f'VQ{i}', f'Verif Q{i}')
            CashClosure.objects.create(node=n, date=D, node_origin=n.code, net_cash=Dc('1'))
        self.assertLessEqual(n_queries(), base + 3, 'N+1 sur la liste des versements')

    def test_hq_account_attached_to_a_bakery_still_sees_all(self):
        d2 = make_user('DIRECTION', self.n1)
        r = cl(d2).get(URL, {'date': D})
        self.assertEqual(set(self.rows(r)), {'V1', 'V2', 'V3'})


class HelpersNodeGuard(TestCase):
    def test_resolve_node_param(self):
        n = make_node('HZ1', 'Helper Z1')
        for raw in (n.pk, str(n.pk), 'HZ1', 'hz1', f' {n.pk} '):
            node, err = resolve_node_param(raw)
            self.assertEqual((node, err), (n, None), raw)
        for raw in ('ZZZ', '999999', '0', '-1', '9' * 40, '1.5', '', 'x' * 500, '%00', '\x00'):
            try:
                node, err = resolve_node_param(raw)
            except Exception as e:  # pragma: no cover - attaque
                self.fail(f'{raw!r} -> exception {e!r}')
            self.assertIsNone(node, raw)
            self.assertEqual(err.status_code, 400, raw)
            self.assertIn('detail', err.data)

    def test_parse_date_param(self):
        self.assertEqual(parse_date_param('2026-11-18')[1], None)
        for raw in ('abc', '2026-13-45', '2026-02-30', '', '18/11/2026', '2026-11-18T10:00'):
            d, e = parse_date_param(raw)
            self.assertIsNone(d, raw)
            self.assertIn('invalide', e)

    def test_month_year_error(self):
        for m, y in ((None, None), ('', ''), (1, 2000), ('12', '2100'), ('6', None)):
            self.assertIsNone(month_year_error(m, y), (m, y))
        for m, y in (('abc', None), ('0', None), ('13', None), (None, 'abc'), (None, '1999'),
                     (None, '2101'), ('13', '99999'), ('1.5', None), ('1' * 40, None), (None, '9' * 40)):
            self.assertIsInstance(month_year_error(m, y), str, (m, y))


class Params500(TestCase):
    """BUG-526/527/528/529 : balayage des routes corrigees (siege + gerant)."""

    @classmethod
    def setUpTestData(cls):
        cls.n1 = make_node('PZ1', 'Params Z1')
        cls.hq = make_user('ADMIN')
        cls.g = make_user('GERANT', cls.n1)

    def get(self, user, url, **q):
        return cl(user).get(url, q)

    def assert_400(self, url, **q):
        for u in (self.hq, self.g):
            r = self.get(u, url, **q)
            self.assertNotEqual(r.status_code, 500, (url, q, u.role))
        r = self.get(self.hq, url, **q)
        self.assertEqual(r.status_code, 400, (url, q, r.content))
        self.assertIn('detail', r.data)

    def test_526_production(self):
        for q in ({'date_from': 'abc'}, {'date_to': '2026-13-45'}, {'date_from': '2026-02-30'}):
            self.assert_400('/api/production/sessions/', **q)
        for q in ({'month': 'abc'}, {'year': 'abc'}, {'month': '13', 'year': '99999'}, {'month': '0'}):
            self.assert_400('/api/production/movements/flour_history/', **q)
        ok = self.get(self.hq, '/api/production/sessions/', date_from='2026-01-01', date_to='2026-12-31')
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(self.get(self.hq, '/api/production/movements/flour_history/', month='11', year='2026').status_code, 200)

    def test_527_sales(self):
        self.assert_400('/api/sales/invoices/daily_summary/', date='abc')
        self.assert_400('/api/sales/invoices/daily_summary/', date='2026-02-30')
        self.assertEqual(self.get(self.hq, '/api/sales/invoices/daily_summary/', date=D).status_code, 200)

    def test_528_finance(self):
        for path in ('summary', 'doc1_report', 'doc1_export'):
            q = {'node': 'ZZZ', 'month': 1, 'year': 2026}
            self.assert_400(f'/api/finance/years/{path}/', **q)
        r = self.get(self.hq, '/api/finance/years/summary/', node='PZ1')
        self.assertEqual(r.status_code, 200, r.content)

    def test_529_blockchain(self):
        for url in ('/api/blockchain/alerts/', '/api/blockchain/snapshots/'):
            for bad in ('ZZZ', '999999', '9' * 40):
                r = self.get(self.hq, url, node=bad)
                self.assertEqual(r.status_code, 400, (url, bad, r.content))
                self.assertIn('detail', r.data)
            for good in (self.n1.pk, 'PZ1', 'pz1'):
                self.assertEqual(self.get(self.hq, url, node=good).status_code, 200, (url, good))
        for kw in ({'params': {'node': 'ZZZ'}}, {'data': {'node': 'ZZZ'}}, {'data': {'node': '9' * 40}}):
            r = cl(self.hq).post('/api/blockchain/snapshots/run_check/', kw.get('data', {}), format='json',
                                 **({'QUERY_STRING': 'node=ZZZ'} if 'params' in kw else {}))
            self.assertEqual(r.status_code, 400, (kw, r.content))
        # un gerant ne doit pas atteindre ces routes
        self.assertEqual(self.get(self.g, '/api/blockchain/alerts/', node='ZZZ').status_code, 403)
        self.assertEqual(cl(self.g).post('/api/blockchain/snapshots/run_check/', {}, format='json').status_code, 403)
        # run_check par code : snapshot du bon noeud
        r = cl(self.hq).post('/api/blockchain/snapshots/run_check/', {'node': 'pz1'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(BlockchainSnapshot.objects.filter(node=self.n1).count(), 1)


class ChaineApresLot(TestCase):
    """Le lot (Versement lecture, helpers) ne casse pas la chaine : une seule fonction de hash."""

    @classmethod
    def setUpTestData(cls):
        cls.n1 = make_node('CH1', 'Chaine 1')
        cls.n2 = make_node('CH2', 'Chaine 2')
        cls.hq = make_user('ADMIN')
        cls.dirn = make_user('DIRECTION')

    def _fill(self, count=30):
        bal = Dc('0')
        for i in range(count):
            n = self.n1 if i % 2 == 0 else self.n2
            e = Dc('1000') + i
            x = Dc('300') if i % 5 == 4 else Dc('0')
            append_cashbook_entry(node=n, date='2026-11-18', piece_number=f'VC-{n.code}-2026111{i % 10}-{i}',
                                  imputation='7000', label=f'Verif {i}', entry_amount=e, exit_amount=x,
                                  node_origin=n.code)
            bal += e - x
        return bal

    def verdicts(self):
        a = cl(self.hq).get('/api/treasury/cashbook/integrity_check/')
        b = cl(self.hq).post('/api/blockchain/snapshots/run_check/', {}, format='json')
        return a, b

    def test_30_entries_valid_and_both_endpoints_agree(self):
        bal = self._fill()
        self.assertEqual(CashbookEntry.chain_queryset().last().running_balance, bal)
        # lecture Versement entre-temps : aucun effet sur la chaine
        cl(self.dirn).get(URL, {'date': D})
        a, b = self.verdicts()
        self.assertEqual(a.status_code, 200)
        self.assertTrue(a.data['chain_valid'], a.data)
        self.assertEqual(b.status_code, 200, b.content)
        self.assertEqual(sum(r['tampered_entries'] if 'tampered_entries' in r else 0
                             for r in (b.data.get('results') or b.data.get('nodes') or [])), 0, b.data)
        self.assertEqual(TamperAlert.objects.count(), 0)

    def test_direct_db_alteration_detected_by_both(self):
        self._fill()
        victim = CashbookEntry.objects.filter(node=self.n2).order_by('chain_seq')[3]
        CashbookEntry.objects.filter(pk=victim.pk).update(entry_amount=victim.entry_amount + 1)
        a, b = self.verdicts()
        self.assertFalse(a.data['chain_valid'])
        self.assertIn(str(victim.pk), a.data['tampered_ids'])
        self.assertTrue(TamperAlert.objects.exists(), 'run_check doit creer une alerte (meme verdict)')

    def test_alteration_of_node_field_detected(self):
        self._fill(6)
        e = CashbookEntry.objects.order_by('chain_seq')[2]
        other = self.n2 if e.node_id == self.n1.pk else self.n1
        CashbookEntry.objects.filter(pk=e.pk).update(node=other)
        a, _ = self.verdicts()
        self.assertFalse(a.data['chain_valid'])

    def test_only_one_hash_function(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[2]
        offenders = []
        for app in ('treasury', 'blockchain'):
            for p in (root / app).glob('*.py'):
                if p.name == 'hashing.py':
                    continue
                code = [l for l in p.read_text(encoding='utf-8').splitlines() if not l.strip().startswith('#')]
                if any('hashlib.sha256(' in l for l in code):
                    offenders.append(p.name)
        self.assertEqual(offenders, [])


class Bug516Migration(TestCase):
    def test_protect_blocks_node_delete_with_alert_or_snapshot(self):
        from django.db.models import ProtectedError
        n = make_node('PR1', 'Protect 1')
        TamperAlert.objects.create(node=n, affected_model='CashbookEntry', description='x')
        with self.assertRaises(ProtectedError):
            n.delete()
        n2 = make_node('PR2', 'Protect 2')
        BlockchainSnapshot.objects.create(node=n2, snapshot_date='2026-11-18', total_entries=0,
                                          tampered_entries=0, is_intact=True)
        with self.assertRaises(ProtectedError):
            n2.delete()
        self.assertTrue(Node.objects.filter(pk__in=[n.pk, n2.pk]).count() == 2)
        # nœud vierge : supprimable
        n3 = make_node('PR3', 'Protect 3')
        n3.delete()
