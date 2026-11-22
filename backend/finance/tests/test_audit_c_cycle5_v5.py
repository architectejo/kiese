"""
Audit comptable, cycle 5, partie C : verification independante de BUG-821 / 822 / 824 et
recoupement commissions <-> finance <-> clients. Donnees fictives uniquement.
"""
from datetime import timedelta
from decimal import Decimal as D

from clients.models import Client
from commissions.models import ClientCommission
from core.models import Config
from core.testing import make_client
from finance.tests.test_audit_c_cycle1_c import _Base, _api, _dates
from finance.tests.test_audit_c_cycle2_c import Cycle2Base
from finance.views import _income_statement_for_year
from sales.models import Invoice
from django.utils import timezone


def _generate(user, node, day):
    r = _api(user).post('/api/commissions/periods/generate/', {
        'node': node.pk, 'month': day.month, 'year': day.year}, format='json')
    assert r.status_code == 201, r.data
    return r


class V821RgAdjustment(Cycle2Base):
    def test_rg_adjustment_positive_gives_no_commission(self):
        inv = self.sale(self.f1, self.cl, [(self.bp_mini, 10)], 0, 'CREDIT', self.d1, code='RG')
        self.adjust(inv, 1, 2, bp=self.bp_mini)
        _generate(self.hq, self.k1, self.d1)
        self.assertFalse(ClientCommission.objects.filter(client=self.cl).exists())

    def test_rg_adjustment_negative_gives_no_commission(self):
        inv = self.sale(self.f1, self.cl, [(self.bp_mini, 10)], 0, 'CREDIT', self.d1, code='RG')
        self.adjust(inv, -1, 2, bp=self.bp_mini)
        _generate(self.hq, self.k1, self.d1)
        self.assertFalse(ClientCommission.objects.filter(client=self.cl).exists())

    def test_rg_adjustment_next_month_gives_no_commission(self):
        inv = self.sale(self.f1, self.cl, [(self.bp_mini, 10)], 0, 'CREDIT', self.d1, code='RG')
        later = self.d1 + timedelta(days=1)
        self.adjust(inv, 1, 2, bp=self.bp_mini)
        _generate(self.hq, self.k1, later)
        self.assertFalse(ClientCommission.objects.filter(client=self.cl).exists())

    def test_mixed_client_commission_only_on_regular_sale(self):
        self.sale(self.f1, self.cl, [(self.bp_grand, 4)], 2000, 'CASH', self.d1)           # 2000 valable
        rg = self.sale(self.f1, self.cl, [(self.bp_mini, 10)], 0, 'CREDIT', self.d1, code='RG')
        self.adjust(rg, 1, 5, bp=self.bp_mini)
        _generate(self.hq, self.k1, self.d1)
        cm = ClientCommission.objects.get(client=self.cl)
        self.assertEqual(cm.order_value, D('2000.00'))
        self.assertEqual(cm.commission_gross, D('500.00'))
        self.assertEqual(cm.total_breads, 4)

    def test_adjustment_of_regular_sale_still_counts(self):
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 4)], 2000, 'CASH', self.d1)
        self.adjust(inv, 1, 2)
        _generate(self.hq, self.k1, self.d1)
        cm = ClientCommission.objects.get(client=self.cl)
        self.assertEqual(cm.order_value, D('3000.00'))
        self.assertEqual(cm.total_breads, 6)

    def test_rg_adjustment_not_in_revenue(self):
        inv = self.sale(self.f1, self.cl, [(self.bp_mini, 10)], 0, 'CREDIT', self.d1, code='RG')
        self.adjust(inv, 1, 2, bp=self.bp_mini)
        self.assertEqual(_income_statement_for_year(self.d1.year)['total_revenue'], D('0'))


