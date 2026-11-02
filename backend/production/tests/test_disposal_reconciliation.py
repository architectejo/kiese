"""
Pains non vendus au prix fort / Réconciliation — BUG-014, CLAUDE.md §5.4.

- BreadDisposal (soldés, déclassés, invendus, sorties gratuites, reste à
  vendre) : impact correct sur le stock.
- Réconciliation : écart production déclarée − (ventes + retours), en pains
  et en FC.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price, make_client
from production.models import BreadStock, BreadDisposal, ProductionSession, _adjust_bread_stock


class BreadDisposalCategorizationTests(TestCase):
    """Pains non vendus au prix fort : chaque catégorie affecte le stock correctement."""

    def setUp(self):
        self.node = make_node()
        self.user = make_user(role='GERANT', node=self.node)
        self.bp = make_bread_price(category='MOYEN', label='Pain 500 FC', unit_price=500)
        _adjust_bread_stock(self.node, self.bp, produced=1000)
        self.session = ProductionSession.objects.create(
            node=self.node, team='A', date='2026-10-06', declared_by=self.user, node_origin=self.node.code,
        )
        self.client_api = APIClient()
        self.client_api.force_authenticate(self.user)

    def _dispose(self, disposal_type, qty, unit_price_sold=0):
        return self.client_api.post('/api/production/disposals/', {
            'session': str(self.session.pk),
            'bread_price': self.bp.pk, 'disposal_type': disposal_type,
            'quantity': qty, 'unit_price_sold': unit_price_sold,
        }, format='json')

    def test_declassed_unsold_free_dist_decrement_stock(self):
        """
        BUG-092 : `SOLD_DISCOUNT` retiré de ce scénario — la vente soldée
        passe désormais exclusivement par la facturation (`Invoice.is_soldee`,
        voir `sales/tests/test_invoices.py`). Les trois autres types restent
        pleinement fonctionnels, sans aucun changement de comportement.
        """
        for disposal_type, qty in [
            ('DECLASSED', 20), ('UNSOLD', 10), ('FREE_DIST', 5),
        ]:
            resp = self._dispose(disposal_type, qty, unit_price_sold=0)
            self.assertEqual(resp.status_code, 201, resp.data)

        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp)
        # 1000 produits - (20+10+5) disposés = 965
        self.assertEqual(stock.qty_available, 1000 - 35)

    def test_remaining_does_not_decrement_stock(self):
        """REMAINING = reste à vendre demain : ne doit pas sortir du stock."""
        resp = self._dispose('REMAINING', 100)
        self.assertEqual(resp.status_code, 201, resp.data)
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp)
        self.assertEqual(stock.qty_available, 1000)

    def test_sold_discount_creation_is_rejected_with_clear_message(self):
        """
        BUG-092, décision du coordinateur : le pain soldé s'enregistre
        désormais exclusivement depuis Facturation/Gestion Clientèle
        (`Invoice.is_soldee`) — la création d'un nouveau `BreadDisposal`
        `SOLD_DISCOUNT` doit être refusée (400), message clair à l'appui,
        sans toucher au stock.
        """
        stock_before = BreadStock.objects.get(node=self.node, bread_price=self.bp).qty_available
        resp = self._dispose('SOLD_DISCOUNT', 10, unit_price_sold=300)
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn('disposal_type', resp.data)
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp)
        self.assertEqual(stock.qty_available, stock_before)

    def test_sold_discount_historical_entry_still_readable(self):
        """
        BUG-092 : seule la CRÉATION de nouvelles entrées `SOLD_DISCOUNT` est
        bloquée — une entrée historique (créée directement en base, comme
        l'étaient celles saisies avant cette correction) doit rester lisible
        normalement via l'API (liste + détail), total_value inchangé.
        """
        historical = BreadDisposal.objects.create(
            node=self.node, session=self.session, bread_price=self.bp,
            disposal_type=BreadDisposal.DisposalType.SOLD_DISCOUNT,
            quantity=10, unit_price_sold=300, node_origin=self.node.code,
        )
        self.assertEqual(historical.total_value, Decimal('3000.00'))

        detail_resp = self.client_api.get(f'/api/production/disposals/{historical.pk}/')
        self.assertEqual(detail_resp.status_code, 200, detail_resp.data)
        self.assertEqual(detail_resp.data['disposal_type'], 'SOLD_DISCOUNT')
        self.assertEqual(Decimal(detail_resp.data['total_value']), Decimal('3000.00'))

        list_resp = self.client_api.get('/api/production/disposals/', {'disposal_type': 'SOLD_DISCOUNT'})
        self.assertEqual(list_resp.status_code, 200, list_resp.data)
        results = list_resp.data.get('results', list_resp.data)
        self.assertEqual(len(results), 1)

    def test_sold_discount_cannot_be_reintroduced_via_patch(self):
        """
        BUG-106 (vérification indépendante de BUG-092) : `BreadDisposalViewSet.
        perform_create` refuse bien la création directe d'un `SOLD_DISCOUNT`
        (voir test ci-dessus), mais `BreadDisposalViewSet` n'a pas de
        `perform_update`/`update` qui reprenne le même garde-fou. Un GERANT
        peut donc créer une entrée `DECLASSED` (autorisée) puis la PATCHer en
        `disposal_type=SOLD_DISCOUNT` : la restriction est entièrement
        contournée et la duplication Production/Ventes que BUG-092 devait
        éliminer redevient possible par ce chemin détourné.
        """
        create_resp = self._dispose('DECLASSED', 10, unit_price_sold=0)
        self.assertEqual(create_resp.status_code, 201, create_resp.data)
        disposal_id = create_resp.data['id']

        patch_resp = self.client_api.patch(f'/api/production/disposals/{disposal_id}/', {
            'disposal_type': 'SOLD_DISCOUNT', 'unit_price_sold': 300,
        }, format='json')
        # Devrait être refusé (400), comme à la création — ce n'est pas le cas.
        self.assertEqual(patch_resp.status_code, 400, patch_resp.data)


class ProductionSalesReconciliationTests(TestCase):
    """
    CLAUDE.md §5.4 : écart = production déclarée − (ventes + retours), en
    pains et en FC, pour une boulangerie et une période donnée.
    """

    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.user = make_user(role='GERANT', node=self.node)
        self.bp = make_bread_price(category='MOYEN', label='Pain 500 FC', unit_price=500)
        self.client_api = APIClient()
        self.client_api.force_authenticate(self.user)

    def test_reconciliation_endpoint_computes_gap_between_production_and_sales(self):
        """
        Déclare 1 fournée de 200 pains à 500 FC (100 000 FC produits), vend
        150 pains (75 000 FC) sans aucun retour : l'écart attendu est de
        50 pains / 25 000 FC restant non vendu (hors soldes/dons/invendus).
        Aucun endpoint de réconciliation production ↔ ventes n'existe
        actuellement dans l'API (`production` ni `sales`).
        """
        declare_resp = self.client_api.post('/api/production/sessions/', {
            'team': 'A', 'date': '2026-10-06', 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 200}],
        }, format='json')
        self.assertEqual(declare_resp.status_code, 201, declare_resp.data)

        resp = self.client_api.get('/api/production/sessions/reconciliation/', {
            'node': self.node.pk, 'date': '2026-10-06',
        })
        self.assertEqual(
            resp.status_code, 200,
            "Aucun endpoint de réconciliation (production déclarée − "
            "(ventes + retours), en pains et en FC) n'est implémenté — "
            f"réponse reçue : {resp.status_code}."
        )

    def test_reconciliation_values_are_correct_with_real_sale_and_disposal(self):
        """
        Vérification indépendante des CHIFFRES renvoyés (pas seulement du
        code 200) — le test initial de dev-backend ne crée ni vente ni
        disposition réelle et ne vérifie jamais la formule elle-même.
        Scénario : 200 pains produits à 500 FC (100 000 FC) ; une facture
        livrée de 120 pains (60 000 FC) ; une disposition DECLASSED de 30
        pains à 0 FC (non valorisée, 0 FC). Écart attendu :
          pains = 200 - (120 + 30) = 50
          fc    = 100000 - (60000 + 0) = 40000
        """
        from sales.models import Invoice, InvoiceLine

        declare_resp = self.client_api.post('/api/production/sessions/', {
            'team': 'A', 'date': '2026-10-06', 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 200}],
        }, format='json')
        self.assertEqual(declare_resp.status_code, 201, declare_resp.data)
        session_id = declare_resp.data['id']

        client_obj = make_client(self.node)
        facturier = make_user('FACTURIER', node=self.node)
        sales_api = APIClient()
        sales_api.force_authenticate(facturier)

        invoice_resp = sales_api.post('/api/sales/invoices/', {
            'client': str(client_obj.pk), 'payment_type': 'CASH', 'payment_amount': '60000',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 120}],
        }, format='json')
        self.assertEqual(invoice_resp.status_code, 201, invoice_resp.data)
        invoice = Invoice.objects.get(pk=invoice_resp.data['id'])
        # Important : la facture doit être au statut DELIVERED pour compter
        # comme une vente dans la réconciliation (CLAUDE.md §5.2) — une
        # facture seulement PENDING ne doit pas apparaître dans `sales`.
        invoice.invoice_date = declare_resp.data['date']
        invoice.save(update_fields=['invoice_date'])
        deliver_resp = sales_api.post(f'/api/sales/invoices/{invoice.pk}/deliver/')
        self.assertEqual(deliver_resp.status_code, 200, deliver_resp.data)

        disposal_resp = self.client_api.post('/api/production/disposals/', {
            'session': session_id, 'bread_price': self.bp.pk,
            'disposal_type': 'DECLASSED', 'quantity': 30, 'unit_price_sold': 0,
        }, format='json')
        self.assertEqual(disposal_resp.status_code, 201, disposal_resp.data)

        resp = self.client_api.get('/api/production/sessions/reconciliation/', {
            'node': self.node.pk, 'date': '2026-10-06',
        })
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['production_declared']['breads'], 200)
        self.assertEqual(Decimal(resp.data['production_declared']['fc']), Decimal('100000'))
        self.assertEqual(resp.data['sales']['breads'], 120)
        self.assertEqual(Decimal(resp.data['sales']['fc']), Decimal('60000.00'))
        self.assertEqual(resp.data['returns']['breads'], 30)
        self.assertEqual(Decimal(resp.data['returns']['fc']), Decimal('0.00'))
        self.assertEqual(resp.data['gap']['breads'], 50)
        self.assertEqual(Decimal(resp.data['gap']['fc']), Decimal('40000'))
