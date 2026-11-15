# Rapport dev-frontend — 2026-11-15

Ticket traité : BUG-301 (adaptations frontend de BUG-289, 290, 291, 292, 293, 295) : CORRIGÉ. Aucun ticket passé à VÉRIFIÉ.
Décisions client appliquées : signe « − » accepté pour le versement du jour ; carte client supprimée.

## Vérifications
- `npx tsc --noEmit` : aucune erreur.
- `npm run build` : OK (seul l'avertissement de taille de chunk, préexistant).
- E2E : aucun spec existant pour ces écrans ; étapes manuelles décrites dans le registre (BUG-301).
- Non vérifié visuellement à 360 / 768 / 1440 px (pas de navigateur lancé) : à contrôler par le testeur.
- `backend/db.sqlite3` non touché ; aucun fichier backend modifié.

## Modifications
- `frontend/src/components/sales/MotifSelect.tsx` (nouveau) : liste « Motif » ; utilisée dans `Sales.tsx` (facture et modal « versement sans commande »). Le modal accepte un entier signé non nul.
- `frontend/src/components/clients/SocialDistributionPanel.tsx` (nouveau, extrait de `Clients.tsx`) : tarif modifiable, « Recalculer les indices », saisie du mérite, libellé INDICE × TARIF + MÉRITE, états chargement / erreur / vide.
- `frontend/src/api/services.ts` : `motif`, `createRepayment(..., motif)`, `distributions.update`, `distributions.refreshIndices`, `Node.monthly_social_contribution`, `Client.cotisation_sociale: string | null` + `effective_cotisation_sociale`.
- `frontend/src/pages/dashboard/Commissions.tsx` : colonnes CARTE retirées (écran, fiche, impression, CSV) ; ligne « Crédit client » si `deduction_debt < 0` ; libellé remise 0,25 % non déduite.
- `frontend/src/pages/dashboard/Nodes.tsx` : champ cotisation sociale mensuelle par boulangerie.
- `frontend/src/pages/dashboard/Clients.tsx` : cotisation facultative à la création, `effective_cotisation_sociale` en lecture seule dans la fiche, panneau de distribution extrait.
- `frontend/src/pages/dashboard/Settings.tsx` : `annual_bonus_rate` retiré.
- `docs/qa/REGISTRE_BUGS.md` : BUG-301 CORRIGÉ avec détail.

## Points à signaler
- `Sales.tsx` portait déjà des modifications non commitées (champ versement signé) ; conservées.
- Le reçu affiche le négatif avec le signe typographique « − » (rendu `toLocaleString('fr-FR')`), pas le tiret « - » ; `ThermalReceipt.tsx` non modifié.
- `Nodes.tsx` utilise encore `apiClient` directement (existant) ; non migré vers `services.ts` ici.
- Le champ `annual_bonus_incorporated` reste dans le type API ; aucune case correspondante n'existait dans l'interface.
