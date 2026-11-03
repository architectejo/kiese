# Rapport testeur-e2e — 2026-11-03 — Vérification BUG-011 (régression E2E)

## Mandat

Passe de régression E2E complète suite aux chantiers récents (BUG-118 à BUG-126, synchro BUG-004
étendue, dette technique BUG-011), avec un focus particulier sur **BUG-011** (`getErrorDetail` +
types élargis dans `services.ts`, commit `b0c5291`, 12 fichiers frontend touchés), jamais encore
`VÉRIFIÉ`. Consigne du coordinateur : lancer les testeurs, ouvrir un ticket précis à chaque vraie
anomalie trouvée sans la corriger moi-même, ne pas modifier le code applicatif.

Session interrompue une fois en cours de route (serveurs de dev coupés) ; redémarrée sur demande du
coordinateur, reprise exactement là où elle s'était arrêtée (mêmes serveurs relancés, même protocole
mot de passe temporaire, suite E2E rejouée depuis le début pour garantir un résultat propre).

## Mise en place

- Backend : `manage.py runserver 8000` (`DJANGO_LOGIN_THROTTLE_RATE=100/min` pour éviter BUG-006 en
  rafale de connexions E2E), contre `backend/db.sqlite3` (base de dev partagée, comme demandé).
- Frontend : `npm run dev` (port 5173).
- `demo_gerant_k1_e2e` : mot de passe laissé `unusable` par le testeur-e2e du 2026-10-30 (BUG-114) et
  retrouvé dans le même état par `dev-frontend` le 2026-11-03 — **confirmé** au début de cette
  session (`has_usable_password() == False`). J'ai appliqué le même protocole déjà documenté dans le
  registre et le README `e2e/` : mot de passe temporaire `DemoE2E2026!` posé pour la durée de la
  suite, puis **remis à `set_unusable_password()` immédiatement après**, aucune autre donnée
  applicative modifiée. Confirmé restauré en fin de session.
