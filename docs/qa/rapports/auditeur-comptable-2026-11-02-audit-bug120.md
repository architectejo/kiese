# Audit comptable — BUG-120, Chantier C « Clôture & Caisse »

Auditeur : auditeur-comptable — 2026-11-02
Mission : trancher (ou documenter comme ambigus) les 3 points laissés ouverts par dev-backend sur
`BUG-120` (`GET /api/production/daily-closure/`). Recoupement comptable uniquement — **aucun code
applicatif modifié**. Le statut du ticket reste `CORRIGÉ` (ce n'est pas à cet agent de le faire passer
à `VÉRIFIÉ`/`À CLARIFIER`).

Méthode : lecture des formules réelles (`openpyxl`, `load_workbook(..., data_only=False)`) et des
valeurs figées (`data_only=True`) de `data_kiese/EXTRAIT RAPPORT DE CLOTUREOCTOBRE 2026.xlsx` (feuille
`K6`, deux blocs journaliers : K5/MPIANGU du 06/10/2026 et K6/ZADIM du 03/10/2026) et de
`data_kiese/daja_analysé/DOC 1 - RAPPORT  CLOTURE PAR GERANT  AOUT  2026.xlsx` (feuille `TABORA`,
01-02/08/2026). Ces fichiers contiennent des données réelles (noms de clients) : seuls des agrégats et
des cellules isolées sans valeur client identifiante sont cités ci-dessous, à l'exception de deux noms
de clients strictement nécessaires pour démontrer la dérive de référence du point 3 (BBC, MIFIE) —
aucune donnée personnelle sensible (téléphone, dette, photo) n'est reprise.

Ticket mis à jour : `docs/qa/REGISTRE_BUGS.md` → section « Audit comptable — auditeur-comptable,
2026-11-02 » sous `BUG-120`. Questions ouvertes : `docs/qa/QUESTIONS_CLIENT.md` → Q-006, Q-007.

---

## Point 1 — `facture_mvm_interne` toujours vide : **À CORRIGER**

### Preuve chiffrée

`K6!L21` (ligne « FACTURE MVM INTERNE », bloc du 06/10/2026, boulangerie K5) :

```
L21 = SUM(L8:L20)
```

c'est-à-dire la somme de toutes les lignes de mouvement situées entre la facturation client et le
total du jour : RESTE DU JOUR, RESTE DU HIER/S, APPRO EFFECTUE, APPRO RECU/S, NON SERVI/S,
REGULARISATION, VENTE CASH, VENTE SOLDE, NON VENDU(NV), DECLASSES, EXCEDENT PAINS, MANQUANT PAINS.

Valeurs figées (`data_only=True`), recalculées à la main :

| Ligne | L (FC) |
|---|---|
| RESTE DU JOUR (L8) | 193 500 |
| RESTE DU HIER/S (L9) | -156 500 |
| APPRO EFFECTUE (L10) | 0 |
| APPRO RECU/S (L11) | 0 |
| NON SERVI/S (L12) | 0 |
| REGULARISATION (L13) | 40 000 |
| VENTE CASH (L14) | 86 500 |
| VENTE SOLDE (L15) | 79 500 |
| NON VENDU(NV) (L16) | 0 |
| DECLASSES (L17) | 0 |
| EXCEDENT PAINS (L18) | -2 500 |
| MANQUANT PAINS (L19) | 0 |
| **Somme** | **240 500** |
| `L21` (valeur figée dans le classeur) | **240 500** ✓ |

Confirmation indépendante sur `DOC 1 - RAPPORT CLOTURE PAR GERANT AOUT 2026.xlsx!TABORA` (01/08/2026) :
les lignes de mouvement inter-boulangeries y sont **intercalées dans la même liste que les clients**,
avec le même code nœud en colonne B :

```
B160='K1'  C160='APRO EFFECT MPETE'
B161='K1'  C161='Appro effect k3'
B162='K1'  C162='Appro reçu K2'      (H162=-120, J162=-1 : quantités négatives)
B163='K1'  C163='RECU DE K4'
```

sommées dans le **même total** que les factures clients (`L178 = SUM(L5:L177)`), sans jamais être une
facture séparée avec un `special_code` = code boulangerie.

### Conclusion

« FACTURE MVM INTERNE » **n'est pas** une facture dont `special_code` vaudrait le code d'une autre
boulangerie (l'interprétation de dev-backend colle au texte littéral de CLAUDE.md §5.1 mais est
invalidée par la pièce réelle). C'est un **sous-total agrégé** de « tout ce qui n'est pas une vente
nommée à un client » : restes (j/j-1), appros/transferts, non-servi, régularisations, ventes spéciales
(cash/solde) et dispositions (non vendu/déclassés/excédent/manquant).

