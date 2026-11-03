# Rapport testeur-clients-commissions — 2026-11-03 — Vérification BUG-124 / BUG-125

Mission : vérifier les correctifs `dev-frontend` (2026-11-02, `CORRIGÉ`, non
`VÉRIFIÉ`) exposant deux champs additifs lecture seule introduits côté API en
clôturant BUG-122 et BUG-123 : `ClientCommission.carried_debt_in`
(Commissions.tsx) et `ConsumableStock.average_unit_cost` (Production.tsx §3.2).

Document de référence lu avant vérification :
`docs/qa/rapports/dev-frontend-2026-11-02-bug124-125.md`.

## Méthode

Pas de correction de code (CLAUDE.md §7 règle 3) : relecture attentive du
code applicatif (frontend et backend pour contrôler la cohérence de la
formule affichée), puis exécution des vérifications statiques demandées.
Aucun test automatisé Commissions/Intrants n'existe encore (relevé par
dev-frontend) — vérification manuelle par lecture de code uniquement, comme
demandé par le coordinateur pour cette mission.

## BUG-124 — `carried_debt_in` (Commissions.tsx)

1. **Formule backend relue** (`backend/commissions/models.py`,
   `ClientCommission.compute()` lignes 115-213) :
   - `carried_debt_in` est recalculé à chaque appel de `compute()` via
     `_compute_carried_debt_in()` — jamais une valeur stockée en entrée. Il
     reprend la valeur absolue du `net_payable` négatif de la commission la
     plus récente du même client/nœud, strictement antérieure à la période
     courante.
   - `net_payable = net_carte - deduction_social - deduction_prints -
     deduction_other - carried_debt_in + bonus`, **sauf** si
     `manuel_adjustment is not None`, auquel cas `net_payable =
     manuel_adjustment + bonus` (le report n'est pas réappliqué).
2. **Frontend relu** (`frontend/src/pages/dashboard/Commissions.tsx`) :
   - Tableau listing (lignes ~400-430) : badge rouge « Report » affiché
     uniquement si `carriedDebtIn = parseFloat(c.carried_debt_in || '0') >
     0`, info-bulle avec le montant exact. Lecture directe du champ API, pas
     de calcul.
   - Fiche de paie (modale, lignes ~498-582) : ligne « (−) Report période
     précédente » insérée entre les retenues existantes
     (dette/sociale/imprimés/autre/remise) et le total « NET À PAYER »,
     visible si `carriedDebtIn > 0`, en rouge. Mention secondaire « non
     appliqué au net à payer : un ajustement manuel est en vigueur » affichée
     seulement si `f.manuel_adjustment != null` — cohérent avec la formule
     backend (le report n'est pas réappliqué dans ce cas).
   - Le NET À PAYER affiché (`net = parseFloat(f.net_payable || '0')`) est
     **strictement** la valeur renvoyée par l'API, jamais recombiné/recalculé
     côté client à partir des lignes affichées (pas de `gross - debt -
     carte - social - ... - carriedDebtIn` recalculé en JS). Confirmation :
     affichage en lecture seule stricte, conforme au mandat de vérification.
   - `frontend/src/api/services.ts` ligne 438 : `carried_debt_in: string`
     ajouté à l'interface `ClientCommission`, commenté comme champ additif
     lecture seule (BUG-124).
3. **`npx tsc --noEmit`** : exit code 0, aucune erreur.
4. **`npm run build`** : exit code 0 (`tsc && vite build`). Seuls
   avertissements : taille de chunk `index-legacy...js` > 500 kB et
   dépréciation du minifieur `oxc` pour les chunks legacy — préexistants,
   identiques à ceux relevés par dev-frontend, aucun nouvel avertissement.
5. Aucun nouvel `any` introduit (grep du diff et relecture du fichier).
6. Pas de régression visuelle détectée : `colSpan={10}` du tableau listing
   inchangé (pas touché par ce ticket), états chargement/vide toujours
   corrects.

**Conclusion : conforme.** Passage à `VÉRIFIÉ` dans le registre (note datée
2026-11-03).

## BUG-125 — `average_unit_cost` (Production.tsx §3.2)

1. **Contrat backend** (confirmé dans le rapport dev-backend BUG-123) :
   `average_unit_cost` (CUMP) est un champ lecture seule sur
   `ConsumableStock`, recalculé par le backend à chaque entrée de stock
   (`ENTRY`), moyenne pondérée par quantité.
2. **Frontend relu** (`frontend/src/pages/dashboard/Production.tsx`, lignes
   ~490-520, onglet Intrants) :
   - En-tête de tableau passé à 5 colonnes : `Intrant / Qté / Unité / CUMP /
     Statut`, avec info-bulle explicative sur la colonne CUMP.
   - `cump = st.average_unit_cost != null ? parseFloat(st.average_unit_cost)
     : null` — lecture directe, affichage `—` si absent (pas de
     régression si le backend ne renvoie pas le champ). Aucun recalcul
     (pas de somme/moyenne refaite côté client).
   - `colSpan` de la ligne « Aucun stock » mis à jour `4 → 5`
     (`colSpan={5}`), vérifié correct dans le code lu.
   - `frontend/src/api/services.ts` ligne 326 : `average_unit_cost?: string`
     (optionnel), commenté BUG-125, lecture seule.
3. `npx tsc --noEmit` et `npm run build` : même exécution que ci-dessus
   (une seule passe couvrant les deux fichiers), exit code 0, aucune erreur,
   aucun avertissement nouveau, aucun nouvel `any`.
4. Pas de régression visuelle détectée : bloc d'alerte stock bas et section
   « Inventaire Physique » (non-FLOUR) non affectés par l'ajout de colonne.

**Conclusion : conforme.** Passage à `VÉRIFIÉ` dans le registre (note datée
2026-11-03).

## Résultats

| Ticket | Vérification | Résultat |
|---|---|---|
| BUG-124 | Lecture formule backend + relecture Commissions.tsx + tsc + build | Conforme → `VÉRIFIÉ` |
| BUG-125 | Lecture contrat backend + relecture Production.tsx §3.2 + tsc + build | Conforme → `VÉRIFIÉ` |

Aucune ambiguïté rencontrée, aucun défaut trouvé. Aucun nouveau ticket ouvert.

## Remarque transmise au coordinateur (non bloquante)

Le rapport dev-frontend signale explicitement que le report de dette
(`carried_debt_in`) n'est **pas** répercuté dans le listing imprimé/exporté
Excel du tableau Commissions (`handlePrint`/`handleExportExcel` gardent leurs
colonnes actuelles : NET/ORDI, CARTE, NET/CARTE, NET À PAYER). Ce point était
hors périmètre strict des tickets BUG-124/125 (affichage écran uniquement) et
n'empêche pas leur validation, mais je le signale au coordinateur au cas où
le listing papier/export doive aussi porter la mention du report pour un
usage comptable externe (le NET À PAYER imprimé reste exact, seule la ligne
de détail du report est absente de l'impression/export).

## Fichiers consultés (lecture uniquement, aucune modification applicative)

- `backend/commissions/models.py`
- `frontend/src/pages/dashboard/Commissions.tsx`
- `frontend/src/pages/dashboard/Production.tsx`
- `frontend/src/api/services.ts`
- `docs/qa/rapports/dev-frontend-2026-11-02-bug124-125.md`
- `docs/qa/REGISTRE_BUGS.md` (mis à jour : BUG-124, BUG-125 → `VÉRIFIÉ`)
