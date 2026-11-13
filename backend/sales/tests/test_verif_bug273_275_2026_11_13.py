"""Verification BUG-273/275 (testeur-ventes, 2026-11-13) : cas limites, base de test isolee."""
from decimal import Decimal

from sales.tests.test_vague4_calendaire_ventes_2026_11_12 import (
    Base, INV, D, PREV, _api, _now,
)


class Verif273275(Base):
    def setUp(self):
        super().setUp()
        self.assign(PREV, 'A')
        self.assign(D, 'B')

    def _ds(self, d=D):
        rows = _api(self.gerant).get(INV + 'daily_summary/', {'date': str(d)}).data
        cash = sum(Decimal(str(r['total'])) for r in rows if r['payment_type'] == 'CASH')
        credit = sum(Decimal(str(r['total'])) for r in rows if r['payment_type'] == 'CREDIT')
        return cash, credit, sum(r['count'] for r in rows)

    def test_cash_credit_remboursement_ns_rg_coherents_avec_rapports_et_cloture(self):
        other = __import__('core.testing', fromlist=['x']).make_client(self.node)
        with _now(23, 55, PREV):
            a = self.sale(qty=2, pay=400).data['id']          # 1000, 400 cash, 600 credit
        with _now(0, 10):
            self.assertEqual(self.deliver(a).status_code, 200)
            b = self.sale(user=self.fb, qty=4, pay=2000).data['id']   # tout cash
            self.deliver(b)
            ns = self.sale(user=self.fb, special_code='NS', qty=3, client=other)
            self.assertEqual(ns.status_code, 201)
            rg = self.sale(user=self.fb, special_code='RG', qty=1, client=other, pay=0)
            self.assertEqual(rg.status_code, 201)
            self.deliver(rg.data['id'])
            rf = self.refund(300)
            self.assertEqual(rf.status_code, 201, rf.data)
            self.deliver(rf.data['id'])
            before = self._ds(PREV)
            cash, credit, count = self._ds(D)
            rep = _api(self.gerant).post('/api/treasury/reports/generate/', {}, format='json')
            self.assertEqual(rep.status_code, 200)
        self.assertEqual(before[2], 0)                  # rien au jour de facturation
        rep_cash = sum(Decimal(x['total_cash_sales']) for x in rep.data)
        print('DAILY', cash, credit, count, 'REPORT', rep_cash,
              [(x['team'], x['total_cash_sales'], x['total_credit_sales']) for x in rep.data])
        self.assertEqual(cash, rep_cash)
        with _now(20, 0):
            c = _api(self.gerant).post('/api/treasury/closures/', {'date': str(D), 'bills_500': 1}, format='json')
        print('CLOSURE', c.status_code, c.data.get('total_entries'))
        self.assertEqual(Decimal(c.data['total_entries']), cash)
