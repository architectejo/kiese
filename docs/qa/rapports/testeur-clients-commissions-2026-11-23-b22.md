# Testeur clients/commissions - cycle 22 partie B (2026-11-23)

Tests : `backend/clients/tests/test_clients_v18.py` (10 tests), `backend/sync/tests/test_verif_sync_v6.py` (10 tests) + 1 inclus ; 21 tests, OK (log $TEMP/b22.log).

## Résultats
- BUG-1027 VÉRIFIÉ : facturier/livreur K1 = 0,30, K2 = 0,25 ; boulangerie à 0 = 0 ; boulangerie sans taux = Config ; taux/plafond forgés ignorés (BUG-250) ; PATCH facturier sans effet ; gérant/direction : explicite prioritaire, 0 valide ; commission générée à 0,30 (50 000 x 0,30 = 15 000).
- BUG-1028 VÉRIFIÉ : `card_applied` exposé (liste/détail), PATCH et POST ne le modifient pas.
- BUG-1030 VÉRIFIÉ : bloc propre au nœud du jeton, aucune fuite K2, idempotent (updated_at inchangé), valeurs invalides ignorées, cloud ancien sans bloc sans effet, chemins `sync_now` et desktop OK, TOP_KEYS v13 toujours testé.
- BUG-1103 re-examiné : VÉRIFIÉ de bout en bout (K1 0,30 après pull, K2 0,25, changement cloud sans effet sur les clients existants).
- BUG-1029 reste À CLARIFIER.

## Note de méthode
Deux premiers échecs étaient des artefacts de test (utilisateur en cache avec ancien Node ; base unique jouant cloud et poste), corrigés dans les tests, aucun bug applicatif.

## Nouveaux tickets : 0. Balayage final partie B : rien de nouveau.
