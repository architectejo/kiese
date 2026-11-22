# Rapport testeur charge et résilience, ronde b2, 2026-11-22

Périmètre : Dev B (sync, concurrence côté clients, commissions et core), selon `docs/PLAN_TESTS_CORRECTIONS_A_B_C.md`.
Aucun code applicatif modifié. Aucun commit. Données fictives uniquement. Moteur de test : SQLite.

## Résultat global

| Fichier de test (nouveau) | Tests | Passent | `expectedFailure` |
|---|---|---|---|
| `backend/sync/tests/test_hostile_payloads_v2.py` | 38 | 17 | 21 (ticket cité) |
| `backend/sync/tests/test_consumables_prices_resilience_v2.py` | 19 | 9 | 10 |
| `backend/clients/tests/test_volumetrie_v2.py` | 11 | 10 | 1 |
| `backend/commissions/tests/test_concurrence_volumetrie_v2.py` | 12 | 8 | 4 |
| Total | 80 | 44 | 36 |

Les suites ont été lancées en trois passes ciblées (jamais la suite complète) : la dernière est verte (`OK`, `expected failures`), sans « unexpected success ». Chaque `expectedFailure` a été vérifié en retirant temporairement le décorateur : tous échouent sur l'assertion métier visée, aucun sur une erreur de test.

## Tickets ouverts (BUG-720 à BUG-736, `docs/qa/REGISTRE_BUGS.md`)

| Ticket | Gravité | Constat |
|---|---|---|
| BUG-722 | Bloquant | Le jeton K1 peut pousser une clôture `node='K2'` validée : ACCEPTÉE, le Cloud écrit une `CashbookEntry` K2 (`node_origin='CLOUD'`) dans le livre de caisse chaîné. Même chose pour client, facture, mouvement de dette, `node_origin` forgé. Les nouveaux handlers `ConsumableInventory/Count` contrôlent bien le nœud, pas les anciens. |
| BUG-721 | Bloquant | Aucune borne de plage ni de longueur. Un `DebtMovement` de 40 chiffres est accepté et `Client.current_debt` devient illisible (`decimal.InvalidOperation`) : `GET /api/clients/clients/` répond 500 pour tous. Différent de PostgreSQL qui rejetterait. |
| BUG-726 | Majeur | Idempotence de lot par `batch_id` seul : même `batch_id` avec un autre contenu = données avalées ; `batch_id` d'un autre nœud = fuite des résultats de K1 vers K2 et lot de K2 non appliqué. |
| BUG-730 | Majeur | Deux lignes FARINE de valeurs différentes pour un même inventaire sont toutes deux acceptées. |
| BUG-731 | Majeur | Un inventaire accepté dont une ligne est rejetée est marqué synchronisé : la ligne n'est plus jamais renvoyée (perte silencieuse). |
| BUG-732 | Majeur | Ligne ajoutée à la facture d'une autre boulangerie ; prix net supérieur au prix plein ; somme des lignes sans rapport avec `order_total`. |
| BUG-725 | Majeur | Facture : statut/type de paiement hors énumération et montants négatifs acceptés. |
| BUG-728 | Majeur | Dette d'ouverture écrasée par `recompute_client_debt` (20 000 FC + mouvement de 1 000 = 1 000 FC). Limite documentée dans le code, non ticketée jusque-là. |
| BUG-734 | Majeur | Endpoints non paginés (voir mesures). |
| BUG-720 | Majeur | Lot mal formé = 500 (valeur de modèle non liste, enregistrement non objet) ; id entier ou booléen converti en UUID. |
| BUG-723, 724, 727, 729, 733, 735, 736 | Mineur | Inondation du journal de conflits ; collision de code sans conflit journalisé et fuite du motif SQL ; mouvement rejoué avec un autre montant ignoré ; validations métier des consommables (date future, quantité négative, type inconnu) ; `apply_push_response` lève `KeyError` ; `mark_paid`/`set_manuel` sans verrou (lost update simulé) ; `generate` répond 500 sur paramètres invalides et accepte `month=13`. |

## Mesures de volumétrie (5 000 clients ou 5 000 commissions, SQLite mémoire)

Nombre de requêtes SQL identique entre 50 et 5 000 lignes pour tous les endpoints testés : aucun N+1 sur clients, commissions, `deficit_report`, bassins, `summary`, `payroll_listing`, `risk_alerts`, `best_clients`, `history`. Les écarts de 1 requête observés sur la recherche par code ne dépendent pas du volume.