**Gap réel = option (b) de la mission** : le endpoint ne double-compte rien aujourd'hui (le bucket
`facture_mvm_interne`, vide par construction, n'entre déjà dans aucun total), mais **il confond deux
concepts distincts** — le vrai « FACTURE MVM INTERNE » (un sous-total de mouvements déjà calculés
ailleurs dans le rapport) et une fonctionnalité hypothétique « facture avec code boulangerie » qui
n'existe pas dans `sales/` et qui, à la lumière de la pièce réelle, ne correspond probablement pas à ce
que le client appelle ainsi sur CETTE rubrique précise (CLAUDE.md §5.1 peut très bien décrire un vrai
besoin, mais ailleurs — p. ex. sur le flux `BreadTransfer` lui-même, ou pour un autre document).

**Conséquence sur `TOTAL DU JOUR`** : la pièce réelle calcule
`TOTAL DU JOUR = S/TOTAL AB CARTE (clients) + FACTURE MVM INTERNE (mouvements)` —
vérifié `K6!L132 = L128 + L21 = 599 500 + 240 500 = 840 000`. Le code actuel calcule
`total_du_jour_fc = total_facture_fc + total_soldee_fc + total_regularisation_fc + total_mvm_fc`, qui
**omet** les restes, les appros, le non-servi et les dispositions. Même en renommant/ignorant le bucket
`facture_mvm_interne`, le calcul actuel de `TOTAL DU JOUR` ne reproduit donc pas celui de la pièce
réelle — c'est un écart de formule, pas seulement un écart de nommage.

