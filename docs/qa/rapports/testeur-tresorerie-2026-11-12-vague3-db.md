# Rapport testeur-tresorerie — vague 3 sur la base réelle (K3) — 2026-11-12

Périmètre : re-vérification de BUG-238 à 242 (statut CORRIGÉ) et non-régression trésorerie. API réelle `http://localhost:8000` (`db.sqlite3`, migration treasury 0017 appliquée), UI `http://localhost:5173/treasury`. Aucune écriture SQL ni migrate sur `db.sqlite3` ; la suppression de la dernière écriture a été simulée sur une COPIE (source ouverte en lecture seule, copie supprimée). Aucun git, aucune modification du code applicatif.

## 1. Verdicts

| Ticket | Reproduction rejouée | Résultat |
|---|---|---|
| BUG-238 | test auto `test_direct_previous_hash_tamper_detected` (30 écritures, `previous_hash='a'*64`) | **VÉRIFIÉ** |
| BUG-239 | base réelle : POST `/treasury/vouchers/` sans billet (comptable zz_ et direction) | 400 « au moins un billet », livre inchangé (6 écritures) ; gérant 403. **VÉRIFIÉ** |
| BUG-240 | COPIE de la base réelle (6 écritures) : intacte, montant altéré, montant restauré, dernière écriture supprimée | Intacte : valide ; montant altéré : 4 écritures signalées, 3 endpoints d'accord ; **dernière supprimée : `integrity_check` total=5 `chain_valid=false`, `run_check` et `global_status` `all_intact=false`, alertes ouvertes**. Base réelle : 6 écritures, `head_problem` vide, `run_check`/`global_status` intacts, K3 intègre. **VÉRIFIÉ** |
| BUG-241 | base réelle `savings/monthly_total/?month=11&year=2026` | `by_node` : `"2040"` et `"20400"` (chaînes). **VÉRIFIÉ** |
| BUG-242 | Playwright 360 px (facturier A) et 1366 px (livreur) sur `/treasury` | « Accès refusé », 0 appel `/api/treasury/`, pas de bouton « Générer Rapport du Jour ». Gérant K3 (360 px) : page normale, 1 appel, aucun 4xx, pas de débordement. **VÉRIFIÉ** |

Limite BUG-240 (déjà indiquée par le dev) : l'ancre `CashbookHead` est dans la même base ; un attaquant qui modifie aussi l'ancre n'est pas détecté. Je ne l'ouvre pas en ticket (limite assumée), mais un instantané hors base reste souhaitable.

## 2. Non-régression (base réelle, K3)

- Clôtures : 4 clôtures K3 (11-10 net 17 900, 11-09 12 400, 11-08 et 11-07 à 0), toutes confirmées. Double clôture même date : 400 (gérant et direction). Re-versement : 400 « déjà inscrite ». Gérant ne peut pas verser : 403. PATCH d'une clôture confirmée : 400 ; DELETE : 403 (figée).
- Livre : POST/PUT/PATCH/DELETE : 405. 6 écritures, soldes progressifs 17 900 / 29 100 / 29 700 / 30 300 / 30 300 / 30 300 inchangés ; `period_summary` novembre : entrées 30 300, sorties 0 (chaînes) ; `final_report` : restant 30 300.
- Rapports facturier lisibles (4), bordereaux : vide 400, gérant 403.
- Suite automatisée `treasury.tests.test_vague2_db_testeur_tresorerie` : 30 tests. 2 échecs initiaux = tests de la fenêtre minuit-01:00 devenus obsolètes à cause de la **décision client du 2026-11-12** (`core/workday.py` : la date de travail est toujours le jour calendaire local, avec ou sans rotation). Ce n'est pas un défaut applicatif : j'ai mis à jour mes deux tests (rapport et clôture datés 2026-11-13 à 00:30 locale en rotation), 3/3 verts. Suite complète `treasury blockchain` : voir §4.

## 3. Autres actions

- Clôture K1 vide `1f467160-c868-430b-8bb9-2793705cb767` (créée par erreur en vague 2) : supprimée via l'API par la direction (`@pierre`, DELETE 204, GET ensuite 404).
- BUG-231 : toujours `CORRIGÉ`, vérification UI complète non refaite (le message d'erreur de billetage hors borne n'a pas été relu ; le comptable n'a pas pu se connecter dans le délai, Vite saturé). À reprendre.
- Aucun nouveau ticket (BUG-247 et suivants non utilisés).
- Observation conservée : après restauration d'une altération, `is_tampered` reste posé sur les écritures et l'alerte reste ouverte, alors que `integrity_check` redevient `valid=true` (comportement voulu : alerte persistante).

## 4. Suite complète

`python manage.py test treasury blockchain` : machine saturée (autres suites en parallèle), exécution non terminée à la remise (≈ 80 tests verts au moment du dernier relevé, un seul `x` = échec attendu préexistant d'un autre fichier). Résultats complets : `test_vague2_db_testeur_tresorerie` 30/30 verts (aucun `expectedFailure` restant sur 238 à 241). Sortie en cours : `C:\Users\MUABIL~1\AppData\Local\Temp\full_tb.txt`.
