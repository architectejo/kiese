# Rapport dev-frontend — 2026-11-10

## BUG-156 — Boîte modale forcée « Reste du jour » à la fin de créneau (volet frontend de BUG-155)

### Cause
Le backend (BUG-155, dev-backend, `CORRIGÉ`) expose désormais
`GET /api/production/sessions/shift-end-status/?node=<code>` mais rien côté frontend ne
l'interrogeait : une fournée dont le créneau d'équipe est dépassé restait silencieusement non
close jusqu'à ce qu'un gérant pense à cliquer manuellement sur « Clôturer la fournée ».

### Fichiers modifiés/créés
- `frontend/src/api/services.ts` — types `ShiftEndTeam`, `ShiftEndRemainingLine`,
  `ShiftEndStatus` (union `ShiftEndStatusPending | ShiftEndStatusAutoClosed | ShiftEndStatusNone`)
  et `productionApi.sessions.shiftEndStatus(params?)`. Aucun nouveau `any`.
- `frontend/src/store/shiftEndStore.ts` (nouveau) — store Zustand sur le modèle exact de
  `openingConfirmationStore.ts` (BUG-151) : `pending` (équipe/session/reste suggéré en attente de
  clôture forcée) et `autoClosedTeam` (notification de clôture automatique à afficher une fois).
- `frontend/src/components/production/CloseSessionModal.tsx` — mode forcé additionnel
  (`forced`/`onForcedClose`), sans toucher au mode volontaire existant (BUG-154) : toutes les
  branches nouvelles sont gardées par `isForced`, qui vaut `false` par défaut (`forced=null`),
  donc le comportement historique est strictement inchangé quand cette prop n'est pas fournie.
- `frontend/src/components/layout/DashboardLayout.tsx` — sondage intégré au cycle de
  notifications existant (même `setInterval` à 10 s, pas de second timer), montage unique de la
  modale forcée et d'un toast de clôture automatique, re-sondage immédiat après résolution d'une
  équipe pour traiter l'autre sans attendre le prochain intervalle.
- `docs/qa/REGISTRE_BUGS.md` — ticket passé à `CORRIGÉ`, détail complet de l'implémentation et
  étapes de vérification manuelle pour le testeur.

### Mécanisme de polling retenu
Pas de second `setInterval` : `fetchShiftEndStatus()` est appelé au montage puis à chaque tick du
`setInterval` déjà en place pour `fetchNotifications()` (10 s) dans `DashboardLayout.tsx`. Gating
par rôle identique à `OpeningStockConfirmationModal` (BUG-134/138) : `GERANT` ou `FACTURIER` non-HQ
uniquement — le backend autorise `IsAuthenticated` sur cet endpoint précisément pour qu'un
facturier seul puisse aussi déclencher/voir la détection (remarque.md), même s'il n'a pas la
permission `IsGerant` requise pour soumettre `close()` lui-même (dans ce cas la modale forcée
s'afficherait et une tentative de soumission échouerait avec le `detail` renvoyé par l'API, affiché
tel quel — aucun contournement de la règle serveur).

Règle de re-sondage immédiat (demandée explicitement) :
- Si la réponse contient `auto_closed: true`, un second appel est fait aussitôt (sans attendre le
  prochain intervalle) pour vérifier si l'AUTRE équipe est elle aussi concernée — un seul niveau de
  récursion (`allowImmediateRetry`), pas de boucle infinie possible puisque la session vient d'être
  close côté serveur.
- Si l'utilisateur soumet avec succès la clôture forcée (`onForcedClose` → `handleForcedClosed`),
  `pending` est réinitialisé puis `fetchShiftEndStatus()` est rappelé immédiatement, même logique.

### Comportement du mode forcé (`CloseSessionModal`)
- Titre « Clôture du créneau — Équipe X », bandeau d'avertissement expliquant le délai de grâce de
  30 min.
- Pas de bouton « Annuler », `showCloseButton={false}`, `closeOnBackdropClick={false}` : la boîte
  ne peut être fermée qu'en soumettant (Échap reste capté par le `Modal` partagé mais appelle un
  `onClose` no-op passé par `DashboardLayout` dans ce mode).
- Quantités pré-remplies depuis `quantity_suggested` (stock physique actuel renvoyé par le
  backend) au lieu de 0.
- Soumission : même appel `productionApi.sessions.close(session, {remaining})` qu'en mode
  volontaire (BUG-152/154), non modifié.
- Clôture automatique (`auto_closed: true`) : pas de modale, toast fixe en bas à droite dans
  `DashboardLayout`, auto-effacé après 8 s ou fermable manuellement.