| Endpoint (5 000 lignes) | Requêtes | Temps | Taille |
|---|---|---|---|
| Liste clients `page_size=500` | 3 | 0,36 à 0,71 s | 330 Ko |
| Recherche client (facturier) | 3 | 71 à 130 ms (objectif p95 < 300 ms : OK) | 16 Ko |
| Recherche par code | 2 à 3 | 60 à 100 ms | 7 Ko |
| `deficit_report` | 4 | 0,25 à 0,8 s | 185 Ko |
| `bassins` | 4 | 0,9 à 1,8 s | 846 Ko |
| `risk_alerts` (1 000 lignes) | 2 | 0,8 à 1,35 s | 662 Ko |
| `best_clients` | 2 | 0,64 s | 330 Ko |
| Liste commissions `page_size=500` | 4 | 0,25 à 0,5 s | 471 Ko |
| Recherche commissions | 4 | 73 à 102 ms | 94 Ko |
| `summary` commissions | 4 | 13 à 15 ms | < 1 Ko |
| `payroll_listing` | 2 | 3,1 à 4,1 s | 4,7 Mo |

Les temps varient d'une passe à l'autre (machine de développement partagée) ; seules les tendances comptent. Pagination hostile (`page_size` 0, -1, abc, 1e9, 100000, `page` 0, abc, 999999, `ordering` inconnu, recherche de 5 000 caractères) : aucun 500, `page_size` plafonné à 500, parcours des 4 pages de 500 sur 2 000 clients avec 40 noms identiques : aucun doublon ni saut.

## Concurrence et verrous

- SQLite n'a aucun effet de `select_for_update()` (`connection.features.has_select_for_update` est faux). Un test de garde le documente et signale le jour où le moteur de test change.
- Espion : `recompute_client_debt` émet bien `select_for_update` sur `Client` (test vert). `mark_paid` n'émet aucun verrou sur `ClientCommission` (BUG-735).
- Lost update reproduit de façon déterministe (paiement concurrent inséré entre le contrôle et l'écriture de `set_manuel`) : `net_payable` d'une commission payée est modifié (BUG-735).
- Séquences vérifiées OK : rejeu du même mouvement de dette 4 fois, même UUID plusieurs fois dans un lot, `generate` deux fois, double `mark_paid` séquentiel (400).

## Résilience

- Réponse perdue après traitement : rejeu du même `batch_id` = `replayed: true`, zéro doublon, dette exacte (vert).
- Coupure franche en milieu de lot (`OperationalError` non « locked » au 2e enregistrement) : réponse 5xx, aucun `SyncBatchLog` figé, rejeu complet sans perte ni doublon (vert).
- Lot dont les clés sont dans l'ordre inverse des dépendances : traité dans l'ordre du graphe, tout accepté ; dépendance manquante rejetée puis acceptée au rattrapage (vert).
- Point faible : BUG-731 (ligne d'inventaire rejetée jamais renvoyée), BUG-733 (réponse Cloud tronquée interrompt le cycle sortant).

## Recommandation moteur (rappel)

Cloud : PostgreSQL obligatoire (verrous de ligne réels, rejet des valeurs hors plage, concurrence multi-nœuds). Nœud local : SQLite en WAL reste acceptable pour un poste, à condition de corriger BUG-721 (validation de plage côté application, puisque SQLite ne l'applique pas). Les tests de verrou réels (BUG-728, BUG-735) doivent être rejoués sous PostgreSQL.

## Non fait dans cette ronde

Pic du matin (16 facturiers en parallèle sur 10 minutes), mesure `database is locked` avec et sans WAL et profil 3G/CPU lent Playwright : hors périmètre de cette ronde (pas de serveur dédié ni de Playwright lancé). Aucune vérification d'un tir contre un serveur de production.

## Commande de relance

```
cd backend
export PYTHONIOENCODING=utf-8 DJANGO_DEBUG=False DJANGO_SECURE_SSL_REDIRECT=False DJANGO_SECRET_KEY=test-only-not-a-real-key-0123456789-abcdefghij
./.venv/Scripts/python.exe manage.py test sync.tests.test_hostile_payloads_v2 sync.tests.test_consumables_prices_resilience_v2 clients.tests.test_volumetrie_v2 commissions.tests.test_concurrence_volumetrie_v2 --noinput
```
(environ 5 minutes ; les tests de volumétrie impriment les lignes `PERF`).
