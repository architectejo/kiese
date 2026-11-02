# Écart entre le module Finance actuel et le Cadre Comptable signé (21/09/2026)

Rédigé par : `auditeur-comptable`, le 2026-10-22/23.
Document de décision pour le client (M. NDUNGA NSAYI PIERRE) — **aucune ligne de ce document
n'implique une obligation de développement** ; il sert à chiffrer et faire trancher ce qui reste
réellement ouvert, conformément à `cadre_comptable.md` (analyse déjà faite cette session) et à la
question `Q-003` de `docs/qa/QUESTIONS_CLIENT.md`.

Référence de priorité (CLAUDE.md §1) : `remarque.md` > `adaptes.md` > `cadre_comptable.md` >
`cahierDesCharges.md`. Ce document ne fait que reformuler/compléter `cadre_comptable.md` du point
de vue « code actuel vs cible », sans le contredire.

---

## 1. Ce qui est déjà conforme (vérifié ce jour, code réel relu + testé)

- `backend/finance/views.py` est **bien connecté aux données réelles** : compte de résultat,
  bilan (partiel, voir §2), cash-flow et comparatif N/N-1 interrogent `sales.Invoice`,
  `commissions.ClientCommission`, `treasury.LocalExpense`/`CashbookEntry`,
  `production.ConsumableMovement` — ce n'est **pas** un mock ni une donnée statique.
  `frontend/src/pages/dashboard/Finance.tsx` appelle réellement `financeApi.*` (pas de données en
  dur). **`remarque.md` l.87 (« États Financiers N/N-1 pas connecté au cerveau backend ») est donc
  marqué `[c]`** : ce point, probablement vrai au moment où il a été noté, est corrigé depuis.
- `cahierDesCharges.md` §2.3.1-2.3.2 (lignes ~208-214, CM brute = commande × taux, dette, sociale,
  imprimés, autre) : la formule `CM Brute = order_value × commission_rate` est bien celle
  implémentée (`commissions/models.py::ClientCommission.compute()`), vérifiée par les tests de
  `testeur-clients-commissions` (BUG-012, 2026-10-22) et par les tests de cette session
  (`backend/finance/tests/test_income_statement.py`).
- 15 nouvelles `ExpenseCategory` alignées sur les comptes de charges du client (WOOD_*, LOAN_*,
  CAPEX_*, FUEL_MISSION, FARM_SUBSIDY, THEFT, RENT, FEES, TAXES) sont déjà en place (migration
  `core/0012_...`, cf. `cadre_comptable.md` — pas un nouveau constat de cette session, confirmé
  présent en relisant `core/models.py::ExpenseCategory` et la liste des migrations).

## 2. Ce qui reste un écart réel avec le Cadre Comptable (chiffré ci-dessous)

