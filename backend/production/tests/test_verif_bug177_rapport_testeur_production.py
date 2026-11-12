"""
Vérification indépendante BUG-177 (volet rapport de Clôture Journalière),
testeur-production, 2026-11-11.

Scénario riche construit par le testeur, tous les attendus sont recalculés
à la main (formule du classeur K6 : L21 = SUM(L8:L20), L132 = L128 + L21)
et non recopiés depuis la vue. Données fictives uniquement.

Catégories 300 FC et 500 FC.
"""
from datetime import timedelta
from unittest import expectedFailure
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price, make_client


class RichScenarioClosureTests(TestCase):
    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.other = make_node()
        self.gerant = make_user('GERANT', node=self.node)
        self.facturier = make_user('FACTURIER', node=self.node, team='A')
        self.other_gerant = make_user('GERANT', node=self.other)
        self.bp300 = make_bread_price('V177T_300', 'Pain 300 V177', 300)
        self.bp500 = make_bread_price('V177T_500', 'Pain 500 V177', 500)
        self.cl = make_client(self.node, credit_limit=Decimal('900000.00'))
        self.g = APIClient(); self.g.force_authenticate(self.gerant)
        self.f = APIClient(); self.f.force_authenticate(self.facturier)
        self.og = APIClient(); self.og.force_authenticate(self.other_gerant)
        self.today = timezone.localdate()
        self.yesterday = self.today - timedelta(days=1)

    # -- utilitaires ------------------------------------------------------
    def _session(self, team, date, flour, lines):
        r = self.g.post('/api/production/sessions/', {
            'team': team, 'date': str(date), 'flour_sacks_used': str(flour),
            'lines': [{'bread_price': bp.pk, 'quantity': q} for bp, q in lines],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data['id']

    def _disp(self, sid, bp, typ, qty, price=0):
        r = self.g.post('/api/production/disposals/', {
            'session': sid, 'bread_price': bp.pk, 'disposal_type': typ,
            'quantity': qty, 'unit_price_sold': price,
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)

    def _inv(self, lines, ptype='CASH', pay='0.00', code='', soldee=False, deliver=True, rate=None, client=True):
        p = {'payment_type': ptype, 'payment_amount': pay, 'special_code': code,
             'lines': [{'bread_price': bp.pk, 'quantity': q} for bp, q in lines]}
        if soldee:
            p['is_soldee'] = True
        if rate:
            p['commission_rate'] = rate
        if client:
            p['client'] = str(self.cl.pk)
        r = self.f.post('/api/sales/invoices/', p, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        if deliver and code != 'NS':
            d = self.f.post(f"/api/sales/invoices/{r.data['id']}/deliver/")
            self.assertEqual(d.status_code, 200, d.data)
        return r.data

    def _build(self):
        # Veille : équipe A produit 50x300, reste 15 -> reste du hier A = -15 (auto)
        s_prev = self._session('A', self.yesterday, 1, [(self.bp300, 50)])
        self._disp(s_prev, self.bp300, 'REMAINING', 15)
        self.assertEqual(self.g.post(f'/api/production/sessions/{s_prev}/close/').status_code, 200)

        # Carryover BUG-142 : confirmation d'ouverture équipe B, 8 pains de 500
        r = self.g.post('/api/production/opening-confirmation/', {
            'team': 'B', 'date': str(self.today),
            'lines': [{'bread_price': self.bp500.pk, 'qty': 8}],
        }, format='json')
        self.assertEqual(r.status_code, 200, r.data)

        sa = self._session('A', self.today, 2, [(self.bp300, 100), (self.bp500, 50)])
        sb = self._session('B', self.today, 1, [(self.bp300, 40)])
        self._disp(sa, self.bp300, 'REMAINING', 20)
        self._disp(sa, self.bp500, 'REMAINING', -5)       # reste négatif BUG-158
        self._disp(sa, self.bp300, 'DECLASSED', 5, 200)    # 1000
        self._disp(sa, self.bp500, 'UNSOLD', 3, 400)       # 1200
        self._disp(sa, self.bp300, 'FREE_DIST', 2)         # hors mvm
        self._disp(sb, self.bp300, 'REMAINING', 10)
        self._disp(sb, self.bp500, 'REMAINING', 3)
        for sid in (sa, sb):
            self.assertEqual(self.g.post(f'/api/production/sessions/{sid}/close/').status_code, 200)

        inv1 = self._inv([(self.bp300, 30), (self.bp500, 20)], pay='19000.00', rate='0.25')
        self._inv([(self.bp300, 10)], ptype='CREDIT', pay='1000.00', rate='0.25')
        self._inv([(self.bp300, 10)], pay='2250.00', soldee=True, client=False)
        self._inv([(self.bp500, 4)], pay='1500.00', soldee=True, client=False)
        self._inv([(self.bp300, 6), (self.bp500, 2)], ptype='CREDIT', code='NS')   # PENDING 2800
        ns2 = self._inv([(self.bp300, 7)], ptype='CREDIT', code='NS')               # annulée
        self.assertEqual(self.f.post(f"/api/sales/invoices/{ns2['id']}/cancel/").status_code, 200)
        self._inv([(self.bp300, 2), (self.bp500, 5)], code='RG')                    # 600 + 2500
        adj = self.g.post(f"/api/sales/invoices/{inv1['id']}/adjust/", {
            'adjustment_sign': -1, 'payment_amount': '0.00',
            'lines': [{'bread_price': self.bp300.pk, 'quantity': 4}],
        }, format='json')
        self.assertEqual(adj.status_code, 201, adj.data)                            # -1200

        # Appro reçu : other -> node, 15x300
        t = self.g.post('/api/production/transfers/', {
            'from_node': self.other.pk,
            'lines': [{'bread_price': self.bp300.pk, 'quantity_sent': 15}]}, format='json')
        self.assertEqual(t.status_code, 201, t.data)
        self.assertEqual(self.og.post(f"/api/production/transfers/{t.data['id']}/respond_to_request/", {
            'approved': True, 'lines': [{'bread_price': self.bp300.pk, 'quantity_sent': 15}]}, format='json').status_code, 200)
        c = self.g.post(f"/api/production/transfers/{t.data['id']}/confirm_reception/", {
            'lines': [{'bread_price': self.bp300.pk, 'quantity_received': 15}]}, format='json')
        self.assertEqual(c.status_code, 200, c.data)
        # Appro effectué : node -> other, 12x500 (other demande à node)
        t2 = self.og.post('/api/production/transfers/', {
            'from_node': self.node.pk,
            'lines': [{'bread_price': self.bp500.pk, 'quantity_sent': 12}]}, format='json')
        self.assertEqual(t2.status_code, 201, t2.data)
        r2 = self.g.post(f"/api/production/transfers/{t2.data['id']}/respond_to_request/", {
            'approved': True, 'lines': [{'bread_price': self.bp500.pk, 'quantity_sent': 12}]}, format='json')
        self.assertEqual(r2.status_code, 200, r2.data)
        c2 = self.og.post(f"/api/production/transfers/{t2.data['id']}/confirm_reception/", {
            'lines': [{'bread_price': self.bp500.pk, 'quantity_received': 12}]}, format='json')
        self.assertEqual(c2.status_code, 200, c2.data)

    def test_rich_scenario_every_total(self):
        self._build()
        r = self.g.get('/api/production/daily-closure/', {'date': str(self.today)})
        self.assertEqual(r.status_code, 200, r.data)
        by = {c['bread_price']: c for c in r.data['categories']}
        c3, c5 = by[self.bp300.pk], by[self.bp500.pk]
        D = Decimal

        # --- colonnes
        self.assertEqual(c3['facture_jr'], {'quantity': 40, 'fc': '12000.00'})
        self.assertEqual(c3['commission_jr']['fc'], '3000.00')
        self.assertEqual(c5['facture_jr'], {'quantity': 20, 'fc': '10000.00'})
        self.assertEqual(c5['commission_jr']['fc'], '2500.00')
        self.assertEqual(c3['vente_cash_soldee']['fc'], '2250.00')
        self.assertEqual(c5['vente_cash_soldee']['fc'], '1500.00')
        self.assertEqual(c3['non_servi'], {'quantity': 6, 'fc': '1800.00', 'fc_signe': '-1800.00'})
        self.assertEqual(c5['non_servi'], {'quantity': 2, 'fc': '1000.00', 'fc_signe': '-1000.00'})
        self.assertEqual(c3['regularisation'], {'quantity': -2, 'fc': '-600.00'})   # 600 - 1200
        self.assertEqual(c5['regularisation'], {'quantity': 5, 'fc': '2500.00'})
        self.assertEqual(c3['reste_du_jour'], {'A': 20, 'B': 10})
        self.assertEqual(c3['reste_du_hier'], {'A': -15, 'B': 0})
        self.assertEqual(c5['reste_du_jour'], {'A': -5, 'B': 3})
        self.assertEqual(c5['reste_du_hier'], {'A': 0, 'B': -8})
        self.assertEqual(c3['appro_recu']['fc'], '4500.00')
        self.assertEqual(c5['appro_effectue']['fc'], '6000.00')
        self.assertEqual(c3['declasses']['fc'], '1000.00')
        self.assertEqual(c5['non_vendu_nv']['fc'], '1200.00')
        self.assertEqual(c3['produit']['quantity'], 140)   # ni veille ni carryover
        self.assertEqual(c5['produit']['quantity'], 50)

        # --- FACTURE MVM INTERNE (classeur : somme signée des rubriques)
        mvm3 = (D(30) * 300 + D(-15 + 0) * 300 + 0 + D(15) * 300 - D(1800) + D(-600) + D(2250) + 0 + D(1000))
        mvm5 = (D(-2) * 500 + D(-8) * 500 + D(12) * 500 + 0 - D(1000) + D(2500) + D(1500) + D(1200) + 0)
        self.assertEqual(c3['facture_mvm_interne']['fc'], f'{mvm3:.2f}')
        self.assertEqual(c5['facture_mvm_interne']['fc'], f'{mvm5:.2f}')
        t = r.data['totals']
        total = D(12000) + D(10000) + mvm3 + mvm5
        self.assertEqual(D(t['total_du_jour_fc']), total)
        # ECART/FACTURE : commandes - paiements (hors NS), ajustement signé
        commande = 19000 + 3000 + 2250 + 1500 + 3100 - 1200
        paye = 19000 + 1000 + 2250 + 1500 + 0 + 0
        self.assertEqual(D(t['ecart_facture_fc']), D(commande - paye))
        self.assertEqual(D(t['ecart_facture_fc']), D(3900))
        self.assertEqual(t['total_breads_billed'], (40 + 20) + (10 + 4) + (-2 + 5))

    def test_repartition_pct_sum_to_100_with_carryover(self):
        """BUG-142 : le carryover (8 pains) ne doit pas fausser la répartition."""
        self._build()
        r = self.g.get('/api/production/daily-closure/', {'date': str(self.today)})
        t = r.data['totals']
        s = sum(Decimal(x['pct']) for x in t['repartition_pct_par_quantite'])
        self.assertEqual(s, Decimal('100.00'), t['repartition_pct_par_quantite'])
        sv = sum(Decimal(x['pct']) for x in t['repartition_pct_par_valeur'])
        self.assertEqual(sv, Decimal('100.00'))

    def test_ns_ignored_cancelled_only_and_no_stock_change(self):
        from production.models import BreadStock
        self._session('A', self.today, 1, [(self.bp300, 10)])
        before = BreadStock.objects.get(node=self.node, bread_price=self.bp300).qty_available
        self._inv([(self.bp300, 4)], ptype='CREDIT', code='NS')
        after = BreadStock.objects.get(node=self.node, bread_price=self.bp300).qty_available
        self.assertEqual(before, after)

    def test_rg_soldee_not_double_counted(self):
        self._session('A', self.today, 1, [(self.bp300, 50)])
        self._inv([(self.bp300, 10)], code='RG', soldee=True)
        r = self.g.get('/api/production/daily-closure/', {'date': str(self.today)})
        # prix pleins attendus (3000), compte une seule fois
        self.assertEqual(Decimal(r.data['totals']['total_du_jour_fc']), Decimal('3000.00'))
