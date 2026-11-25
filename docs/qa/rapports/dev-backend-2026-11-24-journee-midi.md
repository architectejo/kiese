# Rapport dev-backend (B) : journée comptable de midi à midi (BUG-1130)

Date : 2026-11-24. Source : réponse FERME du client Q-018 (la journée va de midi à midi, heure de clôture du nœud, 12:00 par défaut, toutes boulangeries). Remplace la décision du 2026-11-12 (jour calendaire).
Conception : `docs/qa/CONCEPTION_JOURNEE_MIDI_A_MIDI_2026-11-24.md`. Aucun commit, aucun push.

## Tickets
- BUG-1130 : CORRIGÉ (journée de midi à midi, helper unique).
- BUG-1131 : CORRIGÉ (la journée terminée reste clôturable sans réglage « ventes passées » ; évite un blocage mutuel avec le verrou de vente).
- BUG-1132 : À CLARIFIER (question client Q-1130-A : commissions et rapports mensuels suivent la journée comptable).
- BUG-1133 : À CLARIFIER (désignation d'équipe hors rotation encore calendaire : périmètre de l'agent `team_rotation_enabled`).
- BUG-1134 : OUVERT pour dev-frontend (la date « du jour » doit venir de `work_date` serveur, plus de `new Date()`).

## Implémentation (par le helper unique `core/workday.py`)
Aucune migration (aucun schéma modifié ; `makemigrations --check` : « No changes detected »). Aucune réécriture de données passées.

