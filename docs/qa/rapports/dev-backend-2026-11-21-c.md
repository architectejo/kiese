# Rapport dev-backend (Dev C) — 2026-11-21c

Tickets traités : BUG-357, BUG-147, BUG-129. Non traités (hors mission) : BUG-278, BUG-161.

## BUG-357 — CORRIGÉ
- Commande `backend/production/management/commands/recompute_cump.py` (+ `__init__.py` des paquets `management` et `commands`). Simulation par défaut, `--apply`, `--node`, `--dry-run` (incompatible avec `--apply`).
- Rejeu par stock (`created_at`, `pk`) avec `base_qty = max(old_qty, 0)`; revalorise aussi les sorties; `log_activity` par stock modifié; `atomic` + `select_for_update`; Decimal; aucune migration.
- Limite : le rejeu part de 0 (comme la migration 0018); un stock initial non tracé par des mouvements déclenche un avertissement, la quantité n'est jamais modifiée.
- Test : `production/tests/test_bug357_recompute_cump.py` — avant : 5 erreurs `Unknown command`; après : 6 OK.

## BUG-147 — CORRIGÉ
- `production/views.py` : helper `_get_or_create_consumable_stock`, utilisé par `_record_consumable_exits` et par la régularisation de farine du PATCH de session. Stock négatif toujours autorisé (BUG-143).
- Test : `production/tests/test_bug147_auto_create_consumable_stock.py` — avant : 3 erreurs `DoesNotExist` (1 test de contrôle passait); après : 4 OK.
- `test_verif_bug143_testeur_production.py::NoStockRowAtAllTests` réaligné (documentait la perte silencieuse) : à confirmer par testeur-production.

## BUG-129 — déjà corrigé (aucun code)
- Dict `{'detail': ...}` en place depuis 7f1890d + BUG-142. Tests existants `test_bug129_session_duplicate_format.py` passent. Registre : CORRIGÉ « déjà corrigé, à vérifier ». Volet frontend non examiné.

## Contrôles
- `manage.py check` : OK; `makemigrations --check --dry-run` : No changes detected.
- Suite complète (2071 tests, DJANGO_DEBUG=True) : 2 échecs au premier passage.
  1. `production.tests.test_consumables.OverconsumptionAlertTests` : conséquence directe de BUG-147 (la ligne FLOUR auto-créée passe en négatif et émet la notification BUG-143, parasite pour ce test). Setup réaligné (ligne FLOUR approvisionnée, comme en réel) sans toucher aux assertions ; ré-exécuté : OK.
  2. `core...test_verif_bug247_248_252_255_testeur_permissions.Bug255.test_schema_requires_auth_outside_debug` : dépend de `DJANGO_DEBUG=True` imposé par la commande de test ; sans rapport avec production (aucun fichier core touché). Non investigué (core en lecture seule).
- Relance ciblée (41 tests : consumables, bug123/126/129/143/147/357/402, fournées, verif_bug143) : OK.

## Risques
- `recompute_cump --apply` modifie des valorisations de sorties passées (Compte de Résultat) : sauvegarde + simulation préalables sur chaque base réelle.
