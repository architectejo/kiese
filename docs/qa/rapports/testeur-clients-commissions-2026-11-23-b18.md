# Testeur clients/commissions, ronde b18 (2026-11-23)

Fichiers : `backend/clients/tests/test_clients_v14.py` (22 tests), `backend/commissions/tests/test_commissions_v5.py` (21 tests). Résultat : 43 tests, OK, 2 `@expectedFailure`. Log : `$TEMP/b18.log`. Code applicatif non modifié.

## Vérifications
- BUG-999 VÉRIFIÉ : désactivation vue hors ligne puis facturation refusée (400), réactivation redescendue, inactif d'un autre nœud inconnu non créé, inactif local recréé inactif, ancien cloud sans `is_active`, valeurs hostiles ignorées, rejeu, pull initial et SIEGE inchangés, édition locale non poussée (BUG-952) préservée puis appliquée après push. Résiduel -> BUG-1008.
- BUG-1004 VÉRIFIÉ : déplacement vu par les 3 postes (K1, K2, K3), rejeu sans conflit, conflit de code (journal une seule fois, ancien état gardé), conflit dans un même lot, nœud inconnu, code vide/trop long ignoré, édition locale non poussée, `recalculate_category` avance `updated_at`.
- BUG-1005 VÉRIFIÉ : 3 boulangeries x 6 ordres séquentiels et 6 ordres imbriqués x 3 attributions d'UUID, `created_at` figé : toujours une seule retenue (10 000 / 1 500), cartes 700 par boulangerie, régénération stable. Risque résiduel (deux générations strictement simultanées cèdent toutes deux) : accepté, aucune voie réaliste (PostgreSQL verrouille le client, BUG-782 ; SQLite sérialise les écritures) ; état résultant visible et réparable à la main (test de documentation). En revanche une retenue peut être perdue par suppression de la ligne qui retient -> BUG-1009.

## Balayage final
CM 0,25 / 0,30, retenues, remise (0,25 % affichée), net, net négatif non payable, VENTE SOLDE/exonérée/épargne sans CM, totaux verticaux `summary` + `payroll_listing` (valeurs à la main), période close (génération, édition, suppression, set_manuel refusés), mark_paid unique et gel à la régénération, permissions croisées (facturier/livreur/gérant/comptable/anonyme), throttling du login (6e tentative 429, variantes de casse/espaces, comptes indépendants, pas de fuite de secret). Caisse sociale et imports : suites existantes inchangées, non rejouées dans cette ronde.

## Tickets ouverts
- BUG-1008 (Majeur) : pull incrémental paginé, les inactifs sont perdus dès la page 2 (`Q(is_active=False)` conditionné à l'absence de `client_after_id`).
- BUG-1009 (Mineur) : suppression de la ligne de commission qui retient la dette/cotisation, régénération : retenue perdue sans alerte.

## Remarques
- CLAUDE.md 5.3 est en retard sur le code validé (remise annuelle supprimée BUG-295, carte, REMISE 0,25 % non déduite) : à mettre à jour par le coordinateur.
- `summary` renvoie des chaînes sans zéros de fin sous SQLite (`35000` au lieu de `35000.00`) : valeur exacte, formatage à la charge du frontend.
- Les tests sont lents (~290 s pour les deux fichiers : hachage des mots de passe dans `make_user`).
