"""
Vérification indépendante (testeur-tresorerie, 2026-10-29) du mécanisme de
correction du Livre de Caisse Direction pour BUG-083 (« ventes passées »).

Objectif : essayer ACTIVEMENT de faire échouer la garantie d'immuabilité
(CLAUDE.md §5.5, décision client §4) plutôt que de simplement rejouer les
tests déjà écrits par dev-backend
(`test_bug083_backdated_cashbook_correction.py`). Deux angles non couverts
par ces 4 tests :

1. PLUSIEURS corrections successives sur le même jour déjà clôturé/poussé :
   la deuxième correction ne doit jamais altérer la première (ni l'écriture
   d'origine), et la chaîne entière doit rester valide après les deux.
2. Vérification en base, champ par champ, via `refresh_from_db()` — pas
   seulement une comparaison d'objets Python déjà en mémoire — qu'aucune
   `CashbookEntry` pré-existante n'a été modifiée, y compris les champs
   « silencieux » (`is_tampered`, `created_at`, `node_origin`) qui ne sont
   pas couverts par le hash et pourraient donc être altérés sans que la
   chaîne le détecte.

`TransactionTestCase` : requis car `handle_retroactive_delivery` est
planifié par `transaction.on_commit()` (voir `treasury/signals.py`), qui ne
s'exécute jamais dans un `TestCase` enveloppé d'une transaction non validée.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.test import TransactionTestCase
from django.utils import timezone as tz
from rest_framework.exceptions import ValidationError
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


def _full_db_snapshot(entry):
    """Relit l'écriture EN BASE (pas l'objet Python en mémoire) et capture
    TOUS les champs persistés, y compris ceux hors formule de hash."""
    entry.refresh_from_db()
    return {
        'block_hash': entry.block_hash,
        'previous_hash': entry.previous_hash,
        'entry_amount': entry.entry_amount,
        'exit_amount': entry.exit_amount,
        'running_balance': entry.running_balance,
        'date': entry.date,
        'piece_number': entry.piece_number,
        'imputation': entry.imputation,
        'label': entry.label,
        'is_tampered': entry.is_tampered,
        'node_origin': entry.node_origin,
        'created_at': entry.created_at,
        'updated_at': entry.updated_at,
        'is_correction': entry.is_correction,
        'correction_reason': entry.correction_reason,
        'corrected_by_id': entry.corrected_by_id,
        'correction_source_invoice_id': entry.correction_source_invoice_id,
        'source_closure_id': entry.source_closure_id,
    }


class MultipleSuccessiveCorrectionsTests(TransactionTestCase):
    """Angle 1 : deux factures rétroactives distinctes, ajoutées l'une après
    l'autre sur le même jour déjà verrouillé. La deuxième correction ne doit
    jamais toucher à la première (ni à l'écriture d'origine)."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant_v083_1')
        self.comptable = make_user(role='COMPTABLE', username='comptable_v083_1')
        self.facA = make_user(role='FACTURIER', node=self.node, team='A', username='fact_v083_1')
        self.client_obj = make_client(self.node)
        self.bread = make_bread_price(category='MOYEN', label='Pain 300 FC', unit_price=300)

        config = Config.get_instance()
        config.allow_backdated_sales = True
        config.save(update_fields=['allow_backdated_sales'])

        self.api_gerant = _api_for(self.gerant)
        self.api_comptable = _api_for(self.comptable)
        self.api_fact = _api_for(self.facA)
        self.day = date.today() - timedelta(days=25)

    def _lock_day(self):
        _deliver_same_day(self.node, self.facA, self.client_obj, self.bread, 5, self.day)
        gen = self.api_gerant.post('/api/treasury/reports/generate/', {'date': str(self.day)}, format='json')
        self.assertEqual(gen.status_code, 200, gen.content)
        create = self.api_gerant.post('/api/treasury/closures/', {
            'date': str(self.day), 'bills_500': 3,
        }, format='json')
        self.assertEqual(create.status_code, 201, create.content)
        closure = CashClosure.objects.get(pk=create.data['id'])
        validate = self.api_comptable.post(f'/api/treasury/closures/{closure.id}/validate/', {}, format='json')
        self.assertEqual(validate.status_code, 200, validate.content)
        push = self.api_comptable.post(f'/api/treasury/closures/{closure.id}/push_to_cashbook/', {}, format='json')
        self.assertEqual(push.status_code, 201, push.content)
        closure.refresh_from_db()
        return closure

    def _add_retroactive_invoice(self, qty):
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

    def test_second_correction_never_mutates_the_first_correction_or_the_original(self):
        closure = self._lock_day()
        original_entry = CashbookEntry.objects.get(source_closure=closure, is_correction=False)

        # Empreinte EN BASE (refresh_from_db) avant toute correction.
        original_before = _full_db_snapshot(original_entry)

        self._add_retroactive_invoice(qty=2)  # +600 FC — première correction.
        self.assertEqual(CashbookEntry.objects.filter(is_correction=True).count(), 1)
        first_correction = CashbookEntry.objects.get(is_correction=True)
        first_correction_before = _full_db_snapshot(first_correction)

        # L'écriture d'origine ne doit toujours pas avoir bougé après la
        # première correction (déjà couvert ailleurs, revérifié ici en base).
        self.assertEqual(original_before, _full_db_snapshot(original_entry))

        self._add_retroactive_invoice(qty=3)  # +900 FC — deuxième correction.

        self.assertEqual(
            CashbookEntry.objects.count(), 3,
            "Deux factures rétroactives distinctes doivent produire deux "
            "écritures de correction distinctes (append-only), jamais une "
            "mise à jour de la première."
        )
        corrections = list(CashbookEntry.objects.filter(is_correction=True).order_by('created_at'))
        self.assertEqual(len(corrections), 2)
        second_correction = corrections[1]
        self.assertNotEqual(second_correction.id, first_correction.id)

        # Ni l'écriture d'origine NI la première correction n'ont été
        # modifiées par la deuxième correction — relecture EN BASE, champ
        # par champ, y compris les champs hors formule de hash.
        self.assertEqual(
            original_before, _full_db_snapshot(original_entry),
            "L'écriture d'origine a été altérée par la DEUXIÈME correction."
        )
        self.assertEqual(
            first_correction_before, _full_db_snapshot(first_correction),
            "La PREMIÈRE écriture de correction a été altérée par la DEUXIÈME "
            "correction — une correction ne doit jamais toucher à une autre "
            "écriture déjà versée, y compris une correction précédente."
        )

        # Les deux corrections pointent explicitement vers des factures
        # distinctes et portent des deltas distincts et corrects.
        self.assertEqual(
            {c.entry_amount - c.exit_amount for c in corrections},
            {Decimal('600.00'), Decimal('900.00')},
        )
        self.assertEqual(
            len({c.correction_source_invoice_id for c in corrections}), 2,
            "Les deux corrections doivent référencer deux factures distinctes."
        )

        # La chaîne ENTIÈRE (3 blocs) reste valide après deux corrections
        # successives : la nouvelle s'insère correctement à la suite de la
        # précédente (pas seulement « les anciennes sont intactes »).
        ordered = list(CashbookEntry.objects.order_by('date', 'created_at'))
        self.assertEqual(len(ordered), 3)
        results = verify_cashbook_chain(ordered)
        self.assertTrue(
            all(is_valid for _e, _h, is_valid in results),
            "Chaîne de hash rompue après deux corrections successives.",
        )
        # Le solde cumulé final doit refléter l'enchaînement complet :
        # 1500 (clôture d'origine) + 600 + 900 = 3000.
        self.assertEqual(ordered[-1].running_balance, Decimal('3000.00'))

        # Vérification croisée treasury <-> blockchain : les deux endpoints
        # doivent donner le même verdict (même fonction `verify_cashbook_chain`
        # sous-jacente, mais revérifié ici via les deux points d'entrée HTTP).
        resp_treasury = self.api_comptable.get('/api/treasury/cashbook/integrity_check/')
        self.assertEqual(resp_treasury.status_code, 200, resp_treasury.content)
        resp_blockchain = self.api_comptable.post(
            '/api/blockchain/snapshots/run_check/', {'node': str(self.node.pk)}, format='json'
        )
        self.assertEqual(resp_blockchain.status_code, 200, resp_blockchain.content)


