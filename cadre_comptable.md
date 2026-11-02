# cadre_comptable.md — Analyse du "Cadre de Comptes & TFR" transmis par le client

Source : `./data_kiese/Nouveau_/SYNTHESE_CADRE_DEPENSE_AU_DEVELOPEUR_LOGICIEL.docx`
Daté et signé le 21/09/2026 par NDUNGA NSAYI PIERRE (Administrateur Directeur Général).

## Ce que contient le document

Un **Plan Comptable définitif** (Classe 6 = charges 60→69, Classe 7 = produits 70→71) et une
**structure de TFR** (Tableau de Formation du Résultat — cascade Produits → Marge Brute → Marge
Nette → EBE → Résultat Net), avec un TFR **séparé** pour une activité "Ferme Agricole" et un
schéma d'arborescence Recettes/Dépenses/Investissements. Une note finale demande d'ajouter les
ventes de pâtisserie et une "Carte Mapa".

## Verdict : oui, c'est directement utile

C'est le document de référence comptable définitif du client — il doit gouverner la structure du
module "États Financiers" (`finance` app) et les catégories de "Dépenses Locales" (`treasury`
app) que nous avons rendues configurables cette session. Comparé au code actuel
(`backend/finance/views.py::_income_statement_for_year`), l'écart est important :

- Le calcul actuel est **plat** (revenu par catégorie de pain − 4 lignes de coût matière − une
  ligne dépenses − commissions = résultat net). Le document demande une **cascade** à 4 paliers
  (Marge Brute → Marge Nette Commercialisation → EBE → Résultat Net) avec segmentation
  Boulangerie / Pâtisserie / Consolidé.
- Plusieurs domaines métier n'existent **pas du tout** dans l'application : Ferme Agricole,
  Pâtisserie, chaîne Bois en régie (comme sous-registre détaillé), emprunts bancaires/COOPEC,
  vente de cartes revendeurs, investissements (CAPEX), missions liées au carburant, retraits
  personnels.

**Ampleur :** ce n'est pas une correction de bug — c'est une refonte du module financier plus
plusieurs nouvelles lignes d'activité. À prioriser/budgeter avec le client avant de commencer,
pas à implémenter d'un coup.

---

## MODULE 1 — Plan Comptable comme référentiel (fondation)

### [1.1] Catégories de dépenses actuelles vs plan comptable

`ExpenseCategory` (Configuration, ajouté cette session) a aujourd'hui 4 codes libres :
WOOD / MAINTENANCE / TRANSPORT / MISC. Le document définit ~40 comptes de charges granulaires
(6011 à 6914) et ~10 comptes de produits (7011 à 7112).

**Tâche :** Ajouter un champ `account_code` (ex: "6011") optionnel sur `ExpenseCategory`, et
proposer un seed aligné sur le plan comptable du client (une catégorie ETS KIESE par compte de
charge pertinent), sans casser les 4 catégories existantes (migration de données, pas de
suppression).

### [1.2] Comptes de produits (Classe 7) non trackés individuellement

Le document distingue 7011 (pains), 7012 (pâtisserie), 7013 (revente farine), 7014 (sacs vides),
7015 (cartes revendeurs), 7081 (transport tiers), 7082 (retenues épargne). Actuellement seul le
revenu "pains" (via `InvoiceLine`) est structuré ; le reste n'a pas de modèle dédié.

**Tâche :** Décider, compte par compte, s'il faut un nouveau modèle (ex: vente de farine, vente
de sacs vides) ou si ça reste dans "Dépenses/Recettes Locales" génériques. Clarifier avec le
client le volume réel de ces opérations avant de sur-designer.

---

## MODULE 2 — Restructuration du TFR (`finance` app)

### [2.1] Cascade de marges au lieu du calcul plat actuel

`_income_statement_for_year` fait un seul calcul flat. Le document demande :
`Produits Bruts → (− Matières & Bois) → Marge Brute → (− NV/Pertes/Commissions) → Marge Nette
→ (− Personnel/Maintenance/Taxes) → EBE → (− Créances irrécouvrables/Ferme/Crédits) → Résultat
Net`.

**Tâche :** Réécrire `_income_statement_for_year` (et le serializer/UI "États Financiers N/N-1")
pour produire cette cascade à 4 paliers, avec les libellés exacts du document (pour que le
gérant/comptable retrouve le même vocabulaire que le document papier).

### [2.2] Segmentation Boulangerie / Pâtisserie / Consolidé — sans objet

Le TFR du document est présenté en 3 colonnes analytiques (Boulangerie / Pâtisserie /
Consolidé), mais il n'y a pas de Pâtisserie chez ETS KIESE (confirmé, voir [MODULE 4]).

**Tâche :** Construire le TFR à une seule colonne (Boulangerie = Consolidé), sans segmentation.

---

## MODULE 3 — Ferme Agricole — HORS PÉRIMÈTRE

