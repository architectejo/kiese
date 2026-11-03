# Rapport — testeur-production, 2026-11-03

## Ticket vérifié
BUG-128 — Calendrier dans une boîte modale pour « Clôture Journalière » (demande client,
`remarque.md` l.394), fiche complète dans `docs/qa/REGISTRE_BUGS.md` (tableau de suivi + section
`### BUG-128`).

Désigné vérificateur car déjà en charge de cet écran sous BUG-120.

## Statut final
**BUG-128 : CORRIGÉ → VÉRIFIÉ** (registre mis à jour : tableau de suivi + fiche détaillée +
note de vérification datée).

## Fichiers concernés
- `frontend/src/components/shared/CalendarPicker.tsx` (nouveau composant, non modifié par moi).
- `frontend/src/pages/dashboard/ClotureJournaliere.tsx` (intégration, non modifiée par moi).
- `docs/qa/REGISTRE_BUGS.md` (mis à jour : statut, tableau de suivi, note de vérification).

Je n'ai modifié aucun code applicatif (conforme CLAUDE.md §7 règle 2).

## Méthode de vérification

### 1. Relecture de code
- `CalendarPicker.tsx` : composant purement UI, entièrement contrôlé (`value`, `onSelect`, `maxDate`),
  aucun appel réseau, aucun `any`. Logique de grille (7 colonnes lundi→dimanche, `startWeekday`,
  `daysInMonth`) et de comparaison de dates ISO (`cell.iso > effectiveMaxDate`, comparaison lexicale
  valide sur un format `AAAA-MM-JJ`) relue et jugée correcte.
- `ClotureJournaliere.tsx` : remplacement de l'`<input type="date">` par un bouton ouvrant une `Modal`
  (composant partagé existant) contenant le `CalendarPicker`. `onSelect` met à jour l'état `date`
  existant et ferme la modale ; le `useEffect` déjà en place depuis BUG-120 recharge le rapport via
  `fetchReport` — aucune nouvelle logique de récupération de données, donc aucun risque de régression
  sur le calcul du rapport lui-même (déjà couvert par BUG-118/119/120).
- `npx tsc --noEmit` (frontend) : aucune erreur.

### 2. Vérification dynamique réelle (pas seulement visuelle)
J'ai lancé localement :
- Backend Django (`manage.py runserver`) et frontend Vite, contre `backend/db.sqlite3` réel.
- Un script Playwright **ad hoc temporaire** (non committé, supprimé après usage — pas un test E2E
  permanent créé pour ce ticket), exécuté avec les projets `bureau` (1440×900) et `pos` (360×740)
  déjà définis dans `e2e/playwright.config.ts`, connecté avec le compte `demo_gerant_k1_e2e`
  (`e2e/fixtures/comptes.ts`).

Scénarios couverts par ce script et captures d'écran associées (captures supprimées après revue,
non committées) :
1. **Navigation mensuelle** : mois précédent → mois suivant ×2 → mois précédent ×2 (retour net au
   mois courant). Octobre 2026 et Janvier 2027 affichés correctement selon la navigation, aucun
   débordement horizontal à 360 px ni à 1440 px.
2. **Distinction visuelle** « aujourd'hui » / « sélectionné » : à l'ouverture (3 novembre 2026, jour
   sélectionné = aujourd'hui), le jour a un fond plein orange (sélection) avec une bordure de la même
   couleur d'accent (aujourd'hui) — les deux styles coexistent proprement sans se chevaucher
   visuellement.
3. **Jours futurs non cliquables** : un jour futur proche (6 novembre, dans le mois affiché) est
   `disabled`, opacité réduite, `cursor: not-allowed`. Le mois de janvier 2027 (entièrement futur) est
   intégralement grisé et non cliquable.
4. **Sélection d'un jour passé réel** (2 novembre 2026, veille) : la modale se ferme immédiatement,
   le bouton affiche bien `02/11/2026`, et **le rapport se recharge réellement pour ce jour** — les
   valeurs affichées (catégories K1 : Pain de 200/500/1000, totaux) changent entre l'état avant
   sélection et après sélection. Pas de rechargement bloqué sur l'ancien jour, pas de désynchronisation
   entre le bouton et le contenu affiché.