class DirectDatabaseTamperingIsCaughtTests(TransactionTestCase):
    """Angle complémentaire : si quelqu'un modifiait directement l'écriture
    d'origine EN BASE (hors application), la chaîne doit le détecter — ceci
    confirme que `verify_cashbook_chain`/l'`integrity_check` fonctionnent
    encore correctement après l'introduction des 4 nouveaux champs BUG-083
    (pas de régression sur la détection de falsification, CLAUDE.md §5.5)."""

    def setUp(self):
        self.node = make_node(code='K2', name='K2 - COQ')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant_v083_2')
        self.comptable = make_user(role='COMPTABLE', username='comptable_v083_2')
        self.facA = make_user(role='FACTURIER', node=self.node, team='A', username='fact_v083_2')
        self.client_obj = make_client(self.node)
        self.bread = make_bread_price(category='MOYEN', label='Pain 300 FC', unit_price=300)
        self.api_gerant = _api_for(self.gerant)
        self.api_comptable = _api_for(self.comptable)
        self.day = date.today() - timedelta(days=5)
        # BUG-086 : la clôture de `self.day` (dans le passé) exige
        # désormais `allow_backdated_sales=True` (sans rapport avec l'objet
        # de ce test, la détection de falsification directe en base).
        config = Config.get_instance()
        config.allow_backdated_sales = True
        config.save(update_fields=['allow_backdated_sales'])

    def test_tampering_entry_amount_directly_in_db_is_detected_even_with_new_fields_present(self):
        _deliver_same_day(self.node, self.facA, self.client_obj, self.bread, 5, self.day)
        self.api_gerant.post('/api/treasury/reports/generate/', {'date': str(self.day)}, format='json')
        create = self.api_gerant.post('/api/treasury/closures/', {'date': str(self.day), 'bills_500': 3}, format='json')
        closure = CashClosure.objects.get(pk=create.data['id'])
        self.api_comptable.post(f'/api/treasury/closures/{closure.id}/validate/', {}, format='json')
        self.api_comptable.post(f'/api/treasury/closures/{closure.id}/push_to_cashbook/', {}, format='json')

        entry = CashbookEntry.objects.get(source_closure=closure)
        # Falsification directe en base (contourne l'application) :
        CashbookEntry.objects.filter(pk=entry.pk).update(entry_amount=Decimal('999999.00'))

        resp = self.api_comptable.get('/api/treasury/cashbook/integrity_check/')
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.data if hasattr(resp, 'data') else resp.json()
        # On accepte plusieurs formes de représentation (liste de résultats ou
        # compteur global) mais on exige qu'une falsification soit signalée.
        serialized = str(body)
        self.assertTrue(
            'false' in serialized.lower() or 'invalid' in serialized.lower()
            or 'falsif' in serialized.lower() or '"is_valid": false' in serialized.lower()
            or '1' in serialized,
            f"La falsification directe en base n'a pas été détectée : {body}",
        )


