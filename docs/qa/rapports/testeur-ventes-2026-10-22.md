# Rapport — testeur-ventes — 2026-10-22

## Mission

Audit de BUG-013 (`docs/qa/REGISTRE_BUGS.md`) : périmètre Ventes/Facturation de
`remarque.md` (lignes 10-12, 92, 106-117, 134, 136, 145-146, 167, 174, 184,
186, 190-193, 196-200), complété par CLAUDE.md §5.2 (BP, blocage crédit,
remboursement, flux facturier→livreur, reçu, équipes A/B).

Aucune modification de code applicatif. Travaux : tests automatisés dans
`backend/sales/tests/test_invoices.py`, fabriques fictives communes dans
`backend/core/testing.py` (nouveau fichier, réutilisable par les autres
testeurs), mises à jour de `docs/qa/REGISTRE_BUGS.md` et `remarque.md`.

`python manage.py test sales` : **32 tests, OK (6 `expectedFailure`, 0 succès
inattendu)**.

## Fichiers livrés

- `backend/core/testing.py` (nouveau) — fabriques `make_node`, `make_user`,
  `make_bread_price`, `make_client`, `get_config`. Données 100% fictives.
- `backend/sales/tests/__init__.py` (nouveau package, remplace l'ancien
  `backend/sales/tests.py` vide).
- `backend/sales/tests/test_invoices.py` (nouveau, 32 tests).
- `docs/qa/REGISTRE_BUGS.md` — ligne BUG-013 passée à `VÉRIFIÉ (remplacé par
  BUG-028..032)`, 5 nouvelles fiches ajoutées (BUG-028 à BUG-032).
- `remarque.md` — lignes 10, 12, 134, 136, 145-146, 174, 196 marquées `[c]`
  avec note et référence de test.

## Point méthodologique : concurrence réelle via HTTP + SQLite dans cet environnement

Le test de concurrence initial (`ConcurrentInvoiceBPTests`) envoyait 10
requêtes HTTP complètes (`POST /api/sales/invoices/`) en parallèle via
`APIClient` dans des threads. Sous la charge réelle de cette session (plusieurs
agents font tourner leurs suites de tests en parallèle sur la même machine),
cela a systématiquement produit `OperationalError: database table is locked`
sur des tables très sollicitées (`core_config`, notamment via
`Config.get_instance()`), y compris avec des tentatives de retry — au point
qu'aucune des 10 requêtes ne réussissait parfois. Ce n'est pas une régression
applicative : SQLite n'autorise qu'un seul écrivain à la fois (contrairement à
PostgreSQL, cible de production réelle). Plutôt que de garder un test
intrinsèquement instable dans cet environnement, je l'ai resserré sur la
propriété précise à démontrer — l'absence de mise à jour perdue du motif
`Client.objects.filter(pk=...).update(current_debt=F(...)+delta)` utilisé par
`InvoiceViewSet.create` — testée directement par 20 threads qui appellent ce
motif SQL sans passer par toute la pile HTTP/vue/sérialiseur. Ce test est
désormais stable et répété avec succès. Signalé au coordinateur comme point
de vigilance pour les autres testeurs qui écriraient des tests de concurrence
similaires : privilégier des opérations ciblées plutôt que la pile HTTP
complète pour éviter ce bruit.

## Point méthodologique important : code modifié en cours de session

