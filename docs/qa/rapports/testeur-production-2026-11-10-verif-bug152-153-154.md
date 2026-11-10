# Rapport testeur-production — 2026-11-10 — Vérification BUG-152 / BUG-153 / BUG-154

## Tickets traités

- **BUG-152** (backend, lié) — `CORRIGÉ` → `VÉRIFIÉ`.
- **BUG-154** (frontend, lié à BUG-152) — `CORRIGÉ` → `VÉRIFIÉ`.
- **BUG-153** (frontend, indépendant) — `CORRIGÉ` → `VÉRIFIÉ`.

Statuts mis à jour dans `docs/qa/REGISTRE_BUGS.md` (tableau de suivi, lignes BUG-152/153/154, et
notes de vérification ajoutées en fin de chaque fiche détaillée).

## Méthode

Lu intégralement les rapports `docs/qa/rapports/dev-backend-2026-11-10-bug152-reste-jour-integre-cloture.md`,
`docs/qa/rapports/dev-frontend-2026-11-10-bug154-boite-cloture-reste-categorie.md`,
`docs/qa/rapports/dev-frontend-2026-11-10-bug153-export-impression-cloture.md`, puis relu le code
final (pas seulement les rapports) :
- `backend/production/views.py` — `ProductionSessionViewSet.close()` (lignes ~447-614).
- `backend/production/models.py` — `DailyBreadStockSnapshot` (modèle, `record_snapshot()`,
  `unique_together`).
- `frontend/src/components/production/CloseSessionModal.tsx` (nouveau composant).
- `frontend/src/pages/dashboard/Production.tsx` (câblage du bouton de clôture).
- `frontend/src/api/services.ts` (`productionApi.sessions.close`, `disposals.list`).
- `frontend/src/utils/clotureReportExport.ts` et `frontend/src/pages/dashboard/ClotureJournaliere.tsx`
  (BUG-153, indépendant).

## BUG-152 / BUG-154 — vérification bout-en-bout

### Analyse de code confirmée (pas seulement relecture des tests de dev-backend)

- Dans `close()`, la validation complète de `remaining` (liste, chaque entrée : `bread_price`
  requis, `quantity` entier ≥ 0, `bread_price` existant en base) se fait **avant** le
  `transaction.atomic()` qui marque la session clôturée et crée les lignes `BreadDisposal
  REMAINING` — un `return Response(..., 400)` à ce stade ne touche ni `session.is_closed` ni aucune
  ligne de base, confirmé par du code ET par un test construit moi-même (scénario 4 ci-dessous).
- Le recoupement agrégé (`_build_reconciliation_querysets` / `_compute_reconciliation`, qui exclut
  explicitement `disposal_type=REMAINING`) est calculé **avant** toute création/mise à jour de ligne
  `REMAINING` issue de `remaining` — confirmé que `closure_summary['sales'|'returns'|'gap'|'nv'|'anomaly']`
  ne peut structurellement pas être affecté par ce nouveau champ.
- `DailyBreadStockSnapshot.unique_together = ['node', 'bread_price', 'date', 'team']` garantit
  structurellement (pas seulement par construction du code applicatif) qu'un upsert pour l'équipe A
  ne peut jamais toucher la ligne de l'équipe B le même jour.

### Scénarios construits indépendamment (fichier de test temporaire, supprimé après vérification — non livré dans le dépôt, les tests permanents couvrant BUG-152 restent ceux de `dev-backend` dans `test_daily_stock_snapshot.py::CloseWithRemainingBodyTests`)

1. **Fournée multi-catégories, `remaining` complet incluant une catégorie à 0 explicite** : 100
   pains 500FC + 50 pains 200FC déclarés, clôture avec `remaining=[{500FC: 30}, {200FC: 0}]`.
   Résultat : `DailyBreadStockSnapshot` = 30 et 0 respectivement ; `closure_summary` =
   `production_declared.breads=150, sales.breads=0, returns.breads=0, gap.breads=150, nv.breads=150,
   anomaly=False` — exactement le calcul attendu sans aucune vente/disposition, confirmant que les
   lignes `REMAINING` de `remaining` n'altèrent jamais ces agrégats. **PASS.**
