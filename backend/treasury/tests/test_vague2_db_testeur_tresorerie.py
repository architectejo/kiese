"""
Vague 2 « base réelle » — testeur-tresorerie, 2026-11-12.

Complète la vague 1 sur ce qu'elle n'avait pas couvert (la base réelle ne
pouvant pas être altérée, ces scénarios sont rejoués ici sur la base de test) :
altération directe du Livre de Caisse (30 écritures), bordereaux de décaissement,
blocage de clôture par transfert en litige, fenêtre minuit-01:00, ventilation
des billets (écarts positif / négatif / nul) et cohérence des deux endpoints
d'intégrité. Données entièrement fictives.
"""
import unittest
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from blockchain.models import TamperAlert
from core.models import Config, ExpenseCategory
from core.testing import make_node, make_user, make_bread_price, make_client
from production.models import BreadTransfer, BreadTransferLine
from sales.models import Invoice
from treasury.models import CashClosure, CashbookEntry, DisbursementVoucher, FacturierReport
from treasury.tests.test_vague1_db_testeur_tresorerie import _api, _deliver
from treasury.views import append_cashbook_entry


def _append(node, n, exit_amount=None, label=None):
    return append_cashbook_entry(
        node=node, date=date(2026, 11, 1 + (n % 28)),
        piece_number=f'VC-{node.code}-2026110{n % 10}-{n}', imputation='7000',
        label=label or f'ZZ ecriture {n}',
        entry_amount=Decimal('0') if exit_amount else Decimal(1000 + n),
        exit_amount=Decimal(exit_amount) if exit_amount else Decimal('0'),
        node_origin=node.code,
    )


def _verdicts(hq):
    api = _api(hq)
    integ = api.get('/api/treasury/cashbook/integrity_check/').json()
    run = api.post('/api/blockchain/snapshots/run_check/', {}, format='json').json()
    return integ, run