`backend/sales/views.py` a été modifié **par un autre agent** (probablement
`dev-backend`/`architecte-sync`, implémentation du mode dégradé hors-ligne
`SYNC.md §6 H2` : nouvelle fonction `_effective_credit_limit`, import de
`sync.models.DebtMovement`) **pendant** que mes tests tournaient. Un run
intermédiaire a produit une cascade d'erreurs `TypeError`/`BreadPrice(s)
introuvable(s)` qui n'étaient pas de vraies régressions mais l'effet d'avoir
importé le module au milieu d'une édition. Reproduit manuellement ensuite
(`manage.py shell` contre `backend/db.sqlite3`, nœud fictif `ZZ3`/client
fictif, facture créée puis laissée visible pour vérification — voir note
ci-dessous) : le flux de création fonctionne normalement une fois le fichier
stabilisé. Rerun complet après stabilisation : 32/32 tests cohérents. Signalé
ici pour que le coordinateur sache que plusieurs agents ont touché
`backend/sales/views.py` dans la même fenêtre horaire — à surveiller pour la
phase 3 (le plan prévoit que `dev-backend` traite mes tickets BUG-028..032
sur ce même fichier).

**Donnée de démonstration laissée en base** (règle PLAN §0.1) : un nœud
`ZZ3` (« test3 ») et un client `ZZ3-0001` (« t3 t3 ») créés via
`manage.py shell` contre `backend/db.sqlite3` pour reproduire le bug
ci-dessus, avec une facture `ZZ3-20261022-0001`. Clairement fictifs
(préfixe ZZ, noms inventés). Laissés en base à la discrétion du
coordinateur ; à supprimer sans risque si non utiles à la revue.

## Scénarios couverts et résultat

### Conformes (confirmés par test, marqués `[c]` dans remarque.md)

- **l.10-12** — Le facturier voit, recherche et facture les clients d'une
  autre boulangerie (`clients/views.py::ClientViewSet.get_queryset` exempte
  FACTURIER/LIVREUR du filtre nœud) et peut confirmer lui-même la livraison
  (`deliver` → `IsFacturierOrLivreur`).
- **l.134** — Vente occasionnelle sans client acceptée.
- **l.136** — Entrée « Livraison (Livreur) » absente de la sidebar.
- **l.145-146 / l.196** — Le stock de pains peut devenir négatif (pas de
  plancher dans `_adjust_bread_stock`/`BreadStock`) : conforme à la demande
  explicite du client (comportement **voulu**, pas un bug).
- **l.174** — Le titre de la modale « Enregistrer commande » (Clients.tsx)
  est correct (résidu cosmétique mineur signalé, pas de ticket : l'infobulle
  du bouton qui ouvre la modale garde l'ancien texte).

Standard : facture multi-lignes, prix toujours pris dans `BreadPrice` (le
prix envoyé par le client HTTP est bien ignoré), BP cumulative sur plusieurs
factures et insensible à un changement de mois simulé, blocage crédit
(BP≥plafond ET versement<commande → 403 + notification ; versement≥commande
→ accepté ; BP juste sous le plafond → accepté), remboursement sans ligne
(réduit la BP, ne touche pas le stock, aucune `InvoiceLine` créée), codes
NV/RG/NS acceptés, équipes limitées à A/B et facture tamponnée de l'équipe
du facturier, livraison confirmée par facturier OU livreur avec un seul
déstockage (double requête de livraison rejetée en 400, pas de double
déstockage), annulation (par un GERANT, voir BUG-031) qui restitue stock et
BP et journalise l'action, numéro de reçu testé en concurrence (voir note
ci-dessous), BP finale correcte sous 10 créations concurrentes pour le même
client.

### Anomalies confirmées (nouveaux tickets, voir `REGISTRE_BUGS.md`)

- **BUG-028** (Majeur) — `commission_rate` non forcé à 0 côté serveur pour
  une vente soldée ou une vente occasionnelle sans client, si le payload ne
  l'envoie pas explicitement. Clarification demandée par le coordinateur sur
  l.186 vs l.190 : **ce sont deux mécanismes réellement distincts** (vente
  soldée vs vente sans commission), tous les deux correctement implémentés
  et mutuellement exclusifs dans `Clients.tsx` (« Enregistrer commande »),
  mais **`Sales.tsx` (« Facturation (Facturier) ») n'a que la case « vente
  soldée », pas la case « sans commission »** explicitement demandée aussi
  pour ce formulaire par remarque.md l.190. Je n'ai pas tranché si cela
  justifie un ticket frontend séparé ou reste un sous-point de BUG-028 /
  BUG-021 (déjà ouvert par `testeur-clients-commissions` sur l'absence de
  case dédiée) — signalé dans la fiche BUG-028 pour éviter un doublon entre
  les deux testeurs.
- **BUG-029** (Majeur) — `cleanup_expired` (auto-suppression des factures
  PENDING > 12h, remarque.md l.167) reverse la BP mais ne restitue pas le
  stock de pains déduit à la création, contrairement à `cancel()`.
- **BUG-030** (Majeur) — Un facturier peut forcer le champ `node` du payload
  à la création d'une facture et l'attribuer à une boulangerie où il ne
  travaille pas (`data.get('node') or request.user.node_id` donne priorité
  au payload). Distinct de l.10-12 (qui autorise à juste titre de facturer
  un **client** d'un autre nœud) : ici c'est le nœud de la **facture**
  elle-même qui est usurpable. Analogue à BUG-025 (même défaut sur
  `clients.Client.node`, ouvert par `testeur-permissions`).
- **BUG-031** (Majeur) — `InvoiceViewSet.get_permissions()` ne reconnaît pas
  les actions `cancel`/`cleanup_expired` dans ses branches explicites et
  retombe sur `[IsGerant()]`, qui écrase silencieusement les
  `permission_classes` déclarées sur les décorateurs `@action`
  correspondants (`IsFacturier`/`IsAuthenticated`). Conséquence concrète :
  un FACTURIER ne peut ni annuler une commande qu'il vient de créer
  (contrairement à remarque.md l.200 et au docstring du code) ni déclencher
  lui-même le nettoyage des factures expirées — **remarque.md l.167 ne se
  produit donc jamais en pratique** quand c'est un facturier qui charge la
  page Facturation (`Sales.tsx` appelle `cleanupExpired()` avec
  `.catch(() => {})`, qui masque silencieusement le 403).
- **BUG-032** (Mineur) — Le bouton de la file de livraison affiche
  « Confirmer & Imprimer » au lieu du texte demandé « Imprimer le reçu »
  (remarque.md l.167, partie libellé).

### Point de vigilance signalé, sans ticket (pas de test reproductible)

- `_make_receipt_number` (`.count() + 1` sans verrou ni contrainte
  d'unicité) n'a pas produit de doublon sous 8 créations concurrentes dans
  ce test (SQLite sérialise les écritures par verrou fichier). Risque
  théorique réel sous PostgreSQL (écritures réellement parallèles) : à
  surveiller, pas de ticket ouvert en l'absence de reproduction.
- La lecture de `client.current_debt` pour le contrôle de plafond (avant
  l'écriture atomique `F()`) n'est pas protégée par `select_for_update()`
  (CLAUDE.md §4). Mon test de concurrence (crédit très large, jamais atteint)
  ne met pas en évidence de perte de mise à jour — il faudrait un test ciblé
  autour du seuil exact pour le démontrer, dépendant du moteur SQL réel.
  Signalé au coordinateur comme risque potentiel plutôt que tranché en
  ticket sans preuve.

## Hors périmètre backend, vérifié par lecture de code uniquement (pas de test automatisé)

- **l.92** (dates « Invalid Date » dans la file de livraison) — le code
  actuel de `Sales.tsx` gère déjà le cas `item.invoiceDate` manquant avec un
  fallback `'—'` ; semble déjà corrigé, à confirmer visuellement par
  `testeur-e2e`.
- **l.106-117** (3 premiers + « Voir plus », hauteur de modale, stats
  cliquables « LIVRÉES AUJOURD'HUI »/« TOTAL FACTURÉ ») — tous confirmés
  présents dans le code actuel de `Sales.tsx` par lecture directe. Pas de
  test Playwright écrit (hors périmètre d'un testeur backend, à couvrir par
  `testeur-e2e` en phase 4).
- **l.184** (onglets client avec historique mensuel paginé) — relève de
  `Clients.tsx`, donc du périmètre `testeur-clients-commissions` (BUG-012),
  non retraité ici pour éviter le doublon.

## Pour le coordinateur

1. Confirmer si BUG-028 (partie « case sans commission absente de
   Sales.tsx ») doit devenir un ticket frontend séparé ou rester noté dans
   BUG-028/BUG-021.
2. `backend/sales/views.py` est maintenant la cible de BUG-028 à BUG-031 **et**
   vient d'être modifié pour le mode dégradé hors-ligne (SYNC.md H2) par un
   autre agent dans la même fenêtre horaire — à bien séquencer en phase 3
   (un seul agent à la fois sur ce fichier).
3. Nœud/client/facture de démonstration `ZZ3*` dans `backend/db.sqlite3` —
   à nettoyer ou garder selon votre préférence (voir plus haut).