2. **Non-régression explicite (comportement historique BUG-118)** : pré-déclaration séparée via
   `POST /api/production/disposals/` (REMAINING, qté 25) puis `close()` avec un corps vide (`{}`,
   sans `remaining`). Résultat : snapshot = 25, une seule ligne `BreadDisposal REMAINING` (ni
   dupliquée ni écrasée) — comportement strictement identique à avant BUG-152. **PASS.**
3. **Deux équipes A et B, même jour/nœud/catégorie, chacune son propre `remaining`** :
   équipe A clôture avec `remaining=10`, équipe B avec `remaining=45`. Résultat : deux
   `DailyBreadStockSnapshot` distincts (A=10, B=45), chacun rattaché à sa propre
   `BreadDisposal REMAINING` et à sa propre session — aucune interférence croisée. **PASS.**
4. **Quantité négative** : `remaining=[{bread_price: X, quantity: -5}]` sur une session ouverte.
   Résultat : `400`, `session.is_closed` reste `False`, `session.closed_at` reste `None`, le nombre
   de `BreadDisposal` et de `DailyBreadStockSnapshot` rattachés à la session est identique
   avant/après l'appel (vérifié explicitement par comptage). **PASS.**

Les 4 scénarios passent. Suite complète relancée ensuite :
```
backend/.venv/Scripts/python.exe manage.py test production sales finance
→ Ran 255 tests in 582.833s — OK
```
(251 tests `dev-backend` + 5 tests `CloseWithRemainingBodyTests` déjà en place côté dev-backend =
255, cohérent, aucune régression).

### Frontend (`CloseSessionModal.tsx`) — vérification par lecture de code

- `handleConfirm()` construit `remaining` par `categories.map(line => ({ bread_price:
  line.bread_price, quantity: quantities[line.bread_price] ?? 0 }))` sur `session.lines` (TOUTES les
  catégories produites par la fournée) : une catégorie laissée à 0 est **toujours envoyée
  explicitement** (`?? 0`), jamais omise du tableau — conforme au contrat backend qui, en l'absence
  d'une catégorie dans `remaining`, retomberait sur le comportement historique (écoulée à 0 par
  défaut si rien n'existe déjà) — ici le frontend ne laisse jamais ce cas implicite se produire.
- Le pré-remplissage à l'ouverture (`useEffect`) appelle
  `productionApi.disposals.list({ session: session.id, disposal_type: 'REMAINING' })`, scopé par
  session+type (le backend expose bien `session` et `disposal_type` dans
  `filterset_fields`), et fusionne les quantités trouvées dans l'état par défaut (initialisé à 0
  pour chaque catégorie produite) ; en cas d'échec réseau, le `.catch` est non bloquant — la boîte
  reste utilisable avec les valeurs par défaut à 0.
- Câblage dans `Production.tsx` : le bouton « Clôturer la fournée » (visible seulement si
  `!selectedSession.is_closed`) ouvre la boîte (`setCloseSessionModalOpen(true)`) ; le formulaire
  séparé « Stock Restant » existant n'est pas touché et reste disponible en parallèle.
- `productionApi.sessions.close(id, { remaining })` dans `services.ts` : signature additive,
  l'appel historique sans second argument reste inchangé.

### Build / tests

- `npm run build` (frontend/) → succès (mêmes avertissements préexistants : minifier `oxc`,
  chunk legacy > 500 kB — aucun nouvel avertissement).
- `backend/.venv/Scripts/python.exe manage.py test production sales finance` → **255 tests, OK**.

## BUG-153 (indépendant) — vérification

