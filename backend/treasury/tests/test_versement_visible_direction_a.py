"""BUG-381 : la section « Versement » (clôture de caisse du gérant) doit être
visible, en lecture, de la direction centrale (remarque.md l.456).

`GET /api/treasury/closures/versements/?date=AAAA-MM-JJ[&node=<id|code>]` :
une ligne par boulangerie visible (même celles qui n'ont pas versé), statut,
totaux verticaux. Lecture seule : ne change pas qui valide/infirme/verse au
livre (Q-020 en attente du client). Données fictives uniquement.
"""
from decimal import Decimal as Dc

from core.tests.test_permissions_regression_2026_11_19 import cl, mk
from core.tests.test_verif_isolation_a_c import D, IsoBase
from core.workday import work_date_for
from treasury.models import CashClosure

URL = '/api/treasury/closures/versements/'


def rows_of(r):
    return {x['node_code']: x for x in r.data['results'] if x['node_code'].startswith('P')}


class VersementVisibleDirection(IsoBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # clo2 (K2, D) existe déjà dans IsoBase : en attente
        CashClosure.objects.filter(pk=cls.clo2.pk).update(
            total_entries=Dc('100000'), total_expenses=Dc('20000'), net_cash=Dc('80000'),
            bills_20000=3, bills_10000=2, physical_cash_total=Dc('80000'), cash_gap=Dc('0'))
        cls.clo1 = CashClosure.objects.create(
            node=cls.k1, date=D, node_origin='P1', total_entries=Dc('50000'), total_expenses=Dc('5000'),
            net_cash=Dc('45000'), bills_20000=2, bills_5000=1, physical_cash_total=Dc('45000'),
            cash_gap=Dc('0'), is_validated=True)
        # K3 : n'a pas versé à cette date, mais à une autre
        cls.clo3_other = CashClosure.objects.create(node=cls.k3, date='2026-11-17', node_origin='P3')
        cls.hq_roles = ('ADMIN', 'DIRECTION', 'COMPTABLE')

    def get(self, user, **params):
        return cl(user).get(URL, params)

    def test_every_hq_role_sees_all_bakeries_even_non_versed(self):
        for role in self.hq_roles:
            r = self.get(self.u[role], date=D)
            self.assertEqual(r.status_code, 200, (role, r.content))
            rows = rows_of(r)
            self.assertEqual(set(rows), {'P1', 'P2', 'P3'}, role)
            self.assertEqual(rows['P1']['status'], 'VALIDE')
            self.assertEqual(rows['P2']['status'], 'EN_ATTENTE')
            self.assertEqual(rows['P3']['status'], 'NON_VERSE')
            self.assertIsNone(rows['P3']['closure'])
            self.assertEqual(rows['P3']['physical_cash_total'], '0.00')
            self.assertEqual(rows['P2']['closure']['bills_20000'], 3)
            self.assertEqual(r.data['date'], D)

    def test_totals_are_vertical_sums(self):
        r = self.get(self.u['DIRECTION'], date=D)
        t = r.data['totals']
        # les éventuels autres noeuds de la base de test sont NON_VERSE (0) : les sommes ne changent pas
        self.assertEqual(t['total_entries'], '150000.00')
        self.assertEqual(t['total_expenses'], '25000.00')
        self.assertEqual(t['net_cash'], '125000.00')
        self.assertEqual(t['physical_cash_total'], '125000.00')
        self.assertEqual(t['bills']['bills_20000'], 5)
        self.assertEqual(t['bills']['bills_10000'], 2)
        self.assertEqual(t['bills']['bills_5000'], 1)
        self.assertEqual(t['versed_count'], 2)
        self.assertEqual((t['counts']['VALIDE'], t['counts']['EN_ATTENTE']), (1, 1))
        self.assertGreaterEqual(t['counts']['NON_VERSE'], 1)
        self.assertEqual(r.data['count'], len(r.data['results']))

    def test_rejected_status_and_cashbook_flag(self):
        CashClosure.objects.filter(pk=self.clo2.pk).update(is_rejected=True, rejection_reason='billetage faux')
        rows = rows_of(self.get(self.u['COMPTABLE'], date=D))
        self.assertEqual(rows['P2']['status'], 'INFIRME')
        self.assertEqual(rows['P2']['closure']['rejection_reason'], 'billetage faux')
        self.assertIn('has_cashbook_entry', rows['P2']['closure'])

    def test_node_filter_by_pk_and_code_case_insensitive(self):
        for val in (self.k2.pk, 'P2', 'p2'):
            r = self.get(self.u['DIRECTION'], date=D, node=val)
            self.assertEqual(r.status_code, 200, (val, r.content))
            self.assertEqual([x['node_code'] for x in r.data['results']], ['P2'])
            self.assertEqual(r.data['totals']['net_cash'], '80000.00')

    def test_other_date_shows_other_closures(self):
        rows = rows_of(self.get(self.u['DIRECTION'], date='2026-11-17'))
        self.assertEqual(rows['P3']['status'], 'EN_ATTENTE')
        self.assertEqual(rows['P1']['status'], 'NON_VERSE')

    def test_default_date_is_today(self):
        CashClosure.objects.create(node=self.k3, date=work_date_for(None), node_origin='P3')
        r = self.get(self.u['DIRECTION'])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['date'], work_date_for(None).isoformat())
        self.assertEqual(rows_of(r)['P3']['status'], 'EN_ATTENTE')

    def test_invalid_params_give_french_400_never_500(self):
        for q in ({'date': 'pas-une-date'}, {'date': '2026-13-45'}, {'date': D, 'node': 'ZZZ'},
                  {'date': D, 'node': '99999'}, {'date': D, 'node': '9' * 40}, {'date': D, 'node': 'x' * 300}):
            r = self.get(self.u['DIRECTION'], **q)
            self.assertEqual(r.status_code, 400, (q, r.content))
            self.assertIn('detail', r.data)

    def test_gerant_sees_only_own_bakery_and_cannot_ask_another(self):
        r = self.get(self.u['GERANT'], date=D)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([x['node_code'] for x in r.data['results']], ['P1'])
        self.assertEqual(r.data['totals']['net_cash'], '45000.00')
        for val in (self.k2.pk, 'P2'):
            r = self.get(self.u['GERANT'], date=D, node=val)
            self.assertEqual(r.status_code, 403, r.content)
            self.assertNotIn('80000', r.content.decode())
        # son propre nœud explicitement : permis
        self.assertEqual(self.get(self.u['GERANT'], date=D, node='P1').status_code, 200)

    def test_facturier_livreur_anonymous_refused(self):
        for role in ('FACTURIER', 'LIVREUR'):
            self.assertEqual(self.get(self.u[role], date=D).status_code, 403, role)
        self.assertIn(cl().get(URL, {'date': D}).status_code, (401, 403))

    def test_node_less_gerant_gets_nothing(self):
        orphan = mk('orph_vers_a6', 'GERANT', None)
        r = self.get(orphan, date=D)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['results'], [])
        self.assertEqual(r.data['totals']['net_cash'], '0.00')

    def test_read_only_endpoint(self):
        for method in ('post', 'put', 'patch', 'delete'):
            r = getattr(cl(self.u['DIRECTION']), method)(URL, {}, format='json')
            self.assertEqual(r.status_code, 405, (method, r.content))

    def test_who_can_validate_is_unchanged(self):
        # Q-020 (en attente du client) : la visibilité ne donne aucun droit d'écriture supplémentaire.
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            r = cl(self.u[role]).post(f'/api/treasury/closures/{self.clo1.pk}/validate/', {}, format='json')
            self.assertEqual(r.status_code, 403, role)
        r = cl(self.u2['GERANT']).post(f'/api/treasury/closures/{self.clo2.pk}/validate/', {}, format='json')
        self.assertEqual(r.status_code, 403)
        self.clo2.refresh_from_db()
        self.assertFalse(self.clo2.is_validated)

    def test_existing_list_is_unchanged_for_direction_and_isolated_for_gerant(self):
        r = cl(self.u['DIRECTION']).get('/api/treasury/closures/', {'node': self.k2.pk, 'date': D})
        self.assertEqual(r.status_code, 200)
        data = r.data['results'] if isinstance(r.data, dict) else r.data
        self.assertEqual([c['id'] for c in data], [str(self.clo2.pk)])
        r = cl(self.u['GERANT']).get('/api/treasury/closures/', {'node': self.k2.pk, 'date': D})
        data = r.data['results'] if isinstance(r.data, dict) else r.data
        self.assertEqual(data, [])

    def test_route_does_not_shadow_closure_detail(self):
        r = cl(self.u['DIRECTION']).get(f'/api/treasury/closures/{self.clo2.pk}/')
        self.assertEqual(r.status_code, 200)
