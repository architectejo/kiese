# Rapport — testeur-permissions — 2026-10-22

Agent : `testeur-permissions`. Mission : (1) vérification de BUG-005/006 (nettoyeur-securite) ;
(2) audit BUG-016 partie permissions/dashboard/nodes de `remarque.md` + isolation inter-nœuds
transversale sur toutes les routes API.

Aucun fichier de code applicatif n'a été modifié. Seuls ont été produits/modifiés :
- `backend/core/tests/test_permissions.py` (nouveau, 32 tests)
- `backend/core/tests/__init__.py` (nouveau — package de tests), suppression de `backend/core/tests.py`
  (stub Django vide, incompatible avec la création du package `tests/`)
- `docs/qa/MATRICE_PERMISSIONS.md` (nouveau)
- `docs/qa/REGISTRE_BUGS.md` (mise à jour : BUG-005/006 → VÉRIFIÉ, BUG-016 → partiellement refermé,
  BUG-022 à BUG-027 ouverts)
- `remarque.md` (lignes 110 et 160 marquées `[c]`, avec note)
- Démonstration manuelle ponctuelle sur `backend/db.sqlite3` (voir §4) — nettoyée immédiatement après,
  rien laissé en base.

## 1. Partie 1 — Vérification BUG-005/006

**Verdict : VÉRIFIÉ pour les deux tickets.** Changement de statut appliqué dans le registre.

- **BUG-005** (DEBUG/SECRET_KEY/HTTPS) : `manage.py check --deploy` simulé avec un `.env` de
  production (`DEBUG=False`, `SECRET_KEY` forte, `ALLOWED_HOSTS` renseigné, cookies sécurisés, HSTS)
  → 0 avertissement `security.*` (test `DeploySecurityCheckTests`). Point méthodologique à noter pour
  le prochain agent qui réutiliserait ce test : `X_FRAME_OPTIONS` est décidé par un `if not DEBUG:`
  évalué **une seule fois à l'import de `settings.py`**, donc `override_settings` ne peut pas rejouer
  cette branche a posteriori dans un test — il faut soit forcer `X_FRAME_OPTIONS` explicitement dans
  `override_settings` (ce que fait le test), soit relancer tout le process Python avec
  `DJANGO_DEBUG=False` réellement positionné (ce que nettoyeur-securite avait déjà fait manuellement).
  Aucune faille trouvée.
- **BUG-006** (JWT/blacklist/login) :
  - Throttle login : 6 tentatives erronées en moins d'une minute → la 6e renvoie bien 429
    (`LoginThrottleTests`, `DEFAULT_THROTTLE_RATES['login']='5/min'` confirmé).
  - Blacklist après logout : confirmée **au niveau librairie** — `RefreshToken(...).check_blacklist()`
    lève bien `TokenError` après `logout_view` (`RefreshBlacklistTests`). `token_blacklist` est
    installée et toutes ses migrations sont appliquées sur `backend/db.sqlite3`
    (`manage.py showmigrations token_blacklist` → tout `[X]`).
  - **Découverte annexe, hors périmètre strict de BUG-006 mais découverte en le vérifiant** : aucune
    route HTTP de refresh n'existe (ni `/api/token/refresh/`, jamais câblée dans `kiese/urls.py`, ni
    `/api/core/auth/login/refresh/`, l'URL que `frontend/src/api/client.ts` appelle réellement). Le
    mécanisme de blacklist est donc correct mais **inexploitable en conditions réelles** : tout
    utilisateur est déconnecté de force 30 minutes après connexion (durée raccourcie par BUG-006,
    contre 12h avant — donc BUG-006 rend ce problème préexistant bien plus visible/douloureux). Ouvert
    comme **BUG-024 (Bloquant)**, distinct de BUG-006 lui-même qui est bien corrigé sur son périmètre
    propre (durée de vie, blacklist, throttle).
  - Audit indépendant des `AllowAny` : grep exhaustif de tout `backend/**/*.py` (hors `.env/` = le venv
    mal nommé, hors site-packages) → exactement 3 occurrences, les 3 citées par nettoyeur-securite
    (`login_view`, `ConfigView` GET seul via `get_permissions`, `BreadPriceViewSet` list/retrieve
    seuls). `DEFAULT_PERMISSION_CLASSES=['IsAuthenticated']` confirmé en défaut global dans
    `settings.py`. Échantillon de 12 endpoints représentatifs de toutes les apps testé anonyme → tous
    401/403 (`AllowAnyAuditTests`). Aucune faille trouvée.

## 2. Partie 2 — Audit BUG-016 (permissions/dashboard/nodes) + isolation transversale

### 2.1 Points remarque.md confirmés conformes (marqués `[c]`)