class ChainTamperTests(TestCase):
    """Intégrité : 30 écritures valides puis altérations directes en base."""

    def setUp(self):
        self.nodes = [make_node(code=c, name=c) for c in ('K1', 'K2', 'K3')]
        self.hq = make_user('DIRECTION', username='d_v2')
        self.entries = [_append(self.nodes[i % 3], i + 1) for i in range(30)]

    def test_chain_valid_after_30_entries_and_endpoints_agree(self):
        integ, run = _verdicts(self.hq)
        self.assertEqual(integ['total_entries'], 30)
        self.assertTrue(integ['chain_valid'])
        self.assertTrue(run['all_intact'])
        self.assertEqual(sum(r['total_entries'] for r in run['results']), 30)
        # solde progressif = cumul des entrées
        last = CashbookEntry.chain_queryset().last()
        self.assertEqual(last.running_balance, sum(e.entry_amount for e in CashbookEntry.objects.all()))

    def _assert_tamper_detected(self, entry_pk, label):
        integ, run = _verdicts(self.hq)
        self.assertFalse(integ['chain_valid'], label)
        self.assertIn(str(entry_pk), integ['tampered_ids'], label)
        self.assertFalse(run['all_intact'], label)
        self.assertEqual(integ['tampered_count'], sum(r['tampered_count'] for r in run['results']), label)
        gs = _api(self.hq).get('/api/blockchain/snapshots/global_status/').json()
        self.assertFalse(gs['all_intact'], label)
        self.assertTrue(TamperAlert.objects.exists(), label)

    def test_direct_amount_tamper_detected_by_both_endpoints(self):
        target = self.entries[14]
        CashbookEntry.objects.filter(pk=target.pk).update(entry_amount=Decimal('999999'))
        self._assert_tamper_detected(target.pk, 'entry_amount')

    def test_direct_running_balance_tamper_detected(self):
        target = self.entries[20]
        CashbookEntry.objects.filter(pk=target.pk).update(running_balance=Decimal('1'))
        self._assert_tamper_detected(target.pk, 'running_balance')

    def test_direct_node_and_imputation_tamper_detected(self):
        t1, t2 = self.entries[3], self.entries[9]
        other = next(n for n in self.nodes if n.pk != t1.node_id)
        CashbookEntry.objects.filter(pk=t1.pk).update(node=other)
        self._assert_tamper_detected(t1.pk, 'node')
        CashbookEntry.objects.filter(pk=t2.pk).update(imputation='XXXX')
        integ, _ = _verdicts(self.hq)
        self.assertIn(str(t2.pk), integ['tampered_ids'])

    def test_direct_label_date_piece_tamper_detected(self):
        for i, field, value in ((5, 'label', 'falsifie'), (6, 'piece_number', 'VC-XX-0'), (7, 'date', date(2020, 1, 1))):
            CashbookEntry.objects.filter(pk=self.entries[i].pk).update(**{field: value})
            integ, _ = _verdicts(self.hq)
            self.assertIn(str(self.entries[i].pk), integ['tampered_ids'], field)

    def test_direct_is_correction_flag_tamper_detected(self):
        target = self.entries[11]
        CashbookEntry.objects.filter(pk=target.pk).update(is_correction=True)
        self._assert_tamper_detected(target.pk, 'is_correction')

    def test_direct_previous_hash_tamper_detected(self):
        target = self.entries[12]
        CashbookEntry.objects.filter(pk=target.pk).update(previous_hash='a' * 64)
        self._assert_tamper_detected(target.pk, 'previous_hash')

    def test_chain_seq_swap_detected(self):
        a, b = self.entries[4], self.entries[5]
        sa, sb = a.chain_seq, b.chain_seq  # chain_seq est UNIQUE : échange en 3 temps
        CashbookEntry.objects.filter(pk=a.pk).update(chain_seq=99999)
        CashbookEntry.objects.filter(pk=b.pk).update(chain_seq=sa)
        CashbookEntry.objects.filter(pk=a.pk).update(chain_seq=sb)
        integ, run = _verdicts(self.hq)
        self.assertFalse(integ['chain_valid'])
        self.assertFalse(run['all_intact'])

    def test_deleting_a_middle_entry_is_detected(self):
        CashbookEntry.objects.filter(pk=self.entries[10].pk).delete()
        integ, run = _verdicts(self.hq)
        self.assertFalse(integ['chain_valid'])
        self.assertFalse(run['all_intact'])

    def test_deleting_last_entry_is_detected(self):
        """Suppression directe de la DERNIÈRE écriture : la chaîne restante
        reste cohérente, mais le Livre a été amputé (CLAUDE.md §5.5 : altération
        directe en base détectée). Un instantané antérieur (BlockchainSnapshot)
        connaît pourtant le nombre d'écritures."""
        _verdicts(self.hq)  # instantané à 30 écritures
        CashbookEntry.objects.filter(pk=self.entries[-1].pk).delete()
        integ, run = _verdicts(self.hq)
        self.assertFalse(integ['chain_valid'] and run['all_intact'],
                         "amputation de la dernière écriture non détectée")