class V822TotalBreadsSigned(Cycle2Base):
    def test_chain_minus_then_plus(self):
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 10)], 5000, 'CASH', self.d1)
        self.adjust(inv, -1, 3, pay='1500.00')
        self.adjust(inv, 1, 1, pay='500.00')
        _generate(self.hq, self.k1, self.d1)
        cm = ClientCommission.objects.get(client=self.cl)
        self.assertEqual(cm.total_breads, 8)
        self.assertEqual(cm.order_value, D('4000.00'))
        self.assertEqual(cm.commission_gross, D('1000.00'))

    def test_regenerate_is_idempotent(self):
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 10)], 5000, 'CASH', self.d1)
        self.adjust(inv, -1, 3, pay='1500.00')
        _generate(self.hq, self.k1, self.d1)
        a = ClientCommission.objects.values_list('total_breads', 'order_value', 'commission_gross',
                                                 'net_payable').get(client=self.cl)
        _generate(self.hq, self.k1, self.d1)
        b = ClientCommission.objects.values_list('total_breads', 'order_value', 'commission_gross',
                                                 'net_payable').get(client=self.cl)
        self.assertEqual(a, b)
        self.assertEqual(ClientCommission.objects.filter(client=self.cl).count(), 1)

    def test_doc1_quantity_and_commission_quantity_agree(self):
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 10)], 5000, 'CASH', self.d1)
        self.adjust(inv, -1, 3, pay='1500.00')
        _generate(self.hq, self.k1, self.d1)
        cm = ClientCommission.objects.get(client=self.cl)
        row = self.doc1(self.d1)[0]
        self.assertEqual(cm.total_breads, row['qty_500'])

    def test_negative_adjustment_does_not_create_negative_quantity_or_commission(self):
        """Vente livree le mois M, retour dans le mois M+1 sans autre vente : pas de ligne, pas de CM negative."""
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 4)], 2000, 'CASH', self.d1)
        d_next = (self.d1.replace(day=1) + timedelta(days=40)).replace(day=2)
        if d_next > timezone.localdate():
            self.skipTest('mois suivant dans le futur')
        self.adjust_at(inv, -1, 2, d_next)
        _generate(self.hq, self.k1, d_next)
        self.assertFalse(ClientCommission.objects.filter(
            client=self.cl, period__month=d_next.month, period__year=d_next.year).exists())

    def adjust_at(self, inv_id, sign, qty, day):
        r = _api(self.g1).post(f'/api/sales/invoices/{inv_id}/adjust/', {
            'adjustment_sign': sign, 'payment_amount': '0.00', 'invoice_date': str(day),
            'lines': [{'bread_price': self.bp_grand.pk, 'quantity': qty}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)


class V824TotalBreadsReceived(Cycle2Base):
    def _tb(self):
        self.cl.refresh_from_db()
        return self.cl.total_breads_received

    def test_negative_then_positive(self):
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 10)], 5000, 'CASH', self.d1)
        self.assertEqual(self._tb(), 10)
        self.adjust(inv, -1, 3)
        self.assertEqual(self._tb(), 7)
        self.adjust(inv, 1, 5)
        self.assertEqual(self._tb(), 12)

    def test_multi_line_adjustment(self):
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 4), (self.bp_mini, 5)], 3500, 'CASH', self.d1)
        r = _api(self.g1).post(f'/api/sales/invoices/{inv}/adjust/', {
            'adjustment_sign': -1, 'payment_amount': '0.00', 'invoice_date': str(self.d1),
            'lines': [{'bread_price': self.bp_grand.pk, 'quantity': 1},
                      {'bread_price': self.bp_mini.pk, 'quantity': 2}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self._tb(), 6)

    def test_ns_adjustment_does_not_move_counter(self):
        r = _api(self.f1).post('/api/sales/invoices/', {
            'client': str(self.cl.pk), 'payment_type': 'CREDIT', 'payment_amount': '0',
            'special_code': 'NS', 'invoice_date': str(self.d1),
            'lines': [{'bread_price': self.bp_grand.pk, 'quantity': 4}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        before = self._tb()
        a = _api(self.g1).post(f"/api/sales/invoices/{r.data['id']}/adjust/", {
            'adjustment_sign': 1, 'payment_amount': '0.00', 'invoice_date': str(self.d1),
            'lines': [{'bread_price': self.bp_grand.pk, 'quantity': 2}]}, format='json')
        self.assertIn(a.status_code, (201, 400), a.data)
        self.assertEqual(self._tb(), before)

    def test_counter_never_negative_when_started_low(self):
        """Compteur ramene a 1 (reprise) puis retour de 3 pains : plancher a 0."""
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 4)], 2000, 'CASH', self.d1)
        Client.objects.filter(pk=self.cl.pk).update(total_breads_received=1)
        self.adjust(inv, -1, 3)
        self.assertEqual(self._tb(), 0)

    def test_category_follows_threshold(self):
        cfg = Config.get_instance()
        cfg.best_client_threshold = 10
        cfg.save(update_fields=['best_client_threshold'])
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 10)], 5000, 'CASH', self.d1)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.category, Client.Category.BEST)
        self.adjust(inv, -1, 2)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.category, Client.Category.NORMAL)
        self.adjust(inv, 1, 2)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.category, Client.Category.BEST)

    def test_other_client_counter_untouched(self):
        other = make_client(self.k1, credit_limit=D('900000'), last_name='Zo')
        self.sale(self.f1, other, [(self.bp_grand, 3)], 1500, 'CASH', self.d1)
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 10)], 5000, 'CASH', self.d1)
        self.adjust(inv, -1, 3)
        other.refresh_from_db()
        self.assertEqual(other.total_breads_received, 3)