Fichiers applicatifs modifiés :
- `backend/core/workday.py` : `closure_time_for`, `business_day_for`, `business_day_bounds`, `instant_in_business_day` ; `work_date_for`, `business_date`, `workday_bounds`, `delivered_on_work_date_filter` (intervalle `[début, fin[`), `team_at_day_start` (équipe au début de la journée) en dépendent. Nœud absent ou heure invalide = 12:00.
- `backend/core/utils.py` : `validate_requested_date(..., allow_previous_day=False)` (BUG-1131).
- `backend/treasury/closure_lock.py` : la clôture à valider est celle de la journée terminée (jour de travail - 1).
- `backend/treasury/views.py` : rapport facturier et clôture de caisse (création/modification) acceptent la journée terminée.
- `backend/treasury/services.py` : écriture de correction du livre de caisse datée de la journée comptable.
- `backend/sales/views.py` : `daily_summary` par intervalle et par nœud, `_combine_date_with_now_time` (via `instant_in_business_day`), déduplication de la notification « ventes bloquées » par journée comptable.
- `backend/production/services.py` : `auto_close_day` (journée D terminée à D+1 à l'heure de clôture), `auto_close_due_days`.
- `backend/production/views.py` : `shift-end-status` (jour courant = journée comptable, plus de clôture silencieuse à minuit), inventaire du jour.
- `backend/production/consumables_direction.py`, `backend/production/intrants_stats.py` : jour = journée comptable du nœud (stats par jour et inventaire physique).
- `backend/sync/services.py` : contrôle « pas de date future » comparé à la journée comptable de l'horodatage (`delivered_at`, `not_served_at`, `closed_at`).
- Non concernés (documentés dans la conception) : commissions (suivent `invoice_date`), `clients/views.py`, `finance/*`, `blockchain`, `flour_month_stats` (agrégats mensuels/annuels).

Fichiers de test ajoutés : `backend/core/tests/test_dev_b_journee_midi.py` (12 tests : helper, rapport facturier, `daily_summary`, verrou, vente à 09:00 datée de la veille, clôture de la journée terminée, déblocage).

## Tests existants adaptés (documentés un par un dans les en-têtes/commentaires `BUG-1130` des fichiers)
Principe : une attente « jour calendaire » (03:00 / 00:30 / 09:00 / 10:00 = jour D) devient « journée de la veille » ; les scénarios horaires du matin sont décalés après midi ; « minuit change la date/ferme la fournée » devient « rien ne se passe à minuit, tout se passe à la relève de 12:00 ».
- core : `test_bug161_b3_workday_dates.py` (réécrit, attentes de journée comptable).
- sales : `test_bug161_b3_invoice_dates.py`, `test_vague4_calendaire_ventes_2026_11_12.py` (la journée change à midi ; deux équipes ne partagent plus un même jour), `test_vague1_corrections_ventes.py`, `test_vague1_db_ventes_2026_11_12.py`.
- treasury : `test_dev_d38_blocage_ventes.py`, `test_verif_tresorerie_c15_v14.py` (L973), `c16`, `c17`, `c18` (verrou : la clôture exigée est celle de la journée terminée), `test_vague4_db_testeur_tresorerie.py`, `test_verification_b3_tresorerie_2026_11_12.py`, `test_bug189_vacation_lock_local_date.py`, `test_bug086_*` (3 fichiers : la « veille » est désormais clôturable, le refus s'applique à l'avant-veille), `test_cycle1_tresorerie_c.py` (`today()` = journée comptable).
- production : `test_bug161_b2/b3/b4/b5`, `test_bug190_196`, `test_bug247_calendar_day`, `test_bug278_equipe_redesignee` (plus de réouverture de la session de la veille), `test_bug286_287_288`, `test_bug350_rotation_handover_clock`, `test_dev_bug1120_auto_closed`, `test_restes_journee_cloture_auto_a`, `test_vague1_corrections_production`, `test_vague1_db_production`, `test_vague4_testeur_production`, `test_verif_bug161_*`, `test_verif_bug319_322`, `test_verif_bug356`, `test_verif_bug501_510_a`, `test_verif_bug508_363_512_a2`, `test_verif_croisee_b_a1_a4`, `test_verif_production_a16_v16`, `test_verif_rotation_prod_c`.

## Résultats des tests (ciblés, pas de série complète)
Exécutés : modules `core`, `treasury`, `sales`, `production`, `sync` dont le contenu dépend de l'heure (filtre sur `handover_time`, `work_date_for`, `closure-status`, `daily_summary`, `auto_close`, `shift-end`, `localdate`, `timezone.now`, `delivered_at`…). Résultat final : voir la fin de ce fichier (section « Verdict »).

## Points à trancher / signalés (aucune décision métier prise seul)
1. Q-1130-A : commissions et rapports mensuels suivent `invoice_date` : une vente du 1er à 09:00 compte dans le mois précédent (BUG-1132).
2. Désignation d'équipe hors rotation encore calendaire (BUG-1133) ; Q-017 indique que toutes les boulangeries sont en rotation 24 h.
3. Verrou de vente : bloque dès l'heure de clôture tant que la clôture de la journée terminée n'est pas validée, même s'il n'y a eu aucune vente la veille (comportement identique à l'ancien pour un jour sans vente).
4. Mode « créneaux fixes » hors rotation (équipe A 06:00-11:30, B 14:30-20:00) : incompatible avec une journée de midi à midi (le créneau du matin appartient à la journée de la veille). La réponse Q-017 le rend obsolète ; les tests de cette fonctionnalité ont été décalés après midi, le code hérité (`team_a_end_time` / `team_b_end_time`) n'a pas été retouché.
5. Jour de bascule en production : déployer après la clôture validée de la journée en cours (de préférence à midi) ; la base ayant été remise à zéro le 2026-11-10, le volume à risque est faible. Aucune migration de données (recommandation écrite dans la conception).
6. Les tests qui utilisent `date.today()` / `timezone.localdate()` réels (≈ 300 occurrences) donnent les mêmes résultats tant que l'heure locale est après 12:00 et peuvent échouer le matin (entre 00:00 et 12:00). `today()` du module `test_cycle1_tresorerie_c.py` a été corrigé ; les autres occurrences sont à traiter (ou à figer par horloge simulée) : risque de tests instables le matin.
7. Je n'ai pas modifié `Node.team_rotation_enabled`, les permissions de validation de clôture, ni les notifications d'heure de clôture (autre agent). L'autre agent lit `closure_status()['closure_date']` comme « journée qui s'achève » : après BUG-1130 c'est bien la journée terminée (jour de travail - 1). Ses tests (`test_dev_b_rotation_q017_021.py`, 3 fichiers) passent.
8. Incident de session : un arrêt de processus (`python.exe`) trop large lancé pour interrompre mes propres séries de tests a pu interrompre un test d'un autre agent en cours : à relancer si nécessaire.

## Verdict (tests ciblés, dernière exécution)
- `makemigrations --check --dry-run` : « No changes detected ».
- Verts après adaptation : `core.tests.test_dev_b_journee_midi` (12) et `test_bug161_b3_workday_dates` ; `sales` (série complète des modules dépendant de l'heure + `sync` : 585 tests, les 9 échecs initiaux, tous des attentes calendaires, corrigés puis revérifiés) ; `treasury` (modules clôture/verrou/rapports/BUG-086/versements : 199 tests OK) ; `production` (modules rotation/clôture automatique/restes/stocks/rapport journalier : tous OK après adaptation, dernier lot de 30 tests OK).
- Non exécutés (hors périmètre demandé, pas de série complète) : le reste de `production`, `clients`, `commissions`, `finance`, `blockchain`. À lancer par le testeur avant passage en VÉRIFIÉ.
- Les tickets ne sont PAS passés à `VÉRIFIÉ` (réservé au testeur).
