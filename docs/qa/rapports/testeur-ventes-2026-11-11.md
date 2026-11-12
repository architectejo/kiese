# Rapport testeur-ventes, 2026-11-11

## Vérification BUG-177 (volet ventes : NS / RG) et BUG-161/B2 (blocage `TEAM_NOT_ASSIGNED`)

Fichier de tests : `backend/sales/tests/test_verif_ventes_bug177_bug161b2.py` (35 tests, 7 `@expectedFailure`).
Aucun fichier applicatif modifié ; aucune écriture sur `db.sqlite3` ; ciblage par module de test uniquement.

### Ce qui résiste
- NS CREDIT : dette = `order_total − paiement`, `debt_before/debt_after`, un `DebtMovement ORDER`, stock inchangé, CM 0, prix du catalogue.
- NS puis `cancel()` : dette annulée, mouvements de somme nulle, stock ni restitué ni déduit. NS CASH : aucune dette ni mouvement. NS sans client : sans effet.
- Cohérence BP : chaîne NS crédit -> vente livrée -> RG -> remboursement, `debt_before` = `debt_after` précédent, BP finale 4 500 FC égale à `recompute_client_debt()`. Le recalcul ne ressuscite pas une NS annulée, ne double pas une NS à crédit, est idempotent, ignore RG et NS CASH.
- Plafond : client à plafond atteint, NS acceptée, vente normale suivante 403 (acceptée si payée intégralement).
- RG : paiement 5 000 ignoré, dette inchangée, déstockage unique (pas de doublon à `deliver`), colonne Régularisation de `daily-closure` (hors FACTURE/JR), annulation cohérente.
- Livraison : NS absente de `pending_deliveries` (livreur, facturier, gérant) ; `deliver` livreur -> 400 ; NS exemptée de `cleanup_expired`.
- B2 : 403 `TEAM_NOT_ASSIGNED` pour vente, vente sans client, NS, RG, remboursement et utilisateur HQ avec `node` explicite, sans facture, stock, dette ni mouvement créés ; drapeau inactif inchangé (`team` = équipe de l'utilisateur) ; `Invoice.team` = équipe désignée pour tous les types.
- Frontend (relecture + `tsc`) : voir ci-dessous.

### Défauts ouverts
| Ticket | Gravité | Résumé |
|---|---|---|
| BUG-180 | Majeur | RG refusée par plafond (BP >= plafond, paiement forcé à 0 donc pas de contournement) ; RG livrée comptée dans le déficit du mois et bloquant ensuite les ventes à BP 0 |
| BUG-181 | Majeur | `adjust` sur NS : stock fantôme (`qty_sent` -2) et client crédité de 1 000 FC (NS CASH) ; sur RG : dette de 1 000 FC créée |
| BUG-182 | Mineur | `adjust` porte `request.user.team`, pas l'équipe de service désignée |
| BUG-183 | Mineur, À CLARIFIER | vente rétroactive : équipe du jour courant, pas celle de sa journée |
| BUG-184 | Mineur (frontend) | reçu thermique : `user.team` au lieu de `inv.team` |

Note sur `adjust` non bloqué (point de dev-backend) : jugé acceptable (correction d'une facture passée) ; seule l'attribution d'équipe est incohérente (BUG-182).

### Frontend (`Sales.tsx`, `Clients.tsx`)
- Sélecteur NS : « Le client garde la dette » = CREDIT, « Payé comptant » = CASH ; `payment_type` envoyé = `nsPaymentType` ; `payment_amount: 0` pour NS et RG ; champ versement masqué.
- NS : exclue du compteur « en attente », pas de bouton Imprimer/Livrer, jamais filtrée après 12 h ; Annuler avec message adapté. Aucun reçu pour une NS (à trancher par le client, déjà noté par dev-frontend).
- 403 `TEAM_NOT_ASSIGNED` : création et remboursement affichent le message, rouvrent la désignation (`requestTeamAssignment()`), ne construisent aucun reçu ni élément de file (les mises à jour suivent l'`await` réussi).
- `Clients.tsx` : badge « NS — Non servie ». Aucun `any` dans `Sales.tsx`.
- Écart : BUG-184.

### Verdict
BUG-177 volet ventes : NS conforme aux décisions ; RG partiellement (BUG-180) ; `adjust` sur NS/RG non traité (BUG-181). Statut de la ligne non modifié. BUG-161 B2 volet ventes : blocage conforme, réserves BUG-182/183/184. Temps d'exécution du fichier complet : plusieurs minutes (machine partagée avec d'autres tests).
