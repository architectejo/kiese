# testeur-permissions — Régression droits d'accès sur 528875c — 2026-11-19

Base isolée : `DB_NAME` dans le dossier temporaire (jamais `backend/db.sqlite3`), venv `backend\.venv`. Code applicatif non modifié. Données fictives.

## Verdict
**Régression NON propre : 2 écarts ouverts.** BUG-313 (bloquant, fuite/réaffectation inter-boulangeries) et BUG-314 (mineur). Aucune élévation de droits par champs forgés (`role`, `node`, `is_superuser`, `is_staff`, ...) trouvée. Aucune fuite de `objective_fc`, `progress_*` ni `motif` entre boulangeries.

## Tests ajoutés
`backend/core/tests/test_permissions_regression_2026_11_19.py` : 40 tests, dont 3 `@expectedFailure` (BUG-313 x2 variantes, BUG-314). Résultat : `OK (expected failures=3)`.

| Classe | Contenu |
|---|---|
| `Matrix` | 31 routes x (anonyme + 6 rôles) : anonyme 401, rôle non autorisé 403, rôle autorisé jamais 401/403, aucun 5xx |
| `SalesIsolation` | paiement négatif + motif, versement sans commande, `node` forgé, livreur refusé, motif invisible hors nœud (liste, détail, reçu), PATCH `motif` refusé, deliver/cancel/adjust d'une facture étrangère |
| `ClientsIsolation` | distributions (GET/PATCH/DELETE, `refresh_indices`, `auto_populate_lines`), lignes, cotisations, `bulk_create_month`, `cotisation_sociale`, `credit_limit` par facturier |
| `NodesSocial` | `monthly_social_contribution` : écriture réservée ADMIN/DIRECTION (PATCH/PUT/DELETE 403 pour les 4 autres rôles) |
| `ProductionIsolation` | sessions par sacs, PATCH, `objective_fc`/`progress_*`, `daily-closure`, `shift-end-status`, `close` étranger, valeurs extrêmes de `flour_sacks_used` |
| `Escalation` | PATCH de soi-même avec `role`/`node`/`is_superuser`/`is_staff`/`groups`..., création de comptes privilégiés, DIRECTION sur ADMIN, champs forgés sur facture, journal d'activité et Config fermés aux rôles bas |

## Matrice observée (attendu = observé, sauf mention)
Légende : A = anonyme (401 partout), AD/DI/CO/GE/FA/LI = ADMIN/DIRECTION/COMPTABLE/GERANT/FACTURIER/LIVREUR. `ok` = autorisé, `403` = refusé.

| Route | Méthode | Autorisés |
|---|---|---|
| `sales/invoices/` (versement négatif + motif, versement sans commande) | POST | AD DI CO GE FA ok ; LI 403 |
| `sales/invoices/` | GET | tous les rôles ok |
| `clients/distributions/`, `<id>/` | GET | AD DI CO GE ok ; FA LI 403 |
| `clients/distributions/<id>/refresh_indices/`, `auto_populate_lines/` | POST | idem |
| `clients/distributions/<id>/` | PATCH, DELETE | idem |
| `clients/distribution-lines/` | GET, PATCH | idem |
| `clients/contributions/` ; `bulk_create_month` ; `<id>/toggle_paid/` | GET, POST | idem |
| `clients/clients/<id>/` (`cotisation_sociale`) | PATCH | idem |
| `core/nodes/`, `<id>/` | GET | tous ok |
| `core/nodes/<id>/` (`monthly_social_contribution`), `core/nodes/` | PATCH, POST | AD DI ok ; CO GE FA LI 403 |
| `production/sessions/` | GET | tous ok |
| `production/sessions/` (par sacs), `<id>/` PATCH, `<id>/close/`, DELETE | POST, PATCH, DELETE | AD DI CO GE ok ; FA LI 403 |
| `production/sessions/reconciliation/` | GET | AD DI CO GE ok ; FA LI 403 (réservé gérant, voir remarque) |
| `production/daily-closure/` | GET | AD DI CO GE ok ; FA LI 403 |
| `chat/conversations/`, `unread-count/`, `users/` | GET | tous ok (détail dans le rapport chat) |

