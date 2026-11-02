"""
Vérification indépendante de BUG-017 et BUG-018 (phase 4, 2026-10-22).

Ces tests sont écrits par `testeur-clients-commissions` en vérification
(CLAUDE.md §7 règle 3 : « celui qui corrige ne valide jamais sa propre
correction »), en plus des tests déjà livrés par le même agent en phase 2 et
corrigés/non modifiés par `dev-backend`. Objectif : ne pas se contenter de
relire le diff — prouver la correction par un scénario supplémentaire que
les tests existants ne couvraient pas exactement.
"""
from decimal import Decimal
from unittest import skipIf

from django.db import connection
from django.test import TransactionTestCase

from core.testing import make_node, make_client
from clients.models import Client, SocialDistribution, SocialDistributionLine


class BUG017RealConcurrencyStrictAssertionTests(TransactionTestCase):
    """
    Le test existant `test_concurrent_client_creation_under_real_threads_is_unreliable`
    (clients/tests/test_models.py) ne vérifie que l'absence de plantage total
    (`len(errors) + len(codes) == n_threads`) — il ne vérifie PAS que les
    codes produits sont tous différents entre eux. Sous SQLite, une partie
    des threads peut réellement échouer avec un verrou de fichier
    ("database is locked") plutôt que de révéler une collision de code — ce
    qui masquerait une régression (deux `Client` avec le même code) sans
    faire échouer ce test-là. Ici on vérifie strictement l'unicité des codes
    produits par les créations qui ont réussi, sous une charge plus élevée
    (16 threads) qu'en phase 2 (8 threads).
    """

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')

    def test_all_successful_concurrent_codes_are_unique_no_duplicate_in_db(self):
        import threading

        n_threads = 16
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

        codes = [r[1] for r in results if r[0] == 'ok']
        # Au moins quelques créations doivent avoir réussi (sinon le test ne
        # prouve rien) : sous 16 threads concurrents sur SQLite, on s'attend
        # à ce que la grande majorité réussisse (contrairement à avant
        # correction, où elles auraient toutes visé le même code puis
        # échoué en IntegrityError sauf une).
        self.assertGreater(len(codes), n_threads // 2,
                            f"Trop peu de créations ont réussi : {results}")
        self.assertEqual(
            len(codes), len(set(codes)),
            f"Deux créations concurrentes ont obtenu le même code client : {codes}"
        )
        # Preuve finale, au niveau base de données (pas seulement en mémoire
        # Python) : aucun doublon de `Client.code` pour ce nœud.
        db_codes = list(Client.objects.filter(node=self.node).values_list('code', flat=True))
        self.assertEqual(len(db_codes), len(set(db_codes)),
                          f"Doublon de code trouvé en base : {db_codes}")


class BUG018ComputeDirectCallTests(TransactionTestCase):
    """
    Le test existant (`test_auto_populate_lines_computes_indice_and_remise`)
    prouve la correction via le chemin API réel (`get_or_create` sans
    `merite` explicite). Ici on vérifie directement `compute()` sur une
    instance non sauvegardée en base — le scénario exact décrit dans le
    rapport de bug (`merite` vaut la chaîne `'0.00'` tant que l'instance
    n'est pas relue en base) — avec un `merite` non nul pour s'assurer que
    l'addition Decimal est correcte et pas seulement « ne plante pas ».
    """

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.client = make_client(self.node, first_name='DEMO', last_name='Merite')
        self.distribution = SocialDistribution.objects.create(
            node=self.node, year=2026, tarif=Decimal('700.00'),
        )

    def test_compute_on_unsaved_instance_with_nonzero_merite(self):
        line = SocialDistributionLine(
            distribution=self.distribution, client=self.client,
            indice=5, total_social=Decimal('15000.00'),
        )
        # `merite` n'a jamais été explicitement assigné : sur une instance
        # non relue en base, Django expose la valeur par défaut brute du
        # champ (chaîne '0.00'), exactement le scénario de BUG-018. On
        # force explicitement ce cas avant d'appeler compute(), pour ne pas
        # dépendre d'un comportement d'implémentation Django qui pourrait
        # changer de version en version.
        line.merite = '2500.00'  # chaîne volontaire, pas Decimal — reproduit le bug
        line.compute()
        self.assertEqual(line.remise, Decimal('3500.00'))       # 5 x 700
        self.assertEqual(line.total_payer, Decimal('21000.00'))  # 15000 + 3500 + 2500
        self.assertIsInstance(line.total_payer, Decimal)
