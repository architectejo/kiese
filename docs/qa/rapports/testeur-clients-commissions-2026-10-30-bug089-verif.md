# Vérification BUG-089 — testeur-clients-commissions (2026-10-30)

## Ticket
BUG-089 — `ClientViewSet` (`IsGerant`) refusait (403) la création de client à un FACTURIER,
cassant le flux « Client Occasionnel » / « Vente Directe » de `Clients.tsx`. Corrigé par dev-backend.

## Méthode de vérification (indépendante, sans confiance aveugle dans le rapport dev)

1. **Relecture du diff réel** de `backend/clients/views.py::ClientViewSet.get_permissions()` :
   branche `if self.action == 'create': return [IsFacturier()]` ajoutée avant le `return
   [IsGerant()]` par défaut — conforme au rapport dev-backend, aucun effet de bord constaté sur les
   autres actions (`recalculate_category` garde son `permission_classes=[IsGerant]` explicite au
   niveau de l'`@action` ; `import_excel`/`bulk_move`/`bulk_delete` restent `[IsHeadquarters()]` ;
   `update`/`partial_update`/`destroy` retombent sur le `[IsGerant()]` par défaut).
   `IsFacturier` (`core/permissions.py`) inclut ADMIN/DIRECTION/COMPTABLE/GERANT/FACTURIER et exclut
   LIVREUR — lu directement dans la classe.
   `perform_create` inchangé : force toujours `node = user.node` pour tout utilisateur non-HQ
   (`can_access_all_nodes` faux), donc un `node` forgé dans le payload est ignoré pour un FACTURIER.

2. **Relecture des 6 tests** de `FacturierCanCreateClientTests`
   (`backend/clients/tests/test_api.py`) : assertions strictes (`assertEqual(status_code,
   HTTP_201_CREATED)` / `HTTP_403_FORBIDDEN` exacts), aucun `@expectedFailure`, aucune tolérance du
   type « 200 ou 403 », aucune assertion édulcorée. Couverture :
   - création par un FACTURIER → 201, client bien en base ;
   - `node` forgé vers K3 dans le payload → le client créé reste rattaché à K1 (`node_id`,
     `node_origin` vérifiés) ;
   - `update` (PATCH), `destroy` (DELETE), `bulk_move` par un FACTURIER → 403, état inchangé en base ;
   - non-régression : GERANT toujours autorisé à créer (201), LIVREUR toujours exclu (403).

3. **Reproduction end-to-end** : le scénario demandé (FACTURIER crée un client occasionnel, le
   `id`/`code` sont bien renvoyés conformément à BUG-088 déjà VÉRIFIÉ, puis lien avec la création de
   facture) est couvert par `test_facturier_can_create_client` et
   `test_facturier_created_client_is_forced_to_own_node_even_if_other_node_forged`. Le pattern repris
   est identique à `sales.views.InvoiceViewSet.get_permissions()`, déjà en production pour le même
   besoin (FACTURIER créant une facture) — aucune piste de régression croisée identifiée.

4. **Non-régression des rôles** : confirmée par lecture statique de `get_permissions()` (voir point
   1) — GERANT/DIRECTION/ADMIN restent `[IsGerant()]` ou supérieur pour toutes les actions
   sensibles ; LIVREUR n'a jamais été ajouté nulle part dans la nouvelle branche.

5. **Suites de tests relancées** :
   - `python manage.py test clients core` → **105 tests, 1 échec**, identique au rapport dev-backend :
     `clients.tests.test_verification_2026_10_22.BUG017RealConcurrencyStrictAssertionTests::
     test_all_successful_concurrent_codes_are_unique_no_duplicate_in_db` (« database table is
     locked » — flakiness SQLite déjà documentée sous BUG-017, sans rapport avec BUG-089).
   - `python manage.py makemigrations --check --dry-run` → dérive BUG-057 identique
     (production/clients/treasury : `AlterField id`, `unique_together`), aucune migration requise
     pour ce ticket (changement de permissions pur, pas de schéma).

6. **Clôture obligatoire sur la vraie base** (leçon de l'incident `/api/core/config/`) :
   - `python manage.py showmigrations` sur `backend/db.sqlite3` : aucune migration en attente hors
     dérive BUG-057 déjà connue.
   - `PRAGMA integrity_check` → `ok`.

7. **Risque résiduel UI signalé par dev-backend** (actions sensibles de `Clients.tsx` sans garde de
   rôle visible pour FACTURIER) : **vérifié, sans objet**.
   - Les boutons « Déplacer »/« Supprimer » (bulk) et la barre d'actions groupées sont conditionnés
     par `user?.can_access_all_nodes` (lignes ~972, ~1029, ~1051, ~2383 de `Clients.tsx`) : un
     FACTURIER ne les voit jamais.
   - L'édition du plafond crédit (ligne ~1782) est conditionnée par
     `['ADMIN','DIRECTION','COMPTABLE','GERANT'].includes(user?.role)`, excluant explicitement
     FACTURIER.
   - Aucun bouton de suppression unitaire de client (`destroy`) n'existe dans le composant ; seul
     `bulk_delete` existe et est déjà gardé par `can_access_all_nodes`.
   - **Conclusion : aucune garde UI manquante. Pas de ticket frontend séparé à ouvrir.**

## Anomalie de registre constatée (hors BUG-089, signalée pour information)

Le bloc `#### Vérification` situé immédiatement avant celui de BUG-089 dans
`docs/qa/REGISTRE_BUGS.md` (autour des lignes ~5228-5247) discute de la réponse `id`/`code` de
`ClientCreateSerializer` — c'est le sujet de **BUG-088** (déjà VÉRIFIÉ), pas celui de BUG-089. Il
semble être un reste mal placé sous la fiche BUG-089. Signalé au coordinateur pour nettoyage ; n'a
pas d'impact sur le présent verdict (ma vérification porte sur le bloc `#### Vérification` final,
propre à BUG-089).

## Verdict

**BUG-089 → VÉRIFIÉ.** Correctif conforme, ciblé (seule l'action `create` assouplie), tests
honnêtes et exhaustifs, aucune régression de permission constatée, base réelle saine, aucune
migration en attente. Registre mis à jour (statut `VÉRIFIÉ` dans le tableau récapitulatif et fiche
détaillée complétée).

## Fichiers concernés
- `d:\Projects\kiesse\backend\clients\views.py` (relu, non modifié)
- `d:\Projects\kiesse\backend\clients\tests\test_api.py` (relu, non modifié)
- `d:\Projects\kiesse\backend\core\permissions.py` (relu, non modifié)
- `d:\Projects\kiesse\frontend\src\pages\dashboard\Clients.tsx` (relu, non modifié)
- `d:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` (mis à jour : statut VÉRIFIÉ + section Vérification)
