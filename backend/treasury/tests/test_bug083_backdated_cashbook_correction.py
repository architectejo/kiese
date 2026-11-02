"""
BUG-083 (« ventes passées », remarque.md l.360) — point non négociable du
cahier des charges (décision client §4, 2026-10-29) :

Une livraison rétroactive qui tombe sur un jour dont la `CashClosure` est
déjà validée (et déjà inscrite au Livre de Caisse Direction) ne doit
JAMAIS modifier ou supprimer une `CashbookEntry` existante — la chaîne de
hash (CLAUDE.md §5.5) doit rester strictement intacte. Toute correction se
fait par une NOUVELLE écriture, explicitement marquée, datée du jour réel
de la saisie.

`TransactionTestCase` (pas `TestCase`) : le mécanisme de correction est
déclenché par `transaction.on_commit()` (voir `treasury/signals.py`), qui
ne s'exécute jamais dans une transaction de test non validée (voir le
même choix dans `sales.tests.test_invoices.ConcurrentInvoiceBPTests` /
`treasury.tests.test_ledger.ConcurrentAppendTests`).
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TransactionTestCase
from rest_framework.test import APIClient

from core.models import Config
from core.testing import make_node, make_user, make_bread_price, make_client
from sales.models import Invoice, InvoiceLine
from treasury.hashing import verify_cashbook_chain
from treasury.models import CashClosure, CashbookEntry, FacturierReport


def _api_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _deliver_same_day(node, facturier, client_obj, bread, qty, day):
    """Facture créée puis livrée directement à `day` (ORM, hors API — sert
    uniquement à construire l'historique « normal » du jour D avant que ce
    jour ne soit rapporté/clôturé/poussé)."""
    from django.utils import timezone as tz
    from datetime import datetime

    inv = Invoice.objects.create(
        node=node, client=client_obj, facturier=facturier, team='A',
        status=Invoice.Status.PENDING, payment_type=Invoice.PaymentType.CASH,
        node_origin=node.code, debt_before=Decimal('0.00'), invoice_date=day,
    )
    InvoiceLine.objects.create(invoice=inv, bread_price=bread, quantity=qty)
    inv.compute_order_total()
    inv.payment_amount = inv.order_total
    inv.compute_debt_after()
    inv.save()
    delivered_at = tz.make_aware(datetime(day.year, day.month, day.day, 9, 0, 0))
    inv.deliver(livreur=facturier, delivered_at=delivered_at)
    return inv


class RetroactiveDeliveryOnLockedClosureTests(TransactionTestCase):
    """Le scénario le plus important du ticket : correction SANS jamais
    toucher à une CashbookEntry déjà versée."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant_083')
        self.comptable = make_user(role='COMPTABLE', username='comptable_083')
        self.facA = make_user(role='FACTURIER', node=self.node, team='A', username='fact_083')
        self.client_obj = make_client(self.node)
        self.bread = make_bread_price(category='MOYEN', label='Pain 300 FC', unit_price=300)

        config = Config.get_instance()
        config.allow_backdated_sales = True
        config.save(update_fields=['allow_backdated_sales'])

        self.api_gerant = _api_for(self.gerant)
        self.api_comptable = _api_for(self.comptable)
        self.api_fact = _api_for(self.facA)

        # Jour D largement dans le passé par rapport à "aujourd'hui".
        self.day = date.today() - timedelta(days=20)

    def _lock_day(self):
        """Construit l'historique normal du jour D : facture livrée, rapport
        Niveau 1 généré, clôture Niveau 2 créée + validée + poussée au Livre
        de Caisse — exactement l'état « verrouillé » visé par le ticket."""
        _deliver_same_day(self.node, self.facA, self.client_obj, self.bread, 5, self.day)

        gen = self.api_gerant.post('/api/treasury/reports/generate/', {'date': str(self.day)}, format='json')
        self.assertEqual(gen.status_code, 200, gen.content)

        # 5 pains x 300 FC = 1500 FC cash -> 3 billets de 500 FC comptés.
        create = self.api_gerant.post('/api/treasury/closures/', {
            'date': str(self.day), 'bills_500': 3,
        }, format='json')
        self.assertEqual(create.status_code, 201, create.content)
        closure = CashClosure.objects.get(pk=create.data['id'])
        self.assertEqual(closure.net_cash, Decimal('1500.00'))

        validate = self.api_comptable.post(f'/api/treasury/closures/{closure.id}/validate/', {}, format='json')
        self.assertEqual(validate.status_code, 200, validate.content)

        push = self.api_comptable.post(f'/api/treasury/closures/{closure.id}/push_to_cashbook/', {}, format='json')
        self.assertEqual(push.status_code, 201, push.content)

        closure.refresh_from_db()
        return closure

    def _add_retroactive_invoice(self, qty=2):
        """Nouvelle facture, créée ET livrée via l'API, datée du jour D déjà
        verrouillé — exactement le scénario que le signal BUG-036 bloquait
        avant ce ticket."""
        create = self.api_fact.post('/api/sales/invoices/', {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': str(qty * self.bread.unit_price),
            'invoice_date': str(self.day),
            'lines': [{'bread_price': self.bread.pk, 'quantity': qty}],
        }, format='json')
        self.assertEqual(create.status_code, 201, create.content)
        invoice_id = create.data['id']

        deliver = self.api_fact.post(
            f'/api/sales/invoices/{invoice_id}/deliver/', {'delivered_at': str(self.day)}, format='json'
        )
        self.assertEqual(deliver.status_code, 200, deliver.content)
        return Invoice.objects.get(pk=invoice_id)

    def test_retroactive_delivery_never_mutates_an_existing_cashbook_entry(self):
        closure = self._lock_day()
        original_entry = CashbookEntry.objects.get(source_closure=closure, is_correction=False)

        # Empreinte complète de TOUTES les écritures existantes avant la
        # correction (contenu + hash), pas seulement la dernière.
        before_snapshot = {
            e.id: (e.block_hash, e.previous_hash, e.entry_amount, e.exit_amount, e.running_balance, e.date, e.label)
            for e in CashbookEntry.objects.all()
        }
        self.assertEqual(len(before_snapshot), 1)

        new_invoice = self._add_retroactive_invoice(qty=2)  # +600 FC cash

        after_entries = list(CashbookEntry.objects.all())
        after_snapshot = {
            e.id: (e.block_hash, e.previous_hash, e.entry_amount, e.exit_amount, e.running_balance, e.date, e.label)
            for e in after_entries
        }

        # 1) L'écriture d'origine existe TOUJOURS, strictement inchangée
        #    (égalité stricte de tous ses champs, y compris son hash).
        self.assertIn(original_entry.id, after_snapshot)
        self.assertEqual(
            before_snapshot[original_entry.id], after_snapshot[original_entry.id],
            "BUG-083 (point non négociable) : l'écriture déjà versée au Livre de "
            "Caisse a été modifiée par une correction rétroactive."
        )

        # 2) Une NOUVELLE écriture de correction a été ajoutée (append-only).
        self.assertEqual(len(after_entries), 2)
        correction = CashbookEntry.objects.get(is_correction=True)
        self.assertNotEqual(correction.id, original_entry.id)
        self.assertEqual(correction.correction_source_invoice_id, new_invoice.id)
        self.assertTrue(correction.correction_reason)
        self.assertEqual(correction.corrected_by_id, self.facA.id)

        # 3) La correction est datée du jour RÉEL de la saisie — jamais de
        #    la date rétroactive de la clôture corrigée.
        self.assertEqual(correction.date, date.today())
        self.assertNotEqual(correction.date, self.day)

        # 4) L'écart correspond bien à la vente ajoutée (600 FC cash).
        self.assertEqual(correction.entry_amount - correction.exit_amount, Decimal('600.00'))
        self.assertEqual(correction.running_balance, original_entry.running_balance + Decimal('600.00'))

        # 5) La chaîne de hash tout entière reste valide (pas de fourche, pas
        #    de rupture) après l'ajout de la correction.
        ordered = list(CashbookEntry.objects.order_by('date', 'created_at'))
        results = verify_cashbook_chain(ordered)
        self.assertTrue(all(is_valid for _e, _h, is_valid in results), "Chaîne de hash rompue par la correction.")

    def test_closure_display_totals_are_reopened_without_touching_the_ledger(self):
        closure = self._lock_day()
        original_net_cash = closure.net_cash  # valeur telle que poussée au Livre de Caisse

        self._add_retroactive_invoice(qty=2)  # +600 FC

        closure.refresh_from_db()
        self.assertEqual(
            closure.net_cash, original_net_cash + Decimal('600.00'),
            "Les totaux AFFICHÉS de la clôture doivent être recalculés (réouverture "
            "conceptuelle), même si l'écriture du Livre de Caisse reste inchangée."
        )
        self.assertIn(str(date.today()), closure.notes)

        report = FacturierReport.objects.get(node=self.node, team='A', date=self.day)
        self.assertEqual(report.total_cash_sales, Decimal('2100.00'))  # 1500 + 600

    def test_notification_created_for_the_correction(self):
        from core.models import SystemNotification
        self._lock_day()
        count_before = SystemNotification.objects.count()
        self._add_retroactive_invoice(qty=1)
        self.assertGreater(SystemNotification.objects.count(), count_before)
        self.assertTrue(
            SystemNotification.objects.filter(severity='DANGER').exists(),
            "Une correction du Livre de Caisse doit déclencher une alerte explicite."
        )


