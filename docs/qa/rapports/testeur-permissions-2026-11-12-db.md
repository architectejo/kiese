# Rapport testeur-permissions — vague 2 sur base réelle (2026-11-12)

Cible : backend déjà lancé `http://127.0.0.1:8000` sur `db.sqlite3`. Aucun migrate, aucun SQL, aucun git, `reset-data` jamais appelé, aucun compte réel ni client réel modifié, code applicatif intact. Un seul processus de test à la fois.

## 1. Comptes créés (API admin)
15 comptes `zz_perm_<role>_<noeud>` : ADMIN, DIRECTION, COMPTABLE, GERANT, FACTURIER, LIVREUR x K5 et K6, plus ADMIN/DIRECTION/COMPTABLE au siège (`_hq`). Mot de passe commun non journalisé. Désactivés en fin de passe : `zz_perm_admin_k6` (mot de passe réinitialisé = identifiant, voir BUG-248) et `zz_perm_dirmade_admin` (ADMIN créé par un compte DIRECTION, BUG-247). Les autres restent actifs pour les rejeux.

## 2. Méthode
- Inventaire : schéma OpenAPI (252 routes x méthodes) + `team-assignment` ; matrice observée 7 profils (anonyme + 6 rôles sur K5) ajoutée à `docs/qa/MATRICE_PERMISSIONS.md` §5. Détail : UUID nul pour distinguer 403 (refus de rôle) de 404 (rôle admis), corps vide.
- Isolation : listes (`?node=` forcé inclus), détail par UUID réel d'un autre nœud (K2/K3/K4, lecture seule), PATCH `{}`, objets cibles fictifs `ZZPERM` K5/K6 pour les écritures (clients, facture, transfert, clôture, cotisation, notifications).
- Probes Django : `backend/core/tests/test_vague2_db_permissions.py` (base de test éphémère) : 9 `@expectedFailure`, tous reproduisent (`OK (expected failures=9)`).

## 3. Résultats par axe

### Matrice rôles x routes (7 profils, 247 lignes)
Conforme : anonyme 401 partout sauf `GET config`, `GET bread-prices` (liste et détail) ; `core` écriture config/nodes/users/prix = ADMIN/DIRECTION seulement ; `activities`, `blockchain`, `finance`, `cashbook`, `vouchers`, `direction-cash-counts`, `sync/conflicts` = siège ; `commissions` écriture, `consumable-types`, `expense-categories`, `periods` = siège ; clients/caisse sociale/production/treasury écritures = gérant et au-dessus (sauf création de client et factures : facturier ; livraison : facturier ET livreur ; annulation : facturier et au-dessus, pas le livreur) ; sync push/pull/handshake/status = jeton de nœud (401 pour JWT). Écarts : voir BUG-251, 252, 253, 255.

### Isolation inter-nœuds (K5/K6 contre K2/K3/K4 et entre eux)
- Listes sessions, fournées, mouvements, stocks, stocks pains, factures, dépenses, rapports, clôtures, épargne, journal, livre de caisse, transferts : aucune ligne étrangère pour gérant/facturier/livreur, avec ou sans `?node=` (312 contrôles OK).
- Détail par UUID étranger : 404 partout ; PATCH `{}` : 404 (factures : 400 car le corps est validé avant la recherche, sans fuite).
- Clients : gérant K5/K6 ne voit, ne modifie, ne supprime ni ne recalcule un client étranger (404) ; `node` forcé dans le corps de création ou de PATCH ignoré (nœud du gérant imposé).
- Exceptions documentées OK : facturier et livreur lisent et recherchent les clients des autres boulangeries (200) mais ne les modifient pas (403) ; facturier K5 facture un client K6 (201, `node` forcé à K5 malgré `node=K6`) ; livreur K5 confirme la livraison (200) ; facturier/gérant/livreur K6 ne peuvent ni lire, ni livrer, ni annuler, ni ajuster, ni PATCH cette facture (404/403).
- Transferts : `to_node` forcé au nœud du demandeur, demandeur ne répond pas (403), émetteur ne confirme pas (403), livreur/facturier refusés.
- Échecs : BUG-249 (cotisations), BUG-251 (stocks consommables, `node` du corps).

### Attaques
- `/users/<soi>/` et `/auth/me/` : GÉRANT, FACTURIER, LIVREUR, COMPTABLE : `role`, `node`, `is_superuser`, `is_staff` refusés (403) ou ignorés. DIRECTION : promotion ADMIN effective et création d'ADMIN, prise de contrôle d'un ADMIN : BUG-247 (bloquant).
- `credit_limit` : PATCH facturier 403 ; mais fixé à la création : BUG-250.
- Activity logs : gérant/facturier/livreur 403, comptable 200. Config/prix : siège COMPTABLE 403, DIRECTION/ADMIN 200. Livre de caisse : POST/PUT/PATCH/DELETE = 403/405 pour tous.
- Ancre `CashbookHead` : aucune route (`cashbook-head`, `heads`, `cashbook/head`, `anchor`, `blockchain/head*` : 404/403/405 pour tous les rôles, aucune dans le schéma) ; `integrity_check` expose seulement `head_problem` (lecture). Conforme.

