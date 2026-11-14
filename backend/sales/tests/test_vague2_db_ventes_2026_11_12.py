"""
Vague 2 « base réelle » (testeur-ventes, 2026-11-12) : non-régression des
scénarios rejoués sur la vraie base (K1) après les corrections BUG-208 à 215,
229, 230, 233. Données fictives uniquement (base de test).
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from clients.models import Client
from core.testing import make_bread_price, make_client, make_node, make_user
from production.models import BreadStock
from sales.models import Invoice

INV = '/api/sales/invoices/'


class Base(TestCase):
    def setUp(self):
        self.node = make_node(code='W2')
        self.bp = make_bread_price('B500', 'Pain 500 FC', 500)
        self.fact = make_user('FACTURIER', node=self.node, team='A')
        self.fact_b = make_user('FACTURIER', node=self.node, team='B')
        self.livreur = make_user('LIVREUR', node=self.node, team='A')
        self.gerant = make_user('GERANT', node=self.node, team='')
        self.cl = make_client(self.node)
        self.api = APIClient()
        self.api.force_authenticate(self.fact)

    def as_user(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def post(self, api=None, client='default', qty=2, pay=0, **extra):
        cl = self.cl if client == 'default' else client
        p = {'payment_type': 'CASH' if pay else 'CREDIT', 'payment_amount': pay,
             'lines': [{'bread_price': self.bp.pk, 'quantity': qty}]}
        if cl is not None:
            p['client'] = str(cl.pk)
        p.update(extra)
        return (api or self.api).post(INV, p, format='json')

    def expected_debt(self, client):
        total = Decimal('0')
        for i in Invoice.objects.filter(client=client).exclude(status='CANCELLED'):
            total += i.debt_delta if not i.is_debt_repayment else -i.payment_amount
        return total


class SerieEtCoherenceTests(Base):
    def test_serie_mixte_current_debt_egal_somme_des_mouvements_et_recus_uniques(self):
        users = [self.fact, self.fact_b, self.gerant]
        for k in range(12):
            r = self.post(api=self.as_user(users[k % 3]), qty=(k % 5) + 1, pay=(0, 500, 1000)[k % 3])
            self.assertEqual(r.status_code, 201, r.data)
        self.api.post(INV, {'client': str(self.cl.pk), 'payment_type': 'CASH', 'payment_amount': 1500,
                            'is_debt_repayment': True, 'lines': []}, format='json')
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, self.expected_debt(self.cl))
        numbers = list(Invoice.objects.values_list('receipt_number', flat=True))
        self.assertEqual(len(numbers), len(set(numbers)))

    def test_bp_cumulee_sur_changement_de_mois_et_jours(self):
        self.post(qty=10)  # 5000
        Invoice.objects.update(invoice_date=timezone.localdate() - timedelta(days=40))
        r = self.post(qty=4, pay=500)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Decimal(str(r.data['debt_before'])), Decimal('5000'))
        self.assertEqual(Decimal(str(r.data['debt_after'])), Decimal('6500'))


class PlafondTests(Base):
    def test_plafond_exact_juste_sous_et_paiement_integral(self):
        Client.objects.filter(pk=self.cl.pk).update(current_debt=Decimal('49500'))
        self.assertEqual(self.post(qty=1).status_code, 201)          # 49 500 + 500 = 50 000 : accepté
        r = self.post(qty=1)                                         # BP = plafond, paiement 0
        self.assertEqual(r.status_code, 403)
        self.assertIn('detail', r.data)
        self.assertEqual(self.post(qty=1, pay=499).status_code, 403)
        self.assertEqual(self.post(qty=1, pay=500).status_code, 201)  # règle §5.2 : accepté


class EpargneSoldeTests(Base):
    def test_epargne_bp_negative_puis_commande(self):
        r = self.api.post(INV, {'client': str(self.cl.pk), 'payment_type': 'CASH', 'payment_amount': 5000,
                                'is_debt_repayment': True, 'lines': []}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Decimal(str(r.data['order_total'])), 0)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, Decimal('-5000'))
        r = self.post(qty=6)
        self.assertEqual(r.status_code, 201)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, Decimal('-2000'))

    def test_vente_solde_75_pour_cent_cm_zero_bp_inchangee(self):
        r = self.post(qty=10, is_soldee=True)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Decimal(str(r.data['order_total'])), Decimal('3750'))
        self.assertEqual(Decimal(str(r.data['commission_rate'])), Decimal('0'))
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, 0)

    def test_vente_cash_solde_75_pour_cent(self):
        r = self.post(qty=10, pay=3750, is_soldee=True)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Decimal(str(r.data['order_total'])), Decimal('3750'))
        self.assertEqual(Decimal(str(r.data['commission_rate'])), Decimal('0'))


class LivraisonEtExpirationTests(Base):
    def test_livraison_livreur_puis_double_requete_sans_double_effet(self):
        r = self.post(qty=3)
        iid = r.data['id']
        stock_sent = BreadStock.objects.get(node=self.node, bread_price=self.bp).qty_sent
        lv = self.as_user(self.livreur)
        self.assertEqual(lv.post(f'{INV}{iid}/deliver/').status_code, 200)
        self.assertEqual(self.api.post(f'{INV}{iid}/deliver/').status_code, 400)
        self.assertEqual(BreadStock.objects.get(node=self.node, bread_price=self.bp).qty_sent, stock_sent)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, Decimal('1500'))

    def test_expiration_12h_restitue_bp_et_stock_sans_toucher_les_livrees(self):
        old = self.post(qty=4).data['id']
        delivered = self.post(qty=2).data['id']
        self.api.post(f'{INV}{delivered}/deliver/')
        Invoice.objects.filter(pk=old).update(created_at=timezone.now() - timedelta(hours=13))
        Invoice.objects.filter(pk=delivered).update(created_at=timezone.now() - timedelta(hours=13))
        recent = self.post(qty=1).data['id']
        r = self.as_user(self.gerant).post(f'{INV}cleanup_expired/')  # BUG-284 : GERANT+
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['deleted'], 1)
        self.assertFalse(Invoice.objects.filter(pk=old).exists())
        self.assertTrue(Invoice.objects.filter(pk=delivered).exists())
        self.assertTrue(Invoice.objects.filter(pk=recent).exists())
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, Decimal('1500'))  # (2 + 1) pains de 500
        self.assertEqual(self.expected_debt(self.cl), self.cl.current_debt)
        st = BreadStock.objects.get(node=self.node, bread_price=self.bp)
        self.assertEqual(st.qty_sent, 3)


class DroitsEtContratTests(Base):
    def test_gerant_peut_facturer_et_patcher_commission_exempt_uniquement(self):
        r = self.post(api=self.as_user(self.gerant), qty=2)
        self.assertEqual(r.status_code, 201, r.data)
        iid = r.data['id']
        g = self.as_user(self.gerant)
        self.assertEqual(g.patch(f'{INV}{iid}/', {'commission_exempt': True}, format='json').status_code, 200)
        r = g.patch(f'{INV}{iid}/', {'commission_exempt': False}, format='json')
        self.assertEqual(Decimal(str(r.data['commission_rate'])), Decimal('0.25'))
        self.assertEqual(g.patch(f'{INV}{iid}/', {'order_total': 1}, format='json').status_code, 400)
        self.assertEqual(g.put(f'{INV}{iid}/', {}, format='json').status_code, 405)
        self.assertEqual(g.delete(f'{INV}{iid}/').status_code, 405)
        self.assertEqual(self.api.patch(f'{INV}{iid}/', {'commission_exempt': True}, format='json').status_code, 403)
