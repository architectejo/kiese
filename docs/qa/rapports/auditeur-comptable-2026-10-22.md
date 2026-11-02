# Rapport — auditeur-comptable — 2026-10-22/23

Mission : partie Finance de BUG-016 (`remarque.md` l.87, cahierDesCharges.md §2.3.1-2.3.2) +
recoupement avec les classeurs Excel réels d'août 2026 (`data_kiese/daja_analysé/`).

Toutes les données personnelles/réelles (clients, montants individuels) ont été lues en local
pour vérification, **jamais copiées** dans ce dépôt ni dans les tests (CLAUDE.md §4). Les
tableaux ci-dessous ne contiennent que des agrégats (totaux mensuels par boulangerie).

## 1. BUG-016 — partie Finance : résultat

**États Financiers N/N-1 (`remarque.md` l.87) : vérifié conforme.** Le module est réellement
connecté au backend :
- `backend/finance/views.py::_income_statement_for_year/_cashflow_for_year/_balance_sheet_for_year`
  interrogent `sales.Invoice`/`InvoiceLine`, `commissions.ClientCommission`,
  `treasury.LocalExpense`/`CashbookEntry`, `production.ConsumableMovement` — aucune valeur en dur.
- `frontend/src/pages/dashboard/Finance.tsx` appelle réellement `financeApi.incomeStatement()`,
  `balanceSheet()`, `cashflow()`, `doc1Report()`, et `commissionsApi.periods.history()` ; aucune
  donnée de démonstration codée en dur dans le composant.
- Marqué `[c]` dans `remarque.md` avec référence à ce rapport. Probablement déjà corrigé lors
  d'une session de développement précédente ; ce n'est donc pas une correction de cette mission,
  seulement une vérification qui clôt le point.

**Formule CM Brute (cahierDesCharges.md §2.3.1-2.3.2) : conforme.** `order_value × commission_rate`
implémentée dans `ClientCommission.compute()`, déjà testée par `testeur-clients-commissions`
(BUG-012) ; reconfirmé par mes propres tests de recoupement (`backend/finance/tests/
test_income_statement.py`).

**BUG-016 est donc intégralement clos** (table de suivi `docs/qa/REGISTRE_BUGS.md`) : la partie
permissions/dashboard/nodes avait déjà été traitée par `testeur-permissions`, la partie Finance
l'est désormais.

## 2. Tests de cohérence comptable ajoutés

`backend/finance/tests/` (nouveau, 2 fichiers, 15 tests, données 100 % fictives) :

| Fichier | Couverture |
|---|---|
| `test_income_statement.py` | CA = somme des lignes LIVRÉES uniquement (pas PENDING/CANCELLED) ; répartition par catégorie de pain (MINI→300, MOYEN→400, GRAND→500, PREMIUM→1000) ; coût matière = quantité × prix d'achat des mouvements d'entrée ; dépenses locales déduites ; seules les commissions `is_paid=True` comptent comme charge ; `Résultat net = Marge brute − Commissions payées − Dépenses` ; isolation N/N-1 (une facture de l'an dernier ne doit pas apparaître dans l'exercice courant). |
| `test_cashflow_and_balance.py` | `Flux net = Entrées − Sorties` ; solde de clôture = `running_balance` de la dernière écriture de l'exercice ; année sans écriture → zéro, pas de crash ; créances = somme `current_debt` des clients **actifs** uniquement ; position caisse = dernière écriture du livre de caisse ; total actif = créances + caisse ; **caractérisation explicite** de l'absence de Passif/Capitaux Propres dans la réponse API (§3). |

`backend/commissions/tests/test_audit_comptable_2026_10_22.py` (nouveau, 1 test) : reproduit la
formule réelle NET A PAYER (confirmée sur 3 classeurs réels) avec des montants fictifs et prouve
l'écart avec `ClientCommission.compute()` (voir BUG-058, §4).

`python manage.py test finance commissions` : 15/15 verts. `python manage.py test` (suite
complète, 225 tests) : 219/225 verts ; les 6 échecs restants sont des tests de concurrence/charge
préexistants (verrouillage SQLite sous forte concurrence dans `clients/tests/
test_verification_2026_10_22.py`, `sales/tests/test_charge_morning_peak.py`,
`treasury/tests/test_scope_gaps.py`), non liés à mes modifications, non présents dans les fichiers
que j'ai touchés, et déjà connus comme dépendants du matériel/de la charge de la machine (cf. notes
`testeur-charge`) — je ne les ai pas corrigés (hors périmètre, et je ne corrige pas le code
applicatif).

## 3. Écart avec le Cadre Comptable signé (document séparé pour le client)

