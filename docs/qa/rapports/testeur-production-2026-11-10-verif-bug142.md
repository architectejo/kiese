# Rapport testeur-production — 2026-11-10 — Vérification BUG-142

## Contexte

`dev-backend` a passé **BUG-142** (remarque.md, ligne ajoutée après l.394 — confirmation du reste
d'hier doit alimenter la fournée du jour ; plusieurs déclarations le même jour/équipe doivent
s'additionner) à `CORRIGÉ`. Mission : vérifier indépendamment, sans se contenter de relire les
tests de dev-backend, et statuer sur l'ambiguïté qu'il a lui-même signalée (filtre
`source=DECLARED` introduit dans `_build_daily_closure_report`, BUG-120).

## Nettoyage avant/après (incident récurrent « mauvais interpréteur »)

- Avant de commencer : deux processus fantômes `python.exe` (système, PID 7032 et 19640) étaient
  en écoute sur le port 8000, sans connexion active — arrêtés.
- Pendant la vérification, un serveur `runserver` (système Python, pas le venv) est apparu/a
  rechargé plusieurs fois sur le port 8000 avec une connexion Chrome active (**ESTABLISHED**) —
  manifestement une session de test en direct du client ou du coordinateur, pas quelque chose que
  j'ai lancé. Je ne l'ai **pas arrêté** (couper un serveur activement utilisé par un vrai
  utilisateur aurait été plus nuisible que l'incident lui-même). Signalé ici pour information, pas
  comme une anomalie de ce ticket.
- À la fin : mes propres processus de test (`manage.py test ...`) sont bien terminés et nettoyés
  (vérifié via `Get-CimInstance Win32_Process`, aucun résidu). Le fichier de log temporaire
  `backend/_test_run_bug142.log` a été supprimé. Aucune modification de `backend/db.sqlite3` (la
  base réelle du matin) — toute la vérification s'est faite sur la base de test éphémère de
  `manage.py test`.

## Relecture du code final

Code relu directement dans `backend/production/views.py` (pas seulement le rapport de
dev-backend) : `ProductionSessionViewSet.perform_create()`/`perform_update()`,
`_sync_carryover_session_lines()`, `DailyOpeningConfirmationView.post()`,
`_build_daily_closure_report()` — et `backend/production/models.py`
(`ProductionSessionLine.source`, `ProductionSession.compute_totals()`). Le résumé du rapport de
dev-backend correspond exactement au code livré.

## Vérifications indépendantes (nouveau fichier de tests)

`backend/production/tests/test_verif_bug142_testeur_production.py` — 3 tests, construits sans
reprendre ceux de dev-backend, tous verts :

1. **`Bug142NoCarryoverDayIsUnaffectedTests`** — Point 1 de la mission. Jour SANS confirmation
   BUG-133 (aucune ligne `CARRYOVER` en base, vérifié par assertion explicite) : le rapport de
   clôture journalier (`/api/production/daily-closure/`) donne des totaux strictement identiques à
   ce qu'un calcul manuel donnerait avec ou sans le filtre `source=DECLARED` — non-régression
   confirmée. **Les chiffres de référence 240 500/840 000 (audit BUG-120, 2026-11-02,
   `docs/qa/REGISTRE_BUGS.md:10552` et `:10578`) portent sur `facture_mvm_interne`/
   `total_du_jour_fc`, dont la formule (relue ligne à ligne dans `_build_daily_closure_report`) ne
   contient JAMAIS `produced_by_bp`** — le filtre introduit par BUG-142 ne peut donc, par
   construction, pas affecter ces deux totaux déjà vérifiés par le client, qu'il y ait ou non du
   carryover un jour donné. Le test existant `test_daily_closure_report_aggregates_exact_totals`
   (`test_daily_closure_report.py`, inchangé, toujours vert) reste la bonne ancre de
   non-régression pour ce rapport puisqu'il ne crée jamais de confirmation BUG-133.

2. **`Bug142CarryoverEndToEndTests`** — Point 2. Scénario bout-en-bout construit via les endpoints
   HTTP (pas seulement les modèles) : veille avec reste physique de 15 pains → confirmation du
   reste du hier pour l'équipe A aujourd'hui → vraie fournée de 100 pains (2 sacs) le même
   jour/équipe. Vérifié :
   - La session apparaît dans `/api/production/sessions/` avec une ligne `CARRYOVER` (15) et une
     ligne `DECLARED` (100).
   - `yield_gap`/`theoretical_yield` ne comptent que le déclaré (100×300 − 2×200000), inchangés par
     le carryover.
   - `_build_daily_closure_report` ne double-compte PAS : `produit.quantity` = 100 (jamais 115),
     `reste_du_hier.A` = -15 une seule fois, `facture_mvm_interne` recalculé à la main concorde à
     l'identique avec la valeur renvoyée par l'API.

3. **`Bug142NoDoubleCountingReverseOrderTests`** — Point 3, avec un ordre et un contexte
   différents de ceux déjà couverts par dev-backend (déclaration réelle PUIS confirmation, stock
   physique préexistant non nul créé indépendamment de toute session) : `BreadStock.qty_available`
   passe de 40 → 140 (après la fournée) → 140 (après confirmation telle-que-proposée, delta nul,
   no-op BUG-136) — jamais 280. Confirmé que `_sync_carryover_session_lines` n'appelle jamais
   `_adjust_bread_stock`.

4. **Accumulation (cas A) et refus sur session clôturée (BUG-093)** : j'ai relu en détail les 6
   tests de `FourneeAccumulationSameDayTeamTests` et les 7 tests de
   `OpeningConfirmationFeedsProductionSessionTests` (dev-backend) en cherchant activement un
   contournement (double déclaration concurrente, édition d'une fournée avec lignes CARRYOVER,
   confirmation sur session clôturée par l'autre point d'entrée) — je n'ai trouvé aucune faille
   supplémentaire. Le verrou `select_for_update()` est posé dans les deux points d'entrée
   (`perform_create`, `_sync_carryover_session_lines`) sur la même clé `(node, team, date)`, ce qui
   évite une fourche entre une déclaration et une confirmation simultanées.

## Point signalé — NON bloquant pour BUG-142

En construisant le scénario bout-en-bout (test 2), j'ai trouvé que `totals.total_breads_produced`
(champ `ProductionSession.total_breads`, somme sur **toutes** les lignes, décision client
explicite du ticket) sert de dénominateur à `totals.repartition_pct_par_quantite`, alors que le
numérateur (`produit.quantity` par catégorie) est désormais filtré `DECLARED` seul. Dès qu'une
ligne CARRYOVER existe un jour donné, la somme des pourcentages de cette rubrique ne vaut plus
100 % (ex. mon scénario : 100/115 = 86,96 % pour l'unique catégorie produite ce jour, au lieu de
100 %).

Ce n'est :
- **pas une régression de BUG-142** — ce ticket ne touche jamais `repartition_pct_*`, et cette
  rubrique n'existait de toute façon qu'à l'état « tout DECLARED » avant ce ticket (donc aucun
  comportement vérifié n'est cassé) ;
- **pas un double comptage sur une valeur financière déjà auditée** — `net_produit_fc`,
  `facture_mvm_interne`, `total_du_jour_fc`, `ecart_production_fc` restent corrects (vérifiés par
  calcul indépendant ci-dessus) ;
- **une incohérence de dénominateur dans un indicateur secondaire** (répartition en %, Q-007.3,
  déjà documentée comme affichage à choix du frontend), qui ne devient visible que les jours où un
  reste d'hier est confirmé.

Documenté dans la fiche BUG-142 (`docs/qa/REGISTRE_BUGS.md`) et dans le nouveau test
`test_full_scenario_confirmation_then_fournee_no_double_count_anywhere` (assertion explicite,
commentée, pas un `@expectedFailure` — ce n'est pas un échec mais une caractéristique à discuter).
À ouvrir comme ticket séparé si le coordinateur/`auditeur-comptable` juge que cet indicateur doit
rester exact à 100 % même les jours avec carryover (correction suggérée si besoin : dénominateur
= somme de `produced_by_bp` plutôt que `total_breads_produced`, mais je ne tranche pas ce choix
moi-même).

## Suite de tests complète

- `backend/.venv/Scripts/python.exe manage.py test production.tests.test_verif_bug142_testeur_production`
  → **3/3 OK**.
- `backend/.venv/Scripts/python.exe manage.py test production sales finance sync` (relancée
  moi-même, pas seulement le chiffre de dev-backend) → **285/285 OK** (209 tests `production
  sales finance` + tests `sync` + mes 3 nouveaux tests de vérification — correspond à 567/567
  rapporté par dev-backend pour la suite complète tous modules).
- `backend/.venv/Scripts/python.exe manage.py makemigrations --check --dry-run` → `No changes
  detected`.

## Décision

**BUG-142 passé à `VÉRIFIÉ`** (`docs/qa/REGISTRE_BUGS.md`, tableau de suivi et fiche détaillée,
section « Vérification » ajoutée). Le filtre `source=DECLARED` introduit sur `produced_by_bp` dans
`_build_daily_closure_report` est confirmé correct et ne fausse aucun total déjà vérifié par
`auditeur-comptable` sous BUG-120 — avec ou sans carryover ce jour-là. Le point sur
`repartition_pct_par_quantite` est signalé séparément comme observation mineure, pas comme un
blocage.

## Fichiers

- Lu : `backend/production/views.py`, `backend/production/models.py`,
  `backend/production/serializers.py`, `backend/sync/services.py`,
  `backend/production/tests/test_bug142_fournee_carryover_accumulation.py`,
  `backend/production/tests/test_daily_closure_report.py`,
  `docs/qa/rapports/dev-backend-2026-11-10-bug142-fournee-confirmation-accumulation.md`,
  `docs/qa/REGISTRE_BUGS.md` (fiches BUG-120 et BUG-142).
- Créé : `backend/production/tests/test_verif_bug142_testeur_production.py`.
- Modifié : `docs/qa/REGISTRE_BUGS.md` (statut BUG-142 → VÉRIFIÉ, tableau + fiche détaillée, section
  Vérification ajoutée).
