# Testeur trésorerie c11 (2026-11-23)

Fichier de tests : `backend/treasury/tests/test_verif_tresorerie_c11_v10.py` : 22 tests, OK (3 expected failures).

## Vérifiés
BUG-929, 930, 931, 932 : VÉRIFIÉS. Facturier forgé, inconnu, inactif, d'un autre nœud ou d'un autre rôle refusés ; clôture confirmée refusée ; billetage '4' accepté, entiers et chaînes mixtes OK, rejets ciblés ; rejeu idempotent.
Non-régression OK : deux facturiers du même nœud, un rapport sans facturier une fois (le second est refusé), rapport avant/pendant clôture non confirmée (compté à la validation), autres jours non bloqués.

## Arbitrage point 1 : équipe du facturier
Les documents ne tranchent pas : « équipes A et B uniquement » (remarque.md l.8), rotation 24 h et gérant libre de changer d'équipe (remarque.md l.470, 488). REST fixe l'équipe du rapport sur `user.team`, modifiable (test REST : même utilisateur, rapports A puis B). Pas de code. Ticket BUG-937 À CLARIFIER ; recommandation : accepter (état actuel), retirer `test_facturier_d_une_autre_equipe_refuse` du c10.

## Point 2 : rôle GERANT
Règle REST : création réservée à IsGerant (ADMIN, DIRECTION, COMPTABLE, GERANT) ; un FACTURIER reçoit 403 ; `facturier` = utilisateur connecté. Les rapports générés prennent `invoice.facturier` (IsFacturier inclut GERANT+). Le push doit donc accepter le GERANT : BUG-935 (Majeur, OUVERT).

## Nouveaux tickets (3)
- BUG-935 : facturier GERANT (ou COMPTABLE/DIRECTION) refusé au push (@expectedFailure x2).
- BUG-936 : facturier désactivé avant la synchro => rapport hors ligne perdu, clôture sous-estimée (@expectedFailure). Le rejeu après désactivation reste idempotent.
- BUG-937 : À CLARIFIER, équipe du facturier.

Observation sans ticket : `'+4'`, `' 4'`, `'4 '` acceptés en billetage (normalisation int, comme DRF).
