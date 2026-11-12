"""
Non-régression BUG-208 à BUG-215 (vague 1 « base réelle », ventes).
Données fictives uniquement.
"""
from datetime import time, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from clients.models import Client
from core.testing import make_bread_price, make_client, make_node, make_user
from sales.models import Invoice

INV = '/api/sales/invoices/'


class Base(TestCase):
    def setUp(self):
        self.node = make_node(code='C8')
        self.bp = make_bread_price('B500', 'Pain 500 FC', 500)
        self.fact = make_user('FACTURIER', node=self.node, team='A')
        self.other_node = make_node(code='C9')
        self.fact_other = make_user('FACTURIER', node=self.other_node, team='A')
        self.cl = make_client(self.node)
        self.api = APIClient()
        self.api.force_authenticate(self.fact)

    def post(self, **extra):
        p = {'client': str(self.cl.pk), 'payment_type': 'CREDIT', 'payment_amount': 0,
             'lines': [{'bread_price': self.bp.pk, 'quantity': 2}]}
        p.update(extra)
        return self.api.post(INV, p, format='json')


class Bug208209213214Tests(Base):
    def test_quantites_invalides_refusees_en_400_avec_detail(self):
        for q in (-3, 0, 'abc', 1.5, None, 10 ** 9):
            r = self.post(lines=[{'bread_price': self.bp.pk, 'quantity': q}])
            self.assertEqual(r.status_code, 400, q)
            self.assertIn('detail', r.data)
        self.assertEqual(Invoice.objects.count(), 0)

    def test_ligne_mal_formee_refusee(self):
        for line in ({'quantity': 2}, {'bread_price': 'x', 'quantity': 2}, {'bread_price': self.bp.pk}):
            self.assertEqual(self.post(lines=[line]).status_code, 400, line)

    def test_ligne_valide_acceptee(self):
        r = self.post(payment_type='CASH', payment_amount=1000,
                      lines=[{'bread_price': str(self.bp.pk), 'quantity': '2'}])
        self.assertEqual(r.status_code, 201, r.data)

    def test_versement_negatif_refuse(self):
        self.assertEqual(self.post(payment_amount='-500').status_code, 400)
        r = self.api.post(INV, {'client': str(self.cl.pk), 'payment_type': 'CASH',
                                'payment_amount': '-3000', 'is_debt_repayment': True, 'lines': []}, format='json')
        self.assertEqual(r.status_code, 400)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, 0)

    def test_remboursement_a_zero_refuse_et_positif_accepte(self):
        body = {'client': str(self.cl.pk), 'payment_type': 'CASH', 'is_debt_repayment': True, 'lines': []}
        r = self.api.post(INV, dict(body, payment_amount='0'), format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Invoice.objects.count(), 0)
        r = self.api.post(INV, dict(body, payment_amount='100'), format='json')
        self.assertEqual(r.status_code, 201, r.data)

    def test_vente_sans_client_a_credit_ou_sous_payee_refusee(self):
        lines = [{'bread_price': self.bp.pk, 'quantity': 2}]
        r = self.api.post(INV, {'payment_type': 'CREDIT', 'payment_amount': 0, 'lines': lines}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.api.post(INV, {'payment_type': 'CASH', 'payment_amount': 500, 'lines': lines}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.api.post(INV, {'payment_type': 'CASH', 'payment_amount': 1000, 'lines': lines}, format='json')
        self.assertEqual(r.status_code, 201, r.data)


class Bug210Tests(Base):
    def test_taux_hors_liste_refuse(self):
        for rate in ('1.00', '-0.50', '5.00', '0.10'):
            r = self.post(payment_type='CASH', payment_amount=1000, commission_rate=rate)
            self.assertEqual(r.status_code, 400, rate)

    def test_taux_du_client_impose_par_le_serveur(self):
        Client.objects.filter(pk=self.cl.pk).update(commission_rate='0.30')
        r = self.post(payment_type='CASH', payment_amount=1000)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Decimal(str(r.data['commission_rate'])), Decimal('0.30'))
        # un taux valide envoyé par le client HTTP n'écrase pas celui du client
        r = self.post(payment_type='CASH', payment_amount=1000, commission_rate='0.25')
        self.assertEqual(Decimal(str(r.data['commission_rate'])), Decimal('0.30'))


class BreadSummaryTests(Base):
    def _delivered(self, delivered_at, **extra):
        r = self.post(payment_type='CASH', payment_amount=1000, **extra)
        self.assertEqual(r.status_code, 201, r.data)
        Invoice.objects.filter(pk=r.data['id']).update(status='DELIVERED', delivered_at=delivered_at)
        return r

    def test_pas_de_fuite_vers_une_autre_boulangerie(self):
        self._delivered(timezone.now())
        other = APIClient()
        other.force_authenticate(self.fact_other)
        d = timezone.localdate().isoformat()
        resp = other.get(INV + 'bread_summary/', {'date': d, 'node': self.node.pk})
        self.assertEqual(resp.status_code, 403)
        resp = other.get(INV + 'bread_summary/', {'date': d})
        self.assertEqual(resp.data['grand_total_qty'], 0)
        own = self.api.get(INV + 'bread_summary/', {'date': d, 'node': self.node.pk})
        self.assertEqual(own.data['grand_total_qty'], 2)

    def test_direction_peut_cibler_un_noeud(self):
        self._delivered(timezone.now())
        direction = APIClient()
        direction.force_authenticate(make_user('DIRECTION'))
        d = timezone.localdate().isoformat()
        r = direction.get(INV + 'bread_summary/', {'date': d, 'node': self.node.pk})
        self.assertEqual(r.data['grand_total_qty'], 2)
        r = direction.get(INV + 'bread_summary/', {'date': d, 'node': self.other_node.pk})
        self.assertEqual(r.data['grand_total_qty'], 0)

    def test_suit_le_jour_calendaire_en_rotation(self):
        # BUG-247 (décision 2026-11-12) : même en rotation, le récapitulatif
        # suit le JOUR CALENDAIRE (minuit à minuit), pas la relève.
        from datetime import datetime
        from core.workday import work_date_for, shift_date
        from production.models import DailyTeamAssignment
        self.node.team_rotation_enabled = True
        self.node.handover_time = time(12, 0)
        self.node.save()
        wd = work_date_for(self.node)
        DailyTeamAssignment.objects.create(node=self.node, work_date=shift_date(self.node), team='A', assigned_by=self.fact)
        inst = timezone.make_aware(datetime.combine(wd, time(3, 0)), timezone.get_current_timezone())
        self._delivered(inst)
        resp = self.api.get(INV + 'bread_summary/', {'date': str(wd)})
        self.assertEqual(resp.data['grand_total_qty'], 2)
        resp = self.api.get(INV + 'bread_summary/', {'date': str(wd - timedelta(days=1))})
        self.assertEqual(resp.data['grand_total_qty'], 0)

    def test_date_invalide_400(self):
        self.assertEqual(self.api.get(INV + 'bread_summary/', {'date': 'n/a'}).status_code, 400)


class ModificationDirecteTests(Base):
    def setUp(self):
        super().setUp()
        self.g = APIClient()
        self.g.force_authenticate(make_user('GERANT', node=self.node))

    def _livree(self):
        r = self.post()
        Invoice.objects.filter(pk=r.data['id']).update(status='DELIVERED', delivered_at=timezone.now())
        return r.data['id']

    def test_put_patch_delete_interdits(self):
        pk = self._livree()
        url = f'{INV}{pk}/'
        # BUG-233 : PATCH est rouvert pour `commission_exempt` SEUL ; tout autre
        # champ (paiement, statut, ...) reste refusé (400) et la facture inchangée.
        self.assertEqual(self.g.patch(url, {'payment_amount': '1000'}, format='json').status_code, 400)
        self.assertEqual(self.g.patch(url, {'status': 'CANCELLED'}, format='json').status_code, 400)
        self.assertEqual(Invoice.objects.get(pk=pk).payment_amount, 0)
        self.assertEqual(self.g.put(url, {}, format='json').status_code, 405)
        self.assertEqual(self.g.delete(url).status_code, 405)
        self.assertTrue(Invoice.objects.filter(pk=pk).exists())

    def test_lectures_et_actions_metier_toujours_disponibles(self):
        pk = self._livree()
        self.assertEqual(self.g.get(INV).status_code, 200)
        self.assertEqual(self.g.get(f'{INV}{pk}/').status_code, 200)
        r = self.g.post(f'{INV}{pk}/adjust/', {
            'adjustment_sign': 1, 'payment_amount': '0',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 1}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
