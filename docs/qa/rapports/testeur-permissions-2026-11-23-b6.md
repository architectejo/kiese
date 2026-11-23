# testeur-permissions b6 (2026-11-23)

Fichier de tests : `backend/core/tests/test_verif_permissions_b5_v5.py` (37 tests, 8 `@expectedFailure`, reste vert ; log `$TEMP/b6.log`). SQLite conservé, code applicatif non modifié.

## Vérifiés
- BUG-872 VÉRIFIÉ : DELETE d'une distribution clôturée refusé (400 pour gérant, direction, admin ; 403 facturier/livreur ; 404 autre nœud). Distribution et lignes intactes. Distribution ouverte toujours supprimable. Réouverture refusée.
- BUG-873 VÉRIFIÉ : `me` PATCH corps `[]`, `[1]`, `5`, `"x"` -> 400 pour 4 rôles ; mots de passe non textuels -> 400 et mot de passe inchangé ; élévation `role`/`node`/`is_superuser` toujours ignorée.
- BUG-874 VÉRIFIÉ : l'émettrice ne confirme pas, ne crée pas de transfert CONFIRMED ou avec `quantity_received`, ne crée pas ni ne modifie de ligne reçue ; la réceptrice le peut ; un 3e nœud est rejeté ; pas de régression d'état.
- Registre et rapport d17 cohérents.

## Nouveaux tickets (tests expectedFailure)
- BUG-886 (mineur) : `reset-data` (corps non objet, `confirm_phrase` non texte) et `chat/conversations/direct/` (corps non objet) -> 500.
- BUG-887 (majeur) : push sync d'une ligne de distribution clôturée (modification et création) accepté, contourne BUG-752/872.
- BUG-888 (majeur) : push sync `BreadTransfer` : DISPUTED accepté de l'émettrice, RESPONDED accepté de la réceptrice.
- BUG-889 (mineur) : création d'une `ClientCommission` dans une période clôturée acceptée.

## Contrôles verts (sans ticket)
- Corps non objet et types inattendus sur users, nodes, config, bread-prices, expense-categories, colis, clients, contributions, distributions, lignes, bulk_*, refresh_indices, change-password, login, refresh, logout, sync push/handshake : aucun 500.
- Commission payée ou période clôturée : PATCH/DELETE refusés ; `is_paid` non inscriptible à la création ; gérant/facturier/livreur refusés ; DELETE sur cashbook/closures/journal interdit ; client d'un autre nœud 404.
- Push sync : ligne ou contribution d'un autre nœud refusée, réouverture de distribution par push ignorée.