class RetroactiveDeliveryOnValidatedButNotPushedClosureTests(TransactionTestCase):
    """Clôture validée mais PAS encore poussée au Livre de Caisse : aucune
    CashbookEntry n'existe encore, donc une simple mise à jour des totaux de
    la clôture suffit (pas de correction à verser)."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant_083b')
        self.comptable = make_user(role='COMPTABLE', username='comptable_083b')
        self.facA = make_user(role='FACTURIER', node=self.node, team='A', username='fact_083b')
        self.client_obj = make_client(self.node)
        self.bread = make_bread_price(category='MOYEN', label='Pain 300 FC', unit_price=300)
        config = Config.get_instance()
        config.allow_backdated_sales = True
        config.save(update_fields=['allow_backdated_sales'])
        self.api_gerant = _api_for(self.gerant)
        self.api_comptable = _api_for(self.comptable)
        self.api_fact = _api_for(self.facA)
        self.day = date.today() - timedelta(days=15)

    def test_no_cashbook_entry_created_when_closure_not_yet_pushed(self):
        _deliver_same_day(self.node, self.facA, self.client_obj, self.bread, 5, self.day)
        self.api_gerant.post('/api/treasury/reports/generate/', {'date': str(self.day)}, format='json')
        create = self.api_gerant.post('/api/treasury/closures/', {'date': str(self.day), 'bills_500': 3}, format='json')
        closure = CashClosure.objects.get(pk=create.data['id'])
        self.api_comptable.post(f'/api/treasury/closures/{closure.id}/validate/', {}, format='json')
        # Volontairement PAS de push_to_cashbook ici.

        create_inv = self.api_fact.post('/api/sales/invoices/', {
            'client': str(self.client_obj.pk), 'payment_type': 'CASH', 'payment_amount': '300.00',
            'invoice_date': str(self.day),
            'lines': [{'bread_price': self.bread.pk, 'quantity': 1}],
        }, format='json')
        invoice_id = create_inv.data['id']
        deliver = self.api_fact.post(
            f'/api/sales/invoices/{invoice_id}/deliver/', {'delivered_at': str(self.day)}, format='json'
        )
        self.assertEqual(deliver.status_code, 200, deliver.content)

        self.assertEqual(CashbookEntry.objects.count(), 0)
        closure.refresh_from_db()
        self.assertEqual(closure.net_cash, Decimal('1800.00'))  # 1500 + 300
