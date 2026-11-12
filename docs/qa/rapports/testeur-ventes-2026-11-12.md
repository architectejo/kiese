# Rapport testeur-ventes — 2026-11-12

## Vérification ventes de BUG-161/B3 + BUG-180 à 184

Périmètre : `sales/views.py` (dates de travail), `core/workday.py::work_date_for`, `core/utils.validate_requested_date(node=)`, frontend `Sales.tsx`, `Clients.tsx`, `ThermalReceipt.tsx`. Aucun fichier applicatif modifié. Base de test uniquement (jamais `db.sqlite3`).

### Tests
- Nouveau : `backend/sales/tests/test_verif_ventes_b3_2026_11_12.py` (11 tests, 9 verts + 2 `@expectedFailure` BUG-197).
- Existants relancés (un processus, ciblé) : `test_invoices`, `test_bug083_backdated_sales`, `test_bug097_invoice_adjustment`, `test_bug177_ns_rg`, `test_bug180_181_182_183`, `test_bug161_b3_invoice_dates`, `test_bug161_b2_team_blocking`, `test_monthly_deficit_control`, `test_bug116_repayment_receipt` : **119 tests OK** (542 s). Puis `test_verif_ventes_bug177_bug161b2` + `test_bug083_verification_2026_10_29` : **40 tests OK** (292 s). Il n'existe pas de fichier `test_bug086` dans `sales/tests`.

### Scénarios
1. Rotation (relève 12:00) : 03:00 -> veille, 11:59 -> veille, 12:00 -> jour ; numéro de reçu préfixé de la date de travail ; `delivered_at` d'une vente rétroactive reconstruit dans la bonne journée (y compris relève 23:30 : 23:29 -> veille, 23:30 et 00:10 -> jour) : OK.
2. Hors rotation 00:30 : `invoice_date` = date locale, reçu `V1-20261112-…`, futur refusé, passé refusé sans `allow_backdated_sales` : OK.
3. `validate_requested_date` : OK (date calendaire après minuit = future en rotation ; journée courante acceptée sans option rétroactive).
4. `pending_deliveries`, `daily_summary`, `bread_summary` : journée de travail du nœud de l'utilisateur (03:00 en rotation) ; utilisateur HQ sans nœud : date locale, pas d'erreur : OK.
5. BP/plafond/remboursement/VENTE SOLDE/épargne : suites existantes vertes ; blocage au plafond en rotation (403 sans paiement, 201 avec paiement) : OK.
6. `recompute_client_debt()` = dette stockée après vente 11:59 + vente 12:00 + remboursement : OK (1500+1500-700 = 2300).
7. Frontend (relecture) : `Sales.tsx` : `loadData` dépend de `workDate` (`useEffect` relance la file), plus aucun `toISOString().slice(0,10)` dans `Sales.tsx`/`Clients.tsx`/`ThermalReceipt.tsx` ; `Clients.tsx` gère 403 `TEAM_NOT_ASSIGNED` (vente et remboursement) ; reçu de livraison : `team: inv.team || '—'` (BUG-184), reçu de remboursement `inv.team || …`; `ThermalReceipt` : date/heure réelles de la transaction (BUG-099) ; `npx tsc --noEmit` : aucune erreur ; aucun nouvel `any` dans le diff de `Sales.tsx`/`Clients.tsx`.

### Défaut trouvé : BUG-197
`_make_receipt_number(node.code, current_work_date)` : une facture rétroactive (`invoice_date` passée) reçoit un numéro préfixé de la date de travail COURANTE et compté sur `invoice_date == courante` ; ce compteur ne la voit pas. Une vente rétroactive puis une vente du jour produisent le MÊME numéro (`V1-20261112-0001` deux fois) ; le préfixe ne correspond pas à `invoice_date`. Préexistant (même formule avec `date.today()` avant B3) mais touche « numéro de reçu unique/cohérent ». Tests `@expectedFailure`.

### Contestation / validation de l'inversion
`test_backdated_invoice_blocked_without_today_assignment` -> `test_backdated_invoice_not_blocked_without_today_assignment` (`test_verif_ventes_bug177_bug161b2.py` l.455) : **validée**, conforme à la décision du coordinateur (vente rétroactive jamais bloquée, équipe de SA journée, sinon équipe de l'utilisateur). Le test vérifie bien 201 et `team == 'A'` (équipe désignée de la veille).

### Verdicts
BUG-180, 181, 182, 183, 184 : VÉRIFIÉ. BUG-161/B3 volet ventes : conforme (voir bloc dans la fiche), sous réserve de BUG-197.