class VoucherTests(TestCase):
    """Bons / bordereaux de décaissement : effet sur le solde."""

    def setUp(self):
        self.k3 = make_node(code='K3', name='ATHENEE')
        self.siege, _ = type(self.k3).objects.get_or_create(code='SIEGE', defaults={'name': 'SIEGE'})
        self.hq = make_user('COMPTABLE', username='c_v2')
        self.dir = make_user('DIRECTION', username='d2_v2')
        self.gerant = make_user('GERANT', node=self.k3, username='g_v2')
        _append(self.k3, 1)  # solde 1001
        append_cashbook_entry(node=self.k3, date=date(2026, 11, 2), piece_number='VC-K3-X', imputation='7000',
                              label='ZZ', entry_amount=Decimal('19000'), exit_amount=Decimal('0'), node_origin='K3')
        # solde = 20 001

    def _post(self, user, **payload):
        data = {'date': '2026-11-10', 'motif': 'ZZTEST', 'beneficiary': 'ZZ'}
        data.update(payload)
        return _api(user).post('/api/treasury/vouchers/', data, format='json')

    def test_voucher_reduces_balance_and_chain_stays_valid(self):
        r = self._post(self.hq, bills_10000=1, bills_5000=1, bills_500=1)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Decimal(r.json()['physical_cash_total']), Decimal('15500'))
        last = CashbookEntry.chain_queryset().last()
        self.assertEqual(last.exit_amount, Decimal('15500.00'))
        self.assertEqual(last.running_balance, Decimal('20001.00') - Decimal('15500.00'))
        self.assertTrue(last.piece_number.startswith('BV-20261110-'))
        integ, run = _verdicts(self.dir)
        self.assertTrue(integ['chain_valid'])
        self.assertTrue(run['all_intact'])
        fr = _api(self.hq).get('/api/treasury/vouchers/final_report/').json()
        self.assertEqual(Decimal(fr['total_disbursed']), Decimal('15500'))
        self.assertEqual(Decimal(fr['remaining_balance']), Decimal('4501'))

    def test_voucher_above_balance_refused_and_nothing_written(self):
        n = CashbookEntry.objects.count()
        r = self._post(self.hq, bills_20000=2)  # 40 000 > 20 001
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(CashbookEntry.objects.count(), n)
        self.assertEqual(DisbursementVoucher.objects.count(), 0)

    def test_voucher_exact_balance_allowed_then_nothing_left(self):
        r = self._post(self.hq, bills_20000=1, bills_1000=0, bills_100=10)  # 21 000 > 20 001 : refus
        self.assertEqual(r.status_code, 400, r.content)
        r = self._post(self.hq, bills_10000=2)  # 20 000 <= 20 001
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(CashbookEntry.chain_queryset().last().running_balance, Decimal('1.00'))
        self.assertEqual(self._post(self.hq, bills_50=1).status_code, 400)  # 50 > solde 1

    def test_voucher_oversized_bills_400(self):
        r = self._post(self.hq, bills_10000=99999999999)
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(DisbursementVoucher.objects.count(), 0)

    def test_voucher_forbidden_for_gerant(self):
        self.assertEqual(self._post(self.gerant, bills_50=1).status_code, 403)
        self.assertEqual(_api(self.gerant).get('/api/treasury/vouchers/').status_code, 403)

    def test_voucher_with_no_bills_is_refused_or_zero(self):
        """Un bordereau à 0 FC ne doit pas créer d'écriture de sortie nulle."""
        n = CashbookEntry.objects.count()
        r = self._post(self.hq)
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(CashbookEntry.objects.count(), n)


