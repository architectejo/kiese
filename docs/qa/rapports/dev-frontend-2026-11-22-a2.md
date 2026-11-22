# dev-frontend 2026-11-22 (a2) - BUG-382 volet « envoi direct de pains »

Statut : BUG-382 -> CORRIGÉ (volet Versement déjà fait, BUG-383).

## Fichiers
- Modifié `frontend/src/api/services.ts` : `DirectSendPayload`, `BreadTransfer.flow/flow_display`, `productionApi.transfers.send`.
- Créé `frontend/src/components/production/DirectSendModal.tsx` (modale : destinataire, quantités par catégorie active avec stock disponible de l'émettrice, note, récapitulatif, anti double clic, erreurs 400 via `getErrorDetail`).
- Créé `frontend/src/components/production/DirectSendsOutgoing.tsx` (envois directs de ma boulangerie en attente, lecture seule).
- Modifié `frontend/src/pages/dashboard/Production.tsx` (+~35 lignes : bouton, message persistant, libellés DIRECT).

## Comportement par rôle
- GERANT / siège-direction : bouton « Envoyer des pains » (pleine largeur, 40 px). Siège sans boulangerie : le serveur répond 400, message affiché. Facturier / livreur : bouton masqué.
- Émettrice : message persistant « N pains envoyés à K2 — nom, en attente de validation par la boulangerie réceptrice. » ; liste « Envois directs en attente de validation » sans aucune action.
- Réceptrice : carte « Envoi direct de K1 », badge À CONFIRMER, saisie des quantités reçues (code existant), bouton « Confirmer la réception » (`confirm_reception`) ; écart -> DISPUTED, traité par `TransferDisputeCard` inchangé.
- Flux REQUEST inchangé (libellés, actions). Historique des confirmés : « Envoi direct de X → Y » pour DIRECT.
- Validation formulaire : entier >= 1 (négatif/décimal refusés), refus si > stock affiché.

## Vérifications
- `npx tsc --noEmit` : 0 erreur. `npm run build` : OK (seul l'avertissement de taille de chunk, préexistant).

## Vérification manuelle attendue
1. Gérant K1 : Production > Transferts > « Envoyer des pains », K2, 40 pains d'une catégorie, note, Vérifier, Confirmer : message vert persistant, stock K1 diminué, carte en attente côté K1.
2. Quantité 0,5 / -3 / > stock : refus avec message. Stock insuffisant côté serveur : message `detail` affiché. Double clic : un seul envoi.
3. Gérant K2 : carte « Envoi direct de K1 », confirmer 40 -> CONFIRMED ; confirmer 38 -> litige.
4. Facturier / livreur : pas de bouton.
5. Largeurs 360, 768, 1440 px : modale entièrement visible sans défilement de page, champs 36 px.

## e2e potentiellement impactés (périmètre B, non modifiés)
- `e2e/tests/13-production-vague2-db.spec.ts`, `e2e/tests/21-cycle-final-cloture-transfert.spec.ts` (parcours transferts : le flux REQUEST est inchangé, libellé « Confirmer la Réception » conservé pour REQUEST ; ajouter un scénario DIRECT).
