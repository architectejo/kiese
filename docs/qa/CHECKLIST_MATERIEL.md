# Checklist de test matériel — ETS. KIESE

Procédure de test **physique** (exécution humaine, sur site ou en atelier avant déploiement).
Ce document ne remplace pas les tests automatisés (`e2e/`) : il couvre ce qui ne peut être vérifié
que sur un vrai périphérique (encre thermique, lisibilité au soleil, latence Bluetooth réelle…).

Référence : CLAUDE.md §5.2 (contenu du reçu), §8 (cible desktop) ; cahierDesCharges.md §6.5-6.6 ;
`docs/architecture/DESKTOP.md` §10.

**Avant de commencer** : BUG-075 et BUG-076 (`docs/qa/REGISTRE_BUGS.md`) bloquent une partie des
tests ci-dessous — voir l'avertissement dans chaque section concernée. Ne pas valider D4
(DESKTOP.md §15) tant qu'ils sont ouverts.

Pour chaque ligne : **Attendu** / **OK · KO** / **Modèle exact de l'appareil** / **Observation**.
Toute case KO ouvre un ticket `BUG-NNN` (composant `frontend` ou `desktop`) dans le registre
unique avant de continuer.

---

## 1. Imprimante thermique — impression de reçu

### 1.A Via le navigateur (POS Android, ou tout poste sans Electron)

Chemin : `window.print()` existant, CSS `@media print` de `ThermalReceipt.tsx`.

