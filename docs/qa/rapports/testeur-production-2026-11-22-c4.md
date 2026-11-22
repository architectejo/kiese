# Rapport testeur-production (Dev C) — 2026-11-22 c4

Vérification de BUG-524 et BUG-525 (testeur d'origine, différent du développeur) et balayage des paramètres invalides.

## Verdicts
| Ticket | Verdict |
|---|---|
| BUG-524 | VÉRIFIÉ (testeur-production, Dev C, 2026-11-22c4) |
| BUG-525 | VÉRIFIÉ (testeur-production, Dev C, 2026-11-22c4) |

## BUG-524 — `recompute_cump`
Cas rejoués (tous verts) : stock >= 0 non signalé ; stock négatif + 2 entrées de même instant à prix différents signalé ; prix identiques non signalé (commutatif) ; entrée + sortie signalé ; 3 mouvements de même instant comptés ; `--force` identique pour 3 ordres de pk ; `--apply` sans `--force` ignore sans écrire ; simulation / `--dry-run` sans écriture (stocks, mouvements, journal) ; `--node` ; idempotence.

Point critique (rejeu vs CUMP en ligne de `ConsumableMovement.save()`) :
- Le tri (prix, quantité, pk) ne crée pas de divergence non signalée. Test de propriété sur 60 séquences aléatoires (seed 524) de mouvements réels : quand aucun avertissement n'est émis, le rejeu égale le CUMP en base (< 0,05 FC) et les prix de sortie.
- Divergence réelle possible (ex. -5 puis 1@100 et 10@200 arrivés « 200 puis 100 » : en ligne 183,3333 ; rejeu 200) : elle est signalée et `--apply` ignore le stock.
- Limite acceptée : avec `--force`, le rejeu impose « prix croissant » ; l'ordre d'arrivée réel est invérifiable.
- Trou résiduel couvert ailleurs : stock initial négatif non tracé (hors mouvements) échappe à l'avertissement 524 mais déclenche « quantité en base != rejouée » (BUG-501) ; `--apply` ignore sans `--force`.

## BUG-525 — `_resolve_hq_node_param`
Vérifié : siège `?node=ZZZ` -> 400 `{"detail": "Boulangerie « ZZZ » introuvable."}` ; 999999 / 0 / -1 -> 400 ; pk, code, code en minuscules ; 3 rôles siège ; gérant : paramètre ignoré, jamais 400 (ZZZ, 999999, vide, autre code, injection, 40 chiffres) ; siège sans paramètre ou `node=` vide : comme avant (200, `node` None, totaux = K1 + K2) ; `flour_history` ; `ConsumableCount` POST `node` non numérique -> 400 sans création.
Observation non bloquante : `perform_create` de `ConsumableCountViewSet` ignore silencieusement un `node` numérique inexistant (retombe sur le nœud du compte).

## Inventaire des paramètres numériques non validés (production)
Défauts : `sessions/?date_from|date_to` illisibles et `flour_history` `month`/`year` -> 500 (hypothèse du dev confirmée) : BUG-526. Déjà sûrs : `reconciliation` (dates, node), `daily-closure`, `daily-closure/clients` (page, page_size, team), `opening-confirmation`, `bread-stocks/by-date`, `stocks` (création auto, `ValueError` rattrapé), filtres `django-filter` (`node`, `from_node`, `count_date`...) -> 400, entiers géants (`99999999999999999999999999`) sans 500.

## Balayage boîte noire inter-apps (gérant K1 et siège)
| Ticket | Module | Endpoint -> 500 | Destinataire |
|---|---|---|---|
| BUG-526 | Production | `sessions/?date_from=abc`, `flour_history/?month=abc` | Dev C / production |
| BUG-527 | Ventes | `invoices/daily_summary/?date=abc` | A |
| BUG-528 | Finance | `years/summary|doc1_report|doc1_export ?node=ZZZ` (siège) | A |
| BUG-529 | Blockchain | `alerts|snapshots ?node=ZZZ`, `run_check` (siège) | A |
| BUG-530 | Commissions | `periods/history ?node=ZZZ` et `?months=abc` | B |
Sans 500 : `invoices/bread_summary`, `invoices/?node=ZZZ`, `commissions/commissions`, `commissions/periods`, finance `month/year` invalides. Gérant : aucun 500 (403 ou paramètre ignoré). Clients : hors liste, non sondé.

## Tests écrits
- `backend/production/tests/test_verif_bug524_525_c.py` : Verif524 (12) + Verif525 (10).
- `backend/core/tests/test_verif_params_invalides_c.py` : 1 test vert (production, hors BUG-526) + 5 `@expectedFailure` (BUG-526 à 530).

## Résultats
Commande : `manage.py test` sur `production.tests.test_verif_bug524_525_c`, `core.tests.test_verif_params_invalides_c`, `test_bug524_525_a`, `test_verif_bug364_365_c`, `test_bug364_recompute_cump_ordre`, `test_bug357_recompute_cump`, `test_verif_bug357_147_c`, `test_verif_bug501_510_a` : 134 tests, OK, expected failures = 5 (les miens). Aucun code applicatif modifié.