Document dédié : `docs/qa/ECART_CADRE_COMPTABLE.md`. Résumé :
- **[A] Pas de « Balance » comptable (débit = crédit), pas de Passif/Capitaux Propres dans le
  bilan** : fonctionnalité non développée (pas un bug — rien n'a jamais calculé ce côté).
  L'égalité Actif = Passif demandée par ma mission n'est donc pas vérifiable avec le code actuel.
  Chiffrage : refonte de module (plan de comptes + journal d'écritures), à budgeter (cf. `Q-003`
  déjà ouverte).
- **[B] Cascade TFR à 4 paliers** : statu quo volontaire, déjà recommandé par `cadre_comptable.md`
  (le client raisonne en libellés de trésorerie, pas en cascade de marges) — rien à engager sans
  demande explicite.
- **[C] Comptes de produits Classe 7 non trackés individuellement** : statu quo, en attente de
  confirmation client.
- **[D] Nouveau constat de cette session** : le coût matière du compte de résultat est calculé sur
  les **achats** (`ConsumableMovement` de type `ENTRY`) du mois, pas sur la **consommation
  réelle** en production (`EXIT`). Choix de méthode, pas une erreur de formule — posé comme
  question au client (`Q-005`, `docs/qa/QUESTIONS_CLIENT.md`).

## 4. BUG-058 — CARTE (1 %) et REMISE (0,1 %) déduites par l'application, absentes de la formule réelle NET A PAYER

Recoupement direct des **formules** Excel (pas seulement des valeurs) de 3 classeurs d'août 2026 :

| Boulangerie | Classeur / Feuille | Formule NET A PAYER lue dans le classeur |
|---|---|---|
| K1 (TABORA) | `K1 AOUT 26 REPARTISION...xlsx` / `DOC 2 REPARTITION` | `=IN-IL-IO-IP-IR` → `CM − BP − SOCIAL − CARTE − RETENUE` |
| K2 (COQ) | `K2 AOUT 26 - REPARTITION...xlsx` / `clients cite` | `=II-IG-IJ-IK-IM` → `CM − BP − SOCIAL − CARTE − RETENUE` |
| K3 (ATHENEE) | `K3 AOUT 26 REPARTITION...xlsx` / `clients cite` | `=IU-IS-IV-IW-IY` → `CM − BP − SOCIAL − CARTE − RETENUE` |

Sur les 3 classeurs, la colonne REMISE est bien calculée (`=COMMANDE×0,25 %`, strictement égale à
`CM×1 %` au taux de 25 % en vigueur) **mais n'intervient jamais dans la formule NET A PAYER** —
elle est affichée à titre informatif, jamais soustraite. La colonne CARTE est systématiquement
vide (0) sur les 3 classeurs pour août 2026.

`ClientCommission.compute()` (application), lui, déduit systématiquement les deux : `CM×1 %`
(CARTE) ET `CM×0,1 %` (REMISE), soit 1,1 % du CM en moins par rapport à la pratique de gestion
réelle, sur chaque ligne de commission, chaque mois.

**Agrégats mensuels (août 2026, aucun nom de client, aucun montant individuel) :**

| Boulangerie | CM brute cumulée (FC) | Écart cumulé si l'app avait payé (FC, ≈1,1 % du CM) |
|---|---|---|
| K1 (TABORA) | 6 557 500 | 72 133 |
| K2 (COQ) | 9 980 000 | 109 780 |
| K3 (ATHENEE) | 6 205 500 | 68 261 |

Ticket ouvert : `BUG-058` (Majeur, `docs/qa/REGISTRE_BUGS.md`). **Je ne tranche pas** si c'est
l'application ou `adaptes.md`/l'Excel historique qui a raison sur le principe de la déduction
REMISE — signalé au coordinateur comme point à arbitrer, avec une proposition (rendre CARTE/REMISE
optionnelles, saisies explicitement, plutôt que calculées automatiquement). Aucune autre anomalie
chiffrée n'a été trouvée dans les autres colonnes recoupées (CM = commande × taux, NET/ORDI = CM
− BP, toutes conformes à l'identique sur les 3 classeurs et dans l'application).

## 5. Fichiers créés ou modifiés par cette mission

- `backend/finance/tests/__init__.py`, `test_income_statement.py`, `test_cashflow_and_balance.py`
  (nouveau — remplace `backend/finance/tests.py`, vide, supprimé).
- `backend/commissions/tests/test_audit_comptable_2026_10_22.py` (nouveau).
- `docs/qa/ECART_CADRE_COMPTABLE.md` (nouveau).
- `docs/qa/QUESTIONS_CLIENT.md` (ajout Q-005).
- `remarque.md` (l.87 marquée `[c]`).
- `docs/qa/REGISTRE_BUGS.md` (clôture BUG-016 partie Finance, ouverture BUG-058).
- **Aucun fichier de code applicatif modifié** (conforme à la mission).
