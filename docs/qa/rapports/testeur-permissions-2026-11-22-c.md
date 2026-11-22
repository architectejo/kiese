# Rapport testeur-permissions (Dev C) — 2026-11-22-c

Contre-vérification du lot A : BUG-503, 504, 505, 362 (isolation inter-boulangeries). Aucun code applicatif modifié, aucun commit.

## Relecture du diff (commit b8ac762 : treasury/views.py, production/views.py, production/serializers.py, kiese/node_guard.py, core/mixins.py)
- BUG-503 : `FacturierReportViewSet.create` écrase `node` avant validation pour un non-siège ; `perform_create` force le nœud.
- BUG-504 : `validate_stock` / `validate_session` (404 si nœud étranger), `perform_create` des mouvements vérifie `stock.node`.
- BUG-505 : `?node=` honoré seulement pour le siège dans `flour_history`.
- BUG-362 : `NoNodeGuardMixin` (403 sur écriture) + `.none()` dans les `get_queryset` et `_build_reconciliation_querysets`.

## Étape 1 : `@expectedFailure` de `test_verif_matrice_c.py`
Déjà retirés par A dans b8ac762 (aucune modification de ma part, `git diff` vide). Il ne reste que BUG-507 (`À CLARIFIER`). Les tests concernés passent.

## Étape 2 : `backend/core/tests/test_verif_isolation_a_c.py` (37 tests + `ReconciliationScope`)
Classes : TransferIsolation (BreadTransfer tiers, création forgée, rôles, réécriture from/to), ProductionIsolation (EXIT et variantes sur stock étranger, UUID étrangers en GET/PATCH/PUT/DELETE, stock/disposal/count/session avec `node` forgé, `@action` de session sur session étrangère, GET d'actions avec `?node=`), TreasuryIsolation (UUID étrangers, `@action` de clôture/rapport, clôture/dépense/journal/épargne avec `node` forgé, `generate`, bordereaux et cashbook réservés au siège, comptes sans boulangerie), SalesIsolation (facture étrangère et `@action` pour 3 rôles, `node` forgé, exception 5.1 : facturier/livreur cherchent des clients étrangers sans écriture, gérant K1 ne voit pas le client K2), HQNotBroken, SweepNodeParam (balayage de toutes les routes GET sans paramètre avec `?node=<pk|code>` pour gérant, facturier, livreur, comptes sans boulangerie), DeficitReportLeak, ReconciliationScope.

## Étape 3 : résultats
Labels : `core.tests.test_verif_matrice_c core.tests.test_verif_isolation_a_c core.tests.test_verif_bug503_504_505_362_a production.tests.test_bug503_504_505_fk_node production.tests.test_bug36x_compte_sans_boulangerie treasury.tests.test_bug503_report_forged_node` : 117 tests OK (99 sans le fichier de A), 5 échecs attendus (BUG-507, 521 x2, 522 x2). Aucun succès inattendu.

## Verdicts
| Ticket | Verdict |
|---|---|
| BUG-503 | VÉRIFIÉ (contre-vérifié testeur-permissions, Dev C) : variantes JSON/form/None/chaîne, PATCH/PUT, UUID étranger, `generate`, facturier/node_origin forgés. |
| BUG-504 | VÉRIFIÉ : EXIT/ENTRY/ADJUSTMENT sur stock étranger, session étrangère, PATCH/PUT vers stock étranger, DELETE d'un mouvement propre : stock de K2 inchangé. |
| BUG-505 | VÉRIFIÉ : `?node=` par pk, code, doublons : aucune donnée K2. |
| BUG-362 | VÉRIFIÉ : listes vides, écritures 403, comptes siège non cassés, balayage sans fuite. |

Registre : lignes mises à `VÉRIFIÉ (contre-vérifié testeur-permissions, Dev C, 2026-11-22)`.

## Nouveaux défauts (hors périmètre de A, trouvés par mes tests)
- **BUG-521 (Bloquant, OUVERT)** : `GET /api/clients/clients/deficit_report/` (IsAuthenticated) ne filtre pas par nœud : clients en déficit d'une autre boulangerie lisibles par tout rôle ; `?node=P2` donne un 500. Fichier de B.
- **BUG-522 (Bloquant, OUVERT)** : PATCH/PUT d'un transfert en attente modifie `from_node` et `to_node` (le demandeur se fait passer pour une autre boulangerie). Fichier production (A).

## Observations sans ticket
- `reconciliation` renvoie en écho le `node` demandé alors que les données sont celles du nœud de l'appelant (étiquette trompeuse, données correctes, testé).
- `/api/chat/users/` liste tous les utilisateurs avec leur nœud (annuaire de messagerie, probablement voulu) : exclu du balayage ; à confirmer par le coordinateur.
- Journal/épargne : PATCH/DELETE renvoient 405 sur objet étranger (pas de fuite).
