# Rapport testeur-permissions — vague 3 sur base réelle (2026-11-12)

Cible : backend `http://127.0.0.1:8000` sur `db.sqlite3` (non relancé). Aucun migrate/SQL, `reset-data` jamais appelé, aucun git, aucun des 678 clients ni compte réel modifié, code applicatif intact. Mots de passe et jetons jamais affichés. Comptes `zz_perm_*` réutilisés (zz_perm_admin_k6 reste désactivé).

## Résultats par ticket (rejoués en réel avec les comptes zz_perm_*)
| Ticket | Résultat | Détail |
|---|---|---|
| BUG-247 | VÉRIFIÉ | DIRECTION : PATCH soi `role=ADMIN`/`node`/`is_active` refusé ; `is_superuser`/`is_staff` ignorés (200, inchangés) ; POST ADMIN refusé (aucun compte créé) ; reset/PATCH/DELETE d'un ADMIN = 403. Autres rôles ne se promeuvent pas. Non-régression : ADMIN crée/réinitialise ADMIN, DIRECTION crée un FACTURIER. |
| BUG-248 | VÉRIFIÉ | Mot de passe temporaire aléatoire (différent à chaque reset), jamais l'identifiant, absent de `detail` et du journal ; ancien mot de passe/identifiant refusés, temporaire accepté ; reset 403 pour gérant/facturier/livreur/comptable. Reste proposé : changement forcé à la première connexion. |
| BUG-249 | VÉRIFIÉ | Gérant K5 : `bulk_create_month` node=K6 refusé, cotisation pour client K6 refusée (node K5 ou K6), aucune ligne créée ; cotisation légitime K5 = 201 ; facturier/livreur 403. |
| BUG-250 | VÉRIFIÉ | Facturier : plafond 9 999 999 / taux 0,30 / node K6 à la création -> 50 000 / 0,25 / K5 ; PATCH plafond 403. Gérant : bornes (99 999 999, 0,50 -> 400), plafond 70 000 -> 200. |
| BUG-251 | VÉRIFIÉ | Facturier/livreur : PATCH/PUT/DELETE/POST stocks = 403, lecture 200 ; gérant : `quantity` en lecture seule, POST node=K6 sans effet ; détail étranger 404. |
| BUG-252 | VÉRIFIÉ | Alerte CLOUD de test : livreur/facturier/gérant DELETE et mark_read = 403, alerte intacte ; siège mark_read 200, ADMIN supprime 204. `mark_all_read` : test Django seulement. |
| BUG-254 | VÉRIFIÉ | Sans `distribution` -> 400 (plus de 500) ; ligne légitime K6 201 ; distribution/client d'un autre nœud refusés ; facturier 403. |
| BUG-255 | VÉRIFIÉ (avec réserve) | Config anonyme = `{"on_line": true}`, authentifiée complète, `bread-prices` public. **Le backend réel tourne en DEBUG=True** : schéma/Swagger/ReDoc restent publics (200 anonyme), 401 hors DEBUG couvert par test Django seulement. Voir **BUG-279**. |
| BUG-256 | VÉRIFIÉ (test Django) | `cotisation_sociale__gt=0` confirmé par `Bug256BulkCreateMonthTests` ; non rejoué en réel sur son nœud (écriture sur clients réels). |
| BUG-265 | VÉRIFIÉ | COMPTABLE et GERANT 403 sur `mark_paid`/`set_manuel` (UUID nul et commission réelle) ; DIRECTION 200/404. |
| BUG-263 | VÉRIFIÉ | Période fictive K5 12/2031 : PATCH/DELETE commission payée 400, `set_manuel` sur payée 400, DELETE période avec paiement 400, `is_closed` non écrivable, PATCH après clôture 400, montants inchangés, gérant K6 404. |
| BUG-259 | VÉRIFIÉ | `current_debt`/`total_breads_received` ignorés en PATCH et PUT (gérant et ADMIN). |
| BUG-277 | Test OK, statut non modifié | Classe `DisputedTransferBlocksClosureTests` : 6 tests OK en base de test. Rejeu en réel non fait (écriture sur la vraie chaîne de caisse) ; passage à VÉRIFIÉ laissé à testeur-tresorerie. |
| BUG-253 | À CLARIFIER | Non touché. |

## Tests
- Nouveau `backend/core/tests/test_vague3_db_permissions.py` : matrice route x méthode x rôle (anonyme + 6 rôles) sur core/users (+reset_password), clients, caisse sociale, commissions (mark_paid, set_manuel, PATCH, DELETE), production/stocks, notifications, config ; lectures par rôle ; config anonyme ; auto-PATCH `is_superuser`/`is_staff`. Résultat : OK (la matrice d'écriture passe ; les attentes de lecture ont été alignées sur le code : liste des utilisateurs = siège, cotisations = gérant+).
- `test_vague2_db_permissions.py` : plus aucun `@expectedFailure` ; docstring mise à jour. Avec `test_vague2_corrections_permissions.py` : OK.
- Lot exécuté (24 tests, 258 s, un processus à la fois) : seuls 5 échecs, tous dus à mes attentes de lecture erronées, corrigées puis rejouées OK.

## Nouveau ticket
- **BUG-279** (Mineur, OUVERT) : backend réel en `DEBUG=True` (page technique Django, schéma public).

## Effets de bord sur la base réelle
Comptes fictifs `zz_perm_ok_fac3`, `zz_perm_adm_made3` (désactivé), `zz_perm_reset3` (désactivé) ; clients `ZZPERM FacCreate3`, contributions 2033 (K5 x1-2), ligne de distribution K6 2031, période K5 12/2031 avec une commission payée et clôturée (non supprimable par conception, BUG-263). Alerte CLOUD de test supprimée. Aucune donnée réelle touchée.
