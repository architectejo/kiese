# Rapport auditeur-comptable — 2026-11-02/03 — Vérification de BUG-123

Mission : vérifier le correctif BUG-123 (CORRIGÉ par dev-backend, 2026-11-02) suite à la réponse
du client sur Q-005 (`docs/qa/QUESTIONS_CLIENT.md`) — bascule du coût matière du Compte de Résultat
des achats du mois (`ConsumableMovement` ENTRY) vers la consommation réelle en production
(`ConsumableMovement` EXIT), valorisée au Coût Unitaire Moyen Pondéré (CUMP,
`ConsumableStock.average_unit_cost`).

Rapport source lu avant de commencer : `docs/qa/rapports/dev-backend-2026-11-02-q001-q002-q005.md`
(section BUG-123).

## Méthode

Tous les calculs ci-dessous ont été **rejoués indépendamment** (pas une relecture seule) : scénarios
de test exécutés contre une base de test SQLite jetable (`python manage.py test`), aucune donnée
réelle de `data_kiese/` dans ces scénarios (CLAUDE.md §4, données fictives uniquement). Les fichiers
Excel réels d'août 2026 ont été ouverts en lecture avec `openpyxl` dans une session de travail
temporaire, uniquement pour vérifier l'existence (ou non) de données permettant un recoupement
chiffré — aucune donnée réelle (nom de client, montant précis) n'est reproduite dans ce rapport.

## 1. Reproduction du CUMP (plusieurs achats à prix différents + sorties étalées dans le temps)

Scénario rejoué (indépendamment des tests déjà écrits par dev-backend, en valeurs identiques pour
contrôle croisé) :

| Mouvement | Quantité | Prix saisi | CUMP résultant du stock | `unit_price` figé sur la ligne |
|---|---|---|---|---|
| ENTRY #1 | 10 sacs | 200 000 FC | 200 000,0000 | 200 000,00 |
| ENTRY #2 | 10 sacs | 220 000 FC | (10×200000+10×220000)/20 = **210 000,0000** | 220 000,00 |
| EXIT #1 | 4 sacs | (ignoré, 999 999 FC transmis) | 210 000,0000 (inchangé par une sortie) | **210 000,00** (CUMP au moment de la sortie, valeur transmise écrasée) |

Résultat : **conforme**. La formule pondérée est correcte
(`(ancienne_qté × ancien_CUMP + qté_entrée × prix_entrée) / nouvelle_qté`), recalculée à **chaque**
ENTRY (pas seulement à la première), et chaque EXIT fige bien `unit_price` sur le CUMP **courant**
du stock au moment de la sortie — même principe que `InvoiceLine.save()` figeant `unit_price` depuis
`BreadPrice` (CLAUDE.md §4) : toute valeur transmise par l'appelant pour une sortie est ignorée/
écrasée, garanti par `ConsumableMovement.save()` quel que soit le point d'entrée (API, fournée, ou
tout futur appelant). Les 4 tests `backend/production/tests/test_bug123_average_unit_cost.py`
couvrent exactement ces cas et passent.

## 2. Cas « achat seul, aucune consommation dans le mois »

Rejoué : un `ConsumableMovement` ENTRY (10 sacs, 200 000 FC) créé seul, sans aucun EXIT associé.

- Avant BUG-123 (ancienne méthode, achats du mois) : cet achat aurait été compté intégralement dans
  `cost_flour` (2 000 000 FC), gonflant artificiellement le coût matière d'un mois où rien n'a
  pourtant été transformé en pain.
- Après BUG-123 (rejoué indépendamment) : `_income_statement_for_year(...)['cost_flour'] == Decimal('0.00')`.

**Conforme** : l'ancien défaut est bien corrigé. Le test
`test_entry_purchases_alone_do_not_affect_cogs` (`backend/finance/tests/test_income_statement.py`)
couvre ce cas et passe.

## 3. Non-régression des autres états financiers

- `_balance_sheet_for_year` : lit uniquement `Client.current_debt` et `CashbookEntry.running_balance`
  — **aucune** dépendance à `ConsumableMovement` ou aux champs `cost_*`. Vérifié par lecture directe
  du code (`backend/finance/views.py`) : confirmé, rien à recalculer, rien n'a changé par le
  correctif.
- `_cashflow_for_year` : lit uniquement `CashbookEntry` (entrées/sorties, solde courant) — même
  constat, aucune dépendance aux consommables.