class DisputedTransferBlocksClosureTests(TestCase):
    def setUp(self):
        cfg = Config.get_instance()
        cfg.allow_backdated_sales = True
        cfg.save()
        self.k3 = make_node(code='K3', name='ATHENEE')
        self.k2 = make_node(code='K2', name='COQ')
        self.gerant = make_user('GERANT', node=self.k3, username='g_k3_tr')
        self.g2 = make_user('GERANT', node=self.k2, username='g_k2_tr')
        self.comptable = make_user('COMPTABLE', username='c_tr')
        self.bp = make_bread_price(category='MINI', label='Pain 200 FC', unit_price=200)
        self.closure = CashClosure.objects.create(node=self.k3, gerant=self.gerant, date=date(2026, 11, 8),
                                                  total_entries=Decimal('100'), net_cash=Decimal('100'), is_validated=True)
        self.tr = BreadTransfer.objects.create(from_node=self.k2, to_node=self.k3, initiated_by=self.gerant,
                                               transfer_status=BreadTransfer.TransferStatus.DISPUTED)
        self.line = BreadTransferLine.objects.create(transfer=self.tr, bread_price=self.bp, quantity_sent=10, quantity_received=8)

    def test_closure_creation_blocked_with_message(self):
        r = _api(self.gerant).post('/api/treasury/closures/', {'date': '2026-11-09'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('écart', r.json()['detail'])
        self.assertFalse(CashClosure.objects.filter(date=date(2026, 11, 9)).exists())

    def test_push_to_cashbook_blocked_too(self):
        r = _api(self.comptable).post(f'/api/treasury/closures/{self.closure.id}/push_to_cashbook/')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(CashbookEntry.objects.count(), 0)

    def test_other_bakery_not_blocked(self):
        k4 = make_node(code='K4', name='LOMA')
        g4 = make_user('GERANT', node=k4, username='g_k4_tr')
        r = _api(g4).post('/api/treasury/closures/', {'date': '2026-11-09'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)

    def test_resolution_by_emitter_lifts_block(self):
        r = _api(self.g2).post(f'/api/production/transfers/{self.tr.id}/resolve_dispute/',
                               {'resolution': 'ALIGN_ON_RECEIVED', 'reason': 'ZZ recompte'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        r = _api(self.gerant).post('/api/treasury/closures/', {'date': '2026-11-09'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(_api(self.comptable).post(
            f'/api/treasury/closures/{self.closure.id}/push_to_cashbook/').status_code, 201)

    def test_validate_blocked_then_passes_once_resolved(self):
        """BUG-277 : la confirmation par le comptable est aussi bloquée."""
        pending = CashClosure.objects.create(node=self.k3, gerant=self.gerant, date=date(2026, 11, 7),
                                             total_entries=Decimal('100'), net_cash=Decimal('100'))
        url = f'/api/treasury/closures/{pending.id}/validate/'
        r = _api(self.comptable).post(url)
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('écart', r.json()['detail'])
        pending.refresh_from_db()
        self.assertFalse(pending.is_validated)
        r = _api(self.g2).post(f'/api/production/transfers/{self.tr.id}/resolve_dispute/',
                               {'resolution': 'ALIGN_ON_RECEIVED', 'reason': 'ZZ recompte'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(_api(self.comptable).post(url).status_code, 200)

    def test_cancelled_transfer_does_not_block(self):
        self.tr.transfer_status = BreadTransfer.TransferStatus.CANCELLED
        self.tr.save()
        self.assertEqual(_api(self.gerant).post('/api/treasury/closures/', {'date': '2026-11-09'}, format='json').status_code, 201)


class MidnightWindowTests(TestCase):
    """Entre 00:00 et 01:00 (Africa/Kinshasa = UTC+1) la date UTC est celle de la veille."""

    NOW_UTC = datetime(2026, 11, 12, 23, 30, tzinfo=dt_timezone.utc)  # = 2026-11-13 00:30 local

    def _setup(self, rotation):
        cfg = Config.get_instance()
        cfg.allow_backdated_sales = True
        cfg.save()
        node = make_node(code='K3', name='ATHENEE')
        node.team_rotation_enabled = rotation
        node.save()
        gerant = make_user('GERANT', node=node, username=f'g_mid_{int(rotation)}')
        fac = make_user('FACTURIER', node=node, team='A', username=f'f_mid_{int(rotation)}')
        bp = make_bread_price(category='MINI', label='Pain 200 FC', unit_price=200)
        with mock.patch('django.utils.timezone.now', return_value=self.NOW_UTC):
            _deliver(node, fac, 'A', make_client(node), bp, 5, Invoice.PaymentType.CASH)
            r = _api(gerant).post('/api/treasury/reports/generate/', {}, format='json')
        return node, gerant, r

    def test_no_rotation_report_dated_local_day(self):
        node, gerant, r = self._setup(False)
        self.assertEqual(r.status_code, 200, r.content)
        reps = r.json()
        self.assertTrue(reps, r.content)
        self.assertEqual(reps[0]['date'], '2026-11-13')
        self.assertEqual(Decimal(reps[0]['total_cash_sales']), Decimal('1000'))

    def test_rotation_report_is_dated_calendar_day(self):  # décision client 2026-11-12 : date de travail = jour calendaire local, rotation ou non
        node, gerant, r = self._setup(True)
        self.assertEqual(r.status_code, 200, r.content)
        reps = r.json()
        self.assertTrue(reps, r.content)
        self.assertEqual(reps[0]['date'], '2026-11-13')
        self.assertEqual(Decimal(reps[0]['total_cash_sales']), Decimal('1000'))

    def test_closure_of_calendar_day_has_same_cash(self):
        node, gerant, r = self._setup(True)
        with mock.patch('django.utils.timezone.now', return_value=self.NOW_UTC):
            r = _api(gerant).post('/api/treasury/closures/', {'date': '2026-11-13'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Decimal(r.json()['total_entries']), Decimal('1000'))


class BillsBreakdownTests(TestCase):
    """Ventilation 20 000 -> 50 FC : total = somme quantité x valeur ; écart + / - / 0."""

    VALUES = {'bills_20000': 20000, 'bills_10000': 10000, 'bills_5000': 5000, 'bills_1000': 1000,
              'bills_500': 500, 'bills_200': 200, 'bills_100': 100, 'bills_50': 50}

    def setUp(self):
        self.node = make_node(code='K3', name='ATHENEE')
        self.gerant = make_user('GERANT', node=self.node, username='g_bills_v2')
        self.fac = make_user('FACTURIER', node=self.node, team='A', username='f_bills_v2')
        _deliver(self.node, self.fac, 'A', make_client(self.node),
                 make_bread_price(category='GRAND', label='Pain 500 FC', unit_price=500), 41, Invoice.PaymentType.CASH)
        _api(self.gerant).post('/api/treasury/reports/generate/', {}, format='json')  # 20 500 FC
        self.date = str(date.today())

    def _close(self, bills, d=None):
        return _api(self.gerant).post('/api/treasury/closures/', dict(date=d or self.date, **bills), format='json')

    def test_all_denominations_total_and_gap_zero(self):
        bills = dict(bills_20000=1, bills_10000=0, bills_5000=0, bills_1000=0, bills_500=1, bills_200=0, bills_100=0, bills_50=0)
        r = self._close(bills)
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(Decimal(body['net_cash']), Decimal('20500'))
        self.assertEqual(Decimal(body['physical_cash_total']), Decimal('20500'))
        self.assertEqual(Decimal(body['cash_gap']), Decimal('0'))

    def test_every_denomination_counts_once_and_negative_gap(self):
        bills = {k: 1 for k in self.VALUES}  # 37 850
        total = sum(self.VALUES.values())
        r = self._close(bills)
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(Decimal(body['physical_cash_total']), Decimal(total))
        self.assertEqual(Decimal(body['cash_gap']), Decimal(total) - Decimal('20500'))  # positif (surplus)

    def test_negative_gap_shortage(self):
        r = self._close(dict(bills_10000=1, bills_5000=1, bills_1000=2, bills_500=1))  # 17 500
        body = r.json()
        self.assertEqual(Decimal(body['cash_gap']), Decimal('-3000'))
        self.assertEqual(Decimal(body['physical_cash_total']), Decimal('17500'))

    def test_gap_is_not_editable_by_api(self):
        r = self._close(dict(bills_10000=1))
        cid = r.json()['id']
        _api(self.gerant).patch(f'/api/treasury/closures/{cid}/', {'cash_gap': '0', 'physical_cash_total': '20500',
                                                                     'net_cash': '1', 'is_validated': True}, format='json')
        c = CashClosure.objects.get(pk=cid)
        self.assertEqual(c.cash_gap, Decimal('-10500.00'))
        self.assertEqual(c.net_cash, Decimal('20500.00'))
        self.assertFalse(c.is_validated)

    def test_max_bills_per_denomination_total_fits(self):
        r = self._close({k: 100000 for k in self.VALUES})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Decimal(r.json()['physical_cash_total']), Decimal(sum(self.VALUES.values()) * 100000))


class SavingsMonthlyTotalDecimalTests(TestCase):
    """Règle « argent = Decimal » : pas de flottant JSON dans `monthly_total`."""

    def test_by_node_amounts_are_decimal_strings(self):
        from treasury.models import DailySavings
        node = make_node(code='K3', name='ATHENEE')
        gerant = make_user('GERANT', node=node, username='g_sav_v2')
        DailySavings.objects.create(node=node, date=date(2026, 11, 8), flour_sacks=Decimal('1'),
                                    daily_revenue=Decimal('20400'), savings_rate=Decimal('0.1'),
                                    savings_amount=Decimal('2040'))
        body = _api(gerant).get('/api/treasury/savings/monthly_total/', {'month': 11, 'year': 2026}).json()
        row = body['by_node'][0]
        self.assertIsInstance(row['total_savings'], str, row)
        self.assertIsInstance(row['total_revenue'], str, row)
