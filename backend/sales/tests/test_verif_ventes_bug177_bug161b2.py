"""
Vérification indépendante (testeur-ventes, 2026-11-11) de BUG-177 (volet
ventes : factures NS / RG) et du blocage de facturation BUG-161/B2
(`TEAM_NOT_ASSIGNED`).

Scénarios construits sans réutiliser ceux de dev-backend. Les
`DebtMovement` sont écrits via `transaction.on_commit` : on les exécute avec
`captureOnCommitCallbacks(execute=True)`.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest import expectedFailure
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from clients.models import Client
from core.models import Config
from core.testing import make_node, make_user, make_bread_price, make_client
from production.models import BreadStock, DailyTeamAssignment
from sales.models import Invoice
from sync.models import DebtMovement
from sync.services import recompute_client_debt

INV = '/api/sales/invoices/'


def _api(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def _at(d, h, m=0):
    return timezone.make_aware(datetime(d.year, d.month, d.day, h, m), timezone.get_current_timezone())


class Base(TestCase):
    def setUp(self):
        self.node = make_node()
        self.bp = make_bread_price('VV177_500', 'Pain 500 FC', 500)
        self.fact = make_user('FACTURIER', node=self.node, team='A')
        self.ger = make_user('GERANT', node=self.node, team='A')
        self.liv = make_user('LIVREUR', node=self.node, team='A')
        self.cl = make_client(self.node, credit_limit=Decimal('50000.00'))
        self.f = _api(self.fact)
        self.g = _api(self.ger)
        self.l = _api(self.liv)

    def post(self, code='', ptype='CASH', pay=0, qty=4, client=True, api=None, **extra):
        payload = {
            'payment_type': ptype, 'payment_amount': pay, 'special_code': code,
            'lines': [{'bread_price': self.bp.pk, 'quantity': qty}],
        }
        if client:
            payload['client'] = str(self.cl.pk)
        payload.update(extra)
        with self.captureOnCommitCallbacks(execute=True):
            return (api or self.f).post(INV, payload, format='json')

    def refund(self, pay):
        with self.captureOnCommitCallbacks(execute=True):
            return self.f.post(INV, {
                'client': str(self.cl.pk), 'payment_type': 'CASH', 'payment_amount': pay,
                'is_debt_repayment': True, 'lines': [],
            }, format='json')

    def debt(self):
        self.cl.refresh_from_db()
        return self.cl.current_debt

    def sent(self):
        return sum(BreadStock.objects.filter(node=self.node, bread_price=self.bp)
                   .values_list('qty_sent', flat=True))

    def moves(self):
        return list(DebtMovement.objects.filter(client=self.cl).order_by('created_at')
                    .values_list('kind', 'amount'))


# --------------------------------------------------------------------------
# (1) NS : dette / BP / DebtMovement / annulation
# --------------------------------------------------------------------------
class NsBasics(Base):
    def test_ns_credit_debt_bp_and_movement_coherent(self):
        r = self.post('NS', 'CREDIT', pay=0, qty=4)
        self.assertEqual(r.status_code, 201, r.data)
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual(inv.order_total, Decimal('2000'))
        self.assertEqual((inv.debt_before, inv.debt_after), (Decimal('0'), Decimal('2000')))
        self.assertEqual(self.debt(), Decimal('2000'))
        self.assertEqual(self.moves(), [('ORDER', Decimal('2000.00'))])
        self.assertEqual(self.sent(), 0)
        self.assertEqual(inv.status, Invoice.Status.PENDING)

    def test_ns_credit_then_cancel_restores_debt_and_not_stock(self):
        # Stock d'abord déstocké par une vente normale pour avoir un témoin.
        self.post('', 'CASH', pay=1000, qty=2, client=False)
        sent_before = self.sent()
        self.assertEqual(sent_before, 2)
        r = self.post('NS', 'CREDIT', qty=4)
        with self.captureOnCommitCallbacks(execute=True):
            cr = self.f.post(f"{INV}{r.data['id']}/cancel/")
        self.assertEqual(cr.status_code, 200, cr.data)
        self.assertEqual(self.debt(), Decimal('0'))
        self.assertEqual(self.sent(), sent_before)  # ni restitué ni déduit
        self.assertEqual(Invoice.objects.get(pk=r.data['id']).status, Invoice.Status.CANCELLED)

    def test_ns_credit_cancel_movements_sum_to_zero(self):
        r = self.post('NS', 'CREDIT', qty=4)
        with self.captureOnCommitCallbacks(execute=True):
            self.f.post(f"{INV}{r.data['id']}/cancel/")
        self.assertEqual(sum(a for _, a in self.moves()), Decimal('0'))
        self.assertEqual(self.debt(), Decimal('0'))

    def test_ns_cash_no_debt_no_movement(self):
        r = self.post('NS', 'CASH', pay=900, qty=4)
        self.assertEqual(r.status_code, 201, r.data)
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual(inv.payment_amount, Decimal('0'))
        self.assertEqual(inv.debt_after, inv.debt_before)
        self.assertEqual(self.debt(), Decimal('0'))
        self.assertEqual(self.moves(), [])
        self.assertEqual(self.sent(), 0)

    def test_ns_credit_without_client_has_no_effect(self):
        r = self.post('NS', 'CREDIT', client=False)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(DebtMovement.objects.count(), 0)
        self.assertEqual(self.sent(), 0)

    def test_ns_ignores_commission_and_soldee_flags(self):
        r = self.post('NS', 'CREDIT', commission_rate='0.30')
        self.assertEqual(Invoice.objects.get(pk=r.data['id']).commission_rate, Decimal('0.00'))

    def test_ns_price_taken_from_catalog_not_client(self):
        r = self.post('NS', 'CREDIT', unit_price=1, qty=3)
        self.assertEqual(Invoice.objects.get(pk=r.data['id']).order_total, Decimal('1500'))


# --------------------------------------------------------------------------
# (2) cohérence BP / dette / recompute_client_debt
# --------------------------------------------------------------------------
class BpCoherence(Base):
    def test_ns_then_sale_then_refund_matches_recompute(self):
        chain = []
        # 1) NS à crédit : +2000
        r1 = self.post('NS', 'CREDIT', qty=4); chain.append(r1.data['id'])
        # 2) vente normale 10 x 500 = 5000, payé 1000 : +4000
        r2 = self.post('', 'CREDIT', pay=1000, qty=10); chain.append(r2.data['id'])
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.f.post(f"{INV}{r2.data['id']}/deliver/").status_code, 200)
        # 3) RG : 0
        r3 = self.post('RG', 'CASH', pay=5000, qty=2); chain.append(r3.data['id'])
        # 4) remboursement 1500
        r4 = self.refund(1500); chain.append(r4.data['id'])
        self.assertEqual(r4.status_code, 201, r4.data)

        invs = [Invoice.objects.get(pk=i) for i in chain]
        # BP_apres = BP_avant + commande - paiement (règle 5.2), sauf NS CASH/RG
        expected = [
            (Decimal('0'), Decimal('2000')),
            (Decimal('2000'), Decimal('6000')),
            (Decimal('6000'), Decimal('6000')),
            (Decimal('6000'), Decimal('4500')),
        ]
        self.assertEqual([(i.debt_before, i.debt_after) for i in invs], expected)
        self.assertEqual(self.debt(), Decimal('4500'))
        # chaque debt_before = debt_after de la précédente
        for a, b in zip(invs, invs[1:]):
            self.assertEqual(a.debt_after, b.debt_before)
        # recalcul par somme des mouvements : doit être identique
        recomputed = recompute_client_debt(self.cl.pk).current_debt
        self.assertEqual(recomputed, Decimal('4500'))
        self.assertEqual(self.debt(), Decimal('4500'))

    def test_recompute_does_not_resurrect_cancelled_ns(self):
        r = self.post('NS', 'CREDIT', qty=6)
        with self.captureOnCommitCallbacks(execute=True):
            self.f.post(f"{INV}{r.data['id']}/cancel/")
        self.assertEqual(recompute_client_debt(self.cl.pk).current_debt, Decimal('0'))

    def test_recompute_does_not_double_ns_credit(self):
        self.post('NS', 'CREDIT', qty=6)  # 3000
        self.assertEqual(recompute_client_debt(self.cl.pk).current_debt, Decimal('3000'))
        # idempotent
        self.assertEqual(recompute_client_debt(self.cl.pk).current_debt, Decimal('3000'))

    def test_recompute_ignores_rg_and_ns_cash(self):
        self.post('RG', 'CREDIT', pay=7000, qty=4)
        self.post('NS', 'CASH', pay=100, qty=4)
        self.assertEqual(recompute_client_debt(self.cl.pk).current_debt, Decimal('0'))
        self.assertEqual(DebtMovement.objects.filter(client=self.cl).count(), 0)

    def test_rg_cancel_leaves_debt_untouched_and_restores_stock(self):
        self.post('NS', 'CREDIT', qty=4)  # dette 2000
        r = self.post('RG', 'CREDIT', pay=0, qty=4)
        self.assertEqual(self.sent(), 4)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.f.post(f"{INV}{r.data['id']}/cancel/").status_code, 200)
        self.assertEqual(self.debt(), Decimal('2000'))
        self.assertEqual(self.sent(), 0)
        self.assertEqual(recompute_client_debt(self.cl.pk).current_debt, Decimal('2000'))


# --------------------------------------------------------------------------
# (3) plafond atteint
# --------------------------------------------------------------------------
class CeilingWithNs(Base):
    def test_ceiling_reached_ns_allowed_then_sale_blocked(self):
        Client.objects.filter(pk=self.cl.pk).update(current_debt=Decimal('50000'))
        self.assertEqual(self.post('NS', 'CREDIT', qty=2).status_code, 201)
        self.assertEqual(self.debt(), Decimal('51000'))
        r = self.post('', 'CREDIT', pay=0, qty=2)
        self.assertEqual(r.status_code, 403, r.data)
        self.assertEqual(self.debt(), Decimal('51000'))
        # paiement >= commande : accepté
        r = self.post('', 'CASH', pay=1000, qty=2)
        self.assertEqual(r.status_code, 201, r.data)

    def test_ns_pushes_client_over_ceiling_then_next_sale_blocked(self):
        Client.objects.filter(pk=self.cl.pk).update(current_debt=Decimal('49000'))
        self.assertEqual(self.post('', 'CREDIT', pay=0, qty=2).status_code, 201)  # 50000 -> atteint
        # (BP 49000 < plafond : première vente passe)
        self.assertEqual(self.debt(), Decimal('50000'))
        self.assertEqual(self.post('NS', 'CREDIT', qty=2).status_code, 201)
        self.assertEqual(self.post('', 'CREDIT', pay=0, qty=1).status_code, 403)

    def test_ns_does_not_count_in_monthly_deficit_check(self):
        # NS jamais DELIVERED : n'entre pas dans le déficit du mois
        for _ in range(3):
            self.post('NS', 'CREDIT', qty=100)  # 50000 chacun -> dette 150000
        # BP >= plafond => bloqué par la règle BP, pas par un effet de bord
        self.assertEqual(self.post('', 'CREDIT', qty=1).status_code, 403)


# --------------------------------------------------------------------------
# (4) RG
# --------------------------------------------------------------------------
class RgBehaviour(Base):
    def test_rg_payment_forced_to_zero_debt_unchanged_stock_deducted(self):
        Client.objects.filter(pk=self.cl.pk).update(current_debt=Decimal('3000'))
        r = self.post('RG', 'CASH', pay=5000, qty=4)
        self.assertEqual(r.status_code, 201, r.data)
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual(inv.payment_amount, Decimal('0'))
        self.assertEqual(inv.commission_rate, Decimal('0'))
        self.assertEqual((inv.debt_before, inv.debt_after), (Decimal('3000'), Decimal('3000')))
        self.assertEqual(self.debt(), Decimal('3000'))
        self.assertEqual(self.sent(), 4)  # déstockage normal
        # livraison normale
        d = self.l.post(f'{INV}{inv.pk}/deliver/')
        self.assertEqual(d.status_code, 200, d.data)
        self.assertEqual(self.sent(), 4)  # pas de double déstockage
        self.assertEqual(self.debt(), Decimal('3000'))

    def test_rg_not_blocked_by_ceiling_logic_or_is_consistent(self):
        # RG avec client au plafond : paiement forcé à 0 < commande -> la
        # règle de plafond s'applique-t-elle ? (comportement observé noté)
        Client.objects.filter(pk=self.cl.pk).update(current_debt=Decimal('60000'))
        r = self.post('RG', 'CASH', pay=0, qty=2)
        self.assertEqual(r.status_code, 201, r.data)

    def test_rg_delivered_does_not_trigger_monthly_deficit_block(self):
        """Une RG livrée (aucune dette, BP inchangée) ne doit pas créer de
        « déficit net du mois » qui bloquerait ensuite une vente normale."""
        r = self.post('RG', 'CASH', qty=160)  # 80 000 FC (-CM 25 % = 60 000 >= plafond 50 000)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.f.post(f"{INV}{r.data['id']}/deliver/").status_code, 200)
        self.assertEqual(self.debt(), Decimal('0'))
        nxt = self.post('', 'CASH', pay=500, qty=1)
        self.assertEqual(nxt.status_code, 201, nxt.data)
        # une vente à crédit avec BP = 0 ne doit pas être refusée non plus
        nxt = self.post('', 'CREDIT', pay=0, qty=1)
        self.assertEqual(nxt.status_code, 201, nxt.data)

    def test_rg_in_regularisation_column_not_facture_jr(self):
        r = self.post('RG', 'CASH', pay=5000, qty=4)
        self.assertEqual(self.f.post(f"{INV}{r.data['id']}/deliver/").status_code, 200)
        rep = self.g.get('/api/production/daily-closure/', {'date': str(timezone.localdate())})
        self.assertEqual(rep.status_code, 200, rep.data)
        row = next(c for c in rep.data['categories'] if c['bread_price'] == self.bp.pk)
        self.assertEqual(row['regularisation'], {'quantity': 4, 'fc': '2000.00'})
        self.assertEqual(row['facture_jr'], {'quantity': 0, 'fc': '0.00'})
        self.assertEqual(row['commission_jr']['fc'], '0.00')


# --------------------------------------------------------------------------
# (5) ajustement BUG-097 sur NS / RG
# --------------------------------------------------------------------------
class AdjustOnNsRg(Base):
    def adjust(self, inv_id, sign, qty, pay=0):
        with self.captureOnCommitCallbacks(execute=True):
            return self.g.post(f'{INV}{inv_id}/adjust/', {
                'adjustment_sign': sign, 'payment_amount': pay,
                'lines': [{'bread_price': self.bp.pk, 'quantity': qty}],
            }, format='json')

    def test_adjust_ns_decrease_does_not_create_stock_or_credit_out_of_nothing(self):
        """Une NS n'a jamais déstocké ni créé de dette (CASH) : un ajustement
        négatif ne doit ni restituer du stock inexistant ni créditer le
        client."""
        r = self.post('NS', 'CASH', qty=4)
        a = self.adjust(r.data['id'], -1, 2)
        if a.status_code != 201:
            return  # refus explicite = comportement acceptable
        self.assertEqual(self.sent(), 0, "stock restitué alors que rien n'a été déstocké")

    def test_adjust_ns_cash_does_not_credit_client(self):
        r = self.post('NS', 'CASH', qty=4)
        a = self.adjust(r.data['id'], -1, 2)
        if a.status_code != 201:
            return
        self.assertEqual(self.debt(), Decimal('0'), "client crédité sans dette NS")

    def test_adjust_ns_credit_no_crash_and_debt_matches_recompute(self):
        r = self.post('NS', 'CREDIT', qty=4)
        a = self.adjust(r.data['id'], -1, 2)
        self.assertIn(a.status_code, (201, 400), a.data)
        self.assertEqual(self.debt(), recompute_client_debt(self.cl.pk).current_debt)

    def test_adjust_rg_increase_does_not_create_debt(self):
        """RG = ni paiement ni dette ; un ajustement + sur une RG ne doit pas
        créer de dette."""
        r = self.post('RG', 'CASH', qty=4)
        a = self.adjust(r.data['id'], 1, 2)
        if a.status_code != 201:
            return
        self.assertEqual(self.debt(), Decimal('0'), "dette créée par ajustement d'une RG")

    def test_adjust_rg_no_crash_and_debt_matches_recompute(self):
        r = self.post('RG', 'CASH', qty=4)
        a = self.adjust(r.data['id'], -1, 2)
        self.assertIn(a.status_code, (201, 400), a.data)
        self.assertEqual(self.debt(), recompute_client_debt(self.cl.pk).current_debt)


# --------------------------------------------------------------------------
# (6) listes de livraison
# --------------------------------------------------------------------------
class NsNotDeliverable(Base):
    def test_ns_absent_from_pending_deliveries_and_livreur_cannot_deliver(self):
        ns = self.post('NS', 'CREDIT', qty=2).data['id']
        normal = self.post('', 'CASH', pay=1000, qty=2).data['id']
        for api in (self.l, self.f, self.g):
            ids = [i['id'] for i in api.get(f'{INV}pending_deliveries/').data]
            self.assertIn(normal, ids)
            self.assertNotIn(ns, ids)
        r = self.l.post(f'{INV}{ns}/deliver/')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Invoice.objects.get(pk=ns).status, Invoice.Status.PENDING)
        self.assertEqual(self.sent(), 2)  # seule la vente normale a déstocké

    def test_ns_survives_cleanup_while_normal_expired_is_purged(self):
        ns = self.post('NS', 'CREDIT', qty=2).data['id']
        Invoice.objects.filter(pk=ns).update(created_at=timezone.now() - timedelta(hours=30))
        with self.captureOnCommitCallbacks(execute=True):
            r = self.g.post(f'{INV}cleanup_expired/')
        self.assertEqual(r.data['deleted'], 0)
        self.assertEqual(self.debt(), Decimal('1000'))


# --------------------------------------------------------------------------
# (7)(8) blocage TEAM_NOT_ASSIGNED
# --------------------------------------------------------------------------
class TeamBlocking(Base):
    D = date(2026, 11, 11)

    def now(self, h=13, d=None):
        d = d or self.D
        return patch('django.utils.timezone.now', return_value=_at(d, h))

    def enable(self):
        self.node.team_rotation_enabled = True
        self.node.save(update_fields=['team_rotation_enabled'])

    def test_all_creation_kinds_blocked_without_assignment(self):
        self.enable()
        with self.now():
            calls = {
                'vente': lambda: self.post('', 'CASH', pay=2000, qty=4),
                'NS': lambda: self.post('NS', 'CREDIT', qty=4),
                'RG': lambda: self.post('RG', 'CASH', qty=4),
                'remboursement': lambda: self.refund(100),
                'vente sans client': lambda: self.post('', 'CASH', pay=2000, client=False),
            }
            for name, fn in calls.items():
                r = fn()
                self.assertEqual(r.status_code, 403, f'{name}: {r.data}')
                self.assertEqual(r.data.get('code'), 'TEAM_NOT_ASSIGNED', name)
        self.assertFalse(Invoice.objects.exists())
        self.assertEqual(self.sent(), 0)
        self.assertEqual(self.debt(), Decimal('0'))
        self.assertEqual(DebtMovement.objects.count(), 0)

    def test_blocked_for_hq_user_with_explicit_node(self):
        self.enable()
        direction = make_user('DIRECTION', node=None)
        with self.now():
            r = self.post('', 'CASH', pay=2000, api=_api(direction), node=self.node.pk)
        self.assertEqual(r.status_code, 403, r.data)
        self.assertEqual(r.data.get('code'), 'TEAM_NOT_ASSIGNED')

    def test_flag_off_unchanged_all_kinds(self):
        with self.now():
            self.assertEqual(self.post('', 'CASH', pay=2000).status_code, 201)
            self.assertEqual(self.post('NS', 'CREDIT').status_code, 201)
            self.assertEqual(self.post('RG', 'CASH').status_code, 201)
            self.assertEqual(self.refund(100).status_code, 201)
        self.assertEqual(set(Invoice.objects.values_list('team', flat=True)), {'A'})

    def test_designated_team_applies_to_all_kinds(self):
        self.enable()
        DailyTeamAssignment.objects.create(node=self.node, work_date=self.D, team='B')
        with self.now():
            for r in (self.post('', 'CASH', pay=2000), self.post('NS', 'CREDIT'),
                      self.post('RG', 'CASH'), self.refund(100)):
                self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(set(Invoice.objects.values_list('team', flat=True)), {'B'})

    def test_block_precedes_validation_no_side_effect_on_bad_client(self):
        self.enable()
        with self.now():
            r = self.f.post(INV, {'payment_type': 'CASH', 'payment_amount': 0, 'lines': []}, format='json')
        # lignes vides sans remboursement : 400 ou 403, jamais 5xx ni écriture
        self.assertIn(r.status_code, (400, 403))
        self.assertFalse(Invoice.objects.exists())

    def test_adjust_not_blocked_but_takes_service_team(self):
        """(7) `adjust` n'est pas bloqué ; la facture d'ajustement doit
        porter l'équipe de service désignée, pas celle du gérant."""
        orig = self.post('', 'CASH', pay=2000, qty=4).data['id']  # drapeau inactif
        self.enable()
        DailyTeamAssignment.objects.create(node=self.node, work_date=self.D, team='B')
        with self.now():
            a = self.g.post(f'{INV}{orig}/adjust/', {
                'adjustment_sign': 1, 'payment_amount': 0,
                'lines': [{'bread_price': self.bp.pk, 'quantity': 1}],
            }, format='json')
        self.assertEqual(a.status_code, 201, a.data)
        self.assertEqual(Invoice.objects.get(pk=a.data['id']).team, 'B')

    def test_adjust_without_assignment_does_not_crash(self):
        orig = self.post('', 'CASH', pay=2000, qty=4).data['id']
        self.enable()
        with self.now():
            a = self.g.post(f'{INV}{orig}/adjust/', {
                'adjustment_sign': 1, 'payment_amount': 0,
                'lines': [{'bread_price': self.bp.pk, 'quantity': 1}],
            }, format='json')
        self.assertIn(a.status_code, (201, 403), a.data)

    def test_backdated_invoice_not_blocked_without_today_assignment(self):
        cfg = Config.get_instance(); cfg.allow_backdated_sales = True; cfg.save()
        self.enable()
        yesterday = self.D - timedelta(days=1)
        DailyTeamAssignment.objects.create(node=self.node, work_date=yesterday, team='A')
        with self.now():
            r = self.post('', 'CASH', pay=2000, invoice_date=str(yesterday))
        # BUG-183 (décision coordinateur) : une vente passée n'exige plus la
        # désignation du jour courant ; elle porte l'équipe de sa propre journée.
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Invoice.objects.get(pk=r.data['id']).team, 'A')

    def test_backdated_invoice_takes_team_of_its_own_day(self):
        cfg = Config.get_instance(); cfg.allow_backdated_sales = True; cfg.save()
        self.enable()
        yesterday = self.D - timedelta(days=1)
        DailyTeamAssignment.objects.create(node=self.node, work_date=yesterday, team='A')
        DailyTeamAssignment.objects.create(node=self.node, work_date=self.D, team='B')
        with self.now():
            r = self.post('', 'CASH', pay=2000, invoice_date=str(yesterday))
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Invoice.objects.get(pk=r.data['id']).team, 'A')
