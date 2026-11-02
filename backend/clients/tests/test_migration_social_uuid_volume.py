"""
Passe finale de vérification (testeur-charge, 2026-11-02) — BUG-004.

Complète `clients/tests/test_migration_social_uuid.py` (2 cotisations,
1 distribution, 1 ligne) avec un jeu de données FICTIF de volume réaliste
(plusieurs boulangeries, plusieurs centaines de clients et de lignes) pour
vérifier que la migration 0008/0009 :
- ne perd aucune ligne sur un volume largement supérieur à celui testé
  jusqu'ici (dépasse le `BATCH = 500` de `bulk_update` dans la migration,
  pour vérifier le passage multi-lots) ;
- ne produit jamais de collision d'UUID (ni entre cotisations, ni entre
  distributions, ni entre lignes, ni entre les trois catégories) ;
- réécrit correctement TOUTES les FK `SocialDistributionLine.distribution`
  vers le nouvel UUID, même quand plusieurs boulangeries ont chacune leur
  propre distribution annuelle en même temps dans la même base.

Aucune donnée réelle de `data_kiese/` : tout est généré fictivement
(CLAUDE.md §4).
"""
import os
import tempfile
import unittest
import uuid

from django.db import connections
from django.db.migrations.executor import MigrationExecutor


class SocialSyncableUUIDMigrationVolumeTests(unittest.TestCase):
    """Même technique que `test_migration_social_uuid.py` (base SQLite
    jetable sur un alias dédié, migrée depuis zéro) — voir ce fichier pour
    la justification détaillée du choix `unittest.TestCase`."""

    ALIAS = 'social_uuid_migration_volume'

    N_NODES = 8
    CLIENTS_PER_NODE = 40
    CONTRIBUTIONS_PER_CLIENT = 3  # 8 * 40 * 3 = 960 cotisations
    # 1 distribution par nœud par an, 2 années -> 16 distributions
    YEARS = [2025, 2026]

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

    def test_realistic_volume_survives_uuid_pk_migration_without_loss_or_collision(self):
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

        nodes = [
            Node.objects.using(self.ALIAS).create(code=f'VOL{i}', name=f'Boulangerie Volume {i}')
            for i in range(self.N_NODES)
        ]

        all_clients = []
        expected_contribution_keys = set()  # (node_idx, client_idx, month, year)
        contribution_objs = []
        for n_idx, node in enumerate(nodes):
            node_clients = []
            for c_idx in range(self.CLIENTS_PER_NODE):
                client = Client.objects.using(self.ALIAS).create(
                    code=f'{node.code}-{c_idx:04d}', first_name=f'Client{c_idx}',
                    last_name=f'Node{n_idx}', node=node, node_origin=node.code,
                )
                node_clients.append(client)
                for m in range(1, self.CONTRIBUTIONS_PER_CLIENT + 1):
                    contrib = SocialContribution.objects.using(self.ALIAS).create(
                        client=client, node=node, month=m, year=2026, amount='3000.00',
                    )
                    contribution_objs.append(contrib)
                    expected_contribution_keys.add((client.code, m, 2026))
            all_clients.append(node_clients)

        old_contribution_ids = {c.pk for c in contribution_objs}
        self.assertEqual(len(old_contribution_ids), len(contribution_objs), "PK entières dupliquées avant migration ?!")

        distributions_by_key = {}  # (node_code, year) -> old pk
        lines_expected = {}  # (node_code, year, client_code) -> old line pk
        for n_idx, node in enumerate(nodes):
            for year in self.YEARS:
                distribution = SocialDistribution.objects.using(self.ALIAS).create(
                    node=node, year=year, tarif='700.00',
                )
                distributions_by_key[(node.code, year)] = distribution.pk
                for client in all_clients[n_idx]:
                    line = SocialDistributionLine.objects.using(self.ALIAS).create(
                        distribution=distribution, client=client,
                        indice=year % 12, total_social='6000.00',
                    )
                    lines_expected[(node.code, year, client.code)] = line.pk

        total_contributions_before = SocialContribution.objects.using(self.ALIAS).count()
        total_distributions_before = SocialDistribution.objects.using(self.ALIAS).count()
        total_lines_before = SocialDistributionLine.objects.using(self.ALIAS).count()
        self.assertEqual(total_contributions_before, self.N_NODES * self.CLIENTS_PER_NODE * self.CONTRIBUTIONS_PER_CLIENT)
        self.assertEqual(total_distributions_before, self.N_NODES * len(self.YEARS))
        self.assertEqual(total_lines_before, self.N_NODES * len(self.YEARS) * self.CLIENTS_PER_NODE)

        # --- Migration réelle 0008 -> 0009 --------------------------------
        self.executor.loader.build_graph()
        self.executor.migrate([('clients', '0009_social_syncable_step2')])

        new_apps = self.executor.loader.project_state(
            [('clients', '0009_social_syncable_step2')]
        ).apps
        NewSocialContribution = new_apps.get_model('clients', 'SocialContribution')
        NewSocialDistribution = new_apps.get_model('clients', 'SocialDistribution')
        NewSocialDistributionLine = new_apps.get_model('clients', 'SocialDistributionLine')
        NewClient = new_apps.get_model('clients', 'Client')

        # --- 1. Aucune perte : mêmes effectifs exacts après migration ----
        self.assertEqual(
            NewSocialContribution.objects.using(self.ALIAS).count(), total_contributions_before,
        )
        self.assertEqual(
            NewSocialDistribution.objects.using(self.ALIAS).count(), total_distributions_before,
        )
        self.assertEqual(
            NewSocialDistributionLine.objects.using(self.ALIAS).count(), total_lines_before,
        )

        # --- 2. Toutes les nouvelles PK sont des UUID valides et UNIQUES,
        #        y compris à travers les 3 modèles (pas de collision inter-
        #        catégorie, même si c'est déjà garanti par construction par
        #        des tables séparées — vérifié explicitement ici). --------
        contrib_pks = list(
            NewSocialContribution.objects.using(self.ALIAS).values_list('id', flat=True)
        )
        distrib_pks = list(
            NewSocialDistribution.objects.using(self.ALIAS).values_list('id', flat=True)
        )
        line_pks = list(
            NewSocialDistributionLine.objects.using(self.ALIAS).values_list('id', flat=True)
        )
        all_pks = contrib_pks + distrib_pks + line_pks
        for pk in all_pks:
            self.assertIsInstance(pk, uuid.UUID)
        self.assertEqual(len(all_pks), len(set(all_pks)), "Collision d'UUID détectée entre enregistrements migrés.")
        self.assertEqual(len(contrib_pks), len(set(contrib_pks)))
        self.assertEqual(len(distrib_pks), len(set(distrib_pks)))
        self.assertEqual(len(line_pks), len(set(line_pks)))

        # Aucune nouvelle PK ne réutilise une ancienne valeur entière
        # (comparaison par construction impossible de collisionner — UUID
        # vs entier — mais vérifié explicitement qu'aucun ancien entier
        # n'apparaît tel quel, cohérent avec "jamais d'ID auto-incrémenté
        # transporté", CLAUDE.md §4).
        old_distribution_ids = set(distributions_by_key.values())
        self.assertFalse(any(str(pk) in {str(i) for i in old_distribution_ids} for pk in distrib_pks))

        # --- 3. Chaque cotisation reste bien attachée à SON client, sur
        #        les 8 boulangeries, sans décalage/mélange introduit par la
        #        migration (vérification croisée sur un échantillon large,
        #        pas seulement le premier/dernier enregistrement). -------
        sample_checked = 0
        for n_idx, node in enumerate(nodes):
            for client in all_clients[n_idx][:5]:  # échantillon par nœud, assez large
                new_client = NewClient.objects.using(self.ALIAS).get(code=client.code)
                months = set(
                    NewSocialContribution.objects.using(self.ALIAS)
                    .filter(client=new_client, year=2026).values_list('month', flat=True)
                )
                self.assertEqual(months, set(range(1, self.CONTRIBUTIONS_PER_CLIENT + 1)))
                sample_checked += 1
        self.assertEqual(sample_checked, self.N_NODES * 5)

        # --- 4. Le FK `distribution` de CHAQUE ligne pointe vers le nouvel
        #        UUID de la distribution attendue (node, year) — jamais
        #        vers l'ancienne PK entière, et jamais vers la distribution
        #        d'une AUTRE boulangerie/année (risque réel avec 16
        #        distributions et plusieurs centaines de lignes à
        #        réconcilier correctement). --------------------------------
        checked_lines = 0
        for (node_code, year, client_code), _old_line_pk in lines_expected.items():
            new_client = NewClient.objects.using(self.ALIAS).get(code=client_code)
            new_line = NewSocialDistributionLine.objects.using(self.ALIAS).get(
                client=new_client, distribution__node__code=node_code, distribution__year=year,
            )
            self.assertNotEqual(str(new_line.pk), str(_old_line_pk))
            new_distribution = NewSocialDistribution.objects.using(self.ALIAS).get(
                node__code=node_code, year=year,
            )
            self.assertEqual(new_line.distribution_id, new_distribution.pk)
            checked_lines += 1
        self.assertEqual(checked_lines, total_lines_before)
