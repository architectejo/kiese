# Rapport testeur-production — 2026-11-20

## Objet
`production.tests.test_verif_bug303_304_306_testeur_production.V306IncrementTests.test_rotation_targets_service_team_only` échouait (403 `TEAM_NOT_ASSIGNED` à la création de la facture).

## Diagnostic
- Cause : **test fragile dépendant de l'heure d'exécution**, pas un défaut applicatif.
- Le test créait `DailyTeamAssignment(work_date=work_date_for(node))` (date calendaire locale). Or `current_team()` (utilisée par `sales/views.py` à la facturation) cherche l'affectation sur `business_date(node)` : avant l'heure de relève (`Node.handover_time`), on est encore dans la période de la veille. Entre 00:00 et la relève (ici 02:56 Africa/Kinshasa), la désignation du test n'était donc pas trouvée -> 403.
- Indépendant de l'ordre des tests et de l'état de base ; reproduit en isolé sur base `DB_NAME` temporaire. Aucun lien avec les changements récents du dev.
- Le décalage calendaire / période de service est la conception documentée (`core/workday.py`, décision 2026-11-12) : aucun ticket BUG ouvert (registre non modifié).

## Correction (test uniquement, code applicatif intact)
- Fichier : `backend/production/tests/test_verif_bug303_304_306_testeur_production.py`.
- L'affectation est créée sur `business_date(self.node)`.
- Ajout de `test_rotation_targets_service_team_at_fixed_instants` : horloge simulée (`mock.patch('django.utils.timezone.now')`, freezegun non installé) à 02:30 et 14:30 le 2026-11-20 et à 02:30 et 23:30 le 2026-03-05 ; vérifie que seule la fournée de l'équipe de service reçoit la vente.

## Vérification (base isolée `DB_NAME`, jamais `backend/db.sqlite3`)
- Test seul à 02:56 : échec avant correction, passe après.
- Module complet : 42 tests, OK (1 skipped), incluant les 4 instants simulés (deux dates, avant et après relève).
- Suite `production` complète : voir note finale de l'appelant.
