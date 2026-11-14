"""BUG-286 / 287 / 288 (dev-backend, 2026-11-14) : cloture, daily_summary et rapport facturier alignes."""
from decimal import Decimal

from core.testing import make_client
from sales.models import Invoice
from sales.tests.test_vague4_calendaire_ventes_2026_11_12 import (
    Base, INV, D, PREV, _api, _now,
)


class Bug286ClotureDateLivraison(Base):
    def setUp(self):
        super().setUp()
        self.assign(PREV, 'A')
        self.assign(D, 'B')

    def _closure(self, d):
        r = _api(self.gerant).get('/api/production/daily-closure/', {'date': str(d)})
        self.assertEqual(r.status_code, 200, r.data)
        return r.data['totals']

    def test_vente_facturee_la_veille_livree_apres_minuit_tombe_au_jour_de_livraison(self):
        with _now(23, 55, PREV):
            iid = self.sale(qty=10, pay=2000).data['id']  # 5000 FC, 2000 verses
        with _now(0, 10):
            self.assertEqual(self.deliver(iid).status_code, 200)
            avant = self._closure(PREV)
            apres = self._closure(D)
        self.assertEqual(Decimal(avant['ecart_facture_fc']), 0)
        self.assertEqual(Decimal(apres['ecart_facture_fc']), Decimal('3000'))
        self.assertEqual(apres['total_breads_billed'], 10)
        self.assertEqual(avant['total_breads_billed'], 0)


class Bug287Bug288Credit(Base):
    def setUp(self):
        super().setUp()
        self.assign(D, 'A')
        self.other = make_client(self.node)

    def _credit(self):
        rows = _api(self.gerant).get(INV + 'daily_summary/', {'date': str(D)}).data
        return sum(Decimal(str(r['total'])) for r in rows if r['payment_type'] == 'CREDIT')

    def test_rg_hors_credit_daily_summary_bp_inchangee(self):
        with _now(13, 0):
            a = self.sale(qty=2, pay=1000)          # tout paye
            self.deliver(a.data['id'])
            rg = self.sale(qty=4, special_code='RG', client=self.other, pay=0)
            self.assertEqual(rg.status_code, 201, rg.data)
            self.deliver(rg.data['id'])
            self.other.refresh_from_db()
            self.assertEqual(self.other.current_debt, 0)   # variation de BP nulle
            self.assertEqual(self._credit(), 0)

    def test_vente_solde_hors_credit_rapport_facturier(self):
        with _now(13, 0):
            s = self.sale(qty=6, pay=1000, is_soldee=True)
            self.assertEqual(s.status_code, 201, s.data)
            self.deliver(s.data['id'])
            n = self.sale(qty=2, pay=400)           # vente normale : 600 de credit
            self.deliver(n.data['id'])
            rep = _api(self.gerant).post('/api/treasury/reports/generate/', {'date': str(D)}, format='json')
        self.assertEqual(rep.status_code, 200, rep.data)
        credit = sum(Decimal(x['total_credit_sales']) for x in rep.data)
        self.assertEqual(credit, Decimal('600'))
        inv = Invoice.objects.get(pk=s.data['id'])
        self.assertTrue(inv.is_soldee)
