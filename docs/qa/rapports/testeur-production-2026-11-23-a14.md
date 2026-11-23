# testeur-production a14 (cycle 15) - 2026-11-23

Fichier : `backend/production/tests/test_verif_production_a14_v14.py` (33 tests, banc 3 postes + cloud de a13). Résultat : OK, 4 échecs attendus (`@expectedFailure`). Log : `%TEMP%/a14.log`.

## Vérifiés : BUG-974 à 980
Rejeu du même pull x5 à chaque étape (RESPONDED / DISPUTED / CONFIRMED) : stocks, transferts, lignes, alertes inchangés. ALIGN_ON_RECEIVED et ALIGN_ON_SENT par l'émettrice (REST local) et par le siège (cloud) : somme du groupe revient à 100, mono et multi-lignes, K1 +2 / K2 +2 attribués au bon poste, aucun double crédit si K2 recompte pendant que le siège résout. Confirmation par le siège (100, puis 98 avec recomptage local de K2) : somme nulle, clôture de K2 débloquée. Alertes uniques par poste après rejeux (Demande de Pains, Pains Envoyés, Litige, Litige résolu, Demande Refusée), aucune alerte chez K3. Poste réinstallé (K2 et K1) : aucun mouvement de stock fantôme, litige visible et clôture bloquée tant que non résolu. Poste hors ligne 45 j (K1 et K2) : résolution et stock rattrapés. Réponse de pull perdue : `open_transfers` redéclaré puis rattrapé ; réponse de push perdue : rejeu sans doublon. `open_transfers` forgé (ids d'autres nœuds, types hostiles, 5000 ids, absent) : aucune fuite (K3 ne reçoit rien, filtre émettrice/réceptrice conservé), aucune erreur serveur, borne 1000. Migration 0003 sur base existante : additive, données conservées, cascade OK. Pull sans `node_code` (ancien cloud) : aucun effet, aucun plantage.

Observation (sans ticket) : stock négatif possible par résolution (K2 déclare 105 reçus pour 100 envoyés, ALIGN_ON_RECEIVED : K1 à -5, somme du groupe restant nulle). Même comportement qu'en REST.

## Les deux points À CLARIFIER de d39
Analyse d'après CLAUDE.md 5.4 (« somme nulle au niveau du groupe ») : ce sont des défauts, la somme du groupe n'est plus nulle (-100 pour le point 1, +100 pour le point 2). Tickets Majeur : BUG-989 (siège confirme pour une réceptrice qui n'a pas vu l'envoi), BUG-990 (siège répond à une PENDING, émettrice non débitée).

## Nouveaux défauts
- BUG-989, BUG-990 : voir ci-dessus.
- BUG-991 : réponse de l'émettrice avec quantité ajustée (80 sur 100) : ligne rejetée au push, puis le delta de d39 réécrit la ligne locale à 100 et débite K1 de 20 de plus ; K2 voit 100 annoncés ; faux litige, somme 80.
- BUG-992 : K1 refuse localement pendant que le siège répond au cloud : divergence permanente (K1 CANCELLED non synchronisé à vie, cloud RESPONDED), somme du groupe fausse après validation de K2.

Total : 4 nouveaux tickets (BUG-989 à 992). 7 tickets vérifiés (974 à 980).
Non reproduit (OK) : concurrence K2 confirme 98 en local / siège confirme 100 au cloud : convergence.