Remarque : `reconciliation` est refusée aux facturiers et livreurs (permission par défaut `IsGerant`) ; conforme au périmètre « clôture = gérant » (non contradictoire avec remarque.md, à confirmer si les facturiers doivent voir l'écart).

## Isolation inter-boulangeries (K1 vers K2)
- Factures : `node` forgé ignoré (facture sur le nœud du facturier) ; détail, reçu, deliver, cancel, adjust, PATCH sur facture étrangère : 404 ; motif absent des listes étrangères ; PATCH `motif` : 400 même pour le gérant du nœud.
- Production : liste, détail, filtres `?node=`, `ordering`, `date_from/date_to` : jamais une session K2 (donc ni `objective_fc` ni `progress_*`). HQ voit les deux (objectif 420 000 / 540 000). `daily-closure` d'un gérant : toujours son nœud, quel que soit `node`. Création avec `node`/`declared_by` forgés : nœud et déclarant imposés. PATCH de `objective_fc`, `progress_*`, `is_closed`, `auto_track`, `theoretical_yield`, `total_fc_produced`, `sac_value_fc_used` : ignorés.
- Clients : distributions, lignes, cotisations de K2 : 404 en GET/PATCH/DELETE/actions ; création de ligne avec distribution ou client de K2 : 400 ; déplacement d'une ligne vers une distribution K2 : 400 ; `bulk_create_month` pour K2 : 403 ; PATCH `client` d'une cotisation vers un client K2 : refusé. La réponse de `refresh_indices` ne contient aucun client K2.
- **Échec : PATCH de `node` sur distribution et cotisation (BUG-313).**
- Exception attendue (recherche de clients par facturier) : inchangée, non régressée.

## Élévation par champs forgés
PATCH `/users/<soi>/` avec `role`, `node`, `is_superuser`, `is_staff`, `is_active`, `groups`, `user_permissions`, `can_access_all_nodes` pour les 6 rôles : 403 pour les 4 rôles non direction, aucun champ modifié pour tous les rôles. Création de comptes ADMIN/superuser/staff par COMPTABLE/GERANT/FACTURIER/LIVREUR : 403. DIRECTION ne crée ni ne modifie un ADMIN (403) ; `is_superuser`/`is_staff` forgés à la création ignorés. Facture : `facturier`, `status`, `node`, `role`, `is_staff`, `debt_after` ignorés ; `motif` hors liste : 400. `credit_limit` par facturier/livreur : 403. Journal d'activité et `PATCH config` : 403 pour GE/FA/LI.

## Écarts
| Ticket | Gravité | Résumé |
|---|---|---|
| BUG-313 | Bloquant | Un gérant K1 déplace sa distribution sociale (`PATCH {"node": K2, "year": 2030}`, 200) ou une cotisation (`PATCH {"node": K2}`, 200) vers K2 ; `perform_update` ne neutralise pas `node` (cf. BUG-022/056). Lignes de clients K1 exposées au gérant K2. |
| BUG-314 | Mineur | `PATCH core/nodes/<id>/ {"monthly_social_contribution": "-1"}` par DIRECTION : 200 (valeur négative acceptée). |

## Suites existantes exécutées
Voir « Exécution ».

## Observations (hors tickets)
- `sac_value_fc` et `monthly_social_contribution` sont lisibles par tout rôle authentifié via `GET core/nodes/` (liste de toutes les boulangeries, sans filtre par nœud). Nécessaire à l'interface ; à confirmer par le client pour `sac_value_fc` (valeur d'un sac visible d'un livreur).
- `cancel` d'une facture est accessible au facturier (`IsFacturier`) ; l'isolation tient (404 sur facture étrangère).
- COMPTABLE a des droits d'écriture sur production et distributions (`IsGerant` inclut COMPTABLE) ; cohérent avec les suites existantes, non remis en cause.

## Exécution
- `manage.py test chat core.tests.test_permissions core.tests.test_permissions_verif_2026_10_22 core.tests.test_permissions_regression_2026_11_19 core.tests.test_bug253_verification core.tests.test_bug284_password_change` : 177 tests, `OK (expected failures=3)`, 1181 s.
- `manage.py test core.tests.test_vague2_corrections_permissions core.tests.test_vague2_db_permissions core.tests.test_vague3_db_permissions` : 24 tests, `OK (skipped=1)`, 386 s.
- Exécution complète de toutes les apps (core clients sales production treasury commissions finance blockchain sync chat) : lancée, non terminée à la rédaction (plus d'une heure, hachage de mots de passe dans de nombreux tests) ; résultat non disponible, à rejouer ou à lire par le coordinateur. Les tests de permissions de chaque app ci-dessus sont, eux, verts.
- Les tests de permissions propres aux apps clients, sales, production, treasury, commissions, finance, blockchain et sync (non nommés « permissions ») sont dans la suite complète non terminée.