5. **Largeur POS 360 px** : modale et grille du calendrier entièrement lisibles, aucune case tronquée,
   aucun défilement horizontal nécessaire, cibles tactiles suffisantes (cases ≥ 36 px, boutons de
   navigation ≥ 32 px).

Résultat : **1 passed** sur chacun des deux projets (`bureau`, `pos`) après correction de deux erreurs
dans mon propre script de vérification (navigation mensuelle mal comptabilisée au premier essai,
sélection d'un jour hors du mois affiché au second essai) — aucune des deux n'était un défaut de
l'application.

## Anomalie d'environnement rencontrée (sans rapport avec BUG-128)
Pour faire fonctionner la vérification dynamique, j'ai dû résoudre deux problèmes d'environnement
local, documentés ici par transparence mais **sans impact sur le verdict BUG-128** :
1. **Conflits de ports** : plusieurs instances de `vite`/`runserver` déjà actives dans l'environnement
   (autres sessions d'agents). J'ai utilisé des ports dédiés (8099/5175) le temps de ma vérification,
   avec un élargissement temporaire de `CORS_ALLOWED_ORIGINS` dans `backend/.env` (fichier local non
   versionné) pour autoriser mon port frontend temporaire — **reverté à sa valeur d'origine
   (`http://localhost:5173,http://127.0.0.1:5173`) une fois la vérification terminée**. Tous les
   processus que j'ai démarrés pour cette vérification ont été arrêtés ; je n'ai touché à aucun
   processus préexistant appartenant à d'autres sessions.
2. **Mot de passe du compte `demo_gerant_k1_e2e` désynchronisé** : le mot de passe en base ne
   correspondait plus à `PASSWORD` (`DemoE2E2026!`) documenté dans `e2e/fixtures/comptes.ts` —
   probablement une dérive locale de `backend/db.sqlite3` entre deux sessions d'agents (ce compte est
   un compte fictif `demo_*`, aucune donnée client réelle concernée — CLAUDE.md §4). Je l'ai remis en
   cohérence avec le mot de passe documenté dans la fixture
   (`User.objects.get(username='demo_gerant_k1_e2e').set_password('DemoE2E2026!')`) pour pouvoir me
   connecter. **Signalé au coordinateur** : si d'autres comptes `demo_*` ont dérivé de la même façon,
   la suite Playwright `e2e/` échouera dès la connexion, pour des raisons sans rapport avec le code
   testé à ce moment-là — à surveiller lors des prochaines exécutions de la suite E2E complète.

## Conclusion
Aucun défaut trouvé sur le comportement du calendrier (BUG-128). La demande client (remarque.md
l.394 : calendrier dans une boîte modale pour consulter les jours passés de la Clôture Journalière)
est correctement implémentée : navigation mensuelle correcte, distinction visuelle
aujourd'hui/sélectionné, jours futurs non cliquables, sélection d'un jour passé qui recharge
effectivement le bon rapport, aucun débordement à 360 px ni à 1440 px, aucun `any`, aucun appel réseau
dans le composant réutilisable `CalendarPicker`.

**BUG-128 passé à `VÉRIFIÉ`** dans `docs/qa/REGISTRE_BUGS.md` (tableau de suivi et fiche détaillée).

## Point laissé ouvert pour le coordinateur
Comme déjà signalé par `dev-frontend`, `ClotureJournaliere.tsx` (écran transverse
Production/Ventes/Trésorerie issu de BUG-120) n'a pas de test E2E permanent dans `e2e/tests/` ni de
testeur de module clairement attribué dans l'organisation actuelle. Je m'en suis chargé ici
ponctuellement (même logique que pour BUG-120), mais si l'écran continue d'évoluer, il vaudrait la
peine d'y attacher un test Playwright permanent (`e2e/tests/11-cloture-journaliere.spec.ts` par
exemple) plutôt que de répéter une vérification manuelle à chaque ticket.