### JWT
- Signature altérée, payload altéré (3 `user_id`), `alg=none`, clé HS256 erronée, refresh utilisé comme access : 401. Access expiré (30 min) : 401 `token_not_valid` observé naturellement.
- Refresh : rotation ; ancien refresh refusé (blacklist) ; refresh après logout refusé (401) ; access utilisé comme refresh refusé.
- Compte désactivé : login 401, access existant 401 ; un refresh existant renvoie encore 200 (jeton inutilisable ensuite) : observation, pas de ticket.
- Throttle : 5 essais erronés puis 429 sur le même compte (rattrapé par la fenêtre glissante quand le serveur est lent) ; identifiants inconnus idem.
- `AllowAny` : login, `GET config`, `GET bread-prices` + schéma/swagger/redoc publics : BUG-255. `PATCH /auth/me` laisse un utilisateur changer son propre `username` (observation).

### Restrictions récentes rejouées
| Ticket | Résultat |
|---|---|
| BUG-200 | VÉRIFIÉ (déjà par testeur-tresorerie) : `validate`/`reject`/`push_to_cashbook` refusés (403) au gérant, facturier, livreur, y compris gérant d'un autre nœud ; comptable valide. Versement par le siège non rejoué (chaîne réelle). |
| BUG-198 | **VÉRIFIÉ** : gérant ne supprime plus une clôture confirmée (403), PATCH d'une clôture confirmée 400, gérant étranger 404, facturier 403. Cas « versée » non rejoué. |
| BUG-233 | Déjà VÉRIFIÉ : gérant, direction, comptable PATCH `commission_exempt` 200 ; facturier/livreur 403 ; autre champ 400 ; gérant d'un autre nœud 404. |
| BUG-223 | Déjà VÉRIFIÉ : résolution du litige 200 par le gérant émetteur ; 403 pour le récepteur, facturier, livreur (K5 et K6). |
| BUG-187 | **VÉRIFIÉ** pour `team-assignment` : corps `["A"]` -> 400. |
| team-assignment | livreur 403 (GET et POST) ; facturier : `node` forgé ignoré (K5 inchangé après POST K6 forgé) ; siège sans `node` : 400. |
| BUG-242 | API : `expenses` 403 pour FAC/LIV, mais lecture closures/épargne/journal ouverte (BUG-253). Reste `CORRIGÉ` (côté écran non rejoué ici). |
| BUG-212, BUG-215 | Non rejoués (déjà VÉRIFIÉS par testeur-ventes). |

## 4. Tickets ouverts (BUG-247 à BUG-256)
Bloquants : **BUG-247** (DIRECTION -> ADMIN, création/prise de contrôle d'ADMIN), **BUG-249** (gérant écrit des cotisations sociales pour un autre nœud). Majeurs : BUG-248 (réinitialisation = identifiant, renvoyé en clair), BUG-250 (facturier fixe plafond/taux à la création), BUG-251 (FAC/LIV écrivent les stocks de consommables), BUG-252 (suppression d'alertes siège par tout utilisateur). Mineurs : BUG-253 (lecture trésorerie/commissions FAC/LIV, `cleanup_expired` ouvert, à clarifier), BUG-254 (lignes de distribution : 500), BUG-255 (schéma et config publics), BUG-256 (`cotisation_sociale=True` sur un Decimal).

## 5. Effets de bord sur la base réelle (à connaître)
- 3 notifications vides (`title=''`, `node_origin=CLOUD`) créées par un POST à corps vide (ADMIN/DIRECTION/COMPTABLE) et 3 « Configuration mise à jour » générées par mes PUT/PATCH `{}` de `core/config/` (valeurs inchangées). Suppression refusée par la politique de l'environnement : à purger par l'équipe.
- `treasury/reports/generate` rejoué (200) pour K5 : rapports facturier K5 du jour.
- Objets fictifs conservés (aucun n'est réel) : clients `ZZPERM Cible K5/K6`, `ForgeG5`, `ForgeF5` ; facture K5 livrée (client K6), transfert K5/K6 résolu, clôture K5 confirmée, dépense, épargne, journal, 2 cotisations (K5, K6), 2 distributions (K6 2031, K5 2032), affectations d'équipe K5/K6, stocks K5 restaurés à 0. Aucun des 678 clients réels, aucun compte réel touché.
- Le backend est tombé brièvement (connexion refusée puis revenue) pendant la passe ; non lié à mes requêtes à ma connaissance.

## 6. Non couvert
Versement au livre de caisse par le siège (écriture sur la vraie chaîne), rôles ADMIN/DIRECTION/COMPTABLE rattachés à K5/K6 pour l'isolation (ils voient tout par conception), `distribution-lines` et `colis` avec données (absentes), commissions avec données (aucune période en base), `mark_all_read`, `reset-data`, import Excel avec fichier.
