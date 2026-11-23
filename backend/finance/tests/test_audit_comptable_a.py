"""Auditeur comptable (Dev A, 2026-11-23 a) : BP cumulative sur deux mois, commissions par periode,
blocage de credit, identite CA - cash = creances + manquant soldee. DONNEES FICTIVES (jamais data_kiese/).

Regles (CLAUDE.md 5.2 / 5.3) : BP_apres = BP_avant + commande - paiement, jamais remise a zero d'un mois a l'autre ;
CM brute = valeur commande pains x taux ; blocage si BP_avant >= plafond ET paiement < commande.
Prix fictifs : MINI 300, GRAND 500.

  Client X (CM 25 %, plafond 500 000) :
    M-1 (jour 25) : 10 GRAND = 5 000, paye 2 000  -> BP 3 000
    M   (jour  3) :  4 MINI  = 1 200, paye 5 000  -> BP 3 000 + 1 200 - 5 000 = -800 (credit client)
  Commissions : M-1 = 5 000 x 25 % = 1 250 ; M = 1 200 x 25 % = 300 (les paiements n'entrent pas dans la base).
"""
from datetime import timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.utils import timezone

from clients.models import Client
from commissions.models import ClientCommission
from core.testing import make_client
from finance.tests.test_audit_c_cycle1_c import _Base, _api


def _months():
    first = timezone.localdate().replace(day=1)
    last_of_prev = first - timedelta(days=1)
    m1 = last_of_prev.replace(day=1) - timedelta(days=1)       # dernier jour du mois M-2
    return m1.replace(day=25), last_of_prev.replace(day=3)     # (M-1 j25, M j3) : mois consecutifs


class BpEtCommissionsDeuxMois(_Base):
    @classmethod
    def setUpTestData(cls):
        cls._bootstrap()
        cls.d_a, cls.d_b = _months()
        cls.x = make_client(cls.k1, credit_limit=D('500000'), last_name='Xx')
        cls.sale(cls.f1, cls.x, [(cls.bp_grand, 10)], 2000, 'CREDIT', cls.d_a)
        cls.bp_after_m1 = Client.objects.get(pk=cls.x.pk).current_debt
        cls.sale(cls.f1, cls.x, [(cls.bp_mini, 4)], 5000, 'CASH', cls.d_b)

    def test_bp_cumulative_jamais_remise_a_zero(self):
        self.assertEqual(self.bp_after_m1, D('3000'))
        self.assertEqual(Client.objects.get(pk=self.x.pk).current_debt, D('-800'))

    def test_commission_par_periode_base_sur_la_commande_pas_sur_le_paiement(self):
        hq = _api(self.direction)
        for d in (self.d_a, self.d_b):
            r = hq.post('/api/commissions/periods/generate/',
                        {'node': self.k1.pk, 'month': d.month, 'year': d.year}, format='json')
            self.assertEqual(r.status_code, 201, r.data)
        by_month = {
            (c.period.month, c.period.year): c
            for c in ClientCommission.objects.filter(client=self.x).select_related('period')
        }
        c1 = by_month[(self.d_a.month, self.d_a.year)]
        c2 = by_month[(self.d_b.month, self.d_b.year)]
        self.assertEqual(c1.commission_gross, D('1250'))
        self.assertEqual(c2.commission_gross, D('300'))

    def test_blocage_bp_au_plafond_et_paiement_insuffisant(self):
        y = make_client(self.k1, credit_limit=D('50000'), last_name='Yy')
        self.sale(self.f1, y, [(self.bp_grand, 100)], 0, 'CREDIT', self.d_b)   # BP = 50 000 = plafond
        self.assertEqual(Client.objects.get(pk=y.pk).current_debt, D('50000'))
        api = _api(self.f1)

        def post(pay):
            return api.post('/api/sales/invoices/', {
                'client': str(y.pk), 'payment_type': 'CASH' if pay else 'CREDIT', 'payment_amount': str(pay),
                'invoice_date': str(self.d_b), 'lines': [{'bread_price': self.bp_mini.pk, 'quantity': 4}],
            }, format='json')
        self.assertEqual(post(0).status_code, 403)         # BP >= plafond et paiement < commande
        self.assertEqual(post(1199).status_code, 403)
        self.assertEqual(post(1200).status_code, 201)      # paiement = commande : autorise
        self.assertEqual(Client.objects.get(pk=y.pk).current_debt, D('50000'))   # BP inchange
