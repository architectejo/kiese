"""
Vérification indépendante (testeur-production, 2026-11-20) de BUG-317 :
« Stock de départ de la relève » n'accepte plus de quantité négative
(remarque.md l.441). Endpoint : POST /api/production/opening-confirmation/.
Données entièrement fictives (`core.testing`).
"""
import time
import unittest
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price
from production.models import (
    BreadStock, DailyBreadStockSnapshot, DailyOpeningConfirmation,
    DailyOpeningConfirmationLine, ProductionSession, ProductionSessionLine,
    _adjust_bread_stock,
)
from production.views import _build_daily_closure_report

URL = '/api/production/opening-confirmation/'
DAY = date(2026, 11, 9)
DAY_S = DAY.isoformat()


class _Base(TestCase):
    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.other = make_node(sac_value_fc=Decimal('200000'))
        self.gerant = make_user(role='GERANT', node=self.node)
        self.bp = make_bread_price(category='MOYEN', label='Pain 500 V317', unit_price=500)
        self.bp2 = make_bread_price(category='GRAND', label='Pain 1000 V317', unit_price=1000)
        self.api = APIClient()
        self.api.force_authenticate(self.gerant)
        _adjust_bread_stock(self.node, self.bp, produced=20)
        _adjust_bread_stock(self.node, self.bp2, produced=10)

    def post(self, lines, team='A', client=None, **extra):
        body = {'team': team, 'date': DAY_S, 'lines': lines}
        body.update(extra)
        return (client or self.api).post(URL, body, format='json')

    def q(self, qty, bp=None):
        return [{'bread_price': (bp or self.bp).pk, 'qty': qty}]

    def stock(self, bp=None):
        return BreadStock.objects.get(node=self.node, bread_price=bp or self.bp)

    def assertNothingWritten(self):
        self.assertFalse(DailyOpeningConfirmation.objects.exists())
        self.assertFalse(DailyOpeningConfirmationLine.objects.exists())
        self.assertFalse(ProductionSession.objects.exists())
        self.assertFalse(ProductionSessionLine.objects.exists())
        self.assertEqual(self.stock().qty_adjusted, 0)
        self.assertEqual(self.stock().qty_available, 20)
        self.assertEqual(self.stock(self.bp2).qty_available, 10)


class InvalidValuesTests(_Base):
    def test_each_invalid_value_refused_400_detail_and_no_write(self):
        cases = {
            'negatif': -1, 'negatif_grand': -1000000, 'neg_str': '-3', 'neg_str_espace': ' -3 ',
            'decimal': 1.5, 'decimal_str': '1.5', 'decimal_virgule': '1,5', 'neg_decimal': -0.5,
            'NaN': 'NaN', 'sNaN': 'sNaN', 'Infinity': 'Infinity', '-Infinity': '-Infinity',
            'inf': 'inf', 'texte': 'abc', 'vide': '', 'espaces': '   ', 'null': None,
            'true': True, 'false': False, 'liste': [1], 'objet': {'a': 1},
            'demesure': 2_000_000_001, 'demesure_str': '99999999999', 'e30': 1e30,
            'exp_str': '1E+30', 'moins_exp': '-1E+3',
        }
        for name, bad in cases.items():
            with self.subTest(name):
                resp = self.post(self.q(bad))
                self.assertEqual(resp.status_code, 400, (name, resp.data))
                self.assertIn('detail', resp.data)
                self.assertNothingWritten()

    def test_missing_qty_key_refused(self):
        resp = self.post([{'bread_price': self.bp.pk}])
        self.assertEqual(resp.status_code, 400)
        self.assertNothingWritten()

    def test_negative_message_is_french(self):
        resp = self.post(self.q(-4))
        self.assertEqual(resp.data['detail'], "Le stock de départ ne peut pas être négatif.")

    def test_boundary_2e9_accepted_and_2e9_plus_1_refused(self):
        self.assertEqual(self.post(self.q(2_000_000_000)).status_code, 200)
        self.assertEqual(self.stock().qty_available, 2_000_000_000)
        self.assertEqual(self.post(self.q(2_000_000_001)).status_code, 400)
        self.assertEqual(self.stock().qty_available, 2_000_000_000)

    def test_huge_exponent_string_answers_fast(self):
        t = time.time()
        resp = self.post(self.q('1E+99999'))
        self.assertEqual(resp.status_code, 400)
        self.assertLess(time.time() - t, 0.3)  # constaté ~0,9 s ; 1E+999999 > 90 s (blocage)


