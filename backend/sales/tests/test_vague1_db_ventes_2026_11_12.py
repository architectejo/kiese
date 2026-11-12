"""
Vague 1 « base réelle » (testeur-ventes, 2026-11-12) : non-régression des
anomalies relevées en exécutant le module Ventes sur la vraie base (K1).
Chaque test attendu en échec porte `@expectedFailure` et la référence du
ticket (docs/qa/REGISTRE_BUGS.md). Données fictives uniquement.
"""
from datetime import timedelta
from unittest import expectedFailure

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from clients.models import Client
from core.testing import make_bread_price, make_client, make_node, make_user
from sales.models import Invoice

INV = '/api/sales/invoices/'


class Vague1Base(TestCase):
    def setUp(self):
        self.node = make_node(code='V8')
        self.bp = make_bread_price('B200', 'Pain 500 FC', 500)
        self.fact = make_user('FACTURIER', node=self.node, team='A')
        self.other_node = make_node(code='V9')
        self.fact_other = make_user('FACTURIER', node=self.other_node, team='A')
        self.cl = make_client(self.node)
        self.api = APIClient()
        self.api.force_authenticate(self.fact)

    def post(self, **extra):
        p = {'client': str(self.cl.pk), 'payment_type': 'CREDIT', 'payment_amount': 0,
             'lines': [{'bread_price': self.bp.pk, 'quantity': 2}]}
        p.update(extra)
        return self.api.post(INV, p, format='json')


class QuantiteEtMontantsTests(Vague1Base):
    @expectedFailure  # BUG-208
    def test_quantite_negative_refusee_en_400(self):
        r = self.post(lines=[{'bread_price': self.bp.pk, 'quantity': -3}])
        self.assertEqual(r.status_code, 400)

    @expectedFailure  # BUG-208
    def test_quantite_zero_refusee(self):
        r = self.post(lines=[{'bread_price': self.bp.pk, 'quantity': 0}])
        self.assertEqual(r.status_code, 400)

    @expectedFailure  # BUG-209
    def test_versement_negatif_refuse_sur_facture(self):
        r = self.post(payment_amount='-500')
        self.assertEqual(r.status_code, 400)

    @expectedFailure  # BUG-209
    def test_versement_negatif_refuse_sur_remboursement(self):
        r = self.api.post(INV, {'client': str(self.cl.pk), 'payment_type': 'CASH',
                                'payment_amount': '-3000', 'is_debt_repayment': True, 'lines': []}, format='json')
        self.assertEqual(r.status_code, 400)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, 0)

    @expectedFailure  # BUG-213
    def test_remboursement_a_zero_refuse(self):
        r = self.api.post(INV, {'client': str(self.cl.pk), 'payment_type': 'CASH',
                                'payment_amount': '0', 'is_debt_repayment': True, 'lines': []}, format='json')
        self.assertEqual(r.status_code, 400)

    @expectedFailure  # BUG-214
    def test_vente_sans_client_a_credit_refusee(self):
        r = self.api.post(INV, {'payment_type': 'CREDIT', 'payment_amount': 0,
                                'lines': [{'bread_price': self.bp.pk, 'quantity': 2}]}, format='json')
        self.assertEqual(r.status_code, 400)


class TauxCommissionTests(Vague1Base):
    @expectedFailure  # BUG-210
    def test_taux_hors_025_030_refuse(self):
        for rate in ('1.00', '-0.50', '5.00'):
            r = self.post(payment_type='CASH', payment_amount=1000, commission_rate=rate)
            self.assertEqual(r.status_code, 400, rate)

    @expectedFailure  # BUG-210
    def test_taux_du_client_utilise_quand_absent_du_payload(self):
        Client.objects.filter(pk=self.cl.pk).update(commission_rate='0.30')
        r = self.post(payment_type='CASH', payment_amount=1000)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(str(r.data['commission_rate']), '0.30')


class BreadSummaryTests(Vague1Base):
    @expectedFailure  # BUG-212
    def test_bread_summary_ne_fuite_pas_vers_une_autre_boulangerie(self):
        r = self.post(payment_type='CASH', payment_amount=1000)
        self.assertEqual(r.status_code, 201, r.data)
        Invoice.objects.filter(pk=r.data['id']).update(status='DELIVERED', delivered_at=timezone.now())
        other = APIClient()
        other.force_authenticate(self.fact_other)
        d = timezone.localdate().isoformat()
        resp = other.get(INV + 'bread_summary/', {'date': d, 'node': self.node.pk})
        self.assertEqual(resp.data['grand_total_qty'], 0)

    @expectedFailure  # BUG-211
    def test_bread_summary_suit_la_journee_de_travail_en_rotation(self):
        """Rotation, relève 12:00 : une livraison de 03:00 le jour J+1 appartient à la journée J."""
        from datetime import time
        self.node.team_rotation_enabled = True
        self.node.handover_time = time(12, 0)
        self.node.save()
        from core.workday import work_date_for
        wd = work_date_for(self.node)
        # instant de livraison = dans la journée de travail `wd` mais sur le jour calendaire suivant.
        from core.workday import workday_bounds
        start, end = workday_bounds(self.node, wd)
        inst = end - timedelta(hours=1)  # 11:00 le lendemain calendaire
        r = self.post(payment_type='CASH', payment_amount=1000, invoice_date=str(wd))
        if r.status_code != 201:  # pas de désignation d'équipe : on la crée
            from production.models import DailyTeamAssignment
            DailyTeamAssignment.objects.create(node=self.node, work_date=wd, team='A', assigned_by=self.fact)
            r = self.post(payment_type='CASH', payment_amount=1000, invoice_date=str(wd))
        self.assertEqual(r.status_code, 201, r.data)
        Invoice.objects.filter(pk=r.data['id']).update(status='DELIVERED', delivered_at=inst)
        resp = self.api.get(INV + 'bread_summary/', {'date': str(wd)})
        self.assertEqual(resp.data['grand_total_qty'], 2)


class ModificationDirecteTests(Vague1Base):
    def setUp(self):
        super().setUp()
        self.gerant = make_user('GERANT', node=self.node)
        self.g = APIClient()
        self.g.force_authenticate(self.gerant)

    def _livree(self):
        r = self.post(payment_type='CREDIT', payment_amount=0)
        Invoice.objects.filter(pk=r.data['id']).update(status='DELIVERED', delivered_at=timezone.now())
        return r.data['id']

    @expectedFailure  # BUG-215
    def test_patch_facture_livree_refuse(self):
        r = self.g.patch(f'{INV}{self._livree()}/', {'payment_amount': '1000'}, format='json')
        self.assertIn(r.status_code, (403, 405))

    @expectedFailure  # BUG-215
    def test_delete_facture_livree_refuse(self):
        r = self.g.delete(f'{INV}{self._livree()}/')
        self.assertIn(r.status_code, (403, 405))
