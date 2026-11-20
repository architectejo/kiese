"""
BUG-318 : « Non servi » (manuel et à l'expiration) + livraison partielle.
Données fictives uniquement.
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import ActivityLog, SystemNotification
from core.testing import make_bread_price, make_client, make_node, make_user
from production.models import BreadStock
from sales.models import Invoice

INV = '/api/sales/invoices/'


class Base(TestCase):
    def setUp(self):
        self.node = make_node(code='N1')
        self.other = make_node(code='N2')
        self.bp = make_bread_price('B318A', 'Pain 500 FC', 500)
        self.bp2 = make_bread_price('B318B', 'Pain 300 FC', 300)
        self.fact = make_user('FACTURIER', node=self.node)
        self.livreur = make_user('LIVREUR', node=self.node)
        self.gerant = make_user('GERANT', node=self.node)
        self.fact_other = make_user('FACTURIER', node=self.other)
        self.cl = make_client(self.node, credit_limit=Decimal('500000.00'))

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def post(self, payment='0.00', ptype='CREDIT', lines=None, client=True, **extra):
        payload = {
            'payment_type': ptype, 'payment_amount': payment,
            'lines': lines or [{'bread_price': self.bp.pk, 'quantity': 4},
                               {'bread_price': self.bp2.pk, 'quantity': 2}],
        }
        if client:
            payload['client'] = str(self.cl.pk)
        payload.update(extra)
        r = self.api(self.fact).post(INV, payload, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return Invoice.objects.get(pk=r.data['id'])

    def debt(self):
        self.cl.refresh_from_db()
        return self.cl.current_debt

    def sent(self, bp=None):
        return sum(BreadStock.objects.filter(node=self.node, bread_price=bp or self.bp)
                   .values_list('qty_sent', flat=True))

    def age(self, inv, hours):
        Invoice.objects.filter(pk=inv.pk).update(created_at=timezone.now() - timedelta(hours=hours))

    def ns(self, inv, user=None, **body):
        return self.api(user or self.fact).post(f'{INV}{inv.pk}/mark-not-served/', body, format='json')

    def deliver(self, inv, lines=None, user=None):
        body = {'lines': lines} if lines is not None else {}
        return self.api(user or self.fact).post(f'{INV}{inv.pk}/deliver/', body, format='json')


class PartialDeliveryTests(Base):
    # commande : 4 x 500 + 2 x 300 = 2600

    def line(self, inv, bp):
        return inv.lines.get(bread_price=bp)

    def test_partielle_recalcule_valeur_bp_stock_et_garde_le_commande(self):
        inv = self.post(payment='1000.00')
        self.assertEqual(self.debt(), Decimal('1600'))
        l1 = self.line(inv, self.bp)
        r = self.deliver(inv, [{'id': l1.pk, 'quantity': 1}])
        self.assertEqual(r.status_code, 200, r.data)
        inv.refresh_from_db()
        # servi = 1x500 + 2x300 = 1100 ; initial 2600
        self.assertEqual(inv.status, Invoice.Status.DELIVERED)
        self.assertEqual(inv.order_total, Decimal('1100.00'))
        self.assertEqual(inv.initial_order_total, Decimal('2600.00'))
        self.assertEqual(inv.debt_after, Decimal('100.00'))  # 0 + 1100 - 1000
        self.assertEqual(self.debt(), Decimal('100'))
        self.assertEqual(self.sent(), 1)
        self.assertEqual(self.sent(self.bp2), 2)
        l1.refresh_from_db()
        self.assertEqual((l1.quantity, l1.ordered_quantity, l1.line_total), (1, 4, Decimal('500.00')))
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.total_breads_received, 3)
        self.assertEqual(r.data['initial_order_total'], '2600.00')

    def test_servi_egal_commande_ne_change_rien(self):
        inv = self.post()
        l1 = self.line(inv, self.bp)
        r = self.deliver(inv, [{'id': l1.pk, 'quantity': 4}])
        self.assertEqual(r.status_code, 200, r.data)
        inv.refresh_from_db()
        self.assertIsNone(inv.initial_order_total)
        self.assertEqual(inv.order_total, Decimal('2600.00'))
        self.assertEqual(self.debt(), Decimal('2600'))

    def test_livraison_par_livreur_et_ligne_a_zero_conservee(self):
        inv = self.post()
        l2 = self.line(inv, self.bp2)
        r = self.deliver(inv, [{'id': l2.pk, 'quantity': 0}], user=self.livreur)
        self.assertEqual(r.status_code, 200, r.data)
        inv.refresh_from_db()
        self.assertEqual(inv.order_total, Decimal('2000.00'))
        self.assertEqual(inv.lines.count(), 2)
        self.assertEqual(self.sent(self.bp2), 0)

    def test_cm_se_calcule_sur_le_servi(self):
        inv = self.post()
        l1 = self.line(inv, self.bp)
        self.deliver(inv, [{'id': l1.pk, 'quantity': 2}])
        inv.refresh_from_db()
        self.assertEqual(inv.order_total, Decimal('1600.00'))
        self.assertEqual(inv.commission_rate, Decimal('0.25'))

    def test_vente_sans_client_paiement_ramene_au_servi(self):
        inv = self.post(payment='2600.00', ptype='CASH', client=False)
        l1 = self.line(inv, self.bp)
        r = self.deliver(inv, [{'id': l1.pk, 'quantity': 0}])
        self.assertEqual(r.status_code, 200, r.data)
        inv.refresh_from_db()
        self.assertEqual(inv.order_total, Decimal('600.00'))
        self.assertEqual(inv.payment_amount, Decimal('600.00'))

    def test_quantites_invalides(self):
        inv = self.post()
        l1 = self.line(inv, self.bp)
        other = self.post(lines=[{'bread_price': self.bp.pk, 'quantity': 1}])
        foreign = other.lines.first()
        cases = [
            [{'id': l1.pk, 'quantity': -1}],
            [{'id': l1.pk, 'quantity': 5}],
            [{'id': l1.pk, 'quantity': 1.5}],
            [{'id': l1.pk, 'quantity': 'abc'}],
            [{'id': l1.pk, 'quantity': True}],
            [{'id': foreign.pk, 'quantity': 1}],
            [{'id': l1.pk, 'quantity': 1}, {'id': l1.pk, 'quantity': 2}],
            [{'quantity': 1}],
            'oops',
        ]
        for body in cases:
            r = self.deliver(inv, body)
            self.assertEqual(r.status_code, 400, (body, r.data))
            self.assertIn('detail', r.data)
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.Status.PENDING)
        self.assertEqual(self.debt(), Decimal('2600') + Decimal('500'))

    def test_tout_a_zero_refuse_et_oriente_vers_non_servi(self):
        inv = self.post()
        r = self.deliver(inv, [{'id': l.pk, 'quantity': 0} for l in inv.lines.all()])
        self.assertEqual(r.status_code, 400)
        self.assertIn('Non servi', r.data['detail'])
        self.assertEqual(Invoice.objects.get(pk=inv.pk).status, Invoice.Status.PENDING)

    def test_double_livraison_refusee_et_autre_noeud_404(self):
        inv = self.post()
        l1 = self.line(inv, self.bp)
        self.assertEqual(self.deliver(inv, [], user=self.fact_other).status_code, 404)
        self.assertEqual(self.deliver(inv, [{'id': l1.pk, 'quantity': 1}]).status_code, 200)
        r = self.deliver(inv, [{'id': l1.pk, 'quantity': 0}])
        self.assertEqual(r.status_code, 400)
        inv.refresh_from_db()
        self.assertEqual(inv.order_total, Decimal('1100.00'))

    def test_livraison_totale_sans_corps_inchangee(self):
        inv = self.post()
        r = self.deliver(inv)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.debt(), Decimal('2600'))


class NotServedTests(Base):
    def test_non_servi_retablit_bp_stock_et_garde_le_versement(self):
        inv = self.post(payment='1000.00')
        self.assertEqual(self.debt(), Decimal('1600'))
        r = self.ns(inv, reason='Client absent')
        self.assertEqual(r.status_code, 200, r.data)
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.Status.NOT_SERVED)
        self.assertEqual(inv.order_total, Decimal('0.00'))
        self.assertEqual(inv.initial_order_total, Decimal('2600.00'))
        self.assertEqual(inv.payment_amount, Decimal('1000.00'))
        self.assertEqual(inv.debt_after, Decimal('-1000.00'))
        self.assertEqual(inv.not_served_reason, 'Client absent')
        self.assertEqual(self.debt(), Decimal('-1000'))  # versement = crédit, comme commande 0
        self.assertEqual(self.sent(), 0)
        self.assertEqual(self.sent(self.bp2), 0)
        self.assertEqual(inv.lines.count(), 2)
        self.assertTrue(all(l.quantity == 0 and l.ordered_quantity for l in inv.lines.all()))
        self.assertTrue(ActivityLog.objects.filter(action__icontains='Non Servi').exists())
        self.assertTrue(SystemNotification.objects.filter(title__icontains=inv.receipt_number).exists())

    def test_non_servi_sans_versement_remet_la_bp_a_zero(self):
        inv = self.post()
        self.assertEqual(self.ns(inv, user=self.livreur).status_code, 200)
        self.assertEqual(self.debt(), Decimal('0'))
        self.assertEqual(self.ns(inv, user=self.gerant).status_code, 409)

    def test_non_servi_sans_client_versement_nul(self):
        inv = self.post(payment='2600.00', ptype='CASH', client=False)
        self.assertEqual(self.ns(inv).status_code, 200)
        inv.refresh_from_db()
        self.assertEqual(inv.payment_amount, Decimal('0.00'))

    def test_double_action_et_mauvais_statut(self):
        inv = self.post()
        self.assertEqual(self.ns(inv).status_code, 200)
        r = self.ns(inv)
        self.assertEqual(r.status_code, 409)
        self.assertIn('detail', r.data)
        self.assertEqual(self.deliver(inv).status_code, 409)
        d = self.post()
        self.deliver(d)
        self.assertEqual(self.ns(d).status_code, 409)
        self.assertEqual(self.debt(), Decimal('2600'))
        c = self.post()
        self.api(self.fact).post(f'{INV}{c.pk}/cancel/')
        self.assertEqual(self.ns(c).status_code, 409)

    def test_autre_noeud_et_non_authentifie(self):
        inv = self.post()
        self.assertEqual(self.ns(inv, user=self.fact_other).status_code, 404)
        self.assertEqual(APIClient().post(f'{INV}{inv.pk}/mark-not-served/', {}, format='json').status_code, 401)
        self.assertEqual(Invoice.objects.get(pk=inv.pk).status, Invoice.Status.PENDING)

    def test_motif_invalide(self):
        inv = self.post()
        self.assertEqual(self.ns(inv, reason='x' * 201).status_code, 400)
        self.assertEqual(self.ns(inv, reason=['a']).status_code, 400)
        self.assertEqual(Invoice.objects.get(pk=inv.pk).status, Invoice.Status.PENDING)

    def test_facture_ns_code_speciale_refusee(self):
        inv = self.post(special_code='NS')
        self.assertEqual(self.ns(inv).status_code, 400)

    def test_non_servi_hors_commissions(self):
        inv = self.post()
        self.ns(inv)
        self.assertFalse(Invoice.objects.filter(status=Invoice.Status.DELIVERED, pk=inv.pk).exists())


class ExpirationTests(Base):
    def test_expiree_devient_non_servi_conservee_bp_et_stock_retablis(self):
        inv = self.post(payment='500.00')
        self.age(inv, 13)
        call_command('expire_pending_invoices', stdout=StringIO())
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.Status.NOT_SERVED)
        self.assertEqual(inv.not_served_reason, 'Expirée automatiquement')
        self.assertEqual(inv.order_total, Decimal('0.00'))
        self.assertEqual(inv.initial_order_total, Decimal('2600.00'))
        self.assertEqual(self.debt(), Decimal('-500'))
        self.assertEqual(self.sent(), 0)

    def test_idempotent(self):
        from sales.services import expire_pending_invoices
        inv = self.post()
        self.age(inv, 13)
        self.assertEqual(expire_pending_invoices(), 1)
        self.assertEqual(expire_pending_invoices(), 0)
        self.assertEqual(self.api(self.gerant).post(f'{INV}cleanup_expired/').data['expired'], 0)
        self.assertEqual(self.debt(), Decimal('0'))
        self.assertEqual(ActivityLog.objects.filter(action__icontains='Non Servi').count(), 1)

    def test_non_expiree_inchangee(self):
        from sales.services import expire_pending_invoices
        inv = self.post()
        self.age(inv, 11)
        self.assertEqual(expire_pending_invoices(), 0)
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.Status.PENDING)
        self.assertEqual(self.debt(), Decimal('2600'))

    def test_livree_et_ns_code_jamais_expirees(self):
        from sales.services import expire_pending_invoices
        d = self.post()
        self.deliver(d)
        n = self.post(special_code='NS')
        self.age(d, 30)
        self.age(n, 30)
        self.assertEqual(expire_pending_invoices(), 0)
        self.assertEqual(Invoice.objects.get(pk=d.pk).status, Invoice.Status.DELIVERED)
        self.assertEqual(Invoice.objects.get(pk=n.pk).status, Invoice.Status.PENDING)

    def test_application_a_la_lecture_liste_et_pending_deliveries(self):
        inv = self.post()
        self.age(inv, 13)
        self.assertEqual(self.api(self.fact).get(INV).status_code, 200)
        self.assertEqual(Invoice.objects.get(pk=inv.pk).status, Invoice.Status.NOT_SERVED)
        inv2 = self.post()
        self.age(inv2, 13)
        r = self.api(self.livreur).get(INV + 'pending_deliveries/')
        self.assertEqual(r.data, [])
        self.assertEqual(Invoice.objects.get(pk=inv2.pk).status, Invoice.Status.NOT_SERVED)
        self.assertEqual(self.debt(), Decimal('0'))

    def test_livraison_d_une_expiree_refusee_409_et_traitee_non_servi(self):
        inv = self.post()
        self.age(inv, 13)
        r = self.deliver(inv)
        self.assertEqual(r.status_code, 409, r.data)
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.Status.NOT_SERVED)
        self.assertEqual(self.debt(), Decimal('0'))
        self.assertEqual(self.deliver(inv).status_code, 409)
        self.assertEqual(self.debt(), Decimal('0'))

    def test_livraison_puis_expiration_pas_de_double_traitement(self):
        from sales.services import expire_pending_invoices
        inv = self.post()
        self.deliver(inv)
        self.age(inv, 20)
        self.assertEqual(expire_pending_invoices(), 0)
        self.assertEqual(self.debt(), Decimal('2600'))

    def test_expiration_limitee_au_noeud_de_l_utilisateur(self):
        inv = self.post()
        self.age(inv, 13)
        self.api(self.fact_other).get(INV)
        self.assertEqual(Invoice.objects.get(pk=inv.pk).status, Invoice.Status.PENDING)