class AcceptedValuesTests(_Base):
    def test_zero_accepted_and_stock_set_to_zero(self):
        resp = self.post(self.q(0))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(DailyOpeningConfirmationLine.objects.get(bread_price=self.bp).qty_confirmed, 0)
        self.assertEqual(self.stock().qty_adjusted, -20)
        self.assertEqual(self.stock().qty_available, 0)

    def test_positive_accepted_and_propagated(self):
        resp = self.post(self.q(35))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(self.stock().qty_adjusted, 15)
        self.assertEqual(self.stock().qty_available, 35)
        self.assertEqual(resp.data['stock_adjustments'], [
            {'bread_price_id': self.bp.pk, 'before': 20, 'after': 35, 'delta': 15}])

    def test_integral_forms_accepted(self):
        for ok in ('7', 7.0, '7.0', ' 7 ', '7E0'):
            with self.subTest(ok):
                resp = self.post(self.q(ok))
                self.assertEqual(resp.status_code, 200, (ok, resp.data))
                self.assertEqual(self.stock().qty_available, 7)

    def test_resubmission_idempotent(self):
        for _ in range(3):
            self.assertEqual(self.post(self.q(12)).status_code, 200)
        self.assertEqual(self.stock().qty_adjusted, -8)
        self.assertEqual(DailyOpeningConfirmationLine.objects.count(), 1)
        self.assertEqual(DailyOpeningConfirmation.objects.count(), 1)

    def test_carryover_line_only_for_positive(self):
        resp = self.post(self.q(5) + self.q(0, self.bp2))
        self.assertEqual(resp.status_code, 200, resp.data)
        sess = ProductionSession.objects.get(node=self.node, team='A', date=DAY)
        carry = ProductionSessionLine.objects.filter(
            session=sess, source=ProductionSessionLine.Source.CARRYOVER)
        self.assertEqual(carry.count(), 1)
        self.assertEqual(carry.get().quantity, 5)

    def test_reste_du_hier_in_closure_report_non_negative(self):
        self.post(self.q(9))
        report = _build_daily_closure_report(self.node, DAY)
        row = next(c for c in report['categories'] if c['bread_price'] == self.bp.pk)
        self.assertEqual(row['reste_du_hier']['A'], -9)  # convention BUG-135 : -qty_confirmed
        self.assertEqual(row['reste_du_hier']['B'], 0)


class AtomicityTests(_Base):
    def test_mixed_valid_and_invalid_lines_write_nothing(self):
        resp = self.post(self.q(5) + self.q(-1, self.bp2))
        self.assertEqual(resp.status_code, 400)
        self.assertNothingWritten()
        resp = self.post(self.q(5, self.bp2) + self.q('x'))
        self.assertEqual(resp.status_code, 400)
        self.assertNothingWritten()

    def test_invalid_last_line_after_valid_ones(self):
        resp = self.post(self.q(1) + self.q(2, self.bp2) + [{'bread_price': self.bp.pk, 'qty': -9}])
        self.assertEqual(resp.status_code, 400)
        self.assertNothingWritten()

    def test_previous_confirmation_intact_after_refusal(self):
        self.assertEqual(self.post(self.q(12) + self.q(3, self.bp2)).status_code, 200)
        sess_lines = ProductionSessionLine.objects.count()
        for bad in (-5, 'NaN', None, 1.5, 3_000_000_000):
            self.assertEqual(self.post(self.q(bad)).status_code, 400)
        self.assertEqual(DailyOpeningConfirmation.objects.count(), 1)
        lines = {l.bread_price_id: l.qty_confirmed for l in DailyOpeningConfirmationLine.objects.all()}
        self.assertEqual(lines, {self.bp.pk: 12, self.bp2.pk: 3})
        self.assertEqual(self.stock().qty_available, 12)
        self.assertEqual(self.stock(self.bp2).qty_available, 3)
        self.assertEqual(ProductionSessionLine.objects.count(), sess_lines)

    def test_refusal_does_not_touch_previous_day_snapshot_nor_activity_log(self):
        from core.models import ActivityLog
        DailyBreadStockSnapshot.objects.create(
            node=self.node, bread_price=self.bp, date=DAY - timedelta(days=1), team='A', qty_at_close=12)
        qs = ActivityLog.objects.filter(action__regex=r'Stock de D|Reste d|Ajustement')
        before = qs.count()
        self.assertEqual(self.post(self.q(-3)).status_code, 400)
        self.assertEqual(qs.count(), before)
        self.assertEqual(
            list(DailyBreadStockSnapshot.objects.values_list('qty_at_close', flat=True)), [12])