- Relu intégralement `frontend/src/utils/clotureReportExport.ts` : aucune fonction de calcul, uniquement
  mise en forme (`XLSX.utils.aoa_to_sheet`, formats de cellule `#,##0" FC"` / `#,##0` / `0.00"%"`) à
  partir des champs déjà utilisés par l'écran (`report.totals`, `report.categories`), avec
  `toNum()` = `parseFloat` d'une chaîne Decimal — strictement équivalent à ce que `formatFC`/
  `formatQty` (réexportés depuis `ClotureJournaliere.tsx`, mêmes fonctions utilisées à l'écran) font
  avant arrondi d'affichage. Aucun champ ni calcul ajouté qui ne provienne pas déjà du rapport
  backend affiché.
- L'impression (`printClotureReport`) réutilise strictement le motif déjà établi dans
  `Treasury.tsx` (`window.open` + `<script>window.onload=()=>{print();onafterprint=()=>close()}</script>`),
  document HTML autonome séparé du DOM de l'app — aucune modification de la mise en page existante
  de `ClotureJournaliere.tsx` (seuls deux boutons ajoutés dans le bandeau d'en-tête,
  `disabled={!report}`).
- Vérifié la dépendance `xlsx` :
  - `frontend/package.json` et `package-lock.json` : `"xlsx":
    "https://cdn.sheetjs.com/xlsx-0.20.3/xlsx-0.20.3.tgz"`.
  - `node_modules/xlsx/package.json` (installé) : version `0.20.3`, confirmant que c'est bien cette
    version qui est effectivement utilisée (pas seulement déclarée).
  - `npm audit` (frontend/) : `xlsx` n'apparaît plus dans la liste des vulnérabilités — seules 5
    vulnérabilités préexistantes et sans rapport avec ce ticket (axios, follow-redirects, form-data,
    react-router) subsistent, non traitées ici. Confirme que `0.20.3` corrige bien les deux CVE
    (`<0.19.3` et `<0.20.2`) citées par `dev-frontend`.
- `npx tsc --noEmit` et `npm run build` passent (déjà confirmés ci-dessus, même build que pour
  BUG-152/154).

## Anomalies trouvées

Aucune anomalie bloquante ou majeure trouvée sur BUG-152, BUG-153, BUG-154. Aucun nouveau ticket
`BUG-NNN` ouvert.

## Point d'environnement signalé au coordinateur (sans rapport avec le code applicatif)

Pendant cette vérification, deux processus `manage.py test production sales finance` concurrents
ont été observés sur la machine (un sous `.venv\Scripts\python.exe`, un sous l'interpréteur système
`C:\Program Files\Python312\python.exe`), démarrés à une seconde d'écart alors qu'une seule commande
avait été lancée côté testeur — résultat final néanmoins correct (255 tests, OK) une fois les deux
processus terminés, pas de corruption de données détectée (base de test en mémoire par processus,
pas la base réelle).

Plus préoccupant : `netstat -ano` confirme qu'un seul processus écoute réellement sur
`0.0.0.0:8000` (PID constaté dans l'environnement, utilisé en direct par le client ce jour) — et ce
processus tourne sous l'interpréteur système `C:\Program Files\Python312\python.exe`, **pas** sous
`.venv`, contrairement à ce qui était indiqué comme repère de légitimité (« le serveur sur
0.0.0.0:8000 avec le bon interpréteur `.venv` est légitime »). Un second processus `runserver`
existe bien sous `.venv` mais n'est pas celui qui écoute effectivement sur le port 8000 (confirmé par
`netstat`, une seule ligne `LISTENING`). Aucune action prise sur l'un ou l'autre de ces processus (ni
arrêt ni relance) — signalement uniquement au coordinateur, à vérifier par lui (quel interpréteur le
client utilise réellement en ce moment, et si cela a une incidence, ex. dépendances installées
différemment entre les deux environnements Python).

## Fichiers consultés / modifiés par ce testeur

- Consultés (lecture seule) : `backend/production/views.py`, `backend/production/models.py`,
  `frontend/src/components/production/CloseSessionModal.tsx`,
  `frontend/src/pages/dashboard/Production.tsx`, `frontend/src/api/services.ts`,
  `frontend/src/utils/clotureReportExport.ts`, `frontend/src/pages/dashboard/ClotureJournaliere.tsx`,
  `frontend/package.json`, `frontend/package-lock.json`.
- Modifié : `docs/qa/REGISTRE_BUGS.md` (statuts BUG-152/153/154 → `VÉRIFIÉ`, notes de vérification
  ajoutées en fin de chaque fiche détaillée).
- Créé puis supprimé (temporaire, non livré) : `backend/production/tests/test_verif_bug152_indep.py`
  — 4 scénarios indépendants décrits ci-dessus, tous `PASS` avant suppression.
- Aucun fichier applicatif (backend ou frontend) modifié, conformément à CLAUDE.md §7 règle 2.