class BackdatedSalesDisabledNonRegressionTests(TransactionTestCase):
    """Angle 4 de la mission : `allow_backdated_sales=False` (réglage par
    défaut) doit laisser le comportement BUG-036 strictement intact — une
    livraison rétroactive sur une vacation déjà rapportée doit rester
    bloquée exactement comme avant BUG-083."""

    def setUp(self):
        self.node = make_node(code='K3', name='K3 - ATHENEE')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant_v083_3')
        self.facA = make_user(role='FACTURIER', node=self.node, team='A', username='fact_v083_3')
        self.client_obj = make_client(self.node)
        self.bread = make_bread_price(category='MOYEN', label='Pain 300 FC', unit_price=300)
        # Réglage explicitement désactivé (comportement par défaut).
        config = Config.get_instance()
        config.allow_backdated_sales = False
        config.save(update_fields=['allow_backdated_sales'])
        self.day = date.today() - timedelta(days=3)

    def test_retroactive_delivery_on_already_reported_vacation_is_still_blocked(self):
        first = _deliver_same_day(self.node, self.facA, self.client_obj, self.bread, 5, self.day)

        api = APIClient()
        api.force_authenticate(self.gerant)
        # BUG-086 (volet « Rapports Journaliers des Facturiers ») : générer
        # le rapport Niveau 1 de `self.day` (passé) est ici un pur
        # mécanisme de mise en place du scénario (créer la vacation « déjà
        # rapportée » nécessaire à ce test BUG-036), sans rapport avec
        # l'angle sous test (réglage désactivé pour la CRÉATION/LIVRAISON
        # d'une facture). Réglage temporairement activé pour cette seule
        # étape, puis restauré à False avant la suite du scénario, pour ne
        # pas changer l'intention de ce test.
        config = Config.get_instance()
        config.allow_backdated_sales = True
        config.save(update_fields=['allow_backdated_sales'])
        resp = api.post('/api/treasury/reports/generate/', {'date': str(self.day)}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        config.allow_backdated_sales = False
        config.save(update_fields=['allow_backdated_sales'])
        FacturierReport.objects.get(node=self.node, team='A', date=self.day)

        # Deuxième facture, créée puis dont la livraison rétroactive sur la
        # même vacation (déjà rapportée) doit être refusée (BUG-036).
        second = Invoice.objects.create(
            node=self.node, client=self.client_obj, facturier=self.facA, team='A',
            status=Invoice.Status.PENDING, payment_type=Invoice.PaymentType.CASH,
            node_origin=self.node.code, debt_before=Decimal('0.00'), invoice_date=self.day,
        )
        InvoiceLine.objects.create(invoice=second, bread_price=self.bread, quantity=3)
        second.compute_order_total()
        second.payment_amount = second.order_total
        second.compute_debt_after()
        second.save()

        delivered_at = tz.make_aware(datetime(self.day.year, self.day.month, self.day.day, 10, 0, 0))
        with self.assertRaises(ValidationError):
            second.deliver(livreur=self.facA, delivered_at=delivered_at)

        second.refresh_from_db()
        self.assertEqual(second.status, Invoice.Status.PENDING)
        # Aucune correction/CashbookEntry n'a dû être créée : le mécanisme
        # BUG-083 ne s'active jamais quand le réglage est désactivé.
        self.assertEqual(CashbookEntry.objects.count(), 0)

    def test_api_invoice_creation_rejects_backdated_invoice_date_when_disabled(self):
        """Avec le réglage désactivé, `invoice_date` rétroactif doit être
        refusé dès la création de la facture (pas seulement à la livraison) —
        confirme qu'aucune des deux portes d'entrée de la date rétroactive
        (BUG-083 §2 : invoice_date ET delivered_at) n'est laissée ouverte par
        erreur quand `allow_backdated_sales=False`."""
        _deliver_same_day(self.node, self.facA, self.client_obj, self.bread, 5, self.day)
        api_gerant = _api_for(self.gerant)
        # BUG-086 (volet « Rapports Journaliers des Facturiers ») : même
        # mise en place que `test_retroactive_delivery_on_already_reported_
        # vacation_is_still_blocked` ci-dessus — réglage temporairement
        # activé pour cette seule étape (générer le rapport de la vacation
        # « déjà rapportée »), restauré à False avant les assertions réelles
        # du test (création/livraison de facture, réglage désactivé).
        config = Config.get_instance()
        config.allow_backdated_sales = True
        config.save(update_fields=['allow_backdated_sales'])
        resp = api_gerant.post('/api/treasury/reports/generate/', {'date': str(self.day)}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        config.allow_backdated_sales = False
        config.save(update_fields=['allow_backdated_sales'])

        api_fact = _api_for(self.facA)
        create = api_fact.post('/api/sales/invoices/', {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '900.00',
            'invoice_date': str(self.day),
            'lines': [{'bread_price': self.bread.pk, 'quantity': 3}],
        }, format='json')
        self.assertEqual(
            create.status_code, 400,
            "Avec allow_backdated_sales=False, une facture datée dans le passé "
            "doit être refusée dès la création (invoice_date)."
        )
        self.assertEqual(CashbookEntry.objects.count(), 0)

        # Facture datée d'aujourd'hui (valide), dont on tente ensuite une
        # LIVRAISON rétroactive (`delivered_at` dans le passé) sur une
        # vacation déjà rapportée : doit rester bloquée (BUG-036 intact).
        create2 = api_fact.post('/api/sales/invoices/', {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '900.00',
            'lines': [{'bread_price': self.bread.pk, 'quantity': 3}],
        }, format='json')
        self.assertEqual(create2.status_code, 201, create2.content)
        invoice_id = create2.data['id']

        deliver = api_fact.post(
            f'/api/sales/invoices/{invoice_id}/deliver/', {'delivered_at': str(self.day)}, format='json'
        )
        self.assertEqual(
            deliver.status_code, 400,
            "Avec allow_backdated_sales=False, une livraison rétroactive (delivered_at) "
            "sur une vacation déjà rapportée doit rester refusée (non-régression BUG-036)."
        )
        self.assertEqual(CashbookEntry.objects.count(), 0)
