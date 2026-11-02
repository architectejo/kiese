# Rapport dev-frontend — BUG-075 / BUG-076 — 2026-10-23

## Périmètre
Fichier modifié : `frontend/src/components/shared/ThermalReceipt.tsx`.
Aucun autre fichier de `frontend/src/pages/` touché. `desktop/` et `backend/` non modifiés
(périmètre interdit, respecté).

## BUG-075 — Impression silencieuse Electron inopérante
- Cause : le bouton « Imprimer » appelait uniquement `window.print()`, sans jamais tester la
  présence du pont `window.kiese` ni appeler `window.kiese.printReceipt()`.
- Correction : nouveau gestionnaire `handlePrint()`. Si `window.kiese?.printReceipt` existe
  (mode desktop Electron) :
  1. Clone du nœud `#thermal-receipt-<printId>` (styles déjà inline, donc fidèlement conservés),
     avec retrait des contraintes propres à l'aperçu écran (`maxWidth`, `boxShadow`,
     `borderRadius`).
  2. Construction d'un document HTML autonome (`buildPrintableHtml`) avec une feuille de base
     minimale (police, fond, largeur `body` en mm).
  3. Appel `window.kiese.printReceipt(html, { widthMm: printerWidthMm })` — utilise l'API
     existante de `desktop/src/preload.ts`/`printing.ts` telle quelle, sans aucune modification de
     `desktop/`.
  Hors Electron (navigateur, POS Android) : repli `window.print()` identique à l'existant, non
  régressé.
- États ajoutés : `isPrinting` (bouton désactivé + libellé « Impression… ») et `printError`
  (message affiché sous le reçu si `result.ok === false`, texte `detail`/`error` de l'API
  Electron, ou message générique sur exception).
- Typage : `window.kiese` était déjà déclaré dans `frontend/src/types/kiese.d.ts`
  (`KieseBridge.printReceipt`), réutilisé sans modification. Aucun nouveau `any`.

## BUG-076 — Largeur d'impression figée à 80 mm
- Cause : `@media print` forçait `width: 80mm !important` sans condition ; toutes les tailles de
  police du reçu étaient des `rem` fixes pensés pour 80 mm.
- Confirmation de la limite signalée par testeur-materiel : `window.kiese`
  (`desktop/src/preload.ts`) n'expose **aucun** moyen pour le frontend de lire
  `DesktopConfig.printerWidthMm` (vérifié dans `main.ts`, `config.ts`, `preload.ts` : seul
  `kiese:get-boot-info` existe et ne renvoie que `apiUrl`/`appVersion`). Conformément à la
  consigne, je n'ai pas inventé de mécanisme côté Electron : j'ai ajouté une prop **optionnelle**
  `printerWidthMm?: 58 | 80` (défaut `80`, comportement antérieur inchangé) sur `ThermalReceipt`,
  prête à être branchée dès qu'un tel endpoint existera côté `desktop/`.
- Correction appliquée dans `ThermalReceipt.tsx` :
  - `@media print` utilise `width: ${printerWidthMm}mm !important`.
  - Toutes les tailles de police passent par un utilitaire `rem(n)` avec facteur d'échelle
    (`0.82` à 58 mm, `1` à 80 mm) pour rester lisibles sur la largeur utile plus étroite.
  - La largeur d'aperçu écran (`maxWidth`) s'adapte également (`240px` / `320px`).
  - La même valeur est transmise à `window.kiese.printReceipt` (cohérence avec BUG-075).
- Limite résiduelle documentée dans le composant et dans le registre : aucune page appelante ne
  transmet encore `printerWidthMm` dynamiquement (aucune n'a accès à cette config aujourd'hui).
  Recommandation consignée dans le registre : ticket de suivi pour `packaging-desktop` (exposer
  `printerWidthMm` via `window.kiese`), puis ticket pour `dev-frontend` (brancher la prop déjà
  prête depuis les pages appelantes, ex. `Sales.tsx`) — non ouverts par moi car cela dépasse mon
  périmètre de cette session (pas de modification de page ni de `desktop/`) ; à ouvrir par le
  coordinateur si jugé pertinent.

## Vérifications effectuées
- `npx tsc --noEmit` : aucune erreur.
- `npm run build` : succès (seul avertissement préexistant sur la taille du chunk JS principal,
  non lié à ce correctif).
- Recherche dans `e2e/` : aucun test ne couvre spécifiquement l'impression (ni `printReceipt`, ni
  la largeur CSS). `e2e/tests/04-facturation.spec.ts` vérifie le contenu du reçu (BUG-059) mais
  pas l'impression — je l'ai lancé en arrière-plan (`npx playwright test 04-facturation.spec.ts`)
  en guise de test de non-régression général sur `ThermalReceipt.tsx` ; le backend (`:8000`) et le
  frontend (`:5173`) étaient actifs, mais le test n'a pas produit de résultat dans le temps
  disponible de cette session (aucune sortie après plusieurs minutes d'attente) — à relancer par
  le testeur pour confirmation, résultat non concluant de mon côté.
- Vérification manuelle du matériel (imprimante physique 58/80 mm, boîte de dialogue Windows
  absente en mode desktop) : impossible dans cet environnement de développement (aucune
  imprimante physique ni build Electron packagé disponibles) — étapes détaillées pour
  `testeur-materiel` consignées dans les fiches `#### Correction` de BUG-075 et BUG-076 du
  registre.

## Statuts
- BUG-075 : `OUVERT` → `CORRIGÉ`.
- BUG-076 : `OUVERT` → `CORRIGÉ`.
- Aucun des deux n'a été passé à `VÉRIFIÉ` (réservé à testeur-materiel/testeur-e2e/coordinateur).

## Fichiers
- Modifié : `frontend/src/components/shared/ThermalReceipt.tsx`
- Registre mis à jour : `docs/qa/REGISTRE_BUGS.md` (tableau + fiches détaillées BUG-075/BUG-076)
- Ce rapport : `docs/qa/rapports/dev-frontend-bug075-076-fix-2026-10-23.md`
