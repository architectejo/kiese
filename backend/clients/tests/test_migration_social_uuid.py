"""
Test de non-régression pour les migrations 0008/0009 (`clients`) — BUG-004,
extension 2026-11-02 (passage de `SocialContribution`/`SocialDistribution`/
`SocialDistributionLine` à `SyncableModel`, PK UUID).

Objectif : prouver que la migration de données (0009, `RunPython`) ne perd
aucune ligne existante et réécrit correctement le FK
`SocialDistributionLine.distribution` vers le nouvel UUID de
`SocialDistribution` — jamais vers l'ancienne PK entière, qui disparaît.

Technique : la base de test habituelle (alias `default`) est déjà migrée
jusqu'à la dernière migration de chaque app avant le premier test — on ne
peut donc pas la faire reculer jusqu'à `0007_bug057_schema_drift_fix` : la
migration 0009 est délibérément irréversible (`_populate_uuids_reverse` lève
une `RuntimeError` explicite, voir son en-tête), et c'est exactement le
comportement souhaité en production (on ne revient jamais à des PK entières
une fois les enregistrements partagés entre nœuds). Ce test ouvre donc sa
propre base SQLite jetable (fichier temporaire, alias `social_uuid_migration`
ajouté dynamiquement à `django.db.connections`), construite par migration
forward *depuis zéro* jusqu'à `0007`, jamais par un retour en arrière (ce qui
a d'ailleurs permis de détecter, au passage, que `_populate_uuids` n'était
pas lié explicitement à l'alias de connexion migré — sans conséquence tant
que la seule base du projet s'appelle `'default'`, mais source silencieuse de
doublons d'UUID autrement ; corrigé dans 0009 par `.using(db_alias)`). Ce
test échouait avant la correction de l'ordre des opérations dans 0009
(« duplicate column name: id » sous SQLite, provoqué par un état transitoire
sans aucun champ `primary_key=True` déclaré) et passe après.
"""
import os
import tempfile
import unittest
import uuid

from django.db import connections
from django.db.migrations.executor import MigrationExecutor