- Comparatif N/N-1 (`comparative()`) : appelle les **mêmes** fonctions (`_income_statement_for_year`,
  `_cashflow_for_year`, `_balance_sheet_for_year`) pour `fy.year` et `fy.year - 1`, sans traitement
  différencié — donc aucun risque de fuite entre exercices propre à ce correctif. Le test dédié
  `IncomeStatementPreviousYearIsolationTests.test_comparative_action_uses_distinct_dataset_per_year`
  (déjà existant, pas modifié par BUG-123) a été relancé et passe toujours.

**Conforme** : aucune régression sur bilan, cash-flow ou isolation N-1.

## 4. Performance (non-régression BUG-064/066/070)

Vérifié indépendamment par `EXPLAIN QUERY PLAN` sur la requête réellement émise par
`_income_statement_for_year` pour les mouvements EXIT :

```
SEARCH production_consumablemovement USING INDEX prod_consmove_type_crea_idx
  (movement_type=? AND created_at>? AND created_at<?)
```

Une seule requête SQL agrégée (4 `Sum(..., filter=Q(...))` côte à côte), index déjà en place
(`prod_consmove_type_crea_idx`) bien utilisé par le moteur SQLite. **Conforme** : aucune requête N+1
introduite par le changement `movement_type='ENTRY'` → `movement_type='EXIT'`, aucune dégradation de
performance par rapport à l'architecture validée en BUG-066/070.

## 5. Défaut réel trouvé — BUG-126 (non corrigé, documenté pour dev-backend)

**La migration de backfill ne restampe pas les sorties historiques.**

`production/migrations/0018_bug123_backfill_average_unit_cost.py::backfill_average_unit_cost` rejoue
l'historique de chaque `ConsumableStock` pour recalculer le CUMP **final** du stock
(`ConsumableStock.average_unit_cost`), utile pour valoriser les **futures** sorties. Mais elle ne
réécrit jamais le champ `unit_price` des `ConsumableMovement` de type `EXIT` déjà en base avant le
déploiement de ce correctif (restés à `0.00`, conséquence de l'ancien défaut de
`production/views.py::_record_consumable_exits`, qui ne renseignait jamais `unit_price`).

Or `finance/views.py::_income_statement_for_year` valorise le coût matière en sommant
`quantity × unit_price` **ligne par ligne**, directement sur chaque `ConsumableMovement` EXIT — pas
via le CUMP courant du stock. Conséquence : **toute sortie de consommable enregistrée dans
l'application avant ce correctif reste valorisée à 0 FC dans le Compte de Résultat, pour toujours**,
y compris pour un exercice déjà clos qu'on recalculerait plus tard.

