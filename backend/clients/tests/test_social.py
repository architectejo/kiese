"""
Tests Caisse Sociale — cotisations, distributions, lignes (CLAUDE.md
§5.1, BUG-012).
"""
from decimal import Decimal
from unittest import expectedFailure

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from core.testing import make_node, make_user, make_client
from clients.models import Client, SocialContribution, SocialDistribution, SocialDistributionLine


class SocialContributionTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.client1 = make_client(self.node, first_name='DEMO', last_name='Cotisant1')
        self.client1.cotisation_sociale = True
        self.client1.save(update_fields=['cotisation_sociale'])
        self.client2 = make_client(self.node, first_name='DEMO', last_name='Cotisant2')
        self.client2.cotisation_sociale = True
        self.client2.save(update_fields=['cotisation_sociale'])
        self.gerant = make_user(role='GERANT', node=self.node)
        self.api = APIClient()
        self.api.force_authenticate(user=self.gerant)

    def test_bulk_create_month_creates_one_contribution_per_active_client(self):
        resp = self.api.post('/api/clients/contributions/bulk_create_month/', {
            'node': str(self.node.pk), 'month': 10, 'year': 2026, 'amount': '3000.00',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        self.assertEqual(resp.json()['created'], 2)
        self.assertEqual(SocialContribution.objects.filter(node=self.node, month=10, year=2026).count(), 2)

    def test_bulk_create_month_is_idempotent(self):
        self.api.post('/api/clients/contributions/bulk_create_month/', {
            'node': str(self.node.pk), 'month': 10, 'year': 2026,
        }, format='json')
        resp = self.api.post('/api/clients/contributions/bulk_create_month/', {
            'node': str(self.node.pk), 'month': 10, 'year': 2026,
        }, format='json')
        self.assertEqual(resp.json()['created'], 0)
        self.assertEqual(resp.json()['skipped'], 2)

    def test_toggle_paid_sets_timestamp(self):
        contrib = SocialContribution.objects.create(client=self.client1, node=self.node, month=10, year=2026, amount=Decimal('3000.00'))
        resp = self.api.post(f'/api/clients/contributions/{contrib.pk}/toggle_paid/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        contrib.refresh_from_db()
        self.assertTrue(contrib.is_paid)
        self.assertIsNotNone(contrib.paid_at)


class SocialDistributionTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.client1 = make_client(self.node, first_name='DEMO', last_name='Distrib1')
        self.client1.cotisation_sociale = True
        self.client1.save(update_fields=['cotisation_sociale'])
        self.gerant = make_user(role='GERANT', node=self.node)
        self.api = APIClient()
        self.api.force_authenticate(user=self.gerant)

        for month in range(1, 4):
            SocialContribution.objects.create(
                client=self.client1, node=self.node, month=month, year=2026,
                amount=Decimal('3000.00'), is_paid=True,
            )

    # BUG-018 (docs/qa/REGISTRE_BUGS.md) — corrigé : `@expectedFailure` retiré
    # définitivement (le laisser ferait échouer `manage.py test` par
    # "unexpected success" maintenant que le test passe réellement).
    def test_auto_populate_lines_computes_indice_and_remise(self):
        distribution = SocialDistribution.objects.create(node=self.node, year=2026, tarif=Decimal('700.00'))
        resp = self.api.post(f'/api/clients/distributions/{distribution.pk}/auto_populate_lines/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        line = SocialDistributionLine.objects.get(distribution=distribution, client=self.client1)
        self.assertEqual(line.indice, 3)
        self.assertEqual(line.total_social, Decimal('9000.00'))
        self.assertEqual(line.remise, Decimal('2100.00'))  # 3 x 700
        self.assertEqual(line.total_payer, Decimal('11100.00'))  # social + remise + merite(0)

    def test_closed_distribution_rejects_new_auto_populate(self):
        distribution = SocialDistribution.objects.create(node=self.node, year=2026, tarif=Decimal('700.00'), is_closed=True)
        resp = self.api.post(f'/api/clients/distributions/{distribution.pk}/auto_populate_lines/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
