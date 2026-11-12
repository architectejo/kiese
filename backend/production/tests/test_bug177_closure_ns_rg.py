"""
BUG-177 (volet backend) : colonnes « Non Servi » et « Régularisation » du
rapport de clôture journalier (K6!L12:L13 -> L21 -> L132 du classeur).

- Non Servi = Σ order_total des factures NS du jour (PENDING et DELIVERED,
  jamais CANCELLED), contribution NÉGATIVE au total du jour.
- Régularisation = factures RG (positives) + ajustements BUG-097 (signés) ;
  les RG ne sont plus dans FACTURE/JR.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price, make_client


class ClosureNsRgTests(TestCase):
    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.bp300 = make_bread_price('BUG177C_300', 'Pain 300 FC', 300)
        self.bp500 = make_bread_price('BUG177C_500', 'Pain 500 FC', 500)
        self.gerant = make_user('GERANT', node=self.node)
        self.facturier = make_user('FACTURIER', node=self.node, team='A')
        self.client1 = make_client(self.node, credit_limit=Decimal('500000.00'))
        self.g_api = APIClient(); self.g_api.force_authenticate(self.gerant)
        self.f_api = APIClient(); self.f_api.force_authenticate(self.facturier)
        self.today = timezone.localdate()

    def _invoice(self, code='', lines=((300, 10),), payment='0.00', ptype='CREDIT', deliver=True, client=True):
        bps = {300: self.bp300, 500: self.bp500}
        payload = {
            'payment_type': ptype, 'payment_amount': payment, 'special_code': code,
            'lines': [{'bread_price': bps[p].pk, 'quantity': q} for p, q in lines],
        }
        if client:
            payload['client'] = str(self.client1.pk)
        r = self.f_api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        if deliver and code != 'NS':
            d = self.f_api.post(f"/api/sales/invoices/{r.data['id']}/deliver/")
            self.assertEqual(d.status_code, 200, d.data)
        return r.data

    def _report(self):
        r = self.g_api.get('/api/production/daily-closure/', {'date': str(self.today)})
        self.assertEqual(r.status_code, 200, r.data)
        rows = {row['bread_price']: row for row in r.data['categories']}
        return r.data, rows[self.bp300.pk], rows[self.bp500.pk]

    # ---- Non Servi -------------------------------------------------------

    def test_ns_pending_counted_in_column_with_negative_contribution(self):
        self._invoice('NS', lines=((300, 10), (500, 4)))  # 3000 + 2000, PENDING
        data, r300, r500 = self._report()
        self.assertEqual(r300['non_servi'], {'quantity': 10, 'fc': '3000.00', 'fc_signe': '-3000.00'})
        self.assertEqual(r500['non_servi'], {'quantity': 4, 'fc': '2000.00', 'fc_signe': '-2000.00'})
        self.assertEqual(r300['facture_mvm_interne'], {'fc': '-3000.00'})
        self.assertEqual(r500['facture_mvm_interne'], {'fc': '-2000.00'})
        # NS hors FACTURE/JR, hors pains facturés, hors ECART/FACTURE.
        self.assertEqual(r300['facture_jr'], {'quantity': 0, 'fc': '0.00'})
        self.assertEqual(data['totals']['total_breads_billed'], 0)
        self.assertEqual(data['totals']['ecart_facture_fc'], '0.00')
        self.assertEqual(data['totals']['total_du_jour_fc'], '-5000.00')

    def test_ns_cancelled_not_counted(self):
        inv = self._invoice('NS', lines=((300, 10),))
        self.assertEqual(self.f_api.post(f"/api/sales/invoices/{inv['id']}/cancel/").status_code, 200)
        data, r300, _ = self._report()
        self.assertEqual(r300['non_servi'], {'quantity': 0, 'fc': '0.00', 'fc_signe': '0.00'})
        self.assertEqual(data['totals']['total_du_jour_fc'], '0.00')

    # ---- Régularisation ---------------------------------------------------

    def test_rg_counted_in_regularisation_and_not_in_facture_jr(self):
        self._invoice('RG', lines=((300, 10),))  # 3000, livrée
        data, r300, _ = self._report()
        self.assertEqual(r300['regularisation'], {'quantity': 10, 'fc': '3000.00'})
        self.assertEqual(r300['facture_jr'], {'quantity': 0, 'fc': '0.00'})
        self.assertEqual(r300['commission_jr']['fc'], '0.00')
        self.assertEqual(r300['facture_mvm_interne'], {'fc': '3000.00'})
        self.assertEqual(data['totals']['total_breads_billed'], 10)
        self.assertEqual(data['totals']['total_du_jour_fc'], '3000.00')

    def test_rg_and_adjustment_are_cumulated_with_signs(self):
        normal = self._invoice('', lines=((300, 20),), payment='6000.00', ptype='CASH')  # 6000 FACTURE/JR
        self._invoice('RG', lines=((300, 10),))  # +3000
        adj = self.g_api.post(f"/api/sales/invoices/{normal['id']}/adjust/", {
            'adjustment_sign': -1, 'payment_amount': '0.00',
            'lines': [{'bread_price': self.bp300.pk, 'quantity': 4}],
        }, format='json')
        self.assertEqual(adj.status_code, 201, adj.data)  # -1200
        data, r300, _ = self._report()
        self.assertEqual(r300['regularisation'], {'quantity': 6, 'fc': '1800.00'})
        self.assertEqual(r300['facture_jr'], {'quantity': 20, 'fc': '6000.00'})
        self.assertEqual(data['totals']['total_du_jour_fc'], '7800.00')

    # ---- Formule du classeur ------------------------------------------------

    def test_total_du_jour_matches_workbook_formula(self):
        """total = FACTURE/JR + (… - NS + RG …) : K6!L132 = L128 + L21."""
        self._invoice('', lines=((500, 10),), payment='5000.00', ptype='CASH')  # 5000
        self._invoice('NS', lines=((300, 5),))   # -1500
        self._invoice('RG', lines=((500, 2),))   # +1000
        data, r300, r500 = self._report()
        expected = Decimal('5000') - Decimal('1500') + Decimal('1000')
        self.assertEqual(Decimal(data['totals']['total_du_jour_fc']), expected)
        self.assertEqual(expected, Decimal('4500'))
        # Σ lignes = total du jour
        total = sum(Decimal(r['facture_jr']['fc']) + Decimal(r['facture_mvm_interne']['fc'])
                    for r in data['categories'])
        self.assertEqual(total, expected)

    def test_non_regression_standard_scenario_unchanged(self):
        """Sans NS ni RG : mêmes valeurs qu'avant (vente normale seule)."""
        self._invoice('', lines=((300, 10),), payment='3000.00', ptype='CASH')
        data, r300, _ = self._report()
        self.assertEqual(r300['facture_jr'], {'quantity': 10, 'fc': '3000.00'})
        self.assertEqual(r300['non_servi']['fc'], '0.00')
        self.assertEqual(r300['regularisation'], {'quantity': 0, 'fc': '0.00'})
        self.assertEqual(r300['facture_mvm_interne'], {'fc': '0.00'})
        self.assertEqual(data['totals']['total_du_jour_fc'], '3000.00')
        self.assertEqual(data['totals']['total_breads_billed'], 10)
