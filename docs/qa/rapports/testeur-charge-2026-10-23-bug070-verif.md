# Rapport testeur-charge — Vérification indépendante BUG-070 — 2026-10-23

## Ticket vérifié
**BUG-070** (Majeur, CORRIGÉ → **VÉRIFIÉ**) — `FinancialYearViewSet.summary()`
(`backend/finance/views.py`), N+1 sur les `CommissionPeriod`.

## Démarche
1. Relecture de la fiche BUG-070 (registre) et du rapport
   `docs/qa/rapports/dev-backend-bug070-fix-2026-10-23.md`.
2. Relecture du code corrigé (`backend/finance/views.py::FinancialYearViewSet.summary()`,
   lignes 190-237) : confirmé — une seule requête groupée
   `ClientCommission.objects.filter(period__in=periods).values('period').annotate(Sum/Count...)`,
   résultats réassociés en mémoire aux `CommissionPeriod` déjà chargés, aucune requête par
   itération.
3. Mesure indépendante n°1 : réutilisation sans modification du script de scénario enrichi déjà
   construit pour la vérification de BUG-066 (`volumetrie_bug066_verif.py`, base SQLite temporaire
   isolée, jamais `db.sqlite3` réel) — volume égal ou supérieur à celui ayant révélé le défaut :
   8 nœuds, 696 clients fictifs, 24 000 factures / 48 001 lignes, 1 920 `ClientCommission` pour
   l'année courante + 1 920 pour N-1 (192 `CommissionPeriod`).
4. Mesure indépendante n°2 : script dédié `verif_bug070_format.py` pour vérifier que le format de
   réponse (clés, types `str(Decimal)`, zéros par défaut) n'a pas changé par rapport à avant la
   correction.
5. `python manage.py test finance sales production treasury commissions`.

## Résultats

### Performance (mesure n°1, scénario enrichi)
| Endpoint | Médiane | Requêtes SQL | Verdict |
|---|---|---|---|
| **Commissions — `summary()` [BUG-070]** | **29,3 ms** (min 28,4/max 30,9) | **3** | OK, sous l'objectif 500 ms, conforme à la mesure dev-backend (30,9 ms / 3 requêtes) |
| Recherche client (~700 clients) | 53,3 ms | 3 | OK |
| Liste factures (filtrée) | 89,1 ms | 6 | OK |
| Liste factures (non filtrée) | 83,0 ms | 5 | OK |
| Finance — `comparative()` [BUG-066] | 366,6 ms | 18 | OK, pas de régression croisée |
| Finance — `income_statement()` | 278,0 ms | 10 | OK |
| Finance — `cashflow()` | 16,5 ms | 6 | OK |
| Production — `reconciliation()` | 21,0 ms | 7 | OK |
| Livre de caisse direction — liste | 35,0 ms | 3 | OK |

Nombre de requêtes de `summary()` indépendant du nombre de périodes (3 requêtes fixes), confirmé.

### Format de réponse (mesure n°2)
2 `CommissionPeriod` (une avec 1 `ClientCommission`, une sans aucune) :
- Les 12 clés attendues sont présentes et identiques pour les deux lignes :
  `node`, `node_code`, `node_name`, `month`, `year`, `period_id`, `is_closed`, `client_count`,
  `total_orders`, `total_cm`, `total_net`, `total_debt`.
- Valeurs `str(Decimal)` correctes pour la période avec données :
  `total_orders='500000'`, `total_cm='125000'`, `total_net='100000'`, `total_debt='25000'`.
- Période sans `ClientCommission` : zéros par défaut confirmés
  (`client_count=0`, tous les totaux `'0'`), comportement strictement identique à avant la
  correction.
- **Aucune régression de format.**

### Tests automatisés
`python manage.py test finance sales production treasury commissions` → **136 tests, 2 échecs**,
exactement les deux déjà connus et sans rapport avec ce ticket (**BUG-068**, date codée en dur) :
- `treasury.tests.test_cashbook_level3.FullDayIntegrationTests.test_full_day_scenario`
- `treasury.tests.test_reports_closures.CashClosureNetCashTests.test_net_cash_is_cash_sales_minus_local_expenses`

Aucune régression nouvelle liée à BUG-070.

## Conclusion
**BUG-070 passé à VÉRIFIÉ** dans `docs/qa/REGISTRE_BUGS.md`. Correction conforme : cause confirmée
par relecture de code, performance mesurée indépendamment (29,3 ms médiane / 3 requêtes, sous
l'objectif de référence 500 ms), format de réponse API inchangé, aucune régression dans les suites
de tests `finance`/`sales`/`production`/`treasury`/`commissions`.

Avec ce ticket vérifié, aucun ticket bloquant ou majeur ouvert n'est connu pour le mandat
testeur-charge au 2026-10-23 (phase 4) — à confirmer par le coordinateur pour la clôture de phase.

## Fichiers
- Modifié : `docs/qa/REGISTRE_BUGS.md` (BUG-070 → VÉRIFIÉ, section « Vérification » complétée).
- Créé (ce rapport) : `docs/qa/rapports/testeur-charge-2026-10-23-bug070-verif.md`.
- Scripts hors dépôt (scratchpad, jamais exécutés contre un serveur de production ni `db.sqlite3`),
  tous dans `C:\Users\MUABIL~1\AppData\Local\Temp\claude\d--Projects-kiesse\8fca5c01-a750-49dc-ad35-bcecf262b57d\scratchpad\` :
  - `volumetrie_bug066_verif.py` (réutilisé sans modification)
  - `verif_bug070_format.py` (nouveau, vérification de format)

Aucune modification de code applicatif.
