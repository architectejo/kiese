# Rapport testeur-clients-commissions - 2026-11-21 (dev B) - verification BUG-400

Verdict : **BUG-400 VERIFIE** (aucun ticket BUG-401..409 ouvert).

## Tests ajoutes
`backend/clients/tests/test_verif_bug400_testeur_clients_commissions.py` : mois limites (dec./janv., 2000-01, 9999-12, futur),
formats invalides (jamais 500), UUID inconnu / non-UUID, autre noeud (404, pas de fuite), roles (gerant/comptable/direction/admin 200 ;
facturier/livreur 403 ; anonyme 401 ; POST 405), statuts NOT_SERVED/PENDING/CANCELLED listes mais exclus des totaux,
achat/depot/retrait/remboursement/ajustement, coherence BP debut/fin = variation, BP negatif (epargne), Decimal a 2 decimales
(chaines), tri deterministe, limite de mois a 23h50/00h10 (suit invoice_date), available_months (desc, unique, mois courant),
isolation entre clients, nombre de requetes constant (3 vs 33 operations).

## Resultats
`manage.py test clients commissions` : 201 tests OK. `npx tsc --noEmit` : sans erreur.

## Revue frontend (ClientHistoryModal.tsx, Commissions.tsx, Clients.tsx)
- Pas de `any`, types `ClientHistory` dans services.ts, appel via `clientsApi.history`.
- Erreur (dont 403) affichee via `getErrorDetail`, etat vide, chargement, annulation des requetes obsoletes : OK.
- Format `12 500 FC` (espaces simples, arrondi entier), negatifs OK.
- Clic masque pour FACTURIER/LIVREUR (Commissions et Clients) : OK, coherent avec l'API (403).
- Navigation par mois via available_months (jamais de mois inexistant).

## Remarques mineures (non bloquantes, pas de ticket)
- Apres une erreur sur changement de mois, `data` precedent reste en memoire mais est masque : OK.
- Totaux sur DELIVERED seuls : les ventes en attente n'apparaissent pas dans "Commande" (choix documente).
- Montants arrondis au franc a l'affichage, centimes ignores (conforme CLAUDE.md).

## Non verifiable sans navigateur
Rendu reel, largeur 360 px (defilement horizontal, empilement), accessibilite clavier de la modale, `toLocaleString('fr-FR')` des dates
(fuseau du navigateur : l'heure affichee suit le poste, la date de groupement suit invoice_date), comportement du clic dans le tableau
Commissions (stopPropagation) a confirmer visuellement.
