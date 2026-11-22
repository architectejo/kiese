"""
Contre-attaque (testeur-production, Dev A, 2026-11-22-a2) : BUG-508 (full_unit_price),
BUG-363 (perte figee), BUG-512 (alerte de surconsommation sur sacs ajoutes).
Donnees fictives uniquement.
"""
from decimal import Decimal, ROUND_HALF_UP

from unittest import expectedFailure

from django.test import TestCase

from core.models import SystemNotification
from core.testing import make_bread_price
from core.workday import work_date_for
from production.models import ConsumableMovement, ConsumableStock, ProductionSession
from production.tests import test_verif_rotation_prod_c as R
from production.tests.test_verif_bug501_510_a import Bug502CounterTests
from sales.models import InvoiceLine

D = Decimal
PRICES = (50, 150, 250, 300, 500)


def _frozen(p):
    return int((D(p) * D('0.75')).quantize(D('1'), rounding=ROUND_HALF_UP))


class Bug508FullPriceTests(R._ReportBase):
    def _retarif(self, bp, *prices):
        for p in prices:
            bp.unit_price = p
            bp.save()

    def test_rg_soldee_all_prices_multiple_changes_stable(self):
        bps = {p: make_bread_price(f'Z{p}', f'Pain {p} Z', p) for p in PRICES}
        with R._now(10):
            self._session('A', R.J, [(bp, 200) for bp in bps.values()])
            for bp in bps.values():
                self._inv([(bp, 7)], code='RG', soldee=True)
            for p, bp in bps.items():
                got = []
                for newp in (p + 1, 1000, 75, p):
                    self._retarif(bp, newp)
                    got.append(self._cat(self._report(R.J), bp)['regularisation']['fc'])
                self.assertEqual(set(got), {str(D(7 * p).quantize(D('0.01')))}, (p, got))

    def test_plain_rg_and_normal_sale_stable(self):
        with R._now(10):
            self._session('A', R.J, [(self.bp300, 100)])
            self._inv([(self.bp300, 5)], code='RG')
            self._inv([(self.bp300, 4)])
            b = self._cat(self._report(R.J), self.bp300)
            self._retarif(self.bp300, 900, 10)
            a = self._cat(self._report(R.J), self.bp300)
        self.assertEqual(b['regularisation']['fc'], '1500.00')
        self.assertEqual(a['regularisation'], b['regularisation'])
        self.assertEqual(a['facture_jr'], b['facture_jr'])
        self.assertEqual(b['facture_jr']['fc'], '1200.00')

    def test_loss_all_prices_stable_and_exact(self):
        bps = {p: make_bread_price(f'L{p}', f'Pain {p} L', p) for p in PRICES}
        with R._now(10):
            self._session('A', R.J, [(bp, 200) for bp in bps.values()])
            for bp in bps.values():
                self._inv([(bp, 8)], soldee=True)
            for p, bp in bps.items():
                exp = D((p - _frozen(p)) * 8).quantize(D('0.01'))
                b = self._cat(self._report(R.J), bp)['vente_cash_soldee']
                self._retarif(bp, 1234, 5)
                a = self._cat(self._report(R.J), bp)['vente_cash_soldee']
                self.assertEqual(b['perte_fc'], str(exp), p)
                self.assertEqual(a, b, p)

    def test_line_resave_keeps_full_price(self):
        with R._now(10):
            self._session('A', R.J, [(self.bp300, 100)])
            inv = self._inv([(self.bp300, 10)], soldee=True, deliver=False)
            self._retarif(self.bp300, 700)
            ln = InvoiceLine.objects.get(invoice_id=inv['id'])
            self.assertEqual((ln.full_unit_price, ln.unit_price), (300, 225))
            ln.quantity = 6
            ln.save()
            ln.refresh_from_db()
            self.assertEqual((ln.full_unit_price, ln.unit_price, ln.line_total), (300, 225, D('1350.00')))
            self.assertEqual(ln.loss, D('450'))

    def test_new_invoice_after_change_uses_new_full_price_old_untouched(self):
        with R._now(10):
            self._session('A', R.J, [(self.bp300, 100)])
            old = self._inv([(self.bp300, 10)], code='RG', soldee=True)
            self._retarif(self.bp300, 400)
            new = self._inv([(self.bp300, 10)], code='RG', soldee=True)
            fc = self._cat(self._report(R.J), self.bp300)['regularisation']['fc']
        self.assertEqual(InvoiceLine.objects.get(invoice_id=old['id']).full_unit_price, 300)
        self.assertEqual(InvoiceLine.objects.get(invoice_id=new['id']).full_unit_price, 400)
        self.assertEqual(fc, '7000.00')

    @expectedFailure  # BUG-513
    def test_past_day_produced_value_after_tariff_change(self):
        """Valorisation de la production d'un jour passe : relit-elle le catalogue ?"""
        with R._now(10):
            self._session('A', R.J, [(self.bp300, 100)])
            b = self._cat(self._report(R.J), self.bp300)['produit']
            self._retarif(self.bp300, 400)
            a = self._cat(self._report(R.J), self.bp300)['produit']
        self.assertEqual(b['fc'], '30000.00')
        self.assertEqual(a, b)


class Bug512CounterTests(TestCase):
    setUp = Bug502CounterTests.setUp
    _post = Bug502CounterTests._post

    def _hist(self):
        past = ProductionSession.objects.create(
            node=self.k1, team='A', date=work_date_for(self.k1).replace(year=2026, month=1, day=5),
            flour_sacks_used=D('2.00'), declared_by=self.user, node_origin='K1')
        st = ConsumableStock.objects.create(node=self.k1, consumable_type='SALT', unit='g')
        ConsumableMovement.objects.create(node=self.k1, stock=st, movement_type='EXIT',
                                          quantity=D('100'), session=past)

    def _n(self):
        return SystemNotification.objects.filter(title__startswith='Surconsommation SALT').count()

    def test_third_declaration_alerts_only_when_abnormal(self):
        self._hist()
        self._post('1.00', consumables_used=[{'consumable_type': 'SALT', 'quantity': '50'}])
        self._post('1.00', consumables_used=[{'consumable_type': 'SALT', 'quantity': '90'}])
        self.assertEqual(self._n(), 0)
        self._post('0.50', consumables_used=[{'consumable_type': 'SALT', 'quantity': '60'}])
        self.assertEqual(self._n(), 1)

    def test_decimal_sacks_ratio(self):
        self._hist()
        self._post('0.25', consumables_used=[{'consumable_type': 'SALT', 'quantity': '12'}])
        self.assertEqual(self._n(), 0)
        self._post('0.25', consumables_used=[{'consumable_type': 'SALT', 'quantity': '26'}])
        self.assertEqual(self._n(), 1)

    def test_declaration_without_added_sacks_falls_back_on_cumul(self):
        self._hist()
        self._post('2.00')
        self.assertEqual(self._n(), 0)
        self._post('0', consumables_used=[{'consumable_type': 'SALT', 'quantity': '500'}])
        self.assertEqual(self._n(), 1)

    def test_no_false_alert_cumul_diluted_case(self):
        self._hist()
        self._post('4.00', consumables_used=[{'consumable_type': 'SALT', 'quantity': '200'}])
        self._post('1.00', consumables_used=[{'consumable_type': 'SALT', 'quantity': '55'}])
        self.assertEqual(self._n(), 0)
