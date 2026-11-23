# Rapport auditeur-comptable (Dev A) - 2026-11-23-a

Périmètre : clôture journalière (formule du produit, transferts BUG-675, repli BUG-676, perte soldée), BP, commissions. Code applicatif en lecture seule.

## 1. Source des données : recoupement fictif, pas Excel réel
Aucun classeur d'août 2026 n'existe hors de `data_kiese/`. Seuls des exports générés par l'application sont présents (`docs/qa/captures/*.xlsx`), donc inutilisables comme référence. Conformément à la consigne, `data_kiese/` n'a pas été ouvert. Le recoupement a été fait sur des jeux fictifs calculés à la main, selon CLAUDE.md §5 et la formule BUG-319. **Ce rapport ne prouve donc pas la concordance avec les chiffres réels d'août** : il vérifie la cohérence interne et les règles. Le recoupement ligne à ligne reste à faire sur un poste où les classeurs sont accessibles (travail sur copie temporaire).

## 2. Tests ajoutés (DB isolée dans le scratchpad, sans `--parallel`)
- `backend/production/tests/test_audit_comptable_cloture_a.py` : 9 tests, OK avec 3 `expectedFailure` (BUG-1200, 1201, 1202).
- `backend/finance/tests/test_audit_comptable_a.py` : 3 tests, OK.

## 3. Tableau de rapprochement (jeu fictif K1, MINI 300 FC)
Veille : reste 20. Jour : 40 vendus, 10 soldés (225 FC), 3 invendus, 2 déclassés, 4 gratuits, 5 envoyés à K2, reste 8.

| Agrégat | Calcul à la main | Application | Verdict |
|---|---|---|---|
| Produit dérivé (qté) = 40+10+8-20+(3+2+4)+5 | 52 | 52 | OK |
| Produit dérivé (FC) | 15 600 | 15 600 | OK |
| Perte soldée = 10 x (300-225) | 750 | 750 | OK |
| Perte soldée après hausse du tarif à 400 | 750 | 750 | OK (prix plein figé) |
| Transferts : émettrice +1 500 / réceptrice -1 500 (BUG-675) | somme nulle | somme nulle | OK |
| Repli BUG-676, jour non clôturé | 100 % (50 pains) | 100 % base `vendu_jour` | OK |
| FACTURE MVM INTERNE (valeur au prix saisi) | 150 | 150 | conforme au code |
| Total du jour | 12 150 | 12 150 | conforme au code |
| Total du jour vs valeur produite | idem produit si identité stricte | écart 3 450 = invendus 900 + déclassés 600 + gratuits 1 200 + perte soldée 750 | ECART : BUG-1200 (À CLARIFIER) |
| Soldés déclarés en disposition (6 x 225) | inclus dans le total | absents | ECART : BUG-1201 |
| 2 équipes le même jour (veille A10/B3, jour A12/B8) | 5 pains (1 500 FC) | 7 pains (2 100 FC) | ECART : BUG-1202 |
| BP : 3 000 puis +1 200 -5 000 sur deux mois | -800, jamais remise à zéro | -800 | OK |
| CM : 5 000 x 25 % et 1 200 x 25 % par période | 1 250 / 300 | 1 250 / 300 | OK |
| Blocage : BP = plafond, paiement < commande | refus 403 ; paiement = commande accepté | idem, BP inchangé | OK |

## 4. Écarts trouvés
- **BUG-1200 (Majeur, À CLARIFIER, Q-043)** : le produit compte invendus, déclassés et gratuits en quantité au prix catalogue, mais le total du jour les valorise au prix de vente saisi (0 pour une perte sèche), et les gratuits n'y figurent pas. Sans le classeur, impossible de dire si l'Excel fait de même.
- **BUG-1201 (Majeur)** : disposition `SOLD_DISCOUNT` comptée dans le produit, absente de FACTURE MVM INTERNE.
- **BUG-1202 (Majeur)** : hors rotation, `facture_mvm_interne` additionne les restes par équipe, alors que le produit dérivé et les champs journaliers prennent le dernier instantané. Doublon possible quand les deux équipes clôturent le même jour.

## 5. Constats sans ticket
- Valorisation par repli BUG-676 : correcte sur le jeu fictif, `repartition_base` renseignée.
- États N / N-1 de `finance/` : non rejoués ici, déjà couverts par les cycles du 22/11 (rapport `auditeur-comptable-2026-11-22-c.md`). Les dérives BUG-513/518 (tarif courant relu) restent ouvertes et dépendent de Q-028.
- Branche morte : `exclude(special_code__in=node_codes)` (views.py l.2673). `SpecialCode` ne propose pas de code boulangerie (le transfert passe par `BreadTransfer`). Sans effet, à nettoyer.
- Épargne (commande = 0, dépôt) : non rejoué, API non documentée dans les tests existants.

## 6. À valider par le client
1. Q-043 : valorisation des invendus, déclassés et gratuits dans le total du jour, et place des gratuits.
2. Statut des soldés déclarés par disposition par rapport aux factures soldées (BUG-1201).
3. Q-028 (existante) : tarif figé ou courant pour les jours passés.
4. Rejeu sur les classeurs réels d'août (clôture K6, DOC 01, livres D1-3/D1-4, DOC 06), hors de ce poste de test.

Exécution : `manage.py test production.tests.test_audit_comptable_cloture_a` puis `finance.tests.test_audit_comptable_a`, un processus à la fois. Suites complètes non relancées.