| # | Test | Attendu | OK/KO | Modèle imprimante | Observation |
|---|---|---|---|---|---|
| 1 | Reçu 80 mm, facture simple (2-3 lignes) | Entête complet lisible (ETS. KIESE, RCCM 021-A-650, Id.Nat 10-F4300-N85947U, Impôt A1902266K, siège 49 Av. Tabora), code boulangerie visible, tableau articles non coupé, pied « Solde arrêté ce jour » visible | | | |
| 2 | Reçu 80 mm, facture longue (8+ lignes de pains) | Le ticket continue sur la longueur nécessaire, pas de contenu tronqué en bas, pas de page blanche intercalée | | | |
| 3 | Reçu **58 mm** | **⚠️ Risque connu (BUG-076)** : la CSS impose `width: 80mm` quelle que soit l'imprimante réelle → sur un rouleau 58 mm, vérifier colonne par colonne (QTE / DÉSIGNATION / P.U / T.P) si un débordement ou une réduction d'échelle illisible apparaît | | | |
| 4 | Caractères accentués | « é », « è », « à », « ç », « É » s'impriment correctement (pas de « ? » ni de caractère vide) dans le nom client et les désignations de pains | | | |
| 5 | Symbole FC | « FC » après chaque montant s'imprime sans coupure ni caractère erroné | | | |
| 6 | Coupe papier (si l'imprimante a un coupeur auto) | Coupe nette après le pied de ticket, sans perte de la dernière ligne | | | |
| 7 | Vitesse perçue au comptoir | Du clic « Imprimer » à l'impression effective : délai acceptable pour un facturier en file d'attente (cible : quelques secondes) | | | |

### 1.B Via l'application desktop (Electron)

**⚠️ Bloqué par BUG-075 dans l'état actuel du code** : le bouton « Imprimer » de `ThermalReceipt.tsx`
appelle `window.print()`, **jamais** `window.kiese.printReceipt()` — le chemin « silencieux » décrit
ci-dessous (`desktop/src/printing.ts`) n'est donc atteint par aucun clic utilisateur aujourd'hui.
Tant que ce ticket n'est pas corrigé par `dev-frontend`, les tests 8-12 ne peuvent constater que le
comportement du §1.A (boîte de dialogue Windows, imprimante par défaut système), pas le comportement
silencieux attendu. Documenter ce constat (pas une liste à cocher « normale ») si testé avant
correction.

| # | Test | Attendu (une fois BUG-075 corrigé) | OK/KO | Modèle imprimante | Observation |
|---|---|---|---|---|---|
| 8 | Imprimante choisie à l'assistant de première installation (DESKTOP.md §7 étape 6) | L'imprimante listée correspond au pilote Windows réellement installé ; le ticket de test proposé par l'assistant s'imprime | | | |
| 9 | Clic « Imprimer » sur un reçu de facturation | **Aucune** boîte de dialogue d'impression Windows ne s'affiche (`silent: true`), impression directe sur l'imprimante configurée | | | |
| 10 | Largeur 58 mm vs 80 mm configurée | `printing.ts` utilise `WIDTH_MICRONS[widthMm]` : vérifier que le ticket physique correspond bien à la largeur choisie à l'installation (pas de dépendance à la CSS écran, contrairement au §1.A) | | | |
| 11 | Imprimante débranchée/éteinte | Message d'erreur clair affiché à l'écran (pas de blocage de l'application), reçu reste consultable/réimprimable depuis le Dashboard | | | |
| 12 | Imprimante Bluetooth appairée à Windows | Fonctionne identiquement à une imprimante USB si elle apparaît dans `window.kiese.listPrinters()` (aucune gestion Bluetooth spécifique codée — simple pilote Windows) | | | |

---

## 2. Terminal POS Android (navigateur, ≈ 360 px de large)

| # | Test | Attendu | OK/KO | Modèle terminal | Observation |
|---|---|---|---|---|---|
| 1 | Connexion (login facturier) | Champs utilisables au doigt, clavier virtuel ne masque pas le bouton de connexion | | | |
| 2 | Facturation en série (plusieurs clients à la suite) | Recherche client rapide (voir BUG-065/BUG-069 déjà au registre, performance), boutons de quantité assez grands pour taper sans erreur répétée | | | |
| 3 | Lisibilité en plein soleil (terrasse/comptoir extérieur) | Contrastes du Dashboard restent lisibles (texte noir sur fond clair prioritaire), pas de dépendance à un dégradé pâle | | | |
| 4 | Taille des boutons tactiles | Boutons d'action (Confirmer, Livrer, Imprimer) ≥ ~44px de cible tactile, espacés pour éviter les doubles clics involontaires | | | |
| 5 | Impression intégrée (si le terminal a une imprimante thermique embarquée, pas USB) | Le flux est celui du §1.A (navigateur) : confirmer qu'aucune API Web Bluetooth/SDK natif n'est requis côté frontend actuel (cahierDesCharges.md §6.6 l'évoque en option, non implémentée — à signaler si le matériel du client l'exige) | | | |
| 6 | Rotation d'écran | L'interface reste utilisable si le terminal tourne accidentellement (portrait verrouillé recommandé côté OS si l'app ne gère pas le paysage) | | | |

---

## 3. Scanner de code-barres (code client)

| # | Test | Attendu | OK/KO | Modèle scanner | Observation |
|---|---|---|---|---|---|
| 1 | Lecture d'un code client imprimé sur une fiche/reçu | Le scanner agit comme un clavier (saisie + Entrée) dans le champ de recherche client de la facturation ; le client correspondant apparaît immédiatement | | | |
| 2 | Saisie manuelle directe (sans scanner) comparée au scan | Même résultat de recherche prédictive, aucune différence de comportement | | | |
| 3 | Code mal imprimé / illisible | Message d'erreur clair (« client introuvable »), pas de blocage ni de sélection d'un autre client par erreur | | | |

Remarque : aucun module scanner dédié n'a été identifié dans le code frontend (`frontend/src/`) à
la date de ce rapport — le scanner, s'il est utilisé, fonctionne en mode « clavier HID » générique
sur le champ de recherche existant. À confirmer avec le modèle de scanner réellement fourni par le
client avant d'aller plus loin (pas de SDK propriétaire à intégrer a priori).

---

## 4. Écran TV — mode kiosque

Référence : cahierDesCharges.md §6.5 point 4 (« Dashboard Kiosque » plein écran, graphiques temps
réel des volumes de production par boulangerie).

| # | Test | Attendu | OK/KO | Modèle TV | Observation |
|---|---|---|---|---|---|
| 1 | Affichage plein écran (pas de barre de navigateur visible) | Mode kiosque du navigateur/launcher Android TV, aucune UI de contrôle visible | | | |
| 2 | Rafraîchissement automatique | Les données (CA du jour, volumes de production) se mettent à jour sans intervention manuelle, sans rechargement complet visible (flash blanc) | | | |
| 3 | Lisibilité à ~3 mètres | Taille de police et contrastes des graphiques suffisants depuis la distance d'observation réelle au siège | | | |
| 4 | Comportement en cas de perte réseau/API | Pas d'écran blanc ou d'erreur JavaScript bloquante affichée en boucle devant la direction ; dernière donnée connue conservée à l'écran si possible | | | |

**Constat** : aucune page « kiosque » dédiée (plein écran, sans navigation, auto-refresh) n'a été
localisée dans `frontend/src/pages/` à la date de ce rapport (recherche `kiosque`/`Kiosk`/
`diagnostic` : aucun résultat). Avant de pouvoir dérouler ce test, demander à `dev-frontend` la
création de cet écran (ticket à ouvrir par le coordinateur si confirmé absent du périmètre déjà
livré), sauf si le client utilise simplement le Dashboard existant en plein écran navigateur — à
clarifier.

---

## 5. Tablette atelier (saisie de fournée)

| # | Test | Attendu | OK/KO | Modèle tablette | Observation |
|---|---|---|---|---|---|
| 1 | Saisie des sacs de farine (décimaux) au doigt | Champs numériques décimaux faciles à ajuster au doigt (pas de clavier qui bloque les décimales) | | | |
| 2 | Saisie du sel en grammes / levure en paquets décimaux / huile en litres décimaux | Unités clairement affichées, pas de confusion d'unité possible pour un opérateur non technique | | | |
| 3 | Boutons gros format (gants de boulangerie, mains enfarinées) | Cibles tactiles larges, pas de double-saisie accidentelle | | | |
| 4 | Transfert inter-boulangeries (saisie de sortie) | Flux complet utilisable à la tablette jusqu'à validation | | | |

---

## 6. Page de diagnostic matériel (à demander à `dev-frontend`)

Aucune page de diagnostic accessible aux administrateurs n'existe à la date de ce rapport
(recherche de `diagnostic`/`Diagnostic` dans `frontend/src/` : aucun résultat). Pour fiabiliser les
tests ci-dessus sans dépendre d'un parcours métier complet (créer une vraie facture pour tester une
imprimante), demander via ticket à `dev-frontend` une page minimale (menu Administration) avec :
- bouton « Imprimer un reçu de test 58 mm » / « … 80 mm » (données fictives, mêmes composants que
  `ThermalReceipt.tsx`) ;
- bloc de texte fixe contenant tous les caractères sensibles : `é è à ç É` et `FC` ;
- affichage de `window.kiese?.listPrinters()` et de la configuration imprimante active (nom,
  largeur) si disponible (desktop uniquement) ;
- champ de saisie « Test scanner » qui affiche en direct le dernier code lu (focus automatique) ;
- lien vers le mode kiosque TV (voir §4).

Cette page n'est pas un prérequis bloquant pour exécuter les tests §1 à §5 (qui peuvent se faire
sur de vraies factures/données de démonstration), mais accélère grandement les vérifications
répétées lors du déploiement dans chacune des 8 boulangeries.

---

## 7. Matrice de compatibilité (à remplir au fur et à mesure des tests)

| Modèle testé | Imprimante USB | Imprimante Bluetooth | POS Android | Scanner HID | TV kiosque | Tablette | Recommandé client ? |
|---|---|---|---|---|---|---|---|
| (à compléter) | | | | | | | |

But : fixer la liste du matériel recommandé à l'achat pour les 8 boulangeries une fois les tests
physiques réalisés. Une ligne par modèle réellement testé — ne pas présumer la compatibilité d'un
modèle non testé.