### Vérifications effectuées
- `npx tsc --noEmit` (frontend/) : aucune erreur.
- `npm run build` (frontend/) : succès (`✓ built in 1m 43s`). Seul avertissement présent :
  taille de chunk > 500 kB, préexistant, sans rapport avec ce ticket.
- Pas de test automatisé ajouté pour ce ticket : le scénario nécessite un temps simulé (fin de
  créneau dépassée de 0 à 30+ minutes), incompatible avec un test Playwright chronométré sur base
  réelle, et le client a explicitement demandé de ne plus recréer de comptes `demo_*_e2e` dans
  `db.sqlite3` (reset du 2026-11-10). Aucun outillage Vitest/React Testing Library n'est configuré
  dans `frontend/package.json` à ce jour — signalé au coordinateur comme piste pour un futur
  ticket d'outillage si ce type de scénario (logique de polling/état, sans vrai navigateur) doit
  être couvert automatiquement.
- Étapes de vérification manuelle détaillées déposées dans la fiche BUG-156 du registre, à
  destination du testeur d'origine (ou du coordinateur) qui doit passer le ticket à `VÉRIFIÉ`.

### Remarque sur le registre
En lisant la fiche détaillée de BUG-156 avant de commencer, j'ai trouvé en fin de section une ligne
« Statut : `VÉRIFIÉ` (`testeur-production`, 2026-11-10) » alors que la ligne de tableau indiquait
`OUVERT` et qu'aucune correction n'avait encore été apportée — chronologiquement impossible (un
testeur ne peut pas vérifier une correction qui n'existe pas encore) et contraire à CLAUDE.md §7
règle 3 (seul le testeur d'origine ou le coordinateur fait passer un ticket à `VÉRIFIÉ`, jamais le
développeur, et certainement pas avant la correction). J'ai traité cette ligne comme une incohérence
du document plutôt que comme une validation acquise, et j'ai remplacé ce statut par `CORRIGÉ` en
y ajoutant le détail de mon implémentation, conformément au cycle de vie normal du ticket. Je
signale ce point au coordinateur au cas où cette ligne provenait d'une autre source.

## BUG-157 — L'annonce de clôture automatique reste affichée jusqu'à confirmation

Instruction directe du client (2026-11-10) : « La boîte qui annonce une clôture automatique doit
rester affichée sur l'écran jusqu'à la confirmation du gérant. » Ce ticket remplace la dernière
puce de la section BUG-156 ci-dessus (« toast fixe […] auto-effacé après 8 s »).

### Cause
Sous BUG-156, la réponse `auto_closed: true` alimentait un état `autoClosedTeam` (une seule équipe)
affiché en toast et effacé par un `setTimeout` de 8 s. Le backend ne renvoyant cette réponse qu'une
fois, l'annonce était perdue après 8 s, après un rechargement de page, ou écrasée par celle de
l'autre équipe lors du re-sondage immédiat.

### Fichiers modifiés/créés
- `frontend/src/store/shiftEndStore.ts` — file `autoClosedNotices` (`{team, date}`), persistée dans
  `localStorage` sous `kiese_shift_end_auto_closed:<user.node>` (try/catch, garde de type à la
  relecture, dédoublonnage équipe+date) ; retrait uniquement par `confirmAutoClosedNotice`.
  `notifyAutoClosed` ne ferme plus la modale forcée que si elle concerne la même équipe.
- `frontend/src/components/production/AutoClosedNoticeModal.tsx` (nouveau) — boîte modale (composant
  `Modal` partagé), bouton unique « J'ai compris », sans croix, sans fermeture par l'arrière-plan,
  Échap sans effet, aucun minuteur d'effacement ; annonces présentées une par une (« Annonce 1 sur
  N ») ; bouton inactif 0,7 s à l'apparition de chaque annonce (anti double appui).
- `frontend/src/components/layout/DashboardLayout.tsx` — toast et minuteur supprimés, rechargement
  des annonces en attente au montage et sur événement `storage`, rendu de la nouvelle boîte après
  la modale forcée (au premier plan si les deux coexistent). Garde de rôle BUG-156 inchangée.
- `frontend/src/components/shared/Modal.tsx` — compteur de modales ouvertes : `body.modal-open`
  n'est retiré qu'à la fermeture de la dernière (deux modales peuvent désormais coexister).
- `docs/qa/REGISTRE_BUGS.md` — ligne BUG-157 passée à `CORRIGÉ` + fiche détaillée (en fin de
  fichier, après BUG-158).

### Vérifications effectuées
- `npx tsc --noEmit` : aucune erreur. `npm run build` : succès (`✓ built in 2m 31s`), seul
  avertissement : taille de chunk > 500 kB, préexistant.
