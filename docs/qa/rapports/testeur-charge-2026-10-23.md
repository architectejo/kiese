# Rapport testeur-charge — Vérification indépendante BUG-066 — 2026-10-23

## Mission
Vérification indépendante de la correction dev-backend pour BUG-066 (`FinancialYearViewSet.comparative()`,
`backend/finance/views.py`) : relecture du code et des migrations, re-mesure sous charge, enrichissement
du scénario avec `ConsumableMovement`/`LocalExpense`/`ClientCommission` (angle mort signalé par dev-backend),
exécution de la suite de tests concernée.

## 1. Relecture du code et des migrations
- `backend/finance/views.py` : les 4+4 `.aggregate()` séparés de `_income_statement_for_year()`
  (revenu par catégorie de pain, COGS par type de consommable) sont bien fusionnés en 2 appels
  uniques via `Sum(..., filter=Q(...))`. `_cashflow_for_year()` : `total_in`/`total_out` fusionnés
  en un seul `.aggregate()`. Même format de réponse, mêmes clés, mêmes valeurs `Decimal` — conforme
  à la description du rapport dev-backend.
- 3 migrations d'index relues :
  - `backend/production/migrations/0012_bug066_consumablemovement_index.py` :
    `ConsumableMovement(['movement_type', 'created_at'])`.
  - `backend/treasury/migrations/0010_bug066_cashbook_localexpense_indexes.py` :
    `CashbookEntry(['date', 'created_at'])` + `LocalExpense(['date'])`.
  - `backend/commissions/migrations/0003_clientcommission_comm_clico_period_paid_idx.py` :
    `ClientCommission(['period', 'is_paid'])`.
  Chacune isolée au seul `AddIndex` attendu — ne reprend pas la dérive de schéma préexistante
  BUG-057 détectée au passage sur ces mêmes apps (`production`/`clients`/`treasury`). Conforme.

## 2. Re-mesure indépendante, scénario enrichi

Le script original `backend/scripts/charge/volumetrie.py` ne seedait aucune donnée dans
`ConsumableMovement`/`LocalExpense`/`ClientCommission` — point explicitement signalé par dev-backend
comme non validé par sa propre mesure. J'ai écrit une copie enrichie du script (hors dépôt, mêmes
garde-fous d'isolation de base temporaire — jamais `db.sqlite3` ni serveur de production), qui
ajoute :
- 1 600 `ConsumableMovement` (ENTRY) sur 10 jours × 8 nœuds,
- 240 `LocalExpense` sur 10 jours × 8 nœuds,
- 1 920 `ClientCommission` (192 `CommissionPeriod`, 8 nœuds × 12 mois × 2 ans, `is_paid=True`),

en plus du volume de base identique à la mission d'origine : 24 000 factures / 48 000 lignes / 8
nœuds / 696 clients / 10 jours.

| Endpoint | Mesure | Requêtes SQL | Verdict |
|---|---|---|---|
| Recherche client (~700 clients) | 49,4 ms médiane | 3 | OK |
| Liste factures — filtrée nœud+jour | 74,1 ms médiane | 6 | OK |
| Liste factures — NON filtrée (1ère page) | 67,2 ms médiane | 5 | OK |
| **Finance — `comparative()` [BUG-066]** | **353,8 ms** médiane (min 301,1/max 375,3) | **18** | **OK, sous l'objectif 500 ms** |
| Finance — `income_statement()` seul | 421,6 ms médiane | 10 | OK |
| Finance — `cashflow()` seul | 44,2 ms médiane | 6 | OK |
| Production — `reconciliation()` | 50,6 ms médiane | 7 | OK |
| Livre de Caisse Direction — liste | 56,3 ms médiane | 3 | OK |
| Commissions — `summary()` | **538,8 ms** médiane (min 435,4/max 747,3) | **194** | **HORS OBJECTIF — nouveau constat, voir §4** |

**Conclusion BUG-066** : `comparative()` reste sous l'objectif de référence (353,8 ms vs 341,5 ms
mesuré par dev-backend) **même avec les 3 tables `ConsumableMovement`/`LocalExpense`/
`ClientCommission` réellement peuplées** — ce que la mesure dev-backend seule n'avait pas pu
valider. Les 18 requêtes et le gain mesuré sont cohérents entre les deux mesures indépendantes.
Aucune régression sur les 6 autres endpoints du scénario original.

## 3. Tests automatisés
`python manage.py test finance sales production treasury commissions` relancé indépendamment :
**136 tests, 2 échecs**, strictement les deux mêmes que ceux rapportés par dev-backend :
- `treasury.tests.test_cashbook_level3.FullDayIntegrationTests.test_full_day_scenario`
- `treasury.tests.test_reports_closures.CashClosureNetCashTests.test_net_cash_is_cash_sales_minus_local_expenses`

Cause confirmée (déjà documentée, ticket **BUG-068**, hors périmètre de ce mandat) : date codée en
dur `'2026-10-22'` alors que `Invoice.invoice_date` est `auto_now_add` (date réelle du jour,
2026-10-23 dans cette session). Aucune régression nouvelle.

## 4. Constat additionnel — nouveau ticket BUG-070 (Majeur, OUVERT)
En peuplant `CommissionPeriod`/`ClientCommission` de façon représentative (192 périodes, 1 920
lignes) pour valider l'index posé pour BUG-066, l'endpoint `Commissions — summary()`
(`FinancialYearViewSet.summary()`, même fichier `backend/finance/views.py`) est ressorti à
**538,8 ms médiane / 194 requêtes** — dépasse l'objectif de référence. Cause : boucle Python sur
chaque période avec 2 requêtes séparées (`.aggregate()` + `.count()`) par période au lieu d'une
requête groupée (`.values('period').annotate(...)`). Ce défaut était invisible dans toutes les
mesures précédentes (BUG-064, ouverture et correction de BUG-066) car le script de charge
original ne seedait jamais ces deux tables (queryset vide → boucle jamais exécutée, mesuré à
8-12 ms). Ticket détaillé : `docs/qa/REGISTRE_BUGS.md` fiche BUG-070. **Ne bloque pas la
vérification de BUG-066** (endpoint différent, hors périmètre d'origine du ticket).

## Verdict final
**BUG-066 passé à VÉRIFIÉ** dans `docs/qa/REGISTRE_BUGS.md`. Correction conforme, mesure
indépendante confirmée sous l'objectif de référence (< 500 ms), y compris avec les 3 index
auxiliaires réellement sollicités. Nouveau ticket **BUG-070** ouvert pour un N+1 distinct découvert
pendant la vérification, à traiter séparément.

## Fichiers
- Modifiés : `docs/qa/REGISTRE_BUGS.md` (BUG-066 → VÉRIFIÉ, fiche de vérification ajoutée ; BUG-070
  ouvert avec fiche détaillée).
- Créé (hors dépôt, scratchpad, outil de mesure ponctuel) :
  `C:\Users\MUABIL~1\AppData\Local\Temp\claude\d--Projects-kiesse\8fca5c01-a750-49dc-ad35-bcecf262b57d\scratchpad\volumetrie_bug066_verif.py`.
- Code applicatif : **non modifié** (conforme au mandat testeur).
