"""
Passage de non-régression COMPLET Clients/Commissions (2026-10-29), demandé
par le coordinateur après BUG-083 (avertissement vente rétroactive en
période verrouillée) et BUG-086 (validation de date partagée).

Objectif de ce fichier : prouver que le parcours NORMAL (sans aucune date
rétroactive, sans toucher `Config.allow_backdated_sales`) d'un gérant qui
crée un client puis fait facturer/livrer une commande par un facturier se
comporte EXACTEMENT comme avant ces deux tickets — aucun champ de date
n'est fourni explicitement nulle part dans ce fichier, afin de rester sur
le chemin "aucune date demandée" de `sales.views._create_once`/`deliver`.

Complète aussi un scénario de CLAUDE.md §5.3 non couvert ailleurs : la
« fiche individuelle des retenues » d'un client (historique de ses
`ClientCommission` à travers plusieurs périodes), via le filtre standard
`?client=<uuid>` de `ClientCommissionViewSet`.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from core.models import Config
from core.testing import make_node, make_user, make_bread_price, make_client
from clients.models import Client
from sales.models import Invoice
from commissions.models import CommissionPeriod, ClientCommission


def _api_for(user):
    api = APIClient()
    api.force_authenticate(user=user)
    return api


class NormalGerantClientAndOrderJourneyTests(TestCase):
    """Parcours normal complet : un gérant crée un client, un facturier le
    facture et livre la commande, aucune date explicite n'est jamais
    fournie — reproduction du comportement attendu AVANT BUG-083/BUG-086.
    """

    def setUp(self):
        self.node = make_node(code='K2', name='K2 - COQ')
        self.bp = make_bread_price(category='MOYEN', label='Pain Test 500 FC', unit_price=500)
        self.gerant = make_user(role='GERANT', node=self.node)
        self.facturier = make_user(role='FACTURIER', node=self.node)
        # Comportement par défaut de l'application fraîchement configurée :
        # `allow_backdated_sales` reste à sa valeur par défaut, jamais touché ici.
        self.assertFalse(Config.get_instance().allow_backdated_sales)

    def test_gerant_creates_client_then_facturier_invoices_and_delivers_without_any_date_field(self):
        # 1. Le gérant crée un client — aucun champ de date dans le payload.
        gerant_api = _api_for(self.gerant)
        create_resp = gerant_api.post('/api/clients/clients/', {
            'first_name': 'Jean',
            'last_name': 'MUKENDI',
            'phone': '0999000111',
        }, format='json')
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED, create_resp.data)

        # NB : la réponse de création ne contient ni `id` ni `code`
        # (BUG-088, docs/qa/REGISTRE_BUGS.md) — on récupère donc le client
        # via l'ORM ici, comme le ferait un gérant en le retrouvant par la
        # recherche prédictive juste après sa création dans l'UI réelle.
        client = Client.objects.get(last_name='MUKENDI', first_name='Jean')

        # Code auto-généré, rattaché au nœud du gérant, plafond par défaut.
        self.assertTrue(client.code)
        self.assertEqual(client.node_id, self.node.id)
        self.assertEqual(client.credit_limit, Decimal('50000.00'))
        self.assertEqual(client.current_debt, Decimal('0.00'))
        self.assertEqual(client.category, Client.Category.NORMAL)

        # 2. Le facturier facture une commande pour ce client — toujours
        # aucun champ de date fourni (ni `invoice_date`, ni `delivered_at`).
        facturier_api = _api_for(self.facturier)
        invoice_resp = facturier_api.post('/api/sales/invoices/', {
            'client': str(client.pk),
            'payment_type': 'CREDIT',
            'payment_amount': '0.00',
            'lines': [{'bread_price': str(self.bp.pk), 'quantity': 20}],
        }, format='json')
        self.assertEqual(invoice_resp.status_code, status.HTTP_201_CREATED, invoice_resp.data)

        invoice = Invoice.objects.get(pk=invoice_resp.data['id'])
        self.assertEqual(invoice.status, Invoice.Status.PENDING)
        self.assertEqual(invoice.order_total, Decimal('10000.00'))  # 20 x 500 FC
        # Comportement par défaut strictement inchangé : date du jour.
        from django.utils import timezone
        self.assertEqual(invoice.invoice_date, timezone.localdate())
        self.assertIsNone(invoice.delivered_at)

        # 3. Le facturier confirme la livraison — toujours sans champ de date.
        deliver_resp = facturier_api.post(f'/api/sales/invoices/{invoice.pk}/deliver/', {}, format='json')
        self.assertEqual(deliver_resp.status_code, status.HTTP_200_OK, deliver_resp.data)

        invoice.refresh_from_db()
        client.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.DELIVERED)
        self.assertIsNotNone(invoice.delivered_at)
        # BP après = BP avant (0) + commande (10000) − versement (0) = 10000 FC.
        self.assertEqual(invoice.debt_after, Decimal('10000.00'))
        self.assertEqual(client.current_debt, Decimal('10000.00'))

        # 4. Génération de la période de commission (direction/HQ) à partir
        # de cette seule facture livrée — formule CM brute = 25 % du défaut.
        direction = make_user(role='DIRECTION', node=None)
        direction_api = _api_for(direction)
        gen_resp = direction_api.post('/api/commissions/periods/generate/', {
            'node': str(self.node.pk),
            'month': timezone.localdate().month,
            'year': timezone.localdate().year,
        }, format='json')
        self.assertEqual(gen_resp.status_code, status.HTTP_201_CREATED, gen_resp.data)

        commission = ClientCommission.objects.get(client=client)
        self.assertEqual(commission.order_value, Decimal('10000.00'))
        self.assertEqual(commission.commission_gross, Decimal('2500.00'))  # 10000 x 0.25


class ClientCommissionIndividualHistoryTests(TestCase):
    """CLAUDE.md §5.3 : « Fiche individuelle des retenues : historique des
    dettes apurées » — reproduite via le filtre `?client=` standard de
    `ClientCommissionViewSet`, qui doit renvoyer l'historique chronologique
    des retenues du client à travers plusieurs périodes de commission."""

    def setUp(self):
        self.node = make_node(code='K4', name='K4 - LOMA')
        self.client = make_client(self.node, commission_rate=Decimal('0.25'))
        self.direction = make_user(role='DIRECTION', node=None)
        self.api = _api_for(self.direction)

        self.period_jan = CommissionPeriod.objects.create(node=self.node, month=1, year=2026)
        self.period_feb = CommissionPeriod.objects.create(node=self.node, month=2, year=2026)

        # Janvier : dette de 5000 FC retenue (en cours d'apurement).
        c1 = ClientCommission.objects.create(
            period=self.period_jan, client=self.client,
            total_breads=100, order_value=Decimal('20000.00'), commission_rate=Decimal('0.25'),
            deduction_debt=Decimal('5000.00'),
        )
        c1.compute()
        c1.save()

        # Février : dette totalement apurée (retenue à 0), nouvelle commission.
        c2 = ClientCommission.objects.create(
            period=self.period_feb, client=self.client,
            total_breads=150, order_value=Decimal('30000.00'), commission_rate=Decimal('0.25'),
            deduction_debt=Decimal('0.00'),
        )
        c2.compute()
        c2.save()

    def test_filtering_by_client_returns_full_chronological_deduction_history(self):
        resp = self.api.get('/api/commissions/commissions/', {'client': str(self.client.pk)})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        rows = resp.json()
        results = rows['results'] if isinstance(rows, dict) and 'results' in rows else rows
        self.assertEqual(len(results), 2)

        by_month = {r['period'] for r in results}
        self.assertEqual(len(by_month), 2)

        deductions = sorted(Decimal(r['deduction_debt']) for r in results)
        self.assertEqual(deductions, [Decimal('0.00'), Decimal('5000.00')])

        # La dette a bien été intégralement apurée d'une période à l'autre.
        jan_row = next(r for r in results if r['period'] == str(self.period_jan.pk))
        feb_row = next(r for r in results if r['period'] == str(self.period_feb.pk))
        self.assertEqual(Decimal(jan_row['deduction_debt']), Decimal('5000.00'))
        self.assertEqual(Decimal(feb_row['deduction_debt']), Decimal('0.00'))