- Non fait : aucun test automatisé (pas d'outillage de test unitaire frontend, pas de Playwright
  sur base réelle) et aucune exécution dans un navigateur. La correction n'a été contrôlée que par
  compilation et relecture ; la règle §7.4 de CLAUDE.md n'est pas satisfaite. Huit étapes de
  vérification manuelle (dont une simulation par `localStorage` qui évite d'attendre un créneau
  réel) sont dans la fiche BUG-157.

### Points à arbitrer par le coordinateur
- L'annonce est liée au navigateur du poste, pas au compte : elle n'apparaît que sur le poste qui a
  reçu `auto_closed: true`, et un FACTURIER peut la confirmer (garde de rôle BUG-156 conservée,
  comme demandé). Une confirmation garantie « par le gérant », visible sur tous les postes,
  demanderait un accusé de lecture côté serveur — ticket `dev-backend` non ouvert, à décider.
- La date affichée est celle du poste au moment de la détection (l'API ne renvoie pas la date de
  la fournée close).
- Si la modale forcée s'ouvre alors qu'une annonce est déjà à l'écran, le focus clavier initial va
  dans la modale forcée située dessous (souris/tactile non concernés).

## Fichiers touchés (récapitulatif)
- `frontend/src/api/services.ts`
- `frontend/src/store/shiftEndStore.ts` (nouveau)
- `frontend/src/components/production/CloseSessionModal.tsx`
- `frontend/src/components/production/AutoClosedNoticeModal.tsx` (nouveau, BUG-157)
- `frontend/src/components/shared/Modal.tsx` (BUG-157)
- `frontend/src/components/layout/DashboardLayout.tsx`
- `docs/qa/REGISTRE_BUGS.md`
- `docs/qa/rapports/dev-frontend-2026-11-10.md` (ce rapport)

## BUG-159 — Reste du jour négatif dans `CloseSessionModal` (CORRIGÉ)
Clamp `Math.max(0, …)` et `min={0}` supprimés, saisie texte avec bouton ± (compatibilité clavier mobile), avertissement « Stock négatif » non bloquant, pré-remplissage forcé négatif conservé. Fichier : `frontend/src/components/production/CloseSessionModal.tsx`. Détails et vérification manuelle : fiche BUG-159 du registre.

## BUG-162 — Volet frontend : stock de départ négatif (volet frontend CORRIGÉ)
Cause : `OpeningStockConfirmationModal.tsx` utilisait `<input type="number" min={0}>` et ramenait toute quantité < 0 à 0 à la soumission (`parsed >= 0 ? parsed : 0`).
Corrections :
- Nouveau composant partagé `frontend/src/components/production/SignedIntegerField.tsx` (saisie « - », bouton ±, champ rouge, libellé « Stock négatif »), extrait de la logique BUG-159.
- `CloseSessionModal.tsx` refactoré pour l'utiliser (comportement BUG-159 inchangé, états `rawInputs`/handlers retirés).
- `OpeningStockConfirmationModal.tsx` : champ remplacé par `SignedIntegerField` (150 px, ± inclus), clamp supprimé (la valeur négative est envoyée telle quelle), bandeau non bloquant « Stock négatif : la valeur sera enregistrée telle quelle ». Pré-remplissage `qty_proposed` négatif affiché tel quel. Comportement >= 0 inchangé.
- `OpeningConfirmationManualSection.tsx` : aucune saisie propre (il ne fait que piloter la modale), rien à changer.
Le registre n'a pas été modifié : la ligne BUG-162 passera à CORRIGÉ quand dev-backend aura fini (l'API refuse encore le négatif tant que son volet n'est pas livré).
Vérification manuelle (360 px et bureau, base de test non réelle) : ouvrir la modale « Stock de départ du jour » ; 1) pré-remplissage avec un stock proposé négatif affiché en rouge avec « Stock négatif » ; 2) taper « - » puis « 5 » -> -5, bandeau visible ; 3) bouton ± bascule le signe ; 4) valider : la requête contient `qty: -5` (onglet Réseau) ; 5) valeurs >= 0 : aucun libellé rouge. Rouvrir la clôture de fournée : saisie négative toujours fonctionnelle.
`npx tsc --noEmit` : OK. `npm run build` : voir fin de session.


## BUG-166 — saisie écrasée dans la modale de clôture forcée (CORRIGÉ, 2026-11-11)

- `frontend/src/store/shiftEndStore.ts` : `setPending` ne remplace `pending` que si équipe, session ou lignes `remaining` ont changé (comparaison en profondeur).
- `frontend/src/components/production/CloseSessionModal.tsx` : effet d'initialisation keyé sur `équipe:session` ; second effet qui ne met à jour que les champs jamais saisis quand `quantity_suggested` change.
- `tsc --noEmit` et `npm run build` verts. Procédure manuelle dans la fiche BUG-166 du registre.
