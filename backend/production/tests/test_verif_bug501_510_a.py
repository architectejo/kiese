"""
Contre-attaque (testeur-production, Dev A, 2026-11-22-a) des tickets CORRIGÉ
BUG-501, 502, 508, 509, 510 et points signalés par le dev (perte des soldées,
alerte de surconsommation approximative). Données fictives uniquement.
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest import expectedFailure

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import ActivityLog, SystemNotification
from core.testing import make_bread_price, make_node, make_user
from core.workday import work_date_for
from production.models import (
    ConsumableMovement, ConsumableStock, ConsumableType, DailyBreadStockSnapshot,
    ProductionSession,
)
from production.tests import test_verif_rotation_prod_c as R

D = Decimal
SESSIONS = '/api/production/sessions/'


def _run(*args):
    out = StringIO()
    call_command('recompute_cump', *args, stdout=out)
    return out.getvalue()


def _mv(stock, kind, qty, price='0.00'):
    return ConsumableMovement.objects.create(
        node=stock.node, stock=stock, movement_type=kind, quantity=D(qty), unit_price=D(price))


# --------------------------------------------------------------------------
# BUG-502
# --------------------------------------------------------------------------
class Bug502CounterTests(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1', sac_value_fc=D('200000'))
        self.user = make_user('GERANT', node=self.k1)
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        for code, unit in (('FLOUR', 'sacs'), ('SALT', 'g'), ('YEAST', 'paquets'), ('OIL', 'L')):
            ConsumableType.objects.update_or_create(code=code, defaults={'label': code, 'unit': unit})
        self.api = APIClient()
        self.api.force_authenticate(self.user)
        ConsumableStock.objects.create(node=self.k1, consumable_type='FLOUR', quantity=D('20'), unit='sacs')

    def _post(self, sacks='2.00', qty=100, team='A', **extra):
        p = {'team': team, 'date': str(work_date_for(self.k1)), 'flour_sacks_used': sacks,
             'lines': [{'bread_price': self.bp.pk, 'quantity': qty}]}
        p.update(extra)
        r = self.api.post(SESSIONS, p, format='json')
        self.assertIn(r.status_code, (200, 201), r.data)
        return r

    def _flour(self):
        return ConsumableStock.objects.get(node=self.k1, consumable_type='FLOUR').quantity

    def _flour_exits(self):
        return sorted(m.quantity for m in ConsumableMovement.objects.filter(
            stock__node=self.k1, stock__consumable_type='FLOUR', movement_type='EXIT'))

    def test_three_declarations_with_decimals_sum_exactly(self):
        self._post('2.00')
        self._post('1.50')
        self._post('0.25')
        self.assertEqual(self._flour(), D('16.250'))
        self.assertEqual(self._flour_exits(), [D('0.250'), D('1.500'), D('2.000')])
        s = ProductionSession.objects.get()
        self.assertEqual(s.flour_sacks_used, D('3.75'))

    def test_declaration_without_flour_creates_no_flour_exit_and_keeps_stock(self):
        self._post('2.00')
        r = self.api.post(SESSIONS, {'team': 'A', 'date': str(work_date_for(self.k1)),
                                     'lines': [{'bread_price': self.bp.pk, 'quantity': 50}]}, format='json')
        self.assertIn(r.status_code, (200, 201), r.data)
        self.assertEqual(self._flour(), D('18.000'))
        self.assertEqual([m for m in self._flour_exits() if m == 0], [])

    def test_other_consumables_only_decrement_request_amount_on_second_declaration(self):
        self._post('2.00', consumables_used=[{'consumable_type': 'SALT', 'quantity': '500'},
                                             {'consumable_type': 'YEAST', 'quantity': '0.25'}])
        self._post('2.00', consumables_used=[{'consumable_type': 'SALT', 'quantity': '300'},
                                             {'consumable_type': 'OIL', 'quantity': '0.33'}])
        q = {s.consumable_type: s.quantity for s in ConsumableStock.objects.filter(node=self.k1)}
        self.assertEqual(q['FLOUR'], D('16.000'))
        self.assertEqual(q['SALT'], D('-800.000'))
        self.assertEqual(q['YEAST'], D('-0.250'))
        self.assertEqual(q['OIL'], D('-0.330'))

    def test_other_team_same_day_is_independent_session(self):
        self._post('2.00', team='A')
        self._post('3.00', team='B')
        self._post('1.00', team='A')
        self.assertEqual(self._flour(), D('14.000'))

    def test_movement_stock_ledger_equals_stock_quantity(self):
        self._post('2.00')
        self._post('2.00')
        st = ConsumableStock.objects.get(node=self.k1, consumable_type='FLOUR')
        net = sum((m.quantity if m.movement_type == 'ENTRY' else -m.quantity)
                  for m in ConsumableMovement.objects.filter(stock=st))
        self.assertEqual(st.quantity, D('20') + net)

    # Point signalé par le dev : _check_overconsumption approximative.
    def test_overconsumption_alert_on_second_declaration_uses_added_sacks(self):
        """Historique : 2 sacs / 100 g de sel (50 g/sac). Aujourd'hui : 1 sac + 50 g (RAS),
        puis 1 sac + 120 g (120 g/sac = 2,4x la moyenne, seuil 2x) => alerte attendue.
        `_check_overconsumption` divise 120 par le cumul de la session (2 sacs) = 60 g/sac."""
        past = ProductionSession.objects.create(
            node=self.k1, team='A', date=work_date_for(self.k1).replace(year=2026, month=1, day=5),
            flour_sacks_used=D('2.00'), declared_by=self.user, node_origin='K1')
        st = ConsumableStock.objects.create(node=self.k1, consumable_type='SALT', unit='g')
        ConsumableMovement.objects.create(node=self.k1, stock=st, movement_type='EXIT',
                                          quantity=D('100'), session=past)
        self._post('1.00', consumables_used=[{'consumable_type': 'SALT', 'quantity': '50'}])
        n0 = SystemNotification.objects.filter(title__startswith='Surconsommation SALT').count()
        self._post('1.00', consumables_used=[{'consumable_type': 'SALT', 'quantity': '120'}])
        n1 = SystemNotification.objects.filter(title__startswith='Surconsommation SALT').count()
        self.assertEqual(n1, n0 + 1)

    def test_overconsumption_alert_on_first_declaration_still_works(self):
        past = ProductionSession.objects.create(
            node=self.k1, team='A', date=work_date_for(self.k1).replace(year=2026, month=1, day=5),
            flour_sacks_used=D('2.00'), declared_by=self.user, node_origin='K1')
        st = ConsumableStock.objects.create(node=self.k1, consumable_type='SALT', unit='g')
        ConsumableMovement.objects.create(node=self.k1, stock=st, movement_type='EXIT',
                                          quantity=D('100'), session=past)
        self._post('1.00', consumables_used=[{'consumable_type': 'SALT', 'quantity': '120'}])
        self.assertEqual(SystemNotification.objects.filter(title__startswith='Surconsommation SALT').count(), 1)


# --------------------------------------------------------------------------
# BUG-501
# --------------------------------------------------------------------------
class Bug501CounterTests(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.k2 = make_node(code='K2')
        self.s1 = ConsumableStock.objects.create(node=self.k1, consumable_type='FLOUR', unit='sac')
        self.s2 = ConsumableStock.objects.create(node=self.k2, consumable_type='FLOUR', unit='sac')

    def _untraced(self, stock):
        ConsumableStock.objects.filter(pk=stock.pk).update(quantity=D('10.000'), average_unit_cost=D('50.0000'))
        stock.refresh_from_db()
        out = _mv(stock, 'EXIT', '2', '50')
        ent = _mv(stock, 'ENTRY', '5', '100')
        # BUG-416 : horloge Windows grossiere -> created_at explicite et croissant
        base = out.created_at
        ConsumableMovement.objects.filter(pk=out.pk).update(created_at=base)
        ConsumableMovement.objects.filter(pk=ent.pk).update(created_at=base + timedelta(seconds=1))
        stock.refresh_from_db()
        return out

    def test_without_force_untouched_exit_prices_quantity_and_no_activity_log(self):
        out = self._untraced(self.s1)
        qty = self.s1.quantity
        avg = self.s1.average_unit_cost
        logs = ActivityLog.objects.count()
        text = _run('--apply')
        self.s1.refresh_from_db()
        out.refresh_from_db()
        self.assertIn('IGNORÉ', text)
        self.assertEqual(self.s1.average_unit_cost, avg)
        self.assertEqual(out.unit_price, D('50.00'))
        self.assertEqual(self.s1.quantity, qty)
        self.assertEqual(ActivityLog.objects.count(), logs)
        self.assertIn('0 corrigé', text)

    def test_cump_value_identical_before_and_after_apply_without_force(self):
        self._untraced(self.s1)
        before = ConsumableStock.objects.get(pk=self.s1.pk).average_unit_cost
        _run('--apply')
        self.assertEqual(ConsumableStock.objects.get(pk=self.s1.pk).average_unit_cost, before)

    def test_force_revalues_exits_and_logs(self):
        out = self._untraced(self.s1)
        logs = ActivityLog.objects.count()
        _run('--apply', '--force')
        out.refresh_from_db()
        self.assertEqual(out.unit_price, D('0.00'))  # rejeu parti de 0 : comportement documenté de --force
        self.assertEqual(ActivityLog.objects.count(), logs + 1)

    def test_mixed_run_corrects_traced_stock_and_skips_untraced(self):
        self._untraced(self.s1)
        # K2 : stock tracé mais CUMP corrompu
        _mv(self.s2, 'ENTRY', '10', '100000')
        ConsumableStock.objects.filter(pk=self.s2.pk).update(average_unit_cost=D('200000.0000'))
        text = _run('--apply')
        self.s2.refresh_from_db()
        self.assertEqual(self.s2.average_unit_cost, D('100000.0000'))
        self.assertIn('1 corrigé', text)
        self.assertIn('2 stock(s) examiné(s)', text)

    def test_dry_run_with_force_writes_nothing(self):
        out = self._untraced(self.s1)
        before = ConsumableStock.objects.get(pk=self.s1.pk).average_unit_cost
        _run('--dry-run', '--force')
        _run('--force')
        out.refresh_from_db()
        self.assertEqual(out.unit_price, D('50.00'))
        self.assertEqual(ConsumableStock.objects.get(pk=self.s1.pk).average_unit_cost, before)

    def test_untraced_but_nothing_to_fix_has_no_ignored_message(self):
        ConsumableStock.objects.filter(pk=self.s1.pk).update(quantity=D('10.000'), average_unit_cost=D('0.0000'))
        text = _run('--apply')
        self.assertNotIn('IGNORÉ', text)

    def test_node_filter_respected_with_force(self):
        out1 = self._untraced(self.s1)
        out2 = self._untraced(self.s2)
        _run('--apply', '--force', '--node', 'K1')
        out1.refresh_from_db(); out2.refresh_from_db()
        self.assertEqual(out1.unit_price, D('0.00'))
        self.assertEqual(out2.unit_price, D('50.00'))

    def test_simulation_summary_counts_untraced_as_to_correct_but_apply_does_not(self):
        """Cohérence de l'affichage : la simulation annonce un stock « à corriger » que
        --apply ignorera (voir rapport : incohérence mineure, sans conséquence sur les données)."""
        self._untraced(self.s1)
        sim = _run()
        self.assertIn('1 à corriger', sim)


# --------------------------------------------------------------------------
# BUG-508 / loss : rapport de clôture
# --------------------------------------------------------------------------
class Bug508CounterTests(R._ReportBase):
    def test_rg_soldee_with_price_150_stable_after_tariff_change(self):
        """150 FC -> prix figé 113 (112,5 arrondi) ; 113/0,75 = 150,67 -> 151 si le tarif a changé."""
        bp = make_bread_price('VR_150', 'Pain 150 VR', 150)
        with R._now(10):
            self._session('A', R.J, [(bp, 50)])
            self._inv([(bp, 10)], code='RG', soldee=True)
            before = self._cat(self._report(R.J), bp)['regularisation']['fc']
            bp.unit_price = 400
            bp.save()
            after = self._cat(self._report(R.J), bp)['regularisation']['fc']
        self.assertEqual(before, '1500.00')
        self.assertEqual(after, before)

    def test_rg_soldee_with_price_50_stable_after_tariff_change(self):
        bp = make_bread_price('VR_50', 'Pain 50 VR', 50)
        with R._now(10):
            self._session('A', R.J, [(bp, 50)])
            self._inv([(bp, 10)], code='RG', soldee=True)
            before = self._cat(self._report(R.J), bp)['regularisation']['fc']
            bp.unit_price = 200
            bp.save()
            after = self._cat(self._report(R.J), bp)['regularisation']['fc']
        self.assertEqual(before, '500.00')
        self.assertEqual(after, before)

    def test_rg_soldee_multiple_tariff_changes_300_stable(self):
        with R._now(10):
            self._session('A', R.J, [(self.bp300, 50)])
            self._inv([(self.bp300, 7)], code='RG', soldee=True)
            vals = []
            for price in (300, 500, 100, 1000, 300):
                self.bp300.unit_price = price
                self.bp300.save()
                vals.append(self._cat(self._report(R.J), self.bp300)['regularisation']['fc'])
        self.assertEqual(set(vals), {'2100.00'}, vals)

    def test_rg_soldee_without_tariff_change_is_full_price_and_plain_rg_unchanged(self):
        with R._now(10):
            self._session('A', R.J, [(self.bp500, 50)])
            self._inv([(self.bp500, 4)], code='RG', soldee=True)
            self._inv([(self.bp500, 2)], code='RG')
            fc = self._cat(self._report(R.J), self.bp500)['regularisation']['fc']
        self.assertEqual(fc, '3000.00')

    def test_soldee_loss_of_past_day_stable_after_tariff_change(self):
        """Vente soldée 10 x 300 : prix figé 225, perte 750. Après passage du tarif à 400,
        `InvoiceLine.loss` relit le catalogue : perte = (400-225) x 10 = 1750."""
        with R._now(10):
            self._session('A', R.J, [(self.bp300, 50)])
            self._inv([(self.bp300, 10)], soldee=True)
            before = self._cat(self._report(R.J), self.bp300)['vente_cash_soldee']['perte_fc']
            self.bp300.unit_price = 400
            self.bp300.save()
            after = self._cat(self._report(R.J), self.bp300)['vente_cash_soldee']['perte_fc']
        self.assertEqual(before, '750.00')
        self.assertEqual(after, before)


# --------------------------------------------------------------------------
# BUG-509
# --------------------------------------------------------------------------
class Bug509CounterTests(R._Base):
    def _snap(self, bp, qty, team='A', d=R.J, h=20):
        with R._now(h, 0, d=d):
            DailyBreadStockSnapshot.objects.create(node=self.node, bread_price=bp, date=d, team=team,
                                                   qty_at_close=qty)

    def _open(self, qty, bp=None, **extra):
        r = self.g.post(R.OPENING, {**extra, 'lines': [{'bread_price': (bp or self.bp500).pk, 'qty': qty}]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)

    def _hier(self, bp=None):
        bp = bp or self.bp500
        rep = self.g.get(R.CLOSURE, {'date': str(R.J1)})
        self.assertEqual(rep.status_code, 200, rep.data)
        return sum(self._row(rep, bp)['reste_du_hier'].values())

    def test_three_successive_confirmations_last_wins(self):
        self._rotation()
        self._snap(self.bp500, 10)
        with R._now(13, 0, d=R.J1):
            self._assign('B'); self._open(8)
            self._assign('A'); self._open(9)
            self._assign('B'); self._open(6)
            hier = self._hier()
        self.assertEqual(hier, -6)

    def test_flip_back_without_reconfirmation_keeps_first_confirmation(self):
        self._rotation()
        self._snap(self.bp500, 10)
        with R._now(13, 0, d=R.J1):
            self._assign('B'); self._open(8)
            self._assign('A'); self._assign('B')
            hier = self._hier()
        self.assertEqual(hier, -8)

    def test_two_categories_confirmed_separately_each_last_wins(self):
        self._rotation()
        self._snap(self.bp500, 10)
        self._snap(self.bp300, 20)
        with R._now(13, 0, d=R.J1):
            self._assign('B')
            self._open(8, self.bp500)
            self._open(15, self.bp300)
            self._assign('A')
            self._open(9, self.bp500)
            h500 = self._hier(self.bp500)
            h300 = self._hier(self.bp300)
        self.assertEqual((h500, h300), (-9, -15))

    def test_confirmation_equal_to_snapshot_no_adjustment(self):
        self._rotation()
        self._snap(self.bp500, 10)
        with R._now(13, 0, d=R.J1):
            self._assign('B'); self._open(10)
            self._assign('A'); self._open(10)
            hier = self._hier()
        self.assertEqual(hier, -10)

    def test_closure_report_twice_is_idempotent(self):
        self._rotation()
        self._snap(self.bp500, 10)
        with R._now(13, 0, d=R.J1):
            self._assign('B'); self._open(8)
            self._assign('A'); self._open(9)
            a = self._hier()
            b = self._hier()
        self.assertEqual((a, b), (-9, -9))

    def test_no_rotation_unaffected_by_confirmation(self):
        self._snap(self.bp500, 10)
        with R._now(13, 0, d=R.J1):
            self._open(7, team='A')
            hier = self._hier()
        self.assertEqual(hier, -7)


# --------------------------------------------------------------------------
# BUG-510
# --------------------------------------------------------------------------
class Bug510CounterTests(R._Base):
    def setUp(self):
        super().setUp()
        self.g = APIClient(raise_request_exception=False)
        self.g.force_authenticate(self.gerant)

    def _sid(self):
        with R._now(13):
            r = self._produce(self.bp500, 10, team='A', date='2026-11-12')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data['id']

    def _close(self, sid, remaining):
        with R._now(13):
            return self.g.post(f'{R.SESSIONS}{sid}/close/', {'remaining': remaining}, format='json')

    def test_invalid_ids_all_400_with_detail_and_session_stays_open(self):
        sid = self._sid()
        bad_ids = ['abc', '', ' ', '1.5', 1.5, -1, '-3', 0, '0', 2 ** 63, 2 ** 70, '9' * 40, '9' * 5000,
                   True, False, [1], {'a': 1}, '1e3', 'NaN', None, '١٢٣abc', '0x10', '1; DROP TABLE']
        for b in bad_ids:
            r = self._close(sid, [{'bread_price': b, 'quantity': 1}])
            self.assertEqual(r.status_code, 400, (b if not isinstance(b, str) else b[:20], r.status_code))
            self.assertIn('detail', r.data)
        self.assertFalse(ProductionSession.objects.get(pk=sid).is_closed)

    def test_unknown_but_wellformed_id_is_400_not_found(self):
        sid = self._sid()
        r = self._close(sid, [{'bread_price': 999999, 'quantity': 1}])
        self.assertEqual(r.status_code, 400)
        self.assertIn('introuvable', r.data['detail'])

    def test_valid_int_and_numeric_string_ids_still_close(self):
        sid = self._sid()
        r = self._close(sid, [{'bread_price': str(self.bp500.pk), 'quantity': 3}])
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(ProductionSession.objects.get(pk=sid).is_closed)

    def test_valid_int_id_closes_and_mixed_list_with_one_bad_entry_rejected_atomically(self):
        sid = self._sid()
        r = self._close(sid, [{'bread_price': self.bp500.pk, 'quantity': 3},
                              {'bread_price': 'abc', 'quantity': 1}])
        self.assertEqual(r.status_code, 400)
        self.assertFalse(ProductionSession.objects.get(pk=sid).is_closed)
        r = self._close(sid, [{'bread_price': self.bp500.pk, 'quantity': 3}])
        self.assertEqual(r.status_code, 200, r.data)

    def test_other_validation_paths_unchanged(self):
        sid = self._sid()
        cases = [
            ([{'bread_price': self.bp500.pk, 'quantity': -1}], 'négative'),
            ([{'bread_price': self.bp500.pk, 'quantity': 'x'}], 'invalide'),
            ([{'quantity': 1}], 'requise'),
            ('x', 'liste'),
        ]
        for body, word in cases:
            r = self._close(sid, body)
            self.assertEqual(r.status_code, 400, body)
            self.assertIn(word, r.data['detail'])
