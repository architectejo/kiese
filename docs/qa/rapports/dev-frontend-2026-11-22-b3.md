# Rapport dev-frontend (Dev B) - 2026-11-22-b3 : e2e adaptes a « Caisse » / « Clôture Journalière » + envoi direct de pains

## Environnement
Base SQLite jetable hors depot (migrate + seed_kiese + `e2e/fixtures/seed/` setup1..20 et fix5 ; seed10/13/14/seed4 non rejoues), runserver :8000 (limites de login relevees via variables d'environnement), vite :5173. Chromium 1243 via config Playwright temporaire (executablePath, headless, video off, outputDir hors depot), supprimee. Pas de `playwright install`. Processus arretes (PID du port 8000 et 5173 uniquement), base supprimee. La base a ete recreee 3 fois pour rejouer les parcours dependants de l'etat (19/21/22/24). Les captures versionnees de `docs/qa/captures/` ecrasees par les specs ont ete restaurees (`git checkout`). Frontend et backend non modifies. Rien committe ni pousse.

## Modifications (dossier e2e/ uniquement)
- `06` : titre de page « Caisse » (h1 ; un h2 d'en-tete du meme nom existe, d'ou `level: 1`) ; pour le gerant, absence de « Saisir le nombre de coupures » sur /treasury ; commentaires et titre du fixme mis a jour.
- `18` : BUG-242 verifie /treasury ET /cloture-journaliere (refus facturier/livreur, zero appel /api/treasury/), gerant : Caisse sans billetage, Clôture Journalière avec billetage ; BUG-276 (billetage hors borne) sur /cloture-journaliere.
- `19` : menu sans lien /cloture-journaliere et route refusee pour facturier et livreur.
- `21` : `allerTreso(page, route = '/cloture-journaliere')` ; le test « Livre de caisse » utilise `/treasury`.
- `22`, `24` : /cloture-journaliere ; `24` : regex heuristique « 15 000 FC puis SOLDE » precisee (ancree sur « TOTAL CASH DU JOUR ») car la page Clôture Journalière intercale « TOTAL CRÉDIT DU JOUR » (faux positif avec 15 000 FC de credit).
- `fixtures/cycle.ts` : `login()` purge systematiquement la session avant d'ouvrir /login (sinon, session ouverte, /login redirige vers /dashboard apres un instant, le champ disparait et la modale « Stock de depart » masque la page : echec observe sur 21 « BUG-277 » etape 4).
- `10`, `17`, `23` : aucune modification necessaire (le Journal de Caisse reste sur /treasury ; 17 liste deja les deux routes ; 23 ne visite aucune route de tresorerie).
- Nouveau `34-envoi-direct-pains-dev-b.spec.ts` (voir ci-dessous).

## Nouveau test 34 : envoi direct de pains (remarque.md l.450, Production §3.3)
Scenario 1 (K4 -> K3, comptes zz_clients_gerant et zz_prod_gerant_k3, prerequis stock K4 du seed setup9) : onglet Transferts, bouton « Envoyer des pains », modale entierement dans la fenetre (verifie a 360, 768, 1440, 1920 px, pas de debordement horizontal) ; refus sans destinataire ; emettrice absente de la liste ; quantites decimale/negative bloquees par le champ numerique ; stock insuffisant refuse ; recapitulatif puis envoi ; message de succes ; carte « Envois directs en attente de validation » ; API : stock K4 -QTE tout de suite, transfert `flow=DIRECT`, `RESPONDED`, stock K3 inchange ; cote K3 : carte « Envoi direct de … / À CONFIRMER / Envoyé spontanément », confirmation, API : `CONFIRMED`, stock K3 +QTE, stock K4 inchange (somme nulle). Note unique par execution (rejouable).
Scenario 2 : facturier -> POST `transfers/send/` = 403 avec `detail` ; pas de bouton « Envoyer des pains ».
Les decimaux/negatifs sont bloques par la validation native du champ (`min=1 step=1`) et non par le message du composant : le test verifie `checkValidity() === false` et l'absence de recapitulatif.

## Resultats REELS (projet bureau sauf mention)
Reussis :
- 05 (fournee) ; son test de transfert reste `skip` dans le fichier.
- 06 : 2 reussis (bureau et pos), 2 `fixme` ignores.
- 17 : 7/7. 18 : BUG-282, BUG-242 (nouveau), BUG-276 reussis. 10 : Clôture de fournee, Vente sans commission, Journal de Caisse (BUG-091/105) reussis.
- 21 : 3/3 (cloture avec billetage, BUG-277 litige puis resolution et inscription, livre de caisse) sur base neuve. 22 : reussi. 24 : BUG-298 et BUG-299 reussis (apres l'ajustement de regex).
- 23 : 2/2. 31 : 16/16. 32 : 2/2 (bureau et pos). 33 : 2/2 (bureau). 34 : 2/2 sur bureau, pos, tablette, tv.

Echoues, non lies a cette tache (constates avant et apres mes modifications) :
- 10 « Vente Soldee (BUG-107/111) », 19 FACTURIER K4 et LIVREUR K4 : le test cherche un bouton « Imprimer le reçu » dans la file de livraison ; l'ecran propose desormais « Confirmer livraison » / « Confirmer livraison partielle » (PendingDeliveryActions.tsx, BUG-317 a 322). Specs perimees. Le volet routes/menu de 19, execute avant, passe.
- 10 « BUG-315 » : `batch-objective` absent apres declaration d'une fournee (non investigue ; peut dependre de l'etat de la base ou de la regle « une fournee par equipe et par jour »).
- 18 « BUG-283 » : creation par API d'une facture retro-datee refusee (`Config.allow_backdated_sales`, 400), c'est le reglage de la base neuve.
- 18 « BUG-281 » : ignore (K3 en rotation requis).
Premiers essais echoues dus a moi puis corriges : erreur de parametre par defaut dans 21 ; assertion de 34 trop large (litige d'un autre test sur K3) supprimee (l'etat CONFIRMED par API suffit) ; 24 (voir plus haut). 21/22/24 echouent si 21 est rejoue sur une base deja polluee par une execution precedente (cash du jour de K4 cumule) : prevoir base neuve ou `E2E_SKIP_SETUP`.

## Points a signaler
- Aucun defaut applicatif frontend trouve par ces tests ; aucun ticket ouvert.
- Les specs 10/19 a reecrire pour le nouveau bouton de livraison ; 18 BUG-283 a adapter a `allow_backdated_sales` (activer le reglage dans la preparation ou changer de scenario).
- Contradiction de libelle : le CLAUDE.md et plusieurs commentaires parlent encore de « Clôture & Caisse ».
- Interface : sur la page Clôture Journalière, la modale « Stock de depart » (Équipe A/B) se rouvre apres chaque connexion en rotation et bloque les parcours qui n'utilisent pas `seConnecter` (le helper de `fixtures/helpers.ts` gere « Plus tard », celui de `fixtures/cycle.ts` doit appeler `later(page)`).