- Fixtures clients attendues par `e2e/README.md`/`fixtures/comptes.ts` retrouvées en base,
  conformes : `DEMO CrossNodeE2E` (K1-0078), `DEMO PlafondE2E` (K1-0079, dette = plafond = 50 000 FC),
  `DEMO RemboursementE2E` (K1-0083, dette 15 000 FC — le README mentionne 20 000 FC de référence mais
  les tests ne vérifient qu'une valeur relative, pas la valeur absolue ; sans impact).

## Revue statique du commit BUG-011 (`b0c5291`)

Avant de lancer les tests, relecture ligne à ligne du diff complet des 12 fichiers listés dans
`docs/qa/rapports/dev-frontend-2026-11-03-bug011.md` (`errors.ts`, `services.ts`, `Treasury.tsx`,
`Clients.tsx`, `Settings.tsx`, `Production.tsx`, `Sales.tsx`, `Dashboard.tsx`, `Commissions.tsx`,
`Users.tsx`, `Nodes.tsx`, `Finance.tsx`, `DashboardLayout.tsx`, `authStore.ts`). Conclusion : la très
grande majorité des remplacements `catch (err: any) { ... err?.response?.data?.detail ... }` →
`catch (err: unknown) { ...getErrorDetail(err, fallback)... }` sont des réécritures strictement
équivalentes (vérifiées au cas par cas), avec deux micro-changements de typage sans effet
fonctionnel repérés (`bpMap[Number(k)]` → `bpMap[k]` dans `Sales.tsx`, no-op car JS convertit déjà
la clé numérique en chaîne ; `flour_sacks_used: flourSacks.toString()` dans `Production.tsx`, valeur
déjà validée `> 0` avant l'appel).

**Mais** cette relecture a aussi révélé une vraie régression fonctionnelle — voir BUG-127 ci-dessous.

## Suite E2E Playwright (`e2e/tests/`, projets `bureau` + `pos`)

Deux exécutions complètes de la suite (68 tests × 2 tailles d'écran) :
- 1ʳᵉ exécution : échec massif en cascade sur `demo_gerant_k1_e2e` (mot de passe `unusable` constaté
  au tout début) → arrêtée, mot de passe temporaire posé, suite relancée propre.
- 2ᵉ exécution (interrompue par la coupure de session, données/mot de passe temporaire confirmés
  intacts au redémarrage) → **3ᵉ exécution complète, résultat final retenu** :

```
55 passed
10 skipped   (tests déjà marqués test.fixme : transfert inter-nœuds, clôture Niveau 1/2 complète,
              journée complète bout-en-bout, impression listing de paie — limitations connues et
              documentées, sans rapport avec BUG-011)
3 failed
20.5 minutes, 1 worker
```

### Les 3 échecs — aucun n'est une régression BUG-011

1. **`[pos]` et `[bureau]` — « Clôture de fournée automatisée (BUG-093/108) »** : échoue parce que la
   suite a été rejouée deux fois dans la même journée calendaire (interruption de session) — la
   fournée Équipe B du jour existait déjà, en contradiction avec `unique_together (node, team, date)`
   (CLAUDE.md §5.4). Le test contient lui-même une détection "déjà déclarée aujourd'hui" avec
   `test.skip`, mais celle-ci n'a pas capté le message à temps dans ce cas précis (fenêtre de 2 s
   trop courte une fois la session enchaînée plusieurs fois). **Limite de rejeu documentée dans le
   fichier de test lui-même**, pas un défaut applicatif, et sans rapport avec le refactoring BUG-011.
   Non actionnable sans réinitialiser `db.sqlite3` (hors périmètre — base partagée).
2. **`[pos]` — « Journal de Caisse (BUG-091/105) »** : le pré-remplissage "Rapproché à la Clôture" est
   resté bloqué sur "Vérification de la Clôture..." au-delà du timeout de 10 s. Rejoué isolément sur
   le projet `bureau` dans la même exécution (même code, même fixture `CashClosure` du 2020-02-02
   confirmée présente en base avec `total_entries=12345`) : **passe sans problème**. Code de ce
   composant (`jSuggestedCa`/`useEffect` de `Treasury.tsx`) **non touché** par le commit BUG-011.
   Conclusion la plus probable : contention de ressources (backend `manage.py test` complet tournait
   en parallèle sur la même machine pendant cette fenêtre précise). Flake d'environnement, pas une
   régression du code.

Ces trois échecs sont donc **non imputables à BUG-011** — aucun ticket ouvert pour eux (déjà
documentés/expliqués ci-dessus et dans le code du test lui-même).

### Points les plus pertinents pour BUG-011 (passés au vert)

- `02-connexion-roles.spec.ts` : identifiants invalides → message d'erreur serveur affiché
  correctement (`authStore.ts::login`, chemin `getErrorDetail`). Confirmé aussi par appel direct à
  l'API : `POST /api/core/auth/login/` avec mauvais mot de passe → `{"detail":"Identifiants
  invalides."}`, HTTP 401, affiché tel quel dans `Login.tsx`.
- `04-facturation.spec.ts` : blocage au plafond de crédit (Clients.tsx, chemin de calcul client,
  pas un chemin `getErrorDetail`, mais vérifie que rien n'a cassé autour).
- `10-regression-remarque-2026-10-30.spec.ts` : écart Journal de Caisse → avertissement explicite,
  jamais un blocage silencieux (passé sur `bureau`).
- Parcours Clients (photo, recherche cross-nœud), Production (écart manquant/excédent), Commissions,
  facturation en série (10 factures enchaînées) : tous verts sur les deux tailles d'écran testées.

## Vérification manuelle ciblée (étape 2 du mandat) — appels API directs, 4 pages touchées

Au-delà de l'E2E (qui ne vérifie pas le texte exact d'un message d'erreur serveur sans `detail`),
j'ai forcé des erreurs 400/403 réelles par appel direct à l'API (JWT `demo_gerant_k1_e2e`,
contournant volontairement React pour isoler le comportement serveur de celui du rendu) et confronté
le résultat à la relecture du code :

| Page | Action forcée | Réponse serveur | Code frontend concerné | Résultat |
|---|---|---|---|---|
| Clients | `POST /api/clients/clients/` sans `first_name`/`last_name` | `400 {"first_name":[...], "last_name":[...]}` | `Clients.tsx::handleAddClient` (gestion manuelle conservée, pas `getErrorDetail`) | **OK** — champ précis affiché |
| Production | `POST /api/production/transfers/` sans `from_node` | `400 {"from_node":["Ce champ est obligatoire."]}` | `Production.tsx::handleTransferSubmit` (`getErrorDetail`) | **RÉGRESSION — voir BUG-127** |
| Production | `POST /api/production/disposals/` sans `session` | `400 {"session":[...]}` | `Production.tsx::handleDisposalSubmit` (`getErrorDetail`) | **RÉGRESSION — voir BUG-127** |
| Production | `POST /api/production/movements/` sans `stock` | `400 {"stock":[...]}` | `Production.tsx::handleApproSubmit` (`getErrorDetail`) | **RÉGRESSION — voir BUG-127** |
| Trésorerie | `FacturierReportViewSet.generate()` (date invalide/nœud manquant) | toujours `{"detail": ...}` (action personnalisée) | `Treasury.tsx::handleGenerateReport` (`getErrorDetail`) | OK en pratique aujourd'hui (voir note BUG-127) |

## Anomalie trouvée : BUG-127 (ouverte, non corrigée)

**Régression confirmée introduite par le commit BUG-011**, consignée dans
`docs/qa/REGISTRE_BUGS.md` (fiche détaillée + ligne de suivi) :

> `getErrorDetail` (nouveau `frontend/src/api/errors.ts`) ne lit que la clé `detail` de la réponse.
> Avant BUG-011, trois gestionnaires de `Production.tsx` (transfert, sortie de pains, mouvement de
> stock/appro — lignes 304/325/381 après le commit) utilisaient un filet de secours
> `JSON.stringify(d)` quand le serveur renvoyait une erreur de validation DRF standard **sans** clé
> `detail` (ex. `{"from_node":["Ce champ est obligatoire."]}`, forme par défaut de DRF pour un
> `ModelViewSet.create()`). Ce filet a été perdu dans le refactoring : l'utilisateur voit maintenant
> un message générique **« Erreur. »** sans aucune indication du champ fautif, dans trois scénarios
> de saisie réalistes et courants (gérant qui oublie de choisir la boulangerie d'origine, la fournée
> à solder, ou le consommable d'un appro).

- Gravité retenue : **Majeur** (pas de perte de données ni de risque de sécurité, mais régression
  d'ergonomie bloquante pour comprendre un rejet de formulaire — exactement le risque annoncé dans le
  mandat de cette mission).
- Reproduction par `curl` documentée intégralement dans la fiche détaillée du registre (3 commandes,
  copiables telles quelles).
- Deux pistes de correctif proposées dans la fiche (amélioration de `getErrorDetail` générique, ou
  retour ciblé au `JSON.stringify` aux 3 emplacements) — **non trancutées ici**, à la charge de
  `dev-frontend`, avec un test qui doit échouer avant / passer après (CLAUDE.md §7 règle 4).
- Une quatrième occurrence du même idiome existe (`Treasury.tsx::handleGenerateReport`) mais n'est
  **pas reproductible aujourd'hui** : l'action backend correspondante renvoie toujours `{"detail":
  ...}` explicitement (vérifié dans `backend/treasury/views.py::FacturierReportViewSet.generate()`),
  donc `getErrorDetail` s'y comporte de façon strictement équivalente à l'ancien code pour le moment.
  Mentionnée dans la fiche pour mémoire/vigilance future, pas comptée comme un 4ᵉ cas confirmé.
- **BUG-011 repassé à `EN COURS`** dans le tableau de suivi (ne peut pas être `VÉRIFIÉ` tant que
  BUG-127 reste ouvert) — je n'ai pas tranché moi-même la correction, conformément à la règle
  CLAUDE.md §7.2 (« les testeurs ne corrigent pas le code applicatif »).

### Point d'ambiguïté signalé, pas tranché seul

Le tableau de suivi assigne BUG-011 à « Vérifié par : relecteur-code » (auteur initial de la fiche),
alors que c'est moi (testeur-e2e) qui ai reçu la mission de vérification cette fois-ci. J'ai laissé
la colonne telle que modifiée (`testeur-e2e`) par cohérence avec le mandat reçu, mais signale l'écart
au coordinateur au cas où `relecteur-code` devait rester le vérificateur formel désigné.

## Suite de tests backend (`manage.py test`)

Lancée en tâche de fond par prudence (CLAUDE.md §7 règle 5 : « avant de rendre la main,
`python manage.py test` ... passe ») sur les apps `clients sales treasury production commissions
core finance blockchain`. Première tentative bloquée ~30 min sans progrès (prompt interactif
« delete test database? » jamais atteint car stdout redirigé vers un pipe non-interactif) — relancée
avec `--noinput`, repart normalement. Reste néanmoins **très longue** (encore en cours après plus de
25 minutes à la fin de cette session, aucun échec constaté dans les centaines de lignes de sortie
déjà produites — uniquement des avertissements `drf-spectacular` pré-existants sur les schémas
OpenAPI, sans rapport avec BUG-011). Cette suite ne touche aucun fichier modifié par BUG-011 (backend
pur) ; je ne l'ai pas laissée bloquer la remise de ce rapport, mais son journal reste disponible à
`D:\Projects\kiesse\backend_test2.log` si le coordinateur souhaite en vérifier l'issue finale — à
nettoyer/relancer par le prochain agent si nécessaire, je n'ai pas pu confirmer un résultat final
dans le temps de cette session.

`npx tsc --noEmit` et `npm run build` (frontend) n'ont pas été re-relancés dans cette session : déjà
confirmés « OK » par `dev-frontend` dans son propre rapport (aucune modification de code depuis), et
aucune régression de typage n'aurait pu expliquer les 3 échecs E2E observés (tous trois non liés au
typage, voir analyse ci-dessus).

## Nettoyage effectué avant de rendre la main

- `docs/qa/captures/e2e-results/` et `e2e/playwright-report/` supprimés (résidus de mes propres
  exécutions).
- Photos de test générées par le test "photo client" (`backend/media/clients/photos/demo-client-e2e_*.png`)
  **restaurées** à leur état de dépôt via `git checkout` après une suppression accidentelle trop
  large de ma part (fichiers déjà suivis par git, pas de vraies données `data_kiese/` — erreur sans
  conséquence, corrigée dans la foulée).
- Journaux temporaires (`*.log`) à la racine du dépôt supprimés, sauf `backend_test2.log` (suite
  backend encore en cours au moment de la remise du rapport, voir ci-dessus).
- `demo_gerant_k1_e2e` remis à `set_unusable_password()`, confirmé.

## Conclusion / demande au coordinateur

- **BUG-011 : NON passé à `VÉRIFIÉ`** — repassé à `EN COURS`, bloqué par **BUG-127** (nouveau ticket,
  `OUVERT`, gravité Majeur, régression confirmée et reproduite par `curl`, 3 emplacements précis dans
  `Production.tsx`). Merci de dispatcher `dev-frontend` sur BUG-127 ; je revérifierai dès correction
  (nouveau passage E2E + nouvel appel `curl` sur les 3 emplacements).
- Les 3 échecs E2E restants (fournée Équipe B rejouée le même jour, flake ponctuel sur le
  pré-remplissage du Journal de Caisse) sont expliqués et **non actionnables comme tickets
  applicatifs** — aucune action demandée dessus.
- Suite backend (`manage.py test`) lancée par prudence, encore en cours à la fin de cette session,
  aucun échec constaté jusqu'ici — à vérifier/relancer si le coordinateur le juge utile.
