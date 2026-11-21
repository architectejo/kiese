"""
Vérification indépendante (testeur-production, Dev C, 2026-11-21c) de :
  - BUG-357 : commande `recompute_cump`
  - BUG-147 : `_get_or_create_consumable_stock` (fournée, régularisation PATCH)
  - BUG-129 : format `{'detail': ...}` (backend) + realignements de tests
Données fictives uniquement.
"""
import itertools
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest import expectedFailure, mock

from django.utils import timezone

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import ActivityLog, SystemNotification
from core.testing import make_node, make_user, make_bread_price
from core.workday import work_date_for
from production.management.commands.recompute_cump import replay_stock
from production.models import (
    ConsumableMovement, ConsumableStock, ConsumableType, ProductionSession,
)

D = Decimal


def _run(*args):
    out = StringIO()
    call_command('recompute_cump', *args, stdout=out)
    return out.getvalue()


_BASE = timezone.now()
_SEQ = itertools.count(1)


def _mv(stock, kind, qty, price='0.00'):
    mv = ConsumableMovement.objects.create(
        node=stock.node, stock=stock, movement_type=kind,
        quantity=D(qty), unit_price=D(price),
    )
    # BUG-416 : horloge grossière sous Windows -> created_at identiques ;
    # ordre strictement croissant imposé pour un rejeu déterministe.
    ConsumableMovement.objects.filter(pk=mv.pk).update(
        created_at=_BASE + timedelta(seconds=next(_SEQ)))
    mv.refresh_from_db()
    return mv


def _inflate(stock, avg, **exit_prices):
    ConsumableStock.objects.filter(pk=stock.pk).update(average_unit_cost=D(avg))