- **l.110** « Registre Blockchain réellement connecté ? » → Oui, `Blockchain.tsx` appelle les vrais
  endpoints `/api/blockchain/snapshots/global_status/`, `/alerts/`, `/run_check/`. Pas de données
  mockées.
- **l.160** « Clients Actifs = achat dans le mois écoulé » → Oui,
  `ClientViewSet.active_last_month` filtre bien sur une fenêtre de 30 jours avec au moins une facture.

### 2.2 l.52-83 — Erreur 400 à la création d'une succursale (Nodes.tsx)

Reproduit précisément : le payload envoyé par `Nodes.tsx` est valide dans le cas général (vérifié par
appel direct à l'API avec un payload identique à celui du formulaire). La cause réelle : le champ
`code` du modèle `Node` est limité à 5 caractères (`max_length=5`), mais le formulaire React
(`Nodes.tsx` l.300-311) n'a ni `maxLength` ni validation avant soumission — un utilisateur qui saisit
un code trop long (ex. le nom complet d'une boulangerie plutôt que son code court) obtient un 400 dont
le message serveur est pourtant correct et déjà remonté dans `formErrors` par le code existant, mais
sans que l'utilisateur comprenne la cause avant de la lire attentivement dans le formulaire. **Ce
n'est pas un bug backend** — ouvert comme **BUG-027 (Mineur, frontend)**.

Démonstration manuelle effectuée une fois contre `backend/db.sqlite3` (règle PLAN §0.1) : création
d'un nœud fictif `code=K9`, `name=DEMO Test Node` pour confirmer qu'un code court passe (201), puis
suppression immédiate de cet enregistrement — rien laissé en base.

### 2.3 Isolation inter-nœuds — cœur de métier, audit transversal (au-delà du strict périmètre remarque.md)

Six bugs confirmés par lecture de code **et** par test automatisé qui échoue avant correction :

| Ticket | Gravité | Résumé |
|---|---|---|
| **BUG-022** | Bloquant | 5 ViewSets sans aucun filtrage par nœud : `SystemNotificationViewSet`, `ColisDistributionViewSet` (core), `ConsumableMovementViewSet` (production), `SocialContributionViewSet`/`SocialDistributionViewSet`/`SocialDistributionLineViewSet` (clients). Un GERANT/FACTURIER/LIVREUR de n'importe quelle boulangerie lit (et pour les `ModelViewSet`, modifie/supprime) les données de toutes les autres. |
| **BUG-023** | Bloquant | `BreadTransferViewSet` : liste non filtrée + `respond_to_request`/`confirm_reception` sans vérifier que l'utilisateur appartient à `from_node`/`to_node` — un GERANT peut répondre/confirmer à la place d'une boulangerie tierce. |
| **BUG-024** | Bloquant | Endpoint de refresh JWT absent (voir §1). |
| **BUG-025** | Majeur | `ClientViewSet.perform_create` accepte le `node` fourni dans le corps sans le confronter à `user.node` pour un rôle non-HQ (GERANT) — création de client forcée dans un autre nœud. |
| **BUG-026** | Majeur | `CashbookEntryViewSet` (Livre de Caisse Direction) lisible par tout utilisateur authentifié, tous nœuds confondus — pas de filtrage, pas de restriction `IsHeadquarters`. Point à clarifier avec le client (transparence volontaire ou oubli ?), signalé sans trancher. |
| **BUG-027** | Mineur | Voir §2.2. |

Points vérifiés **conformes** (pas de ticket, documentés dans `MATRICE_PERMISSIONS.md` §2) :
- Élévation de rôle via `PATCH /users/<soi-même>/` et `/auth/me/` → bloquée (permission + liste de
  champs autorisés explicite).
- `credit_limit` par un facturier → bloqué (`IsGerant` exclut FACTURIER/LIVREUR en update/destroy).
- Logs d'activité → réservés HQ.
- `Config`/`BreadPrice` → réservés `IsDirection`.
- Suppression d'écritures comptables → impossible (ViewSet en lecture seule, pas de route DELETE).
- Modification/suppression d'un client d'un **autre nœud** par un facturier → bloquée (l'exemption de
  `get_queryset` pour FACTURIER/LIVREUR ne s'applique de fait qu'en lecture, car `update`/`destroy`
  exigent `IsGerant`, qui exclut ces deux rôles). **Nuance importante** : la création, elle, n'est pas
  protégée (voir BUG-025) — l'exemption « lecture cross-nœuds » ne doit donc pas être confondue avec
  une protection en écriture, qui existe pour update/destroy par accident de permission (IsGerant) et
  pas par une vérification explicite de cohérence de nœud.
- `BlockchainSnapshotViewSet`/`TamperAlertViewSet` → réservés `IsHeadquarters`, corrects.
- `InvoiceViewSet` (sales) et tous les ViewSets de `treasury`/`commissions` audités en passant →
  filtrage par nœud présent partout (hors `CashbookEntryViewSet`, voir BUG-026). Périmètre détaillé
  laissé à `testeur-ventes`/`testeur-tresorerie`/`testeur-clients-commissions`, non dupliqué ici.

## 3. Registre des bugs — changements

- BUG-005 → **VÉRIFIÉ** (vérifié par testeur-permissions).
- BUG-006 → **VÉRIFIÉ** (vérifié par testeur-permissions) — avec la découverte annexe BUG-024 signalée
  séparément pour ne pas rouvrir BUG-006 lui-même (son périmètre propre est bien corrigé).
- BUG-016 → statut mis à « PARTIELLEMENT REJETÉ » : la partie permissions/dashboard/nodes est
  entièrement traitée (2 points conformes `[c]`, 6 tickets ouverts BUG-022 à BUG-027) ; la partie
  Finance (l.87 États Financiers N/N-1, l.208-214 doublons clients/simulation data_kiese) **reste
  ouverte** pour `auditeur-comptable`, non traitée ici, hors de mon périmètre.
- Ouverture : BUG-022, BUG-023, BUG-024, BUG-025, BUG-026, BUG-027 (fiches complètes dans
  `docs/qa/REGISTRE_BUGS.md`).

## 4. Tests livrés

`backend/core/tests/test_permissions.py` — 32 tests, organisés en deux parties (cf. docstring du
fichier). Résultat final : `OK (expected failures=12)`.

Les 12 tests marqués `@unittest.expectedFailure` documentent les 6 bugs confirmés (chaque test
référence son ticket dans le commentaire du décorateur et dans le message d'assertion) et continueront
d'échouer silencieusement (comptés comme succès par `unittest`) jusqu'à correction par `dev-backend` —
retirer le décorateur fera alors apparaître un **succès inattendu** (`unexpected success`), signal
clair pour `testeur-permissions` de repasser le ticket correspondant à `VÉRIFIÉ`.

`docs/qa/MATRICE_PERMISSIONS.md` — matrice complète route × méthode × rôle, écarts confirmés en
tête, points conformes ensuite, inventaire de toutes les routes `router.register` en annexe.

## 5. `python manage.py test` (suite complète)

Lancé en tâche de fond en fin de session pour vérifier l'absence de régression globale introduite par
l'ajout de `core/tests/test_permissions.py` (suppression du stub `core/tests.py` notamment) — résultat
à vérifier par le coordinateur dans `C:\Users\MUABILU PC\AppData\Local\Temp\claude\test_full.txt` si
le job n'est pas encore terminé au moment de la lecture de ce rapport (l'environnement d'exécution de
cette session est particulièrement lent — chaque lancement de `core.tests.test_permissions` seul a
pris 5 à 7 minutes).

## 6. Points signalés sans trancher (contradictions / décisions à prendre par le coordinateur ou le client)

1. **BUG-026** : le Livre de Caisse Direction doit-il être visible par tout le personnel (transparence
   volontaire) ou réservé à la Direction (ce que suggère la dénomination « Direction » et CLAUDE.md
   §5.5) ? Je n'ai pas tranché, j'ai ouvert le ticket avec les deux lectures possibles.
2. **BUG-024** : le choix de l'URL définitive de refresh (`/api/token/refresh/` standard SimpleJWT vs
   autre) doit être fait conjointement par `dev-backend` (route) et `dev-frontend` (appel dans
   `client.ts`) dans la même itération, pour éviter un nouvel aller-retour cassé.

## 7. Environnement d'exécution — remarque pour les prochains agents

L'environnement de cette session n'a pas de venv Python dédié au projet sous `backend/.venv` (le
dossier `backend/.env` reste le venv mal nommé signalé par BUG-007, pas encore renommé par un humain).
J'ai utilisé l'interpréteur `C:\Users\MUABILU PC\Desktop\projects\credit\venv\Scripts\python.exe`
(un venv global visible dans le PATH de cette machine, contenant déjà Django 5 + toutes les
dépendances du projet) pour lancer `manage.py test`/`check`, avec `DJANGO_DEBUG=True` et
`DJANGO_ALLOWED_HOSTS` incluant `testserver` positionnés dans l'environnement (nécessaires pour que
`manage.py test`/le client de test Django fonctionnent avec le garde-fou anti-DEBUG=False de BUG-005).
Aucune donnée réelle de `backend/db.sqlite3` n'a été utilisée pour les tests automatisés (base éphémère
`manage.py test` à chaque fois) ; la seule interaction avec `db.sqlite3` a été la démonstration
ponctuelle et nettoyée du §2.2.