L'application ETS KIESE gère uniquement les boulangeries. La Ferme Agricole (TFR séparé,
manioc/ananas/bois, comptes 6621/6911) n'est **pas** dans le périmètre de ce logiciel — décision
confirmée. Le seul point qui reste pertinent pour nous est le compte 6621 (subvention/avance
*envoyée* vers la Ferme) : il doit apparaître comme une simple sortie de caisse côté boulangerie
(catégorie de dépense), sans qu'on ait besoin de suivre ce qui se passe ensuite côté ferme.

**Tâche :** Ajouter "Subvention/Avance Ferme Agricole" comme catégorie de dépense possible
(§[1.1]) — c'est tout ce qui est nécessaire de notre côté.

---

## MODULE 4 — Pâtisserie — HORS PÉRIMÈTRE

Confirmé par le client : il n'y a pas de Pâtisserie chez ETS KIESE. Tout ce qui, dans le document,
s'y rapporte (7012, 6015, 6016, colonne "Rayon Pâtisserie" du TFR) est ignoré. Rien à développer
pour ce module.

---

## Réponses du client (25/09/2026) — RÉSOUT LES MODULES 5, 6, 8, 9, 10

> **Q1 (priorité/budget) :** "Patience, la question n'est pas comprise. Sinon ce sont des
> libellés de flux de la trésorerie qui sont enregistrés dans le livre de caisse."
>
> **Q2 (Carte Mapa) :** "Ne pas tenir compte de ça vu qu'on va commencer à imprimer des
> factures."
>
> **Q3 (Retraits Personnels) :** "Déjà fait."
>
> **Q4 (qui saisit CAPEX/Emprunts) :** "Même si je ne comprends pas du tout votre souci. C'est
> aussi des libellés de sorties de fonds, lesquels diminuent le résultat. Enregistrement au
> livre de caisse. Et fusion automatique par le logiciel."

**Interprétation :** le client ne veut PAS de nouveaux modèles/écrans pour la chaîne bois
détaillée, les remboursements de crédits, le CAPEX ou le carburant de mission — ce sont de
simples **libellés de catégorie** pour des sorties de caisse déjà enregistrées via "Dépenses
Locales" (§5.1.2), avec totalisation automatique — ce que `ExpenseCategory`/`LocalExpense` font
déjà. Aucun nouveau rôle utilisateur requis (Q4). "Carte Mapa" et donc les "Cartes Revendeurs"
liées sont abandonnées (focus sur l'impression de factures à la place, déjà fait — voir
`ThermalReceipt`).

**Fait le 25/09/2026 :** migration `core/0012_expensecategory_plan_comptable_seed.py` — 15
nouvelles catégories ajoutées à `ExpenseCategory` (déjà utilisables dans "Dépenses Locales" sans
rien coder de plus) :

| Code | Libellé |
|---|---|
| WOOD_LABOR | Bois — Main-d'œuvre Coupe |
| WOOD_SAW_FUEL | Bois — Carburant & Maintenance Scies/Tronçonneuses |
| WOOD_TRUCK | Bois — Carburant & Maintenance Camions |
| WOOD_CONVOY | Bois — Primes Convoyeurs |
| LOAN_BANK | Remboursement Crédit Bancaire |
| LOAN_COOPEC | Remboursement Crédit COOPEC |
| LOAN_THIRD | Remboursement Crédit Tiers |
| CAPEX_BUILD | Investissement — Construction |
| CAPEX_EQUIP | Investissement — Équipement |
| FUEL_MISSION | Carburant — Mission Véhicule |
| FARM_SUBSIDY | Subvention / Avance Ferme Agricole |
| THEFT | Vol & Détournement |
| RENT | Loyers |
| FEES | Honoraires (Avocat, Conseil, Informatique) |
| TAXES | Taxes & Redevances (DGI, INSS, INPP...) |

D'autres catégories peuvent être ajoutées à tout moment par le comptable/Direction lui-même via
Configuration → "Catégories de Dépenses Locales" (aucune intervention développeur nécessaire).

### MODULE 5, 6, 8, 9, 10 — clos

Tous résolus par le seed ci-dessus. Pas de nouveau modèle (`CompanyLoan`, `CapitalExpenditure`,
`Mission`) — le client a explicitement dit que ces libellés suffisent.

### MODULE 7 — Cartes Revendeurs & Carte Mapa — abandonné

Le client dit de ne pas en tenir compte (focus sur l'impression de factures à la place).

---

## Ce qui reste réellement ouvert

**[MODULE 2] — Cascade du TFR.** Seul point non tranché. La réponse du client à la Q1 suggère
qu'il pense surtout en termes de *libellés dans le livre de caisse*, pas de refonte de l'écran
"États Financiers". Recommandation : ne pas toucher `_income_statement_for_year` pour l'instant
— les nouvelles catégories remontent déjà dans `operational_expenses` (calcul actuel), ce qui
couvre l'essentiel de la demande. Revoir la cascade à 4 paliers seulement si le client la demande
explicitement plus tard, avec un exemple concret de ce qu'il veut voir à l'écran.

**[MODULE 1.2] — Comptes de produits (Classe 7) non trackés** (vente farine, sacs vides...) —
non abordé par les réponses du client ; probablement à ignorer aussi vu le pattern des réponses
(tout ce qui n'est pas déjà fait est explicitement écarté), mais pas confirmé formellement.
