# Rapport dev-backend, 2026-11-22 (c8), branche dev-c

Périmètre : treasury/ et blockchain/ (+ `kiese/node_guard.py` pour BUG-810). Pas de migration, pas de commit.

## Tickets passés à CORRIGÉ
Majeurs : BUG-832, 830, 835, 839. Rouverts : BUG-810, 815, 818. Mineurs : 831, 833, 834, 836, 837, 838.
Aucun ticket laissé OUVERT. BUG-811 (b) reste À CLARIFIER (non touché).

| Ticket | Cause / correction | Fichiers |
|---|---|---|
| 832 | `TamperAlertViewSet` -> `ReadOnlyModelViewSet` + `resolve` (POST/PUT/PATCH/DELETE : 405) | blockchain/views.py |
| 830 | jour (ancien et nouveau) d'une clôture confirmée figé pour PATCH/DELETE de rapport ; `team` en lecture seule | treasury/views.py, serializers.py |
| 835 | référence du comptage = rang de chaîne le plus élevé parmi les écritures datées <= date | treasury/views.py |
| 839 | `promote_closure_to_cashbook` atomique, clôture verrouillée et relue, garde sur requête fraîche ; `validate` relit les totaux ; bon + écriture en une transaction | treasury/services.py, views.py |
| 810 | `resolve_node_param` refuse bool/float ; contrôle `node` du corps (rapports, PATCH épargne) | kiese/node_guard.py, treasury/views.py |
| 815 | unicité sur le nouveau nœud/date (épargne) ; clôture PATCH date : contrôle + IntegrityError -> 400 | treasury/views.py |
| 818 | `parse_date` ValueError rattrapée dans `reports/generate/` | treasury/views.py |
| 831 | dates futures refusées (épargne create/update, bon) | treasury/views.py |
| 833 | sans `?node=` : report et solde final sommés par boulangerie | treasury/views.py |
| 834 | `_check_closure_gap` ; refus 400 d'un solde cumulé hors plage dans `append_cashbook_entry` | treasury/views.py |
| 836 | repli de tête seulement sans `node=` ; pas d'alerte ouverte en double ; `global_status.all_intact` faux si 0 vérification (+ `never_checked`) | blockchain/views.py |
| 837 | `log_activity` : création clôture, création/suppression dépense, `run_check`, `resolve` | treasury/views.py, blockchain/views.py |
| 838 | `select_related` (catégorie, nœud, resolved_by) | treasury/views.py, blockchain/views.py |

`hashing.py` et le format du hash : inchangés.

## Tests
- Nouveau : `backend/treasury/tests/test_bug830_839.py` (35 tests environ, tous verts, échouaient avant).
- `manage.py test treasury blockchain --noinput` : 493 tests, aucun échec ni erreur ; 23 « unexpected success » (marques à retirer) et 1 échec attendu (BUG-811 b, conservé).
- `manage.py test sync --noinput` (promote et node_guard utilisés par sync) : 166 tests OK.
- `manage.py check` : OK. `makemigrations --check --dry-run` : aucun changement.

## Marques `@expectedFailure` à retirer (backend/treasury/tests/test_cycle2_tresorerie_c.py)
V810.test_BUG_810_bool_float_node_in_body_never_creates ; V810.test_BUG_830_report_team_patch_not_free ; V813.test_BUG_830_report_date_patch_into_confirmed_day_changes_pushed_net_silently ; V813.test_BUG_830b_report_cannot_be_deleted_on_confirmed_day ; V814.test_BUG_815_hq_patch_node_to_node_with_same_date_is_400_not_500 ; V814.test_BUG_831_savings_future_date_refused ; V816.test_BUG_832_tamper_alerts_are_not_editable_or_deletable ; V817.test_BUG_833_monthly_report_without_node_mixes_nodes_for_hq ; V818.test_BUG_818_generate_report_date_never_500 ; V818.test_BUG_831_voucher_future_date_refused ; V819.test_BUG_834_gap_overflow_with_max_expense_is_400_not_500 ; V819.test_BUG_834_push_two_max_closures_running_balance_overflow ; Integrite.test_BUG_835_direction_count_theoretical_balance_ignores_chain_order ; Integrite.test_BUG_836_run_check_with_node_filter_blames_unrelated_node ; Integrite.test_BUG_836_repeated_checks_duplicate_alerts ; Integrite.test_BUG_836_global_status_intact_with_zero_nodes_checked ; Integrite.test_BUG_837_activity_log_on_significant_treasury_actions ; Integrite.test_BUG_838_no_n_plus_one_on_lists ; Concurrence.test_BUG_839_stale_push_creates_double_versement ; Concurrence.test_BUG_839_failed_append_leaves_orphan_voucher ; Concurrence.test_BUG_839_failed_append_leaves_closure_modified ; Concurrence.test_BUG_839_validate_confirms_stale_totals_then_push_changes_them ; ClotureMiseAJour.test_BUG_815_closure_patch_date_to_existing_day_is_400_not_500.
Les marques des tests de `test_cycle1_tresorerie_c.py` pour 810/815/818 ont déjà été traitées (statut VÉRIFIÉ puis rouvert via cycle 2).

## Risques et points à noter
- Contrats d'API : alertes de falsification en lecture seule (405 en écriture) ; `global_status` : `all_intact: false` + `never_checked: true` si jamais vérifié ; ticket frontend éventuel (affichage « jamais vérifié »), non ouvert.
- `monthly_report` siège sans nœud : agrégation (pas de 400) ; choix à confirmer par le testeur.
- BUG-830 : `date`/`node` d'un rapport non validé d'un jour non confirmé restent modifiables (seul le gel du jour confirmé a été ajouté).
- `select_for_update` est sans effet sous SQLite : la garantie réelle de non-double versement en dev est la transaction ; sur PostgreSQL le verrou de ligne s'applique. Pas de contrainte d'unicité en base sur `source_closure` (partagée avec les écritures de correction BUG-083).
- Les lignes « Statut » des en-têtes de fiches BUG-830 à 839 n'ont pas toutes été mises à jour (le tableau et les lignes « Correction » font foi).
