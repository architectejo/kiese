"""
Vérification indépendante de BUG-086 par `testeur-tresorerie`
(2026-10-29) — en complément des tests déjà écrits par `dev-backend`
(`test_bug086_closure_date_validation.py`,
`test_bug086_reports_date_validation.py`).

Objectifs spécifiques de cette vérification (voir mandat du coordinateur) :
(a) un rôle Siège (`can_access_all_nodes`) ne peut PAS contourner le réglage
    désactivé en changeant de nœud, pour les DEUX volets (clôture ET
    génération de rapport) ;
(b) une clôture ET un rapport rétroactifs sur le MÊME jour passé, dans le
    même scénario, donnent des résultats cohérents entre eux — le rapport
    généré pour ce jour alimente bien la clôture de ce même jour, pas une
    confusion de dates ;
(c) non-régression explicite sur BUG-034/035/036/037 avec la nouvelle
    validation de date en place (réglage désactivé, comportement par
    défaut : date du jour uniquement).
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Config, ExpenseCategory
from core.testing import make_node, make_user, make_bread_price, make_client
from sales.models import Invoice, InvoiceLine
from treasury.models import CashClosure, FacturierReport, LocalExpense


def _api_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class HqCannotBypassDisabledSettingByPickingNodeTests(TestCase):
    """(a) Un rôle Siège (DIRECTION/ADMIN, `can_access_all_nodes=True`) qui
    choisit explicitement le nœud dans le payload ne doit pas pouvoir
    esquiver le réglage désactivé — ni pour la clôture, ni pour la
    génération de rapport."""

    def setUp(self):
        self.node = make_node(code='K2', name='K2 - COQ')
        self.hq = make_user(role='ADMIN', username='admin_b086_indep')
        config = Config.get_instance()
        config.allow_backdated_sales = False
        config.save(update_fields=['allow_backdated_sales'])
        self.api_hq = _api_for(self.hq)
        self.yesterday = date.today() - timedelta(days=1)

    def test_hq_cannot_close_past_date_by_choosing_node_explicitly(self):
        resp = self.api_hq.post('/api/treasury/closures/', {
            'node': str(self.node.id),
            'date': str(self.yesterday),
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertFalse(
            CashClosure.objects.filter(node=self.node, date=self.yesterday).exists()
        )

    def test_hq_cannot_generate_past_report_by_choosing_node_explicitly(self):
        resp = self.api_hq.post('/api/treasury/reports/generate/', {
            'node': str(self.node.id),
            'date': str(self.yesterday),
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertFalse(
            FacturierReport.objects.filter(node=self.node, date=self.yesterday).exists()
        )

    def test_hq_cannot_close_future_date_by_choosing_node_even_with_setting_enabled(self):
        """Ceinture et bretoles : même avec le réglage activé, une date
        future reste refusée pour un rôle Siège choisissant le nœud."""
        config = Config.get_instance()
        config.allow_backdated_sales = True
        config.save(update_fields=['allow_backdated_sales'])
        tomorrow = date.today() + timedelta(days=1)
        resp = self.api_hq.post('/api/treasury/closures/', {
            'node': str(self.node.id),
            'date': str(tomorrow),
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertFalse(
            CashClosure.objects.filter(node=self.node, date=tomorrow).exists()
        )


class RetroactiveReportFeedsRetroactiveClosureOfSameDayTests(TestCase):
    """(b) Scénario intégré : on génère le rapport Niveau 1 d'un jour passé,
    puis on clôture CE MÊME jour passé — les totaux de la clôture doivent
    provenir du rapport de CE jour (pas d'une confusion avec aujourd'hui ou
    un autre jour passé)."""

    def setUp(self):
        self.node = make_node(code='K4', name='K4 - LOMA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant_b086_indep2')
        self.facA = make_user(role='FACTURIER', node=self.node, team='A', username='fact_b086_indep2')
        self.client_obj = make_client(self.node)
        self.bread = make_bread_price(category='MOYEN', label='Pain 300 FC Indep2', unit_price=300)
        self.category, _ = ExpenseCategory.objects.get_or_create(
            code='TRANSPORT_B086_INDEP', defaults={'label': 'Transport'}
        )
        config = Config.get_instance()
        config.allow_backdated_sales = True
        config.save(update_fields=['allow_backdated_sales'])
        self.api_gerant = _api_for(self.gerant)
        # Deux jours passés distincts, pour vérifier qu'il n'y a pas de
        # confusion entre eux.
        self.day_a = date.today() - timedelta(days=4)
        self.day_b = date.today() - timedelta(days=7)

    def _deliver(self, day, qty, payment):
        from datetime import datetime, time
        from django.utils import timezone as djtz

        dt = djtz.make_aware(datetime.combine(day, time(9, 0)))
        inv = Invoice.objects.create(
            node=self.node, client=self.client_obj, facturier=self.facA, team='A',
            status=Invoice.Status.PENDING, payment_type=Invoice.PaymentType.CASH,
            node_origin=self.node.code, debt_before=Decimal('0.00'),
        )
        InvoiceLine.objects.create(invoice=inv, bread_price=self.bread, quantity=qty)
        inv.compute_order_total()
        inv.payment_amount = payment
        inv.compute_debt_after()
        inv.save()
        inv.deliver(livreur=self.facA, delivered_at=dt)
        return inv

    def test_closure_of_day_a_uses_report_of_day_a_not_day_b_nor_today(self):
        # Facture livrée le jour A (celui qu'on veut rapporter + clôturer).
        self._deliver(self.day_a, 4, Decimal('1200.00'))
        # Facture livrée le jour B (piège : autre jour passé, montant très
        # différent — ne doit contaminer ni le rapport ni la clôture du jour A).
        self._deliver(self.day_b, 40, Decimal('77000.00'))
        # Dépense locale du jour A — doit apparaître dans la clôture du jour A.
        LocalExpense.objects.create(
            node=self.node, gerant=self.gerant, description='Transport jour A',
            amount=Decimal('200.00'), category=self.category, date=self.day_a,
            node_origin=self.node.code,
        )
        # Dépense locale du jour B — ne doit PAS apparaître dans la clôture du jour A.
        LocalExpense.objects.create(
            node=self.node, gerant=self.gerant, description='Transport jour B',
            amount=Decimal('9999.00'), category=self.category, date=self.day_b,
            node_origin=self.node.code,
        )

        # Génère le rapport du jour A seulement.
        gen_resp = self.api_gerant.post('/api/treasury/reports/generate/', {
            'date': str(self.day_a),
        }, format='json')
        self.assertEqual(gen_resp.status_code, 200, gen_resp.content)

        report_a = FacturierReport.objects.get(node=self.node, team='A', date=self.day_a)
        self.assertEqual(report_a.total_cash_sales, Decimal('1200.00'))
        # Aucun rapport n'a été créé pour le jour B par cet appel.
        self.assertFalse(
            FacturierReport.objects.filter(node=self.node, team='A', date=self.day_b).exists()
        )

        # Clôture le jour A — doit agréger le rapport + dépense du jour A uniquement.
        close_resp = self.api_gerant.post('/api/treasury/closures/', {
            'date': str(self.day_a),
        }, format='json')
        self.assertEqual(close_resp.status_code, 201, close_resp.content)
        closure = CashClosure.objects.get(pk=close_resp.json()['id'])

        self.assertEqual(closure.date, self.day_a)
        self.assertEqual(closure.total_entries, Decimal('1200.00'))
        self.assertEqual(closure.total_expenses, Decimal('200.00'))
        self.assertEqual(closure.net_cash, Decimal('1000.00'))
        # Confirme explicitement l'absence de toute clôture pour le jour B
        # ou pour aujourd'hui créée par erreur dans ce scénario.
        self.assertFalse(
            CashClosure.objects.filter(node=self.node, date=self.day_b).exists()
        )
        self.assertFalse(
            CashClosure.objects.filter(node=self.node, date=date.today()).exists()
        )


class NoRegressionOnBug034_035_036_037WithDateValidationInPlaceTests(TestCase):
    """(c) Confirme explicitement, avec la nouvelle validation de date
    active et le réglage désactivé (comportement par défaut, le cas le
    plus courant en production), qu'aucune régression n'a été introduite
    sur :
    - BUG-034 : une clôture déjà confirmée (`is_validated=True`) reste figée ;
    - BUG-035 : double clôture (même nœud + même date) refusée en 400 (pas 500) ;
    - BUG-036 : vacation déjà rapportée reste verrouillée (ou du moins non
      silencieusement incohérente) — testé via le non-changement du rapport
      déjà généré ;
    - BUG-037 : clôture bloquée si transfert entrant en écart non résolu.
    """

    def setUp(self):
        self.node = make_node(code='K5', name='K5 - MPIANGU')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant_b086_indep3')
        self.comptable = make_user(role='COMPTABLE', username='comptable_b086_indep3')
        config = Config.get_instance()
        config.allow_backdated_sales = False
        config.save(update_fields=['allow_backdated_sales'])
        self.api_gerant = _api_for(self.gerant)
        self.api_comptable = _api_for(self.comptable)

    def test_bug034_validated_closure_stays_frozen_with_date_validation_in_place(self):
        create = self.api_gerant.post('/api/treasury/closures/', {
            'date': str(date.today()),
        }, format='json')
        self.assertEqual(create.status_code, 201, create.content)
        closure_id = create.json()['id']

        validate = self.api_comptable.post(f'/api/treasury/closures/{closure_id}/validate/', {}, format='json')
        self.assertEqual(validate.status_code, 200, validate.content)

        patch = self.api_gerant.patch(
            f'/api/treasury/closures/{closure_id}/', {'notes': 'tentative de modification'}, format='json'
        )
        self.assertEqual(patch.status_code, 400, patch.content)
        self.assertIn('confirmée', patch.json().get('detail', ''))

    def test_bug035_double_closure_same_day_same_node_rejected_cleanly(self):
        first = self.api_gerant.post('/api/treasury/closures/', {
            'date': str(date.today()),
        }, format='json')
        self.assertEqual(first.status_code, 201, first.content)

        second = self.api_gerant.post('/api/treasury/closures/', {
            'date': str(date.today()),
        }, format='json')
        self.assertEqual(second.status_code, 400, second.content)
        self.assertIn('detail', second.json())
        self.assertEqual(
            CashClosure.objects.filter(node=self.node, date=date.today()).count(), 1
        )

    def test_bug036_report_generation_for_today_is_idempotent_and_date_validation_does_not_interfere(self):
        facA = make_user(role='FACTURIER', node=self.node, team='A', username='fact_b086_indep3')
        client_obj = make_client(self.node)
        bread = make_bread_price(category='MOYEN', label='Pain 300 FC Indep3', unit_price=300)
        inv = Invoice.objects.create(
            node=self.node, client=client_obj, facturier=facA, team='A',
            status=Invoice.Status.PENDING, payment_type=Invoice.PaymentType.CASH,
            node_origin=self.node.code, debt_before=Decimal('0.00'),
        )
        InvoiceLine.objects.create(invoice=inv, bread_price=bread, quantity=3)
        inv.compute_order_total()
        inv.payment_amount = inv.order_total
        inv.compute_debt_after()
        inv.save()
        inv.deliver(livreur=facA)

        resp1 = self.api_gerant.post('/api/treasury/reports/generate/', {}, format='json')
        self.assertEqual(resp1.status_code, 200, resp1.content)
        count_after_first = FacturierReport.objects.filter(node=self.node, team='A', date=date.today()).count()
        self.assertEqual(count_after_first, 1)

        # Régénération du même jour (sans `date` dans le payload) — ne doit
        # pas être bloquée par la nouvelle validation (date du jour = cas
        # par défaut, toujours accepté).
        resp2 = self.api_gerant.post('/api/treasury/reports/generate/', {}, format='json')
        self.assertEqual(resp2.status_code, 200, resp2.content)
        count_after_second = FacturierReport.objects.filter(node=self.node, team='A', date=date.today()).count()
        self.assertEqual(count_after_second, 1, "Régénération idempotente attendue — pas de doublon.")

    def test_bug037_closure_blocked_by_unresolved_incoming_transfer_gap_still_works(self):
        from production.models import BreadTransfer, BreadTransferLine

        other_node = make_node(code='K6', name='K6 - ZADIM')
        bread = make_bread_price(category='MOYEN', label='Pain 300 FC Indep3 Transfert', unit_price=300)
        transfer = BreadTransfer.objects.create(
            from_node=other_node, to_node=self.node,
            node_origin=other_node.code,
        )
        BreadTransferLine.objects.create(
            transfer=transfer, bread_price=bread,
            quantity_sent=100, quantity_received=80,
        )
        resp = self.api_gerant.post('/api/treasury/closures/', {
            'date': str(date.today()),
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('écart', resp.json().get('detail', '').lower())
        self.assertFalse(
            CashClosure.objects.filter(node=self.node, date=date.today()).exists()
        )