class V5Coherence(Cycle2Base):
    """Commissions <-> finance <-> clients, avec ajustements et retenue unique (BUG-737)."""

    def test_revenue_equals_sum_commission_orders_when_all_eligible(self):
        c2 = make_client(self.k1, credit_limit=D('900000'), last_name='Zd')
        a = self.sale(self.f1, self.cl, [(self.bp_grand, 10)], 3000, 'CREDIT', self.d1)
        self.adjust(a, -1, 3, pay='0.00')
        self.sale(self.f1, c2, [(self.bp_mini, 7)], 2100, 'CASH', self.d1)
        _generate(self.hq, self.k1, self.d1)
        total = sum(c.order_value for c in ClientCommission.objects.all())
        self.assertEqual(total, _income_statement_for_year(self.d1.year)['total_revenue'])
        self.assertEqual(total, D('5600.00'))   # 3500 + 2100

    def test_net_formula_and_decimal_rounding(self):
        self.k1.monthly_social_contribution = D('2000.00')
        self.k1.card_fee_fc = D('1000.00')
        self.k1.save()
        inv = self.sale(self.f1, self.cl, [(self.bp_mini, 7)], 1000, 'CREDIT', self.d1)  # 2100, BP 1100
        self.adjust(inv, -1, 1, bp=self.bp_mini, pay='0.00')                             # 1800, BP 800
        _generate(self.hq, self.k1, self.d1)
        cm = ClientCommission.objects.get(client=self.cl)
        self.assertEqual(cm.order_value, D('1800.00'))
        self.assertEqual(cm.commission_gross, D('450.00'))
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, D('800.00'))
        self.assertEqual(cm.deduction_debt, D('800.00'))
        expected = (cm.commission_gross - cm.deduction_debt - cm.deduction_social
                    - cm.deduction_prints - cm.deduction_other - cm.carried_debt_in)
        self.assertEqual(cm.net_payable, expected)
        for f in ('commission_gross', 'net_payable', 'total_deductions', 'deduction_remise'):
            v = getattr(cm, f)
            self.assertEqual(v, v.quantize(D('0.01')), f)
        self.assertEqual(cm.deduction_remise, D('4.50'))   # 0,25 % de 1800

    def test_unique_withholding_across_two_nodes_with_adjustments(self):
        self.k1.monthly_social_contribution = D('2000.00')
        self.k1.save()
        self.k2.monthly_social_contribution = D('2000.00')
        self.k2.save()
        a = self.sale(self.f1, self.cl, [(self.bp_grand, 4)], 0, 'CREDIT', self.d1)       # BP 2000
        b = self.sale(self.f2, self.cl, [(self.bp_grand, 2)], 0, 'CREDIT', self.d1)       # BP 3000
        self.adjust(a, -1, 1, pay='0.00')                                                 # BP 2500
        _generate(self.hq, self.k1, self.d1)
        _generate(self.hq, self.k2, self.d1)
        rows = list(ClientCommission.objects.filter(client=self.cl).order_by('created_at'))
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(r.deduction_debt for r in rows), D('2500.00'))
        self.assertEqual(sum(r.deduction_social for r in rows), D('2000.00'))
        self.assertEqual(rows[1].deduction_debt, D('0.00'))
        self.assertEqual(rows[1].deduction_social, D('0.00'))
        # CM totale = CM de chaque boulangerie
        self.assertEqual(sum(r.commission_gross for r in rows), D('0.25') * D('2500'))

    def test_bp_equals_sum_of_signed_invoice_deltas(self):
        """BP finale du client = somme(commande signee - versement signe) des factures livrees."""
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 6)], 1000, 'CREDIT', self.d1)
        self.adjust(inv, -1, 2, pay='0.00')
        self.adjust(inv, 1, 1, pay='200.00')
        self.cl.refresh_from_db()
        tot = D('0')
        for i in Invoice.objects.filter(client=self.cl, status=Invoice.Status.DELIVERED):
            tot += D(i.order_total) - D(i.payment_amount)
        self.assertEqual(self.cl.current_debt, tot)