### [A] Pas de « Balance » (débit = crédit) — aucune notion de compte/journal comptable
Le module `finance` ne porte **aucun modèle de compte**, de journal ou d'écriture en partie
double. Il n'existe donc ni la notion de « Balance » (au sens comptable : somme des débits =
somme des crédits par compte), ni de plan de comptes actif (les `account_code` du plan du
20/09/2026 ne sont pas encore reliés systématiquement à des mouvements). Ce que l'application
appelle aujourd'hui « bilan » (`_balance_sheet_for_year`) est une liste de 2 agrégats (créances
clients actifs + solde du livre de caisse), pas un bilan comptable.
- **Conséquence vérifiée par test** (`finance/tests/test_cashflow_and_balance.py::
  test_balance_sheet_has_no_liabilities_or_equity_side`) : il n'y a ni Passif ni Capitaux Propres
  dans la réponse API — **l'égalité Actif = Passif, demandée par ma mission d'audit, n'est donc
  pas vérifiable avec le code actuel : la structure ne le permet pas encore.** Ce n'est pas un
  bug (aucune régression : rien n'a jamais calculé ce côté), c'est une fonctionnalité absente.
- **Chiffrage d'effort (ordre de grandeur, à affiner par `dev-backend` avant engagement)** :
  introduire un modèle `Account` (plan de comptes), un modèle `JournalEntry` générique à 2 lignes
  (débit/crédit) alimenté automatiquement par les événements existants (facture livrée, dépense
  locale, paiement commission, mouvement consommable), puis reconstruire `_balance_sheet_for_year`
  à partir de ces écritures plutôt que des agrégats actuels. **Ampleur : refonte de module
  (plusieurs semaines), pas une correction** — c'est exactement ce que `cadre_comptable.md` avait
  déjà qualifié de « pas une correction de bug » en introduction.

### [B] TFR à cascade de paliers (Marge Brute → Marge Nette → EBE → Résultat Net)
Toujours non fait, confirmé par relecture de `_income_statement_for_year` (calcul plat inchangé
depuis `cadre_comptable.md` §[2.1]). Le client a explicitement répondu (25/09/2026, citée dans
`cadre_comptable.md`) qu'il pense surtout en libellés de trésorerie, pas en cascade de marges —
recommandation déjà actée : **ne pas construire la cascade sans demande explicite et un exemple
concret de ce qu'il veut voir à l'écran.** Rien de nouveau à chiffrer ici tant que cette demande
n'est pas formulée.

### [C] Comptes de produits Classe 7 non trackés individuellement (vente farine, sacs vides, etc.)
Statu quo confirmé (`cadre_comptable.md` §[1.2]/§[MODULE 1.2]) : seul le revenu « pains »
(`InvoiceLine`) est structuré. Le client n'a pas répondu formellement sur ce point (pattern de ses
autres réponses suggère qu'il l'écarterait aussi) — reste `Q-003`/à reconfirmer, pas une action à
engager seul.

### [D] Méthode de calcul du coût matière (COGS) : achats du mois, pas consommation du mois
Nouveau constat de cette session (pas dans `cadre_comptable.md`) : `_income_statement_for_year`
calcule `cost_flour`/`cost_yeast`/`cost_salt`/`cost_oil` à partir des **mouvements
`ConsumableMovement` de type `ENTRY` (achats/approvisionnements)** de l'année, et non des
mouvements `EXIT` (consommation réelle en production). En comptabilité d'exploitation stricte, le
coût matière du mois devrait suivre ce qui a été **consommé** pendant la fabrication des pains
vendus ce mois-ci, pas ce qui a été **acheté** (un sac acheté en décembre pour une production de
janvier gonflerait le coût de décembre et sous-évaluerait celui de janvier). Avec un stock de
consommables qui tourne rapidement (achats fréquents, pas de gros stockage pluri-mensuel d'après
les retours terrain), l'écart mensuel réel est probablement faible en pratique, mais il existe
structurellement. **Ne pas transformer en ticket `BUG-NNN` d'office** : c'est un choix de méthode
comptable (achats vs consommation), pas une erreur de calcul au sens strict de la formule
actuelle — à soumettre au client comme question (voir `docs/qa/QUESTIONS_CLIENT.md`, nouvelle
entrée Q-005 ajoutée par ce rapport) avant de décider s'il faut basculer sur les mouvements `EXIT`.

## 3. Ce qui n'est délibérément pas repris ici
Ferme Agricole, Pâtisserie, Carte Mapa/Cartes Revendeurs : hors périmètre confirmé par le client
(`cadre_comptable.md` MODULE 3/4/7). Rien à chiffrer, rien à faire.

## 4. Recommandation
Ne pas engager [A] (refonte Balance/Bilan comptable complet) sans un avenant chiffré explicite
(Q-003 déjà ouverte) : c'est un changement structurel majeur, pas une correction. [D] peut être
tranché par une réponse courte du client (Q-005) sans refonte. [B] et [C] restent correctement
mis en pause tels que `cadre_comptable.md` l'avait déjà recommandé.