**Action recommandée** : ne pas étendre `special_code` pour l'instant (évolution `sales/` hors
périmètre et probablement pas la bonne réponse). Attendre la réponse du client à Q-006 avant de
corriger `_build_daily_closure_report` : si confirmé, `facture_mvm_interne` et `total_du_jour_fc`
doivent être recalculés comme la somme des FC des rubriques déjà présentes dans le rapport — ce qui
impose au passage d'exposer les FC de `reste_du_jour`/`reste_du_hier`/`appro_effectue`/`appro_recu`/
`non_vendu_nv`/`declasses`/`sorties_gratuites` (aujourd'hui quantité seule).

---

## Point 2 — `ecart_production_fc` global vs par catégorie : **CONFORME**

### Preuve chiffrée

`ECART / PRODUCTION` est une valeur **unique par boulangerie/jour**, jamais décomposée par catégorie :

- `K6!L139` (06/10) : `=+(L137-L138)*L136` = (210 000 − 210 000) × 4 = **0**, converti en
  « Nbre pains » via `N139 = L139/500` — **un seul** prix de référence (500 FC), pas une ventilation
  par catégorie.
- `K6!L175` (03/10) : même structure, `=+(L173-L174)*L172` = (541 520,8 − 210 000) × 5 = **1 657 604**,
  `N175 = L175/500 = 3 315,2`.

`EXCEDENT PAINS`/`MANQUANT PAINS` (lignes 18/19, *avant* la ligne « FACTURE MVM INTERNE ») sont bien des
lignes séparées **par catégorie** (colonnes NBRE par tranche 200/300/500/1000) — exactement ce que
modélise déjà `BreadDisposal` par `bread_price`. Les deux concepts (écart de production global, et
excédent/manquant par catégorie via dispositions) coexistent légitimement dans la pièce réelle, sans
qu'aucune décomposition par catégorie de l'écart global ne soit jamais pratiquée.

### Conclusion

L'ambiguïté soulevée par dev-backend est une **fausse alarme** : la pièce réelle confirme qu'il n'y a
qu'un écart de production global par boulangerie/jour, et que l'excédent/manquant par catégorie est un
concept séparé déjà couvert par `BreadDisposal`. **Aucune correction nécessaire.**

### Observation secondaire (n'affecte pas le verdict — à communiquer au client)

La pièce réelle calcule `ECART/PRODUCTION` à partir de `TOTAL DU JOUR` (facturé + mouvements,
`L137 = L132/L136`) comme **proxy** de la valeur produite, faute d'une saisie de production séparée
dans le processus papier. L'application dispose déjà d'une déclaration de production indépendante
(`ProductionSession.total_fc_produced`/`yield_gap`), conforme au texte explicite de CLAUDE.md §5.4
(« valeur théorique − valeur **produite déclarée** », pas « valeur facturée »). Les deux bases ne
coïncident que si aucun pain ne reste en stock d'un jour à l'autre : le chiffre de l'application ne
reproduira donc jamais exactement celui de l'ancien Excel pour une même journée — ce n'est pas un bug,
mais il faut le dire au client avant le rapprochement pour éviter un faux signal d'alarme.

---

## Point 3 — `ECART/FACTURE`, `Tarif vente`, `Répartition de pains EN %` : **AMBIGU** (les 3)

Les trois formules de la pièce réelle montrent des signes clairs de **dérive de référence par
copier-coller** (feuille modifiée jour après jour sans réajuster les formules) : elles ne constituent
pas une base fiable à reproduire littéralement.

### `ECART/FACTURE`

- `K6!L135` (bloc du 06/10) : `= L76 + L77 - L132`. `L76`/`L77` ne sont **pas des totaux** : ce sont
  les lignes `FACTURE` de deux clients ordinaires (`C76`, `C77`), valeur 40 000 + 3 000 = 43 000 FC.
- `K6!L171` (bloc du 03/10, même feuille) : `= L77 + L78 - L168` — des lignes **différentes** pour la
  même rubrique logique. La référence dérive à chaque insertion de ligne client : c'est un bug de
  feuille, pas une règle métier stable.
- Résultat observé : `L135 = -805 000`.
- Formule proposée par dev-backend (`net_produit_fc − total_du_jour_fc`) = 632 000 − 840 000 =
  **-208 000**.
- Ni l'un ni l'autre n'est validable : le chiffre de la pièce réelle est manifestement corrompu
  (référencé sur des lignes-clients arbitraires), et aucune définition stable n'a pu en être extraite.

### `Tarif vente`

- `K6!L138` (06/10) = `=420*500` = 210 000.
- `K6!L174` (03/10, même boulangerie) = **même formule**, 210 000 — identique malgré des sacs (4 vs 5)
  et un total du jour (840 000 vs 2 707 604 FC) totalement différents d'un jour à l'autre.
- `TABORA!L183` (01/08/2026, autre boulangerie) = `=420*375` = 157 500 — formule identique
  (420 × prix de référence), mais constante différente par boulangerie (375 FC = la catégorie dominante
  de Tabora).
- Conclusion : « Tarif vente » est une **constante de référence saisie manuellement par boulangerie**
  (420 pains de référence × prix de la catégorie dominante du nœud), **pas** une moyenne recalculée
  chaque jour. Ni 210 000 ni 157 500 ne correspondent à `Config.sac_value_fc`/`Node.sac_value_fc` par
  défaut (200 000 FC, `backend/seed_from_excel.py`) — probablement une valeur personnalisée par nœud,
  non vérifiable depuis les fixtures de test disponibles. La définition de dev-backend (« TOTAL DU JOUR
  / pains facturés ce jour ») ne correspond pas à la pièce réelle.

### `Répartition de pains EN %`

- `K6!D141..L141` (barème réel de cette feuille : `E4=200, G4=300, I4=500, K4=1000`) pondère les
  quantités par **150 / 100 / 300 / 500** — incohérent avec son propre barème (devrait être
  200/300/500/1000). Ce jeu de multiplicateurs correspond au barème d'une **autre** feuille du même
  classeur (150/225/375/750), signe d'une formule recopiée par glissement entre boulangeries à barèmes
  différents.
- Les quantités pondérées (`D141=D132`, etc.) proviennent de `TOTAL DU JOUR` (facturé + mouvements),
  **pas** de la production déclarée — contredisant la définition de dev-backend (« part de chaque
  catégorie dans le total de pains **produits** »).
- Conclusion : le calcul réel de cette feuille est à la fois sur une base différente (facturé, pas
  produit) et sur des poids incohérents avec son propre barème de prix — pas une base fiable à copier.

### Conclusion générale du point 3

Ne pas répliquer littéralement ces trois formules de la pièce réelle : elle contient elle-même des
erreurs de glissement de référence (lignes-clients, barème de prix) qui ne sont manifestement pas la
règle métier voulue par le client. Question posée : Q-007 (`docs/qa/QUESTIONS_CLIENT.md`), formulée en
langage simple, avec demande explicite d'une formule à la main pour lever l'ambiguïté avant tout usage
comptable réel de ces trois totaux.

---

## Fichiers modifiés par cet audit

- `docs/qa/REGISTRE_BUGS.md` : ajout de la section « Audit comptable — auditeur-comptable, 2026-11-02 »
  sous `BUG-120` (statut du ticket inchangé, `CORRIGÉ`).
- `docs/qa/QUESTIONS_CLIENT.md` : ajout de Q-006 (sémantique de « FACTURE MVM INTERNE » et de
  « TOTAL DU JOUR ») et Q-007 (formules « ECART/FACTURE », « Tarif vente », « Répartition de pains
  EN % »).
- `docs/qa/rapports/auditeur-comptable-2026-11-02-audit-bug120.md` : ce rapport.

Aucun fichier de `data_kiese/` copié ni cité au-delà des cellules/agrégats strictement nécessaires à la
démonstration ci-dessus ; aucun code applicatif modifié.
