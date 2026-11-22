# Rapport dev-frontend (Dev B) - 2026-11-22-c3 : specs e2e perimees, BUG-315/283, premiere execution du spec 35

## Environnement
Base SQLite jetable hors depot (DB_NAME), `migrate` + `seed_kiese` + `e2e/fixtures/seed/` setup1..20 et fix5 (comme le rapport b3), runserver :8000 (limites de login relevees), vite :5173. Chromium 1243 via config Playwright temporaire (executablePath, headless, video off), supprimee ; pas de `playwright install`. Base recreee une fois en cours de route (rejeu propre). A la fin : processus des ports 8000 et 5173 arretes, base et config supprimees, `git checkout -- docs/qa/captures`. Frontend et backend NON modifies ; rien committe ni pousse. Seuls fichiers touches : `e2e/fixtures/cycle.ts`, `e2e/tests/10`, `18`, `19`, `35`.

## 1. Specs 10 « Vente Soldee » et 19 FACTURIER/LIVREUR (flux de livraison)
Cause : specs perimees (BUG-317 a 322). Le bouton de la file est « Confirmer livraison » (« ... partielle » si une quantite servie est reduite) ; la modale « Confirmer la livraison » / « Confirmer & imprimer » n'apparait que si `allow_backdated_sales` est actif ; le reçu « BON DE LIVRAISON » s'ouvre ensuite.
Correction : helper `confirmerLivraison(page, carte?)` dans `fixtures/cycle.ts` (clic « Confirmer livraison », gere la modale optionnelle, attend le recu). Utilise dans 10 (ciblage de la carte par numero de reçu) et 19 (3 endroits). Verifications du recu (RCCM, Id.Nat, N° Impot, BP, « Solde arrete ce jour », total) inchangees.
Resultat reel : 19 = 6/6 (pos, tablette, bureau ; facturier et livreur). 10 « Vente Soldee » = OK.
Aleas rencontres sur ce test (corriges cote test) : sur base neuve, la liste de suggestions client n'apparaissait pas parfois (1re frappe perdue autour de la modale « Stock de depart ») ou etait re-rendue (element detache) -> saisie du code et clic rejoues dans un `toPass`.

## 2. 10 « BUG-315 » : TEST perime / dependant de l'etat, pas un defaut applicatif
Le panneau affichait, apres « Enregistrer la fournee » : « Session de production cloturee pour l'Equipe B le 2026-11-22 a la boulangerie B2 - declaration impossible » (capture du test). Cause : le test precedent du meme fichier (« Cloture de fournee », meme compte zz_e301_gerant, meme jour, equipe B) a cloture l'equipe B ; la regle serveur « une fournee par equipe et par jour, plus de redeclaration apres cloture » refuse correctement, et l'interface affiche bien le `detail`. Pas de defaut frontend, pas de defaut backend.
Correction du test : essaie l'equipe B puis A (premiere libre), attend `batch-objective` ou le message « declaration impossible », verifie la ligne `Eq.<equipe>` dans l'historique sans rechargement. Resultat : OK sur base neuve. Limite documentee dans le spec : les deux tests de fournee ne sont rejouables qu'une fois par jour et par base (une 2e execution sur la meme base echoue sur le test « Cloture de fournee » : equipes B cloturee et A occupee/cloturee) ; base neuve pour rejouer.

## 3. 18 « BUG-283 »
Cause : base neuve, `Config.allow_backdated_sales = False` -> 400 sur `invoice_date` passee. Le test active le reglage par l'API de config avec le compte `zz_demo_direction` (ADMIN/DIRECTION seulement, BUG-083 : le facturier/gerant ne peuvent pas), puis restaure la valeur initiale dans un `finally`. Resultat reel sur base neuve : 18 = BUG-282, BUG-242, BUG-276, BUG-283 reussis ; BUG-281 ignore (K3 en rotation requis, inchange). Rejouable.

## 4. 35 consommables direction (premiere execution)
Premiere execution : 5/5 sur bureau sans aucune correction du frontend. Rejeu pos + tablette : un echec de test (« gerant : Inventaire Physique », 2e passage du jour) : le bouton « Enregistrer le commentaire » est desactive quand le texte est inchange (comportement voulu de `PhysicalInventoryForm`) ; commentaire rendu unique par execution (`Date.now()`). Resultat final : 15/15 (pos, tablette, bureau), puis 5/5 de nouveau bureau sur base neuve.
Ajout BUG-388 : test « direction : approvisionner le stock direction puis envoyer une partie a une boulangerie » : formulaire `supply-form` visible, quantite vide -> « Quantite invalide » sans ecriture, entree de 2,5 (prix 1 000 FC, note) -> statut « ajoute(s) au stock direction », stock direction +2,5 ; envoi de 1 a K1 -> stock direction -1 et K1 +1 (somme nulle), pas de debordement horizontal. Reussi sur les trois largeurs.

## Resultats REELS (projet bureau sauf mention)
- 10 : sur base neuve, 5/5 (Vente Soldee, Vente sans commission, Cloture de fournee, BUG-315, Journal de Caisse). Un rejeu sur la meme base : Cloture de fournee et BUG-315 echouent (regle une fournee par equipe/jour, voir 2), les 3 autres passent.
- 18 : 4 reussis, 1 ignore (BUG-281).
- 19 : 6/6 (pos, tablette, bureau).
- 35 : 15/15 (pos, tablette, bureau).
- `tsc --noEmit` du dossier e2e : erreur preexistante « Cannot find type definition file for 'node' » (types non installes dans e2e), non liee ; les specs sont executees par Playwright (transpilation) sans erreur.

## Points a signaler
- Aucun defaut applicatif trouve, aucun ticket ouvert.
- Contradiction de libelle inchangee : CLAUDE.md parle encore de « Cloture & Caisse » (ecrans « Caisse » et « Cloture Journaliere »).
- 21/22/24 non rejoues dans cette session (non demandes) ; ils exigent une base neuve.