class SocialSyncableUUIDMigrationTests(unittest.TestCase):
    """
    `unittest.TestCase` natif (pas une sous-classe Django `TestCase`/
    `SimpleTestCase`) : ce test ne touche jamais l'alias `default` de la base
    de test Django — il pilote entièrement sa propre base SQLite jetable sur
    un alias ajouté et retiré dynamiquement, à l'intérieur de ce seul test.
    Les classes de test Django interdiraient cet accès « hors liste blanche »
    (`DatabaseOperationForbidden`) même après ajout dynamique de l'alias
    (la liste blanche `databases` est figée avant l'exécution des tests) ;
    `unittest.TestCase` n'impose pas cette restriction tout en restant
    découvert normalement par `manage.py test` (basé sur `unittest`).
    """

    ALIAS = 'social_uuid_migration'

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.sqlite3')
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(self.db_path) and os.remove(self.db_path))

        connections.databases[self.ALIAS] = {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': self.db_path,
            'ATOMIC_REQUESTS': False,
            'TIME_ZONE': None,
            'CONN_HEALTH_CHECKS': False,
            'CONN_MAX_AGE': 0,
            'AUTOCOMMIT': True,
            'OPTIONS': {},
        }
        self.addCleanup(connections[self.ALIAS].close)
        self.addCleanup(lambda: connections.databases.pop(self.ALIAS, None))

        self.connection = connections[self.ALIAS]
        self.executor = MigrationExecutor(self.connection)

    def test_contribution_distribution_and_line_survive_uuid_pk_migration(self):
        # --- 1. Construire depuis zéro jusqu'à l'état juste avant 0008 ----
        #        (PK entières). `clients` ne dépend que de `core`
        #        (clients.0001_initial -> core.0003...) : on migre
        #        uniquement ces deux apps à leur tête respective plutôt que
        #        toutes les apps du projet — `treasury`, notamment, contient
        #        une migration de données (`0005_localexpense_category_fk`)
        #        qui échoue de façon non liée à ce test quand elle est migrée
        #        isolément sur une connexion ad hoc hors du cycle de test
        #        Django normal (`no such column: category`, probablement une
        #        particularité SQLite propre au cache de requêtes préparées
        #        sur une connexion réutilisée entre deux `MigrationExecutor`
        #        — non reproductible via la suite de tests normale, donc
        #        hors du périmètre de cette correction BUG-004).
        core_leaf = next(
            node for node in self.executor.loader.graph.leaf_nodes() if node[0] == 'core'
        )
        self.executor.migrate([core_leaf, ('clients', '0007_bug057_schema_drift_fix')])

        old_apps = self.executor.loader.project_state(
            [('clients', '0007_bug057_schema_drift_fix')]
        ).apps
        Node = old_apps.get_model('core', 'Node')
        Client = old_apps.get_model('clients', 'Client')
        SocialContribution = old_apps.get_model('clients', 'SocialContribution')
        SocialDistribution = old_apps.get_model('clients', 'SocialDistribution')
        SocialDistributionLine = old_apps.get_model('clients', 'SocialDistributionLine')

        node = Node.objects.using(self.ALIAS).create(code='ZZ', name='Nœud de test migration')
        client = Client.objects.using(self.ALIAS).create(
            code='ZZ-0001', first_name='Jean', last_name='Mbuyi',
            node=node, node_origin='ZZ',
        )
        contrib_jan = SocialContribution.objects.using(self.ALIAS).create(
            client=client, node=node, month=1, year=2026, amount='3000.00',
        )
        contrib_feb = SocialContribution.objects.using(self.ALIAS).create(
            client=client, node=node, month=2, year=2026, amount='3000.00',
        )
        distribution = SocialDistribution.objects.using(self.ALIAS).create(
            node=node, year=2026, tarif='700.00',
        )
        line = SocialDistributionLine.objects.using(self.ALIAS).create(
            distribution=distribution, client=client, indice=2, total_social='6000.00',
        )
        old_contrib_ids = {contrib_jan.pk, contrib_feb.pk}
        old_line_pk = line.pk
        old_distribution_pk = distribution.pk

        # --- 2. Appliquer 0008 puis 0009 (migration réelle du dépôt) ------
        self.executor.loader.build_graph()
        self.executor.migrate([('clients', '0009_social_syncable_step2')])

        new_apps = self.executor.loader.project_state(
            [('clients', '0009_social_syncable_step2')]
        ).apps
        NewSocialContribution = new_apps.get_model('clients', 'SocialContribution')
        NewSocialDistribution = new_apps.get_model('clients', 'SocialDistribution')
        NewSocialDistributionLine = new_apps.get_model('clients', 'SocialDistributionLine')
        NewClient = new_apps.get_model('clients', 'Client')

        new_client = NewClient.objects.using(self.ALIAS).get(code='ZZ-0001')

        # --- 3. Aucune perte : 2 cotisations, 1 distribution, 1 ligne -----
        contributions = list(
            NewSocialContribution.objects.using(self.ALIAS)
            .filter(client=new_client).order_by('month')
        )
        self.assertEqual(len(contributions), 2)
        self.assertEqual([c.month for c in contributions], [1, 2])

        # Nouvelles PK = UUID valides, distinctes des anciennes PK entières.
        for contrib in contributions:
            self.assertIsInstance(contrib.pk, uuid.UUID)
            self.assertNotIn(contrib.pk, old_contrib_ids)

        new_distribution = NewSocialDistribution.objects.using(self.ALIAS).get(
            node__code='ZZ', year=2026,
        )
        self.assertIsInstance(new_distribution.pk, uuid.UUID)
        self.assertNotEqual(str(new_distribution.pk), str(old_distribution_pk))

        new_line = NewSocialDistributionLine.objects.using(self.ALIAS).get(client=new_client)
        self.assertIsInstance(new_line.pk, uuid.UUID)
        self.assertNotEqual(str(new_line.pk), str(old_line_pk))

        # --- 4. Le FK `distribution` pointe vers le NOUVEL UUID, jamais ----
        #        vers l'ancienne PK entière (coeur de la migration de données).
        self.assertEqual(new_line.distribution_id, new_distribution.pk)
