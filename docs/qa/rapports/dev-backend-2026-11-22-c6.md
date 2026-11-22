# Rapport dev-backend (Dev C) - 2026-11-22-c6 - BUG-810 a BUG-819 (tresorerie)

Branche dev-c. Pas de commit ni de push. Frontend non modifie (aucun appel a PUT/PATCH/DELETE de bon de decaissement dans `services.ts`).

## Tickets passes a CORRIGE
| Ticket | Cause | Correction (`backend/treasury/views.py`) |
|---|---|---|
| BUG-810 | `Node.objects.get(pk='abc')` ne rattrapait que `DoesNotExist` | helper `_body_node` (base `kiese.node_guard.resolve_node_param`) : 400 `{"detail"}` pour un `node` illisible/inconnu (depenses, cloture, generation des rapports ; journal/epargne l'avaient deja via le serializer) |
| BUG-811 (a) | billetage facultatif | 400 si aucune des 8 coupures n'est dans le corps a la creation (0 explicite accepte). Verifie apres les controles de date/transfert/totaux, avant toute ecriture |
| BUG-812 | `team=user.team` non controlee | 400 si l'equipe du gerant n'est pas A ou B |
| BUG-813 | date non validee, jour confirme modifiable | date future refusee (creation + modification) ; creation/modification/suppression d'une depense refusees (400) un jour dont la cloture du noeud est confirmee. Dates passees toujours acceptees (pas de dependance a `allow_backdated_sales`) |
| BUG-814 | `or` sur un `Decimal('0')` | test `is None` |
| BUG-815 | `validators = []` | controle d'unicite (noeud, date) dans `perform_update` -> 400 |
| BUG-816 | `ModelViewSet` sur un objet lie a une ecriture hachee | `http_method_names = get/post/head/options` : PUT/PATCH/DELETE -> 405 (403 pour non-siege) |
| BUG-817 | date non validee ; solde depuis l'ecriture la plus recente | date future refusee ; solde calcule a partir de l'ecriture precedente dans l'ordre (date, created_at, pk), puis recalcul de `running_balance`/`month_carried` des ecritures posterieures, dans `transaction.atomic()` avec verrou du noeud |
| BUG-818 | chaines brutes dans `filter(date__gte=...)` | `_date_param` (`parse_date_param`) sur `cashbook/`, `period_summary/`, `final_report/` ; `suggested_ca?node=` via `resolve_node_param` -> 400 |
| BUG-819 | somme des depenses hors DecimalField(14,2) apres ecriture | `_check_closure_totals` : 400 avant ecriture (creation et resoumission ; la resoumission calcule avant `save` et ecrit dans une transaction) |

## Choix BUG-817 (antidatage)
Antidatage accepte avec recalcul plutot que refuse : le journal de caisse par boulangerie n'est pas hache (la chaine SHA-256 ne concerne que `CashbookEntry`), donc recalculer les soldes posterieurs ne peut rien casser, alors que refuser empecherait la saisie legitime d'un jour oublie. Le livre de caisse direction (hash) n'est pas touche. Aucune migration, aucun changement de hash (`treasury/hashing.py` inchange, chaines existantes intactes).

## BUG-811 (b) : non modifie
Le point (b) (billetage d'une cloture ni infirmee ni confirmee modifiable sans trace) est laisse A CLARIFIER cote client (note dans la fiche). Le test `test_BUG_811_pending_closure_gap_cannot_be_silently_rewritten` doit donc RESTER `@expectedFailure`. Le ticket BUG-811 est passe a CORRIGE pour (a) seulement : le testeur peut le garder ouvert pour (b) s'il le juge utile.

## Marques `@expectedFailure` a retirer (`test_cycle1_tresorerie_c.py`, 12 tests, verifies : « unexpected success »)
- `test_BUG_810_non_numeric_node_in_body_is_400_not_500`
- `test_BUG_811_all_denominations_omitted_is_not_accepted_silently` (PAS `..._pending_closure_gap_...` : a garder)
- `test_BUG_812_report_team_must_be_A_or_B`
- `test_BUG_813_expense_future_date_refused`, `test_BUG_813_expense_on_confirmed_closure_day_refused`
- `test_BUG_814_savings_rate_zero_is_honoured`
- `test_BUG_815_savings_put_to_existing_date_is_400_not_500`
- `test_BUG_816_voucher_edit_or_delete_must_not_break_ledger`
- `test_BUG_817_journal_future_date_refused`, `test_BUG_817_journal_backdated_entry_balance_follows_date_order`
- `test_BUG_818_date_period_params_are_400_not_500`
- `test_BUG_819_huge_expenses_do_not_make_closure_500_or_vanish`

## Tests
- Nouveau : `backend/treasury/tests/test_bug810_819.py` (19 tests, sans marque, echouaient avant).
- Contrat modifie (BUG-811 a) : la creation d'une cloture sans aucune coupure est refusee. 13 tests existants creaient une cloture avec `{'date': ...}` seul ; j'ai ajoute `'bills_50': 0` a leur corps (aucune assertion changee ni affaiblie) dans `test_bug086_closure_date_validation.py`, `test_bug086_independent_verification.py`, `test_bug178_verification_2026_11_11.py`, `test_reports_closures.py`, `test_vague2_db_testeur_tresorerie.py`, `test_verification_b3_tresorerie_2026_11_12.py`. Impact API : tout client qui POST une cloture doit envoyer les 8 coupures (le frontend les envoie).
- Resultats : `manage.py test treasury blockchain` (sans --parallel) : 415 tests, aucun echec ni erreur ; 12 « unexpected successes » = les marques ci-dessus a retirer, 1 expected failure (BUG-811 b). `manage.py test commissions core finance sales production sync` : 2413 tests, aucun echec ; 1 unexpected success `test_BUG_564_...` (ticket d'un autre agent, hors perimetre). `check` et `makemigrations --check --dry-run` : propres.

## Risques / a surveiller
- Un client (synchronisation, scripts) qui creerait des clotures sans billetage recevra 400.
- Les depenses d'un jour de cloture confirmee sont gelees : le gerant ne peut plus corriger une depense apres confirmation (comportement voulu ; une correction tracee type BUG-083 serait un ticket separe).
