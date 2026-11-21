# Rapport testeur-e2e (Dev C) - 2026-11-21 - verification croisee du commit d328126

## Environnement : exécution impossible
`e2e/node_modules` absent, aucun navigateur Playwright (`%LOCALAPPDATA%\ms-playwright` absent, `/opt/pw-browsers` absent).
`npx playwright --version` a telecharge puis affiche 1.65.1 (cache npx seulement). `playwright install` non lance.
Le rapport de B signale en outre que le headless-shell est bloque par l'antivirus du poste. => AUCUN test rejoue ; verification par relecture.

## BUG-148 (05-production.spec.ts) - relecture
- Pas de `waitForTimeout` ni `.skip` : attente de `GET /api/production/sessions/?date=` puis `networkidle`, puis `formulaire.or(enCours)`.
- Cause : la modale n'est plus en cause (handler `addLocatorHandler` « Plus tard » present dans helpers.ts l.16) ; les causes citees par B
  (non idempotence, course au chargement du panneau) sont plausibles et ne masquent pas de defaut applicatif evident. La remarque UX
  (formulaire affiche avant chargement) est signalee a A sans ticket : acceptable mais a tracer si A ne la traite pas.
- Reserves : (1) au rejeu du jour la branche `if` n'est pas executee : le chemin « consommables decimaux + Montant a atteindre » n'est teste
  qu'a la 1re execution ; (2) `networkidle` est deconseille par Playwright (fragile avec HMR/polling) ; (3) timeout de login 15 -> 30 s dans
  un fichier partage : masque un demarrage lent, acceptable pour Vite a froid.
- Les « 20/20 » de B n'ont pas pu etre recoupes.

## Spec 32 (Clients 360 px) - relecture
- Role : gerant K4 `zz_clients_gerant` (setup1.py : GERANT K4) : correct.
- Lecture seule, sans attente fixe : bon.
- MAIS ne couvre pas 360 px par construction : aucun `test.use({viewport})`, aucune assertion de largeur, aucune verification
  d'absence de defilement horizontal (`scrollWidth <= clientWidth`, pourtant utilise dans 04, 12, 13), aucune verification d'atteignabilite
  des boutons (oeil/historique) dans le viewport. La largeur POS ne depend que du `--project=pos`. Le test passe donc aussi bien a 1440 px sans rien prouver sur 360 px.
  Recommandation (a faire par B) : ajouter l'assertion scrollWidth sur le body apres chargement de la liste et `toBeInViewport` sur les boutons d'action.
- Le test conditionnel `if (await histo.count())` peut sauter silencieusement la verification de l'historique.

## Verdict
BUG-148 : NON passe a `VERIFIE` (non rejoue). Statut maintenu `CORRIGE`, note ajoutee au registre.
Spec 32 : insuffisante pour valoir « parcours Clients 360 px » tant que les assertions de largeur ne sont pas ajoutees.
A rejouer sur un poste avec navigateur : `npx playwright test 05-production --project=pos --repeat-each=5` puis `32`.
