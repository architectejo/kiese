# Rapport — testeur-materiel — 2026-10-23

Première session de cet agent. Portée : relecture croisée de `desktop/src/printing.ts` (livré par
`packaging-desktop`, voir `docs/qa/rapports/packaging-desktop-2026-10-23.md`) et de
`frontend/src/components/shared/ThermalReceipt.tsx` (BUG-059, corrigé en phase 4), production des
procédures de test matériel. **Aucun code applicatif modifié** (hors de mandat). Aucune imprimante
thermique physique disponible dans cet environnement : les points nécessitant du matériel réel
restent des listes à cocher à dérouler par un humain sur site.

## 1. Réponses aux points demandés

### 1.1 Déclenchement de l'impression silencieuse (`printing.ts`)

- API utilisée : `webContents.print()` d'une `BrowserWindow` cachée (`show: false`), avec
  `silent: true`, `deviceName` (imprimante choisie en config), `margins: { marginType: 'none' }`,
  `printBackground: true`.
- Formats gérés : 58 mm et 80 mm via `pageSize.width` en microns (`WIDTH_MICRONS = { 58: 58000,
  80: 80000 }`), hauteur fixe généreuse (297000 µm, ~A4) laissée à l'avance réelle du pilote
  thermique.
- Configuration de l'imprimante par défaut au premier lancement : oui,
  `desktop/src/firstRun.ts` (étape 6 de l'assistant, DESKTOP.md §7) collecte `printerName` et
  `printerWidthMm` (58 | 80) et les écrit dans `config.json` via `desktop/src/config.ts`
  (`DEFAULT_CONFIG.printerWidthMm = 80` si rien n'est choisi). `desktop/src/main.ts` l.299 relie
  ensuite `registerPrintingHandlers(() => currentConfig.printerName)`.
- **Constat** : il n'existe **aucun écran post-installation** pour changer l'imprimante ou sa
  largeur sans modifier `config.json` à la main ou réinstaller — même lacune que BUG-074 (pont
  Electron fonctionnel, pas d'écran React). Signalé en remarque dans le ticket BUG-075 plutôt qu'en
  ticket séparé (cause commune : wiring frontend manquant).

### 1.2 Cohérence entre `ThermalReceipt.tsx` et `printing.ts` → deux bugs ouverts

En recoupant les deux fichiers, j'ai trouvé une incohérence qui dépasse la simple procédure de
test et relève du code — **BUG-075** et **BUG-076** ouverts dans `docs/qa/REGISTRE_BUGS.md` (table
de suivi + fiches détaillées) :

- **BUG-075 (Majeur, frontend)** : le bouton « Imprimer » de `ThermalReceipt.tsx` (l.162-164)
  appelle uniquement `window.print()` — **jamais** `window.kiese.printReceipt()`. Le module
  `printing.ts`, bien que fonctionnel et testé isolément par `packaging-desktop`, est du **code
  mort côté frontend** : aucun chemin d'exécution ne l'atteint. En desktop, cliquer sur « Imprimer »
  ouvre donc la boîte de dialogue d'impression Windows standard (comportement « navigateur »), pas
  l'impression silencieuse exigée par CLAUDE.md §8 et DESKTOP.md §10/§15 (étape D4, assignée à
  « packaging-desktop + dev-frontend »). C'est un trou de wiring côté `dev-frontend`, pas une
  erreur de `printing.ts` lui-même.
- **BUG-076 (Majeur, frontend)** : la règle `@media print` de `ThermalReceipt.tsx` (l.44-56) force
  `width: 80mm !important` sur `#${domId}` **sans condition**, en ignorant totalement
  `printerWidthMm` (58 ou 80) choisi à l'installation. Tant que BUG-075 n'est pas corrigé, c'est
  cette CSS figée à 80 mm qui déterminera dans les faits la mise en page imprimée, même sur un
  poste configuré en 58 mm — risque de débordement/troncature sur un rouleau 58 mm physique, à
  confirmer visuellement dès qu'une imprimante 58 mm sera disponible pour test.
- Dimensions/marges côté `printing.ts` lui-même (indépendamment du wiring) : cohérentes avec
  DESKTOP.md §10 (`pageSize` en microns selon la largeur, marges nulles, fond imprimé pour
  conserver les cellules grises `#e0e0e0` du tableau). Rien à signaler sur `printing.ts` isolément.

### 1.3 Procédures de test physique

Document créé : `docs/qa/CHECKLIST_MATERIEL.md` (nouveau, n'existait pas avant cette session).
Couvre, avec colonnes Attendu/OK-KO/Modèle exact/Observation :
1. Imprimante thermique 58/80 mm — §1.A navigateur (POS Android, flux actuel réel), §1.B desktop
   Electron (flux attendu une fois BUG-075 corrigé, explicitement marqué bloqué dans le document).
   Inclut accents (`é è à ç É`), symbole « FC », coupe papier.
2. Terminal POS Android (360 px) : connexion, facturation en série, lisibilité au soleil, taille
   des boutons, impression intégrée.
3. Scanner de code-barres : lecture code client, saisie directe, code illisible. Remarque : aucun
   module scanner dédié trouvé dans `frontend/src/` — fonctionnement supposé en mode clavier HID
   générique sur le champ de recherche existant, à confirmer avec le matériel réel du client.
4. Écran TV kiosque : plein écran, rafraîchissement auto, lisibilité à 3 m, comportement hors-ligne.
5. Tablette atelier : saisie de fournée au doigt (farine, sel en grammes, levure en paquets
   décimaux, huile en litres décimaux), transfert inter-boulangeries.
6. Page de diagnostic matériel à demander à `dev-frontend` (n'existe pas actuellement — recherche
   `diagnostic`/`Diagnostic` dans `frontend/src/` : aucun résultat). Spécification proposée dans le
   document, non bloquante pour exécuter les tests §1-5 sur données réelles.
7. Matrice de compatibilité (modèle × fonction) à remplir au fur et à mesure des tests réels,
   squelette créé.

## 2. Tickets ouverts cette session

| ID | Titre court | Composant | Gravité |
|---|---|---|---|
| BUG-075 | Bouton « Imprimer » n'appelle jamais `window.kiese.printReceipt()` (impression silencieuse desktop inopérante) | frontend | Majeur |
| BUG-076 | CSS d'impression figée à 80 mm, ignore la largeur imprimante configurée (58 mm) | frontend | Majeur |

Les deux sont dans `docs/qa/REGISTRE_BUGS.md` (table de suivi l.87-88 + fiches détaillées en fin de
fichier), statut OUVERT, assignés à personne (à trancher par le coordinateur — probablement
`dev-frontend`, cohérent avec DESKTOP.md §15 D4 qui lui attribue déjà cette étape conjointement
avec `packaging-desktop`).

## 3. Ce qui n'a pas pu être testé dans cette session (limite d'environnement)

- Aucune impression physique réelle (pas d'imprimante thermique 58/80 mm, pas de terminal POS
  Android, pas de scanner, pas de TV, pas de tablette disponibles ici) — conforme à la nature de ce
  rôle (préparation de procédures, l'exécution physique revient à un humain sur site).
- Aucun aperçu Playwright automatisé largeur 58/80 mm exécuté cette session (le point 2 de la
  mission standard — rendus de référence + vérification navigateur automatique — n'a pas été
  demandé explicitement dans les points spécifiques de cette session ; à reprendre dans une session
  ultérieure si le coordinateur le souhaite, une fois BUG-075/076 réglés pour ne pas valider une
  mise en page qui sera changée).

## 4. Suite recommandée

1. Coordinateur : assigner BUG-075/BUG-076 à `dev-frontend` (cohérent avec DESKTOP.md §15 D4).
2. Une fois corrigés : dérouler `docs/qa/CHECKLIST_MATERIEL.md` §1.B sur une vraie imprimante
   thermique USB et, si possible, Bluetooth, aux deux largeurs.
3. Demander à `dev-frontend` la page de diagnostic décrite au §6 du checklist (ticket à ouvrir par
   le coordinateur si jugée prioritaire avant le déploiement en boulangerie).
4. Confirmer avec le client le modèle réel de scanner et de terminal POS Android avant de
   compléter la matrice de compatibilité (§7 du checklist).

## 5. Fichiers touchés (chemins absolus)

- `D:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` (modifié : BUG-075, BUG-076 ajoutés — table de
  suivi + fiches détaillées)
- `D:\Projects\kiesse\docs\qa\CHECKLIST_MATERIEL.md` (nouveau)
- `D:\Projects\kiesse\docs\qa\rapports\testeur-materiel-2026-10-23.md` (ce rapport)

Aucun fichier de code applicatif modifié (`desktop/src/printing.ts`, `frontend/src/components/
shared/ThermalReceipt.tsx`, `desktop/src/firstRun.ts` lus uniquement, non modifiés).
