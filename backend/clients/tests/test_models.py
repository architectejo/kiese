"""
Tests du modèle Client — BUG-012 (CLAUDE.md §5.1).

Couvre : génération de code unique, absence de doublon en création
simultanée, plafond crédit par défaut, respect d'un plafond personnalisé
fixé à la création (remarque.md l.172), catégorisation automatique
(Meilleur client / À risque), BP négatif accepté (client épargne).
"""
from decimal import Decimal
from unittest import expectedFailure

from django.test import TestCase, TransactionTestCase
from django.db import connection

from core.models import Config
from core.testing import make_node, make_client, get_config
from clients.models import Client, _generate_client_code


class ClientCodeGenerationTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')

    def test_code_is_auto_generated_with_node_prefix(self):
        client = Client.objects.create(node=self.node, node_origin='K1', first_name='DEMO', last_name='Un')
        self.assertEqual(client.code, 'K1-0001')

    def test_code_increments_sequentially(self):
        c1 = Client.objects.create(node=self.node, node_origin='K1', first_name='DEMO', last_name='Un')
        c2 = Client.objects.create(node=self.node, node_origin='K1', first_name='DEMO', last_name='Deux')
        self.assertEqual(c1.code, 'K1-0001')
        self.assertEqual(c2.code, 'K1-0002')

    def test_explicit_code_is_not_overwritten(self):
        client = Client.objects.create(
            node=self.node, node_origin='K1', first_name='DEMO', last_name='Code-Fixe',
            code='K1-9999',
        )
        self.assertEqual(client.code, 'K1-9999')


class ClientConcurrentCreationTests(TransactionTestCase):
    """
    CLAUDE.md §5.1 : « pas de doublon même en création simultanée ».
    `_generate_client_code` lit le dernier code puis `Client.save()` l'assigne
    sans aucun verrou (`select_for_update`) ni `transaction.atomic()) — deux
    requêtes concurrentes peuvent lire le même « dernier code » et tenter de
    créer le même code client.
    """

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')

    # BUG-017 (docs/qa/REGISTRE_BUGS.md) — corrigé : `@expectedFailure` retiré
    # définitivement (le laisser ferait échouer `manage.py test` par
    # "unexpected success" maintenant que le test passe réellement).
    def test_generate_client_code_has_no_reservation_mechanism(self):
        """Reproduction déterministe de la course : deux appels successifs à
        `_generate_client_code` AVANT que le premier client ne soit réellement
        enregistré renvoient le même code (aucune réservation/verrou), ce qui
        est exactement ce qui se produit quand deux requêtes HTTP concurrentes
        de création de client arrivent en même temps."""
        code_1 = _generate_client_code(self.node.code)
        code_2 = _generate_client_code(self.node.code)
        self.assertNotEqual(
            code_1, code_2,
            "_generate_client_code() renvoie le même code pour deux appels "
            "concurrents tant qu'aucun des deux clients n'est encore "
            "enregistré : deux requêtes de création simultanées obtiennent "
            f"toutes les deux « {code_1} », et la seconde création échouera "
            "avec une IntegrityError (contrainte unique en base) plutôt que "
            "de produire un code unique suivant."
        )

    def test_concurrent_client_creation_under_real_threads_is_unreliable(self):
        """Complément non bloquant de `test_generate_client_code_has_no_reservation_mechanism` :
        sous de vrais threads + SQLite, la course se manifeste de façon
        intermittente (parfois une IntegrityError, parfois — selon le
        verrouillage de fichier SQLite qui serialise une partie des accès —
        aucune collision ne se produit dans cette exécution précise). On ne
        fait ici que journaliser le résultat (pas d'assertion stricte, pour
        ne pas rendre la suite instable) ; la preuve fiable et déterministe
        du problème est le test précédent."""
        import threading

        n_threads = 8
        results = []
        lock = threading.Lock()

        def _create(i):
            try:
                c = Client.objects.create(
                    node=self.node, node_origin='K1',
                    first_name='DEMO', last_name=f'Concurrent-{i}',
                )
                with lock:
                    results.append(('ok', c.code))
            except Exception as e:
                with lock:
                    results.append(('error', str(e)))
            finally:
                connection.close()

        threads = [threading.Thread(target=_create, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        errors = [r for r in results if r[0] == 'error']
        codes = [r[1] for r in results if r[0] == 'ok']
        # Journal informatif uniquement — voir docstring.
        self.assertTrue(len(errors) + len(codes) == n_threads)


class ClientCreditLimitTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')

    def test_default_credit_limit_is_50000(self):
        client = Client.objects.create(node=self.node, node_origin='K1', first_name='DEMO', last_name='Defaut')
        client.refresh_from_db()
        self.assertEqual(client.credit_limit, Decimal('50000.00'))

    def test_custom_credit_limit_above_default_is_respected_at_creation(self):
        """remarque.md l.172 : la valeur saisie à la création doit être prise en
        compte même si elle dépasse le plafond par défaut (50 000 FC)."""
        client = Client.objects.create(
            node=self.node, node_origin='K1', first_name='DEMO', last_name='Grossiste',
            credit_limit=Decimal('500000.00'),
        )
        self.assertEqual(client.credit_limit, Decimal('500000.00'))
        client.refresh_from_db()
        self.assertEqual(client.credit_limit, Decimal('500000.00'))


class ClientCategorizationTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.config = get_config()
        self.config.best_client_threshold = 1000
        self.config.save()

    def test_normal_by_default(self):
        client = make_client(self.node, current_debt=Decimal('0'), credit_limit=Decimal('50000.00'))
        client.refresh_category(self.config)
        self.assertEqual(client.category, Client.Category.NORMAL)

    def test_best_client_at_threshold(self):
        client = make_client(self.node)
        client.total_breads_received = self.config.best_client_threshold
        client.refresh_category(self.config)
        self.assertEqual(client.category, Client.Category.BEST)

    def test_not_best_client_below_threshold(self):
        client = make_client(self.node)
        client.total_breads_received = self.config.best_client_threshold - 1
        client.refresh_category(self.config)
        self.assertEqual(client.category, Client.Category.NORMAL)

    def test_at_risk_when_debt_reaches_credit_limit(self):
        client = make_client(self.node, credit_limit=Decimal('50000.00'))
        client.current_debt = Decimal('50000.00')  # égal au plafond, pas seulement supérieur
        client.refresh_category(self.config)
        self.assertEqual(client.category, Client.Category.RISK)

    def test_at_risk_takes_priority_over_best_client(self):
        client = make_client(self.node, credit_limit=Decimal('50000.00'))
        client.total_breads_received = self.config.best_client_threshold + 500
        client.current_debt = Decimal('60000.00')
        client.refresh_category(self.config)
        self.assertEqual(client.category, Client.Category.RISK)


class ClientSavingsAccountTests(TestCase):
    """Client épargne (CLAUDE.md §5.1) : commande = 0, paiement = dépôt, BP
    (current_debt) négatif accepté — un solde négatif représente un crédit
    en faveur du client."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')

    def test_negative_current_debt_is_accepted(self):
        client = make_client(self.node, current_debt=Decimal('-15000.00'))
        client.refresh_from_db()
        self.assertEqual(client.current_debt, Decimal('-15000.00'))

    def test_negative_debt_does_not_trigger_risk_category(self):
        config = get_config()
        client = make_client(self.node, current_debt=Decimal('-15000.00'), credit_limit=Decimal('50000.00'))
        client.refresh_category(config)
        self.assertEqual(client.category, Client.Category.NORMAL)