class MethodsRolesIsolationTests(_Base):
    def test_put_patch_delete_405(self):
        for m in (self.api.put, self.api.patch, self.api.delete):
            resp = m(URL, {'team': 'A', 'date': DAY_S, 'lines': self.q(-1)}, format='json')
            self.assertEqual(resp.status_code, 405)
        self.assertNothingWritten()

    def test_anonymous_refused(self):
        resp = APIClient().post(URL, {'team': 'A', 'lines': self.q(1)}, format='json')
        self.assertIn(resp.status_code, (401, 403))
        self.assertNothingWritten()

    def test_livreur_refused_even_with_valid_value(self):
        c = APIClient()
        c.force_authenticate(make_user(role='LIVREUR', node=self.node))
        self.assertEqual(self.post(self.q(5), client=c).status_code, 403)
        self.assertNothingWritten()

    def test_facturier_same_rules(self):
        c = APIClient()
        c.force_authenticate(make_user(role='FACTURIER', node=self.node))
        self.assertEqual(self.post(self.q(-5), client=c).status_code, 400)
        self.assertNothingWritten()
        self.assertEqual(self.post(self.q(5), client=c).status_code, 200)

    def test_hq_roles_same_rules_and_node_required(self):
        for role in ('DIRECTION', 'ADMIN'):
            with self.subTest(role):
                c = APIClient()
                c.force_authenticate(make_user(role=role, node=None))
                self.assertEqual(self.post(self.q(5), client=c).status_code, 400)  # node requis
                self.assertEqual(
                    self.post(self.q(-5), client=c, node=self.node.code).status_code, 400)
                self.assertNothingWritten()

    def test_hq_positive_writes_only_targeted_node(self):
        c = APIClient()
        c.force_authenticate(make_user(role='DIRECTION', node=None))
        self.assertEqual(self.post(self.q(6), client=c, node=self.node.code).status_code, 200)
        self.assertEqual(self.stock().qty_available, 6)
        self.assertFalse(BreadStock.objects.filter(node=self.other).exclude(qty_adjusted=0).exists())

    def test_gerant_cannot_target_other_node(self):
        _adjust_bread_stock(self.other, self.bp, produced=4)
        resp = self.post(self.q(9), node=self.other.code)
        self.assertEqual(resp.status_code, 200)  # `node` ignoré
        other_stock = BreadStock.objects.get(node=self.other, bread_price=self.bp)
        self.assertEqual(other_stock.qty_available, 4)
        self.assertEqual(self.stock().qty_available, 9)
        self.assertFalse(DailyOpeningConfirmation.objects.filter(node=self.other).exists())

    def test_refusal_on_one_node_does_not_affect_other(self):
        _adjust_bread_stock(self.other, self.bp, produced=4)
        g2 = make_user(role='GERANT', node=self.other)
        c2 = APIClient()
        c2.force_authenticate(g2)
        self.assertEqual(self.post(self.q(3), client=c2).status_code, 200)
        self.assertEqual(self.post(self.q(-3)).status_code, 400)
        self.assertEqual(BreadStock.objects.get(node=self.other, bread_price=self.bp).qty_available, 3)
        self.assertEqual(self.stock().qty_available, 20)


class GetProposedNegativeTests(_Base):
    def test_get_still_exposes_negative_qty_proposed(self):
        # Stock physique négatif en base (ex. sorties > production).
        _adjust_bread_stock(self.node, self.bp, disposed=50)
        resp = self.api.get(URL, {'date': DAY_S})
        self.assertEqual(resp.status_code, 200)
        row = next(c for c in resp.data['categories'] if c['bread_price'] == self.bp.pk)
        # BUG-330 : changement de spécification voulu (règle « plus de
        # négatifs ») : l'API borne la proposition à 0 ; stock réel inchangé.
        self.assertEqual(row['qty_proposed'], 0)
        self.assertEqual(self.stock().qty_available, -30)

    def test_posting_proposed_negative_is_refused_then_zero_works(self):
        _adjust_bread_stock(self.node, self.bp, disposed=50)
        resp = self.post(self.q(-30))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.stock().qty_available, -30)
        self.assertEqual(self.post(self.q(0)).status_code, 200)
        self.assertEqual(self.stock().qty_available, 0)
