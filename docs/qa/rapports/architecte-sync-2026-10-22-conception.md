# Rapport — architecte-sync — 2026-10-22 (conception, BUG-004)

## Périmètre traité

Conception seule, **aucun code applicatif écrit ni modifié** (conforme à la mission : point d'arrêt
humain avant toute implémentation, car la synchronisation est une fondation potentiellement
irréversible qui conditionne le schéma desktop de la phase 5).

Livrable : `docs/architecture/SYNC.md`. Registre mis à jour : `docs/qa/REGISTRE_BUGS.md` (BUG-004,
fiche détaillée ajoutée, **statut laissé `OUVERT`** — c'est volontaire, pas un oubli).

## Lecture préalable

`CLAUDE.md` (entier), `cahierDesCharges.md` §6.3/§6.4, `docs/architecture/DESKTOP.md` (entier, avec
attention particulière aux §5 et §9), `docs/qa/rapports/ingenieur-blockchain-2026-10-22.md` (pris
comme donnée d'entrée figée — le modèle de hash du Livre de Caisse est stabilisé et ne doit pas être
redérangé par la conception de sync), le code réel de `core.models.SyncableModel` et des 7 apps qui
en héritent (`treasury`, `production`, `clients`, `sales`, `commissions`, `blockchain`), notamment
`Client.current_debt`, `CashClosure`/`CashbookEntry`, `Invoice`/`InvoiceLine`, `BreadTransfer` (déjà
en 3 temps), `sales/views.py::_make_receipt_number` (déjà correctement préfixé par nœud).

## Décisions clés (résumé — le détail et la justification complète sont dans SYNC.md)

1. **Le Livre de Caisse Direction (`CashbookEntry`) reste une table exclusivement Cloud.** Un nœud
   local ne l'écrit jamais directement ; il pousse des `CashClosure`/`DisbursementVoucher`
   synchronisées et c'est le Cloud qui appelle lui-même `append_cashbook_entry()` à réception. C'est
   la décision la plus structurante du document : elle élimine, par construction, tout risque de
   fourche de la chaîne de hash globale unique que `ingenieur-blockchain` vient de sécuriser avec une
   contrainte d'unicité sur `previous_hash` — une chaîne globale ne peut avoir qu'un seul écrivain
   logique, et ce ne peut être que le Cloud.
2. **`current_debt` n'est plus un champ scalaire transporté et écrasé** : nouveau modèle
   `sync.DebtMovement` (journal additif, immuable, un par facture qui affecte la balance de
   paiement). Le Cloud recalcule `current_debt = somme(DebtMovement)` sous verrou à chaque réception
   et republie la valeur à jour vers tous les nœuds concernés. Ce choix rend le recalcul **commutatif**
   : peu importe l'ordre d'arrivée des lots de deux boulangeries ayant facturé le même client
   hors-ligne, le résultat final (somme) est identique — pas de fusion arbitrale nécessaire, donc pas
   de vector clock nécessaire non plus pour ce cas précis (qui était le cas le plus dur du cahier des
   charges).
3. **Idempotence stricte** : upsert par UUID + `batch_id` journalisé (`sync.SyncBatchLog`), rejeu d'un
   lot identique renvoie le résultat déjà archivé sans retraiter la logique métier.
4. **Échecs partiels ligne par ligne**, chaque modèle dans sa propre transaction côté Cloud (un rejet
   sur une ligne de production n'annule jamais les factures déjà acceptées dans le même lot).
5. **Authentification de nœud distincte de l'authentification utilisateur** : nouveau
   `sync.NodeAuthToken`, assigné depuis le menu Nœuds du siège (conforme à cahierDesCharges.md
   §6.3.1), jamais le même jeton qu'un JWT utilisateur, HTTPS obligatoire sur toutes les routes
   `/api/sync/*`.
6. **Confirmation du principe « aucune configuration modifiable en local »** : `Config`, `BreadPrice`,
   `ExpenseCategory`, `ConsumableType`, `User` descendent exclusivement du Cloud ; un nœud local qui
   tenterait d'en pousser un serait rejeté.
7. **Transferts inter-boulangeries** : aucun changement de modèle nécessaire — le workflow existant
   en 3 temps (`BreadTransfer.TransferStatus` : PENDING → RESPONDED → CONFIRMED/DISPUTED) tolère déjà
   nativement que les deux nœuds ne soient jamais en ligne simultanément ; chaque étape attend
   simplement le prochain cycle de sync du nœud concerné.
8. **Numérotation des reçus déjà correcte** : `sales/views.py::_make_receipt_number` préfixe déjà par
   `node_code`, donc déjà unique de facto entre nœuds hors-ligne — aucun changement requis côté sync.
   Point de vigilance signalé mais **hors périmètre sync** : `count()+1` sans verrou local (risque de
   collision interne à un même nœud, pas lié à la synchro) — à ouvrir en ticket séparé pour
   `dev-backend`.
9. **Mode hors-ligne frontend** : exclusivement porté par le backend desktop local (SQLite + service
   de sync en tâche de fond). Le frontend React web pur ne gère pas le hors-ligne en V1 — pas de
   Service Worker, pas d'IndexedDB côté navigateur. Le bandeau de statut (DESKTOP.md §9) est alimenté
   par un nouvel endpoint **local** `GET /api/sync/status/` interrogé par polling léger.
10. **Pas de vector clock sur `SyncableModel`** : les champs actuels (`id` UUIDv4, `node_origin`,
    `is_synced`, `created_at`, `updated_at`) sont jugés suffisants au volume réel (8 boulangeries, pas
    de méga-concurrence). Chaque objet mutable a par construction un seul nœud autorisé à le modifier
    à la fois (machine à états ou propriété exclusive) ; le seul cas de concurrence légitime
    (`current_debt`) est déjà résolu par sommation, pas par un ordre temporel. Ajout nécessaire, mais
    en modèles compagnons et non sur `SyncableModel` lui-même : `DebtMovement`, `NodeAuthToken`,
    `SyncBatchLog`, `SyncConflictLog`, `OutboxBatch`.

## Points qui ont vraiment besoin d'un arbitrage humain avant le code

Détaillés dans `SYNC.md` §6 ; liste précise, pas « tout » :

- **H1 — organisationnel** : accepter qu'une clôture de caisse saisie hors-ligne reste *provisoire*
  (non inscrite au Livre de Caisse Direction officiel) jusqu'à la prochaine synchronisation réussie ?
  C'est la conséquence directe de la décision n°1 ci-dessus. L'alternative (chaîne par nœud fusionnée
  après coup) a été explicitement rejetée dans le document parce qu'elle recréerait le risque de
  fourche que `ingenieur-blockchain` vient d'éliminer — mais c'est un changement de perception pour
  le gérant (« ma caisse n'est pas encore officiellement enregistrée tant que je n'ai pas de
  réseau ») qui mérite une validation côté client/coordinateur, pas seulement technique.
- **H2 — politique de risque métier** : en mode dégradé prolongé, le contrôle de plafond de crédit ne
  peut être qu'optimiste localement (basé sur la dernière valeur connue, qui peut déjà être dépassée
  par des achats simultanés ailleurs). Faut-il, en plus de la notification a posteriori proposée,
  réduire artificiellement le plafond effectif local (ex. 80 % du plafond réel) pour absorber ce
  risque ? Choix de politique commerciale pour le client, pas une question technique que je peux
  trancher seul.
- **H3 — à confirmer formellement, pas supposer** : aucune configuration n'est modifiable depuis
  l'interface d'un nœud local, **y compris** par le compte administrateur local de secours prévu par
  DESKTOP.md §7 étape 5 (créé pendant une coupure prolongée sans cloud) ? Le document suppose que ce
  compte sert uniquement à continuer à facturer/livrer, jamais à changer les prix/plafonds — si c'est
  faux, cela réintroduit un vrai conflit de configuration à résoudre au retour en ligne, qui n'est pas
  traité dans la conception actuelle.
- **H4 — exploitation, pas conception** : combien de temps maximum un nœud peut-il rester hors-ligne
  avant qu'un retard de mise à jour de prix/config devienne un problème opérationnel réel ? Sert à
  dimensionner une recommandation de fréquence minimale de connexion à communiquer au client ;
  n'affecte pas le protocole lui-même mais la documentation utilisateur.
- **H5 — périmètre V1** : le siège a-t-il lui-même besoin d'un mode « nœud local avec file d'attente
  hors-ligne » (coupure Internet au siège), ou le siège est-il toujours supposé être « en ligne avec
  lui-même » puisqu'il EST le Cloud ? Cette conception suppose la deuxième option — à confirmer avant
  que `packaging-desktop` ne commence un éventuel poste siège.

## Ce qui n'est délibérément pas tranché par ce document (signalé, pas oublié)

- Détail d'implémentation du throttling anti-rejeu abusif d'un nœud compromis qui spammerait `push` —
  relève de la sécurité réseau générale, en partie déjà couverte par `nettoyeur-securite`.
- Format exact de la barre de progression de la première synchronisation descendante
  (DESKTOP.md §7 étape 4) — relève de `dev-frontend`/`packaging-desktop`.
- UI dédiée de résolution de conflits au siège (reléguée en V2 ; V1 utilise `/admin/`).

## Prochaine étape proposée

Soumission de `docs/architecture/SYNC.md` au coordinateur/humain pour validation, en priorité sur les
points H1 à H5 ci-dessus. Aucune implémentation ne doit démarrer avant cette validation — en
particulier `packaging-desktop` (phase 5, D6) qui dépend explicitement de ce document selon
DESKTOP.md §15.