Reproduction (scénario de test indépendant, données fictives, exécuté puis retiré de la suite — ce
n'est pas un test de régression permanent, dev-backend devra en écrire un en corrigeant) :

1. `ENTRY` 10 sacs à 200 000 FC/sac → CUMP du stock = 200 000,0000.
2. `EXIT` 4 sacs créé normalement (`ConsumableMovement.save()` fige correctement `unit_price` à
   200 000,00 — comportement normal et correct du correctif pour une **nouvelle** sortie).
3. Pour simuler une ligne **historique** (créée avant le déploiement du correctif, donc par l'ancien
   `_record_consumable_exits` qui ne renseignait jamais `unit_price`), on force
   `ConsumableMovement.objects.filter(pk=exit.pk).update(unit_price=Decimal('0.00'))` — **en
   contournant** `save()`, exactement l'état réel d'une ligne déjà en base avant le 2026-11-02.
4. Exécution directe de la fonction `backfill_average_unit_cost(apps, schema_editor)` de la migration
   0018 (même code que celui déjà appliqué en migration).
5. Résultat observé : `ConsumableStock.average_unit_cost` recalculé correctement à `200000.0000` ;
   **`ConsumableMovement.unit_price` de la sortie historique reste à `0.00`**.

Confirmé une seconde fois en lisant le code de la migration ligne par ligne : la boucle
`for mv in movements:` ne fait jamais `mv.save()` ni `mv.unit_price = ...` — seul `stock` (l'objet
`ConsumableStock`) est modifié et sauvegardé en fin de boucle.

### Impact chiffré pour le client

Ce défaut touche potentiellement **tout mouvement `ConsumableMovement` de type `EXIT` déjà présent en
base avant le déploiement du correctif** (le 2026-11-02) : son coût matière continuera d'être compté
pour 0 FC dans le Compte de Résultat, à chaque recalcul futur, jusqu'à ce que le stock ait tourné
suffisamment pour que tous les mouvements EXIT historiques soient remplacés par de nouveaux
(plusieurs mois selon le rythme de rotation réel). C'est **l'inverse exact de l'objectif de BUG-123**
(rapprocher le Compte de Résultat de la consommation réelle) pour toute période rétroactive déjà
documentée dans l'application.

Ticket ouvert : **BUG-126** (`docs/qa/REGISTRE_BUGS.md`), gravité Majeur, assigné à personne pour
l'instant (coordinateur à désigner dev-backend). Pistes de correctif suggérées, non tranchées :
étendre la migration 0018 (ou une nouvelle migration de données) pour réécrire aussi `unit_price` de
chaque `ConsumableMovement` EXIT déjà en base, à la valeur du CUMP courant au moment de cette sortie
dans le rejeu chronologique (la variable `running_avg` du backfill le connaît déjà à cette étape, il
suffirait de l'écrire aussi sur la ligne EXIT plutôt que de la jeter).

## 6. Recoupement avec les Excel réels d'août 2026 (`data_kiese/`)

Fichiers consultés (ouverts en lecture avec `openpyxl`, dans une session temporaire, sans copie dans
le dépôt) :

- `DOC 1-2-1` à `DOC 1-2-8` (par boulangerie) : facturation + répartition CM + paie CM — **aucune
  donnée de consommables** (farine/levure/sel/huile), uniquement des ventes de pains et commissions.
- `DOC 01- RAPPORT BOULANGERIES AOUT 2026.xlsx` : même nature, par client/jour, en pains et FC —
  aucune donnée de consommables.
- `D1-5- STATISTIQUES AOUT NOVO 2026.xlsx` (onglets FARINE / Levure / HUILE / SEL) : **quantités
  physiques** de consommables entrées/sorties/stock par jour et par boulangerie (sacs de farine,
  paquets de levure, litres d'huile, grammes de sel) — exactement le type de mouvement que le CUMP
  de l'application cherche à valoriser, mais **sans aucun prix d'achat par mouvement**. Aucune colonne
  « prix » ni « valeur FC » par ligne de consommation journalière dans ces onglets.
- `DOC 06- CASH FLOW 2 eme SEMESTRE 2026.xlsx` (onglet « compte princ ») : contient une valeur
  ponctuelle « farine 50k k1/k2/... = 82 446 FC » à une date donnée (06/06/2026) — un **prix de
  référence de marché saisi à la main pour un inventaire de synthèse**, pas un coût unitaire moyen
  pondéré recalculé à chaque achat, et pas daté par mouvement.

**Conclusion du recoupement (agrégats uniquement, aucun nom de client)** : le jeu de données réel
d'août 2026 ne permet **pas** de recoupement chiffré ligne à ligne du CUMP calculé par l'application,
parce que le client ne pratique **aucune méthode de type CUMP** dans ses propres classeurs — il
suit les quantités physiques consommées (D1-5) séparément d'un prix de référence ponctuel saisi
manuellement (DOC 06), sans jamais les relier mouvement par mouvement. Impossible donc d'affirmer, à
partir des seules données disponibles, si la nouvelle méthode de l'application (CUMP sur consommation
réelle) rapproche ou éloigne le Compte de Résultat calculé des chiffres réels du client sur un mois
comparable — **ce n'est pas un défaut de l'application**, c'est une limite des données sources
disponibles pour ce recoupement précis. Sans lien avec BUG-126 (qui est un défaut de code, indépendant
des données réelles, démontré sur données fictives).

## 7. Suite de tests complète

`python manage.py test` (suite complète, `backend/.venv/Scripts/python.exe`) relancée intégralement
pendant cette vérification : **488 tests, 3 échecs** (`FAILED (failures=3)`, 1139,9 s). Les 3
suites ciblées de mon périmètre (`production`, `finance`, `commissions`) sont **intégralement
vertes** (aucun échec) — voir points 1 à 4 ci-dessus.

Les 3 échecs sont **tous dans `treasury`**, aucun rapport avec BUG-123/le Compte de Résultat/les
consommables, et aucun fichier que j'ai modifié n'est en cause (je n'ai modifié aucun code
applicatif — seuls `docs/qa/REGISTRE_BUGS.md` et ce rapport ont été écrits ; le seul script de test
temporaire que j'ai créé pour reproduire le point 5 a été supprimé avant la fin de cette mission) :

```
FAIL: test_blocked_delivery_still_leaves_client_bread_counter_incremented
  (treasury.tests.test_bug053_signal_side_effects.DeliveryBlockedSideEffectTests...)
  AssertionError: ValidationError not raised

FAIL: test_normal_sale_delivery_still_blocked_after_report_generated
  (treasury.tests.test_repayment_after_vacation_locked_probe.RepaymentNotBlockedByVacationLockTests...)
  AssertionError: Exception not raised

FAIL: test_no_new_invoice_affects_an_already_generated_report
  (treasury.tests.test_scope_gaps.FacturierSessionLockTests...)
  BUG-036 (voir registre) : CLAUDE.md §5.5 / mission testeur-tresorerie
  AssertionError: ValidationError not raised
```

Reconfirmé en relançant isolément `python manage.py test treasury` (104 tests, mêmes 3 échecs,
mêmes messages) : les trois tests attendaient qu'une tentative de livraison sur une vacation
(nœud+équipe+date) déjà rapportée (`FacturierReport` Niveau 1 généré, BUG-036) soit refusée par une
`ValidationError` — elle ne l'est plus. C'est **le mécanisme de verrou de vacation lui-même** (BUG-036,
déjà `VÉRIFIÉ` dans le registre) qui semble ne plus bloquer la livraison dans ces trois scénarios,
alors que le rapport dev-backend du 2026-11-02 (Q-001/Q-002/Q-005) indiquait la suite complète
« 485 tests, OK » juste avant cette vérification. N'étant pas de mon périmètre de mission (BUG-123,
Finance) et n'ayant touché à aucun code applicatif, **je n'ai pas investigué la cause ni corrigé** —
je le signale ici comme un **blocage pour la règle « `python manage.py test` complet doit passer
avant de rendre la main » (CLAUDE.md §7 règle 5)**, à traiter par le coordinateur/testeur-tresorerie/
dev-backend, indépendamment de la vérification de BUG-123 elle-même. Aucun ticket ouvert par moi sur
ce point (hors périmètre de ma mission du jour, à qualifier par le module concerné) — signalé au
coordinateur dans mon rapport de remise plutôt que tranché seul.

Vérification indépendante de la requête SQL de `_income_statement_for_year` par
`EXPLAIN QUERY PLAN` : confirmé l'usage de l'index `prod_consmove_type_crea_idx`, une seule requête
agrégée (voir point 4).

## Conclusion et statut des tickets

- **BUG-123** : laissé à `CORRIGÉ` (pas `VÉRIFIÉ`). La méthode CUMP elle-même (calcul, figement,
  formule, non-régression des autres états, performance) est **conforme en tout point** à ce qui a
  été demandé et documenté par dev-backend — mais le correctif est **incomplet** pour les données
  déjà en base avant son déploiement (voir BUG-126), ce qui empêche de le passer à `VÉRIFIÉ` tant que
  ce point n'est pas traité.
- **BUG-126** (nouveau, `OUVERT`) : défaut réel trouvé — la migration de backfill 0018 ne restampe pas
  `unit_price` sur les `ConsumableMovement` EXIT historiques. Documenté précisément ci-dessus pour
  dev-backend, non corrigé par l'auditeur (hors périmètre, CLAUDE.md §7 règle 2).
- Aucune ambiguïté ni contradiction entre documents de référence rencontrée pendant cette mission —
  rien à signaler au coordinateur sur ce point, ni de nouvelle entrée nécessaire dans
  `docs/qa/QUESTIONS_CLIENT.md` (le recoupement Excel du point 6 est une limite de données, pas une
  question à trancher par le client).
- **`python manage.py test` complet NE PASSE PAS actuellement** (488 tests, 3 échecs — point 7) :
  signalé au coordinateur, hors périmètre de cette mission (3 échecs dans `treasury`, mécanisme de
  verrou de vacation BUG-036, aucun rapport avec BUG-123/Finance/consommables, aucun fichier
  applicatif modifié par moi). Les suites de mon périmètre (`production`, `finance`, `commissions`)
  sont intégralement vertes.

## Fichiers/documents mis à jour par cette mission

- `docs/qa/REGISTRE_BUGS.md` : note de vérification ajoutée à la fiche BUG-123 (statut inchangé,
  `CORRIGÉ`) + nouvelle fiche détaillée **BUG-126** (`OUVERT`), + ligne de tableau de suivi
  correspondante.
- `docs/qa/rapports/auditeur-comptable-2026-11-02-verif-bug123.md` : ce rapport.
- Aucune donnée réelle de `data_kiese/` copiée dans le dépôt ; aucun code applicatif modifié.