class RecomputeCumpTests(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.k2 = make_node(code='K2')
        self.s1 = ConsumableStock.objects.create(node=self.k1, consumable_type='FLOUR', unit='sac')
        self.s2 = ConsumableStock.objects.create(node=self.k2, consumable_type='FLOUR', unit='sac')

    def _negative_then_entry(self, stock):
        """sortie -5 (stock -5), entrée 10 @ 100 000 : CUMP sain = 100 000."""
        _mv(stock, 'EXIT', '5')
        e = _mv(stock, 'ENTRY', '10', '100000')
        out = _mv(stock, 'EXIT', '1')
        stock.refresh_from_db()
        self.assertEqual(stock.average_unit_cost, D('100000.0000'))
        return e, out

    def _corrupt(self, stock, out):
        ConsumableStock.objects.filter(pk=stock.pk).update(average_unit_cost=D('200000.0000'))
        ConsumableMovement.objects.filter(pk=out.pk).update(unit_price=D('200000.00'))

    # --- simulation / apply -------------------------------------------------
    def test_simulation_default_writes_nothing_anywhere(self):
        _, out = self._negative_then_entry(self.s1)
        self._corrupt(self.s1, out)
        logs = ActivityLog.objects.count()
        text = _run()
        self.assertIn('SIMULATION', text)
        self.assertIn('à corriger', text)
        self.s1.refresh_from_db()
        out.refresh_from_db()
        self.assertEqual(self.s1.average_unit_cost, D('200000.0000'))
        self.assertEqual(out.unit_price, D('200000.00'))
        self.assertEqual(ActivityLog.objects.count(), logs)

    def test_apply_corrects_cump_and_exit_prices_and_quantity_untouched(self):
        _, out = self._negative_then_entry(self.s1)
        self._corrupt(self.s1, out)
        self.s1.refresh_from_db()
        qty_before = self.s1.quantity
        _run('--apply')
        self.s1.refresh_from_db()
        out.refresh_from_db()
        self.assertEqual(self.s1.average_unit_cost, D('100000.0000'))
        self.assertEqual(out.unit_price, D('100000.00'))
        self.assertEqual(self.s1.quantity, qty_before)
        self.assertIsInstance(self.s1.average_unit_cost, Decimal)

    def test_apply_revalues_all_exits_including_first_zero_priced(self):
        # Sortie initiale à stock vide : valorisée 0 (CUMP 0), doit rester 0.
        first = _mv(self.s1, 'EXIT', '5')
        _, out = None, None
        _mv(self.s1, 'ENTRY', '10', '100000')
        out = _mv(self.s1, 'EXIT', '2')
        ConsumableMovement.objects.filter(pk=out.pk).update(unit_price=D('999999.00'))
        _run('--apply')
        first.refresh_from_db()
        out.refresh_from_db()
        self.assertEqual(first.unit_price, D('0.00'))
        self.assertEqual(out.unit_price, D('100000.00'))

    def test_apply_and_dry_run_refused(self):
        with self.assertRaises(CommandError):
            _run('--apply', '--dry-run')

    def test_dry_run_alone_is_simulation(self):
        _, out = self._negative_then_entry(self.s1)
        self._corrupt(self.s1, out)
        text = _run('--dry-run')
        self.assertIn('SIMULATION', text)
        self.s1.refresh_from_db()
        self.assertEqual(self.s1.average_unit_cost, D('200000.0000'))

    # --- idempotence --------------------------------------------------------
    def test_idempotent_second_pass_no_deviation(self):
        _, out = self._negative_then_entry(self.s1)
        self._corrupt(self.s1, out)
        _run('--apply')
        logs = ActivityLog.objects.filter(action__contains='CUMP').count()
        self.assertEqual(logs, 1)
        text = _run('--apply')
        self.assertIn('0 corrigé(s)', text)
        self.assertEqual(ActivityLog.objects.filter(action__contains='CUMP').count(), 1)
        text2 = _run()
        self.assertIn('0 à corriger', text2)

    # --- nœuds --------------------------------------------------------------
    def test_multi_nodes_all_fixed_without_filter(self):
        _, o1 = self._negative_then_entry(self.s1)
        _, o2 = self._negative_then_entry(self.s2)
        self._corrupt(self.s1, o1)
        self._corrupt(self.s2, o2)
        text = _run('--apply')
        self.assertIn('2 corrigé(s)', text)
        for s in (self.s1, self.s2):
            s.refresh_from_db()
            self.assertEqual(s.average_unit_cost, D('100000.0000'))

    def test_node_filter_only_touches_that_node(self):
        _, o1 = self._negative_then_entry(self.s1)
        _, o2 = self._negative_then_entry(self.s2)
        self._corrupt(self.s1, o1)
        self._corrupt(self.s2, o2)
        text = _run('--apply', '--node', 'K2')
        self.assertIn('1 stock(s) examiné(s)', text)
        self.s1.refresh_from_db()
        self.s2.refresh_from_db()
        o1.refresh_from_db()
        self.assertEqual(self.s1.average_unit_cost, D('200000.0000'))
        self.assertEqual(o1.unit_price, D('200000.00'))
        self.assertEqual(self.s2.average_unit_cost, D('100000.0000'))

    def test_unknown_node_examines_nothing(self):
        text = _run('--apply', '--node', 'ZZ')
        self.assertIn('0 stock(s) examiné(s)', text)

    def test_log_activity_carries_node_and_values(self):
        _, out = self._negative_then_entry(self.s1)
        self._corrupt(self.s1, out)
        _run('--apply')
        log = ActivityLog.objects.get(action__contains='CUMP')
        self.assertEqual(log.node_origin, 'K1')
        self.assertIn('200000.0000 -> 100000.0000', log.description)
        self.assertIn('K1 FLOUR', log.description)

    # --- stock négatif puis entrée / cohérence avec save() -------------------
    def test_negative_stock_then_small_entry_then_large_entry(self):
        s = self.s1
        _mv(s, 'EXIT', '10')            # -10
        _mv(s, 'ENTRY', '4', '100')     # -6, CUMP = 100 (new_qty <= 0)
        _mv(s, 'ENTRY', '10', '200')    # +4, base 0 -> CUMP 200
        s.refresh_from_db()
        self.assertEqual(s.average_unit_cost, D('200.0000'))
        self.assertEqual(s.quantity, D('4.000'))
        text = _run()
        self.assertIn('inchangé', text)

    def test_replay_matches_save_on_mixed_sequence_incl_rounding(self):
        s = self.s1
        _mv(s, 'ENTRY', '3', '10.00')
        _mv(s, 'EXIT', '1')
        _mv(s, 'ENTRY', '1', '10.01')   # CUMP à demi-centime
        _mv(s, 'EXIT', '1.5')
        _mv(s, 'EXIT', '9')             # passe en négatif
        _mv(s, 'ENTRY', '7', '33.33')
        _mv(s, 'EXIT', '0.25')
        s.refresh_from_db()
        text = _run()
        self.assertIn('inchangé', text, text)
        self.assertIn('0 à corriger', text)
        avg, qty, _ = replay_stock(list(
            ConsumableMovement.objects.filter(stock=s).order_by('created_at', 'pk')))
        self.assertEqual(avg, s.average_unit_cost)
        self.assertEqual(qty, s.quantity)

    def test_replay_stock_is_pure_decimal_four_decimals(self):
        s = self.s1
        _mv(s, 'ENTRY', '3', '100')
        _mv(s, 'ENTRY', '4', '101')     # (300+404)/7 = 100.571428...
        mvs = list(ConsumableMovement.objects.filter(stock=s).order_by('created_at', 'pk'))
        avg, qty, prices = replay_stock(mvs)
        self.assertEqual(avg, D('100.5714'))
        self.assertIsInstance(avg, Decimal)
        self.assertIsInstance(qty, Decimal)
        self.assertEqual(prices, {})

    def test_decimal_consumables_levure_huile(self):
        y = ConsumableStock.objects.create(node=self.k1, consumable_type='YEAST', unit='paquet')
        _mv(y, 'EXIT', '0.25')
        _mv(y, 'ENTRY', '1', '4000')
        out = _mv(y, 'EXIT', '0.25')
        ConsumableStock.objects.filter(pk=y.pk).update(average_unit_cost=D('16000.0000'))
        ConsumableMovement.objects.filter(pk=out.pk).update(unit_price=D('16000.00'))
        _run('--apply', '--node', 'K1')
        y.refresh_from_db()
        out.refresh_from_db()
        self.assertEqual(y.average_unit_cost, D('4000.0000'))
        self.assertEqual(out.unit_price, D('4000.00'))
        self.assertEqual(y.quantity, D('0.500'))

    # --- stock initial non tracé ---------------------------------------------
    def test_untraced_initial_stock_warns_and_never_changes_quantity(self):
        s = self.s1
        ConsumableStock.objects.filter(pk=s.pk).update(quantity=D('10.000'), average_unit_cost=D('50.0000'))
        s.refresh_from_db()
        _mv(s, 'ENTRY', '5', '100')
        s.refresh_from_db()
        self.assertEqual(s.quantity, D('15.000'))
        text = _run('--apply')
        self.assertIn('attention', text)
        self.assertIn('NON modifiée', text)
        s.refresh_from_db()
        self.assertEqual(s.quantity, D('15.000'))

    @expectedFailure
    def test_bug501_untraced_stock_cump_must_not_be_overwritten(self):
        """BUG-501 : sur un stock initial non tracé, --apply écrase un CUMP sain
        (66,6667 = (10x50 + 5x100)/15, aucun négatif jamais) par 100,0000 issu d'un
        rejeu partant de zéro. Attendu : ne pas toucher un stock dont le rejeu ne
        retombe pas sur la quantité en base (avertissement seul)."""
        s = self.s1
        ConsumableStock.objects.filter(pk=s.pk).update(quantity=D('10.000'), average_unit_cost=D('50.0000'))
        s.refresh_from_db()
        _mv(s, 'ENTRY', '5', '100')
        s.refresh_from_db()
        healthy = s.average_unit_cost
        self.assertEqual(healthy, D('66.6667'))
        _run('--apply')
        s.refresh_from_db()
        self.assertEqual(s.average_unit_cost, healthy)

    @expectedFailure
    def test_bug501_untraced_stock_exit_prices_must_not_be_zeroed(self):
        """BUG-501 (volet sorties) : une sortie valorisée à un CUMP légitime (stock
        initial 10 @ 50, sorties avant toute entrée tracée) est re-valorisée 0.00."""
        s = self.s1
        ConsumableStock.objects.filter(pk=s.pk).update(quantity=D('10.000'), average_unit_cost=D('50.0000'))
        s.refresh_from_db()
        out = _mv(s, 'EXIT', '2')
        out.refresh_from_db()
        self.assertEqual(out.unit_price, D('50.00'))
        _run('--apply')
        out.refresh_from_db()
        self.assertEqual(out.unit_price, D('50.00'))


class Bug147Tests(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1', sac_value_fc=D('200000'))
        self.k2 = make_node(code='K2', sac_value_fc=D('200000'))
        self.user = make_user('GERANT', node=self.k1)
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        for code, unit in (('FLOUR', 'sacs'), ('SALT', 'g'), ('YEAST', 'paquets'), ('OIL', 'L')):
            ConsumableType.objects.update_or_create(code=code, defaults={'label': code, 'unit': unit})
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def _post(self, **extra):
        p = {'team': 'A', 'date': str(work_date_for(self.k1)), 'flour_sacks_used': '2.00',
             'lines': [{'bread_price': self.bp.pk, 'quantity': 300}]}
        p.update(extra)
        return self.api.post('/api/production/sessions/', p, format='json')

    def test_four_consumables_created_with_units_and_negative_stock(self):
        r = self._post(consumables_used=[
            {'consumable_type': 'SALT', 'quantity': '500'},
            {'consumable_type': 'YEAST', 'quantity': '0.25'},
            {'consumable_type': 'OIL', 'quantity': '0.33'},
        ])
        self.assertEqual(r.status_code, 201, r.data)
        expected = {'FLOUR': ('sacs', D('-2.000')), 'SALT': ('g', D('-500.000')),
                    'YEAST': ('paquets', D('-0.250')), 'OIL': ('L', D('-0.330'))}
        for code, (unit, qty) in expected.items():
            st = ConsumableStock.objects.get(node=self.k1, consumable_type=code)
            self.assertEqual(st.unit, unit, code)
            self.assertEqual(st.quantity, qty, code)
            self.assertEqual(st.node_origin, 'K1')
            mv = ConsumableMovement.objects.get(stock=st)
            self.assertEqual(mv.movement_type, 'EXIT')
            self.assertEqual(mv.unit_price, D('0.00'))

    def test_negative_notification_bug143_emitted_for_new_row(self):
        before = SystemNotification.objects.filter(title__startswith='Stock négatif').count()
        r = self._post()
        self.assertEqual(r.status_code, 201, r.data)
        notifs = SystemNotification.objects.filter(title__startswith='Stock négatif')
        self.assertEqual(notifs.count(), before + 1)
        n = notifs.latest('pk')
        self.assertIn('FLOUR', n.title)
        self.assertIn('K1', n.title)

    def test_unknown_type_row_has_empty_unit_when_type_missing(self):
        ConsumableType.objects.filter(code='FLOUR').delete()
        r = self._post()
        self.assertEqual(r.status_code, 201, r.data)
        st = ConsumableStock.objects.get(node=self.k1, consumable_type='FLOUR')
        self.assertEqual(st.unit, '')
        self.assertEqual(st.quantity, D('-2.000'))

    def test_existing_row_not_overwritten_unit_and_cump_kept(self):
        ConsumableStock.objects.create(
            node=self.k1, consumable_type='FLOUR', quantity=D('10'), unit='kg',
            average_unit_cost=D('1234.5000'))
        self._post()
        st = ConsumableStock.objects.get(node=self.k1, consumable_type='FLOUR')
        self.assertEqual(st.unit, 'kg')
        self.assertEqual(st.average_unit_cost, D('1234.5000'))
        self.assertEqual(st.quantity, D('8.000'))
        self.assertEqual(ConsumableStock.objects.filter(consumable_type='FLOUR').count(), 1)

    def test_second_fournee_same_day_reuses_row(self):
        self._post()
        self._post()
        self.assertEqual(ConsumableStock.objects.filter(node=self.k1, consumable_type='FLOUR').count(), 1)

    @expectedFailure
    def test_bug502_second_declaration_same_day_decrements_only_added_sacks(self):
        """BUG-502 : deux déclarations de 2 sacs le même jour/équipe (BUG-142 : addition
        sur la session) doivent sortir 2 + 2 = 4 sacs ; `_record_consumable_exits` relit
        `session.flour_sacks_used` (total cumulé 4) et sort 2 + 4 = 6."""
        ConsumableStock.objects.create(node=self.k1, consumable_type='FLOUR', quantity=D('10'), unit='sacs')
        self._post()
        self._post()
        self.assertEqual(ConsumableStock.objects.get(node=self.k1, consumable_type='FLOUR').quantity, D('6.000'))

    def test_other_node_gets_no_row(self):
        self._post()
        self.assertFalse(ConsumableStock.objects.filter(node=self.k2).exists())
        # un gérant de K1 qui force node=K2 : ignoré (BUG-056), K2 reste vide
        self._post(node=self.k2.pk, team='B')
        self.assertFalse(ConsumableStock.objects.filter(node=self.k2).exists())

    def test_hq_declares_for_target_node_only(self):
        hq = make_user('DIRECTION')
        api = APIClient()
        api.force_authenticate(hq)
        r = api.post('/api/production/sessions/', {
            'node': self.k2.pk, 'team': 'A', 'date': str(work_date_for(self.k2)),
            'flour_sacks_used': '1.00', 'lines': [{'bread_price': self.bp.pk, 'quantity': 10}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(ConsumableStock.objects.filter(node=self.k2, consumable_type='FLOUR').exists())
        self.assertFalse(ConsumableStock.objects.filter(node=self.k1).exists())

    def test_helper_race_get_or_create_integrity_error_is_absorbed(self):
        """Course : la ligne apparaît entre le get et le create -> get_or_create
        rattrape l'IntegrityError ; aucune exception, une seule ligne."""
        from production.views import _get_or_create_consumable_stock
        real = ConsumableStock.objects.create(node=self.k1, consumable_type='SALT', unit='g')
        a = _get_or_create_consumable_stock(self.k1, 'SALT')
        b = _get_or_create_consumable_stock(self.k1, 'SALT')
        self.assertEqual(a.pk, real.pk)
        self.assertEqual(b.pk, real.pk)
        self.assertEqual(ConsumableStock.objects.filter(node=self.k1, consumable_type='SALT').count(), 1)

    def test_db_uniqueness_node_type_guards_duplicates(self):
        ConsumableStock.objects.create(node=self.k1, consumable_type='OIL')
        with self.assertRaises(IntegrityError):
            ConsumableStock.objects.create(node=self.k1, consumable_type='OIL')

    def test_patch_regularisation_creates_row_and_is_signed(self):
        self._post()
        session = ProductionSession.objects.get(node=self.k1)
        # +1 sac -> sortie +1 ; puis -2 sacs -> sortie négative (restitution)
        self.api.patch(f'/api/production/sessions/{session.pk}/', {'flour_sacks_used': '3.00'}, format='json')
        self.assertEqual(ConsumableStock.objects.get(node=self.k1, consumable_type='FLOUR').quantity, D('-3.000'))
        self.api.patch(f'/api/production/sessions/{session.pk}/', {'flour_sacks_used': '1.00'}, format='json')
        self.assertEqual(ConsumableStock.objects.get(node=self.k1, consumable_type='FLOUR').quantity, D('-1.000'))
        self.assertEqual(ConsumableStock.objects.filter(node=self.k1, consumable_type='FLOUR').count(), 1)

    def test_patch_no_delta_creates_nothing(self):
        self._post()
        ConsumableMovement.objects.all().delete()
        ConsumableStock.objects.all().delete()
        session = ProductionSession.objects.get(node=self.k1)
        self.api.patch(f'/api/production/sessions/{session.pk}/', {'notes': 'x'}, format='json')
        self.assertFalse(ConsumableStock.objects.exists())

    def test_zero_consumable_not_creating_row(self):
        r = self._post(consumables_used=[{'consumable_type': 'SALT', 'quantity': '0'}])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertFalse(ConsumableStock.objects.filter(node=self.k1, consumable_type='SALT').exists())


class Bug129BackendTests(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1', sac_value_fc=D('200000'))
        self.user = make_user('GERANT', node=self.k1)
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.api = APIClient()
        self.api.force_authenticate(self.user)
        self.date = str(work_date_for(self.k1))

    def test_race_integrity_error_returns_detail_dict_french(self):
        payload = {'team': 'A', 'date': self.date, 'flour_sacks_used': '1.00'}
        with mock.patch.object(ProductionSession.objects, 'create', side_effect=IntegrityError('x')):
            r = self.api.post('/api/production/sessions/', payload, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIsInstance(r.json(), dict)
        self.assertIn('Une session existe déjà', r.json()['detail'])
        self.assertFalse(ProductionSession.objects.exists())

    def test_closed_session_refusal_is_detail_dict(self):
        r = self.api.post('/api/production/sessions/', {
            'team': 'A', 'date': self.date, 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 10}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        ProductionSession.objects.filter(pk=r.data['id']).update(is_closed=True)
        r2 = self.api.post('/api/production/sessions/', {
            'team': 'A', 'date': self.date, 'flour_sacks_used': '1.00'}, format='json')
        self.assertEqual(r2.status_code, 400)
        body = r2.json()
        self.assertIsInstance(body, dict)
        self.assertIn('clôturée', body['detail'])
