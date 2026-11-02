# Architecture de synchronisation Local ↔ Cloud — ETS. KIESE

> Document de conception produit par `architecte-sync` le 2026-10-22, en réponse à BUG-004.
> **Statut : PROPOSITION — en attente de validation humaine avant tout code.**
> Références : CLAUDE.md §4/§6/§8, cahierDesCharges.md §6.3/§6.4, `docs/architecture/DESKTOP.md` §5/§9,
> `docs/qa/rapports/ingenieur-blockchain-2026-10-22.md` (modèle de hash stabilisé, pris comme donnée d'entrée figée).

---

## 0. Principe fondateur, posé avant tout détail

Le Livre de Caisse Direction (`CashbookEntry`) est **une chaîne de hash globale unique**, comme
confirmé et implémenté par `ingenieur-blockchain` (`_get_last_balance()` ne filtre jamais par
nœud). Une chaîne de hash globale ne peut avoir **qu'un seul écrivain logique à un instant donné** —
deux nœuds qui écriraient chacun « le bloc suivant » pendant qu'ils sont hors-ligne l'un de l'autre
produiraient inévitablement une fourche que la contrainte d'unicité sur `previous_hash` empêcherait
de toute façon de committer des deux côtés en même temps.

**Décision tranchée (voir §4.2) : en V1, le Livre de Caisse Direction n'est jamais écrit localement.**
Il reste une table **exclusivement Cloud**, alimentée uniquement par le Cloud lui-même, à partir des
clôtures (`CashClosure`) et bordereaux (`DisbursementVoucher`) remontés depuis les nœuds après
synchronisation. Un nœud local ne pousse jamais de `CashbookEntry` : il pousse des `CashClosure`
synchronisées, et c'est le Cloud qui, en les recevant, appelle `append_cashbook_entry()` lui-même,
exactement comme il le fait déjà aujourd'hui pour une clôture saisie directement en ligne. Ce
principe simplifie radicalement la synchronisation de l'objet le plus sensible du système : il n'y a
jamais de résolution de conflit à faire sur le Livre de Caisse, parce qu'il n'existe tout simplement
qu'à un seul endroit.

Ce choix a une conséquence organisationnelle à valider avec le client (voir §9, point H1) : un
gérant qui clôture en mode desktop déconnecté voit sa clôture **provisoire** localement (chiffres
corrects, mais pas encore « inscrite au Livre de Caisse Direction officiel ») jusqu'au prochain
handshake réussi.

---

## 1. Topologie et autorité par modèle

### 1.1 Nœuds

- **Cloud** (siège, `node_origin='CLOUD'`) : source de vérité pour la configuration, les droits, les
  prix, et point d'arrivée unique de toute donnée financière consolidée (Livre de Caisse, États
  financiers N/N-1).
- **Nœuds locaux** : K1, K2, K3, K4, K5, K6, B1, B2, et demain un poste desktop par boulangerie
  (`node_origin` = code boulangerie). Chaque nœud a sa propre base (SQLite en desktop), source de
  vérité pour **ses propres opérations du jour** (ventes, production, dépenses locales) jusqu'à
  remontée.
- Le Cloud est aussi un « nœud » techniquement (il peut recevoir des écritures directes via son
  interface web), mais n'est **jamais en retard sur lui-même** : il n'a pas de file d'attente de
  synchronisation sortante vers lui-même.

### 1.2 Sens de circulation par famille de modèles

| Sens | Modèles | Autorité |
|---|---|---|
| **Local → Cloud** (montée) | `Invoice`, `InvoiceLine`, `BreadTransfer`, `BreadTransferLine`, `ProductionSession`, `ProductionSessionLine`, `BreadDisposal`, `ConsumableMovement`, `ConsumableCount`, `LocalExpense`, `FacturierReport`, `CashClosure`, `DisbursementVoucher` (si un poste direction local existe), `JournalEntry`, `DailySavings`, `ActivityLog`, `SocialContribution`/`SocialDistribution`/`SocialDistributionLine` | Le nœud local est seul auteur de ses propres lignes. Le Cloud les accepte, ne les modifie jamais en retour (sauf statut de validation explicite, ex. transfert confirmé par le nœud destinataire, qui reste un autre nœud local légitime). |
| **Cloud → Local** (descente) | `Node`, `User` (y compris `password` déjà haché, `role`, `node`, permissions), `Config`, `BreadPrice`, `ExpenseCategory`, `ConsumableType`, `Client` **créés par d'autres nœuds** (lecture), `SystemNotification` ciblées, numéro de version attendu (electron-updater) | Seul le Cloud modifie ces objets. Un nœud local ne les écrit jamais de son propre chef (confirmé §5.4 CLAUDE.md : aucune configuration n'est modifiable en local — voir §6 H3). |
| **Bidirectionnel avec recalcul** | `Client` (champs d'identité : nom, téléphone, adresse, plafond — montent depuis le nœud propriétaire, descendent en lecture vers les autres) ; `current_debt` / BP (**jamais transporté comme valeur, toujours dérivé**, voir §4.1) ; `BreadStock`, `ConsumableStock` (soldes recalculés au Cloud à partir des mouvements, jamais écrasés) | Cloud = arbitre final, nœud propriétaire = auteur des mouvements. |
| **Cloud uniquement, jamais synchronisé vers le bas** | `CashbookEntry`, `TamperAlert`, `BlockchainSnapshot`, `CommissionPeriod`/`ClientCommission` (calculées au Cloud après consolidation — un nœud local peut au plus proposer les éléments bruts, pas le calcul final) | Voir §0. |

### 1.3 Qui est propriétaire d'un `Client` ?

Chaque `Client.node` est son nœud de rattachement (celui qui l'a créé). Un facturier d'un autre
nœud peut le rechercher et le facturer (CLAUDE.md §5.1) — c'est le scénario qui rend `current_debt`
dangereux (§4.1). Un `Client` créé par K1 est **monté** vers le Cloud par K1 ; il est ensuite
**descendu en lecture** vers tous les autres nœuds (pour que K4 puisse le retrouver et le facturer
hors-ligne). Les champs d'identité (téléphone, adresse, plafond, cotisation) ne peuvent être modifiés
que depuis le nœud propriétaire ou depuis le Cloud — jamais depuis un nœud tiers qui ne fait que
facturer ce client.

---

## 2. Le problème central : `current_debt` / BP, modélisé explicitement

### 2.1 Pourquoi « dernier qui écrit gagne » est faux ici

Scénario concret : le client X (rattaché à K1, `current_debt = 10 000 FC`) achète hors-ligne chez K1
(nouvelle facture, BP avant 10 000 → BP après 15 000) **et** chez K4 le même jour (BP avant 10 000 →
BP après 13 000, lu depuis le cache local de K4, lui-même basé sur la dernière valeur connue avant la
coupure). Les deux nœuds synchronisent ensuite dans un ordre quelconque. Si le Cloud se contente
d'écraser `Client.current_debt` avec la valeur envoyée par chaque facture (`debt_after`), le résultat
final dépend de l'ordre d'arrivée des paquets réseau — pas de la réalité (qui est 10 000 + 5 000 +
3 000 = 18 000 FC).

### 2.2 Solution retenue : la dette est une valeur dérivée, jamais transportée comme vérité

1. **`Invoice.debt_before` / `Invoice.debt_after` restent des champs figés au moment de la création**
   (comme aujourd'hui) — ils représentent « ce que le facturier voyait sur son nœud à cet instant »,
   utile pour le reçu imprimé et pour l'audit, mais ne sont **plus la source de vérité du solde
   courant** une fois qu'on raisonne à l'échelle du groupe.
2. **Journal de mouvements de dette** (nouveau, `sync.DebtMovement`, voir §7.1) : chaque facture qui
   affecte la BP (hors vente soldée / cash pur) génère, au moment de sa création, un mouvement
   `{client_id, invoice_id, node_origin, amount, kind='ORDER'|'PAYMENT'|'REPAYMENT', created_at}`.
   Ce mouvement est une ligne **immuable et additive** : `amount` positif pour une commande à crédit,
   négatif pour un versement/remboursement. Il monte avec la facture, dans le même lot, par la même
   voie `push`.
3. **Recalcul au Cloud** : `Client.current_debt` n'est plus un champ saisi — c'est un champ **calculé
   et republié** par le Cloud : `current_debt = somme(DebtMovement.amount pour ce client, ordonnés par
   created_at)`. À chaque réception d'un lot contenant des `DebtMovement` nouveaux pour un client, le
   Cloud recalcule la somme sous verrou (`select_for_update()` sur la ligne `Client` au Cloud) et
   republie la valeur à jour de `current_debt` + `category` (recalculée via `refresh_category()`) vers
   **tous** les nœuds qui ont déjà vu ce client (y compris celui qui vient d'envoyer, en retour
   d'accusé de réception).
4. **Au niveau local**, le facturier qui crée une facture pendant une coupure continue d'utiliser la
   dernière valeur connue de `current_debt` sur son nœud comme `debt_before` — c'est strictement
   nécessaire pour appliquer la règle de blocage (CLAUDE.md §5.2) **en mode dégradé**. Le document
   assume explicitement (voir §6 H2, point à trancher avec le client) que ce contrôle local peut donc
   être temporairement optimiste (laisser passer une vente qui, consolidée après coup, dépasserait le
   plafond) : c'est un risque métier accepté en V1 en échange de la continuité de service imposée par
   le cahier des charges — le dépassement réel est détecté au Cloud au recalcul et déclenche une
   `SystemNotification` de type « dépassement de plafond détecté a posteriori » plutôt qu'un blocage
   rétroactif (on ne peut pas annuler une pâte déjà livrée).
5. **Avantage de ce modèle** : il est commutatif. Peu importe l'ordre d'arrivée des lots de K1 et K4,
   la somme finale est la même. Aucune fusion « intelligente » de deux valeurs scalaires concurrentes
   n'est nécessaire — on remplace le problème de fusion par un problème de **somme**, qui n'a pas
   besoin d'ordre total.
6. **Rejeu/idempotence** : chaque `DebtMovement` a un UUID propre, généré localement au moment de la
   création de la facture (donc idempotent par construction, voir §3.3) — rejouer un push ne compte
   jamais deux fois le même mouvement.

### 2.3 Remboursements et cas `is_debt_repayment`

Une facture de remboursement (CLAUDE.md §5.2, « facture sans ligne ») génère un `DebtMovement` de
type `REPAYMENT` avec un montant négatif égal au versement — même mécanique, pas de cas spécial
dans le calcul de la somme.

### 2.4 `BreadStock` / `ConsumableStock` — même logique, plus simple

Ces stocks sont déjà, dans le code actuel, recalculés à partir de mouvements (`_adjust_bread_stock`,
`ConsumableMovement`) plutôt que d'un compteur écrasé. **Aucun changement de modèle requis** ici :
chaque nœud a son propre stock physique (pas de stock partagé entre boulangeries en dehors des
transferts explicites, §5), donc il n'y a pas de concurrence multi-nœuds sur un même compteur — la
synchronisation Local→Cloud de ces mouvements sert uniquement à la consolidation et au reporting
siège, jamais à un recalcul arbitral comme pour `current_debt`.

### 2.5 Impact de BUG-083 (« ventes passées ») sur `DebtMovement` — aucun changement requis

`Config.allow_backdated_sales` (BUG-083, décision client 2026-10-29) permet de saisir une facture
avec un `Invoice.invoice_date`/`delivered_at` antérieur à aujourd'hui. Vérifié explicitement lors de
l'implémentation : **ceci ne change rien au modèle `DebtMovement`/au recalcul §2.2**.

- `record_debt_movement` (sales/views.py, appelé via `transaction.on_commit`) continue à créer un
  mouvement avec un UUID propre et un `created_at` = l'instant RÉEL de la création de la facture
  (jamais la date commerciale choisie) — le recalcul `current_debt = somme(DebtMovement.amount,
  ordonné par created_at)` reste donc strictement additif et commutatif, qu'une facture soit
  rétroactive ou non.
- La seule conséquence déjà documentée (voir `docs/qa/REGISTRE_BUGS.md`, fiche BUG-083, section
  « Analyse d'impact ») est que `Invoice.debt_before`/`debt_after` (instantané pris à l'insertion,
  §2.2 point 1) reflète la BP du jour de SAISIE, pas celle de la date antérieure choisie pour
  l'affichage — limite acceptée explicitement par le client, non corrigée par ce ticket, sans rapport
  avec la synchronisation.
- Le mécanisme de correction du Livre de Caisse Direction introduit par BUG-083
  (`treasury.services.record_backdated_correction`) ajoute une **nouvelle** `CashbookEntry` (jamais de
  modification d'une écriture existante — voir CLAUDE.md §5.5) datée du jour réel de la saisie ; comme
  toute `CashbookEntry`, cette table reste exclusivement Cloud (§0) et n'est jamais synchronisée
  Local→Cloud en tant que telle — seules les `CashClosure` montent, et c'est le Cloud qui rejoue
  `promote_closure_to_cashbook`/le nouveau mécanisme de correction localement côté Cloud.

---

## 3. Protocole Local → Cloud (montée)

### 3.1 Détection de connectivité

- Côté desktop (Electron + service de synchronisation en tâche de fond, DESKTOP.md §9) : un ping
  `GET /api/sync/handshake/` toutes les 30 s. Trois états exposés au frontend via `window.kiese` /
  polling : `ONLINE`, `OFFLINE`, `SYNC_ERROR` (le cloud répond mais rejette l'authentification du
  nœud — jeton révoqué/expiré, à distinguer d'une simple coupure réseau).
- Côté web pur (navigateur, pas de desktop) : **pas de mode hors-ligne** en V1 — voir §8. Le service
  de synchronisation ne s'exécute que dans le processus backend du poste desktop/local, jamais dans
  le navigateur.

### 3.2 Extraction et format du payload

- Extraction : toute ligne `is_synced=False` sur les modèles de la famille « montée » (§1.2), triée
  par `created_at` **au sein d'un même modèle**, mais surtout respectant l'**ordre de dépendance entre
  modèles** (§3.5).
- Un lot (`push`) regroupe par défaut au plus **200 enregistrements**, tous modèles confondus dans
  l'ordre de dépendance, pour rester dans une seule transaction raisonnable côté Cloud et permettre
  une reprise fine après coupure (§3.6).
- Format JSON, un objet par modèle synchronisable :

```json
POST /api/sync/push/
Headers: Authorization: Bearer <jeton_de_nœud>, Idempotency-Key: <uuid batch>
{
  "node_code": "K4",
  "batch_id": "b1f2...-uuid",
  "client_app_version": "1.3.2",
  "records": {
    "clients.Client":        [ {...}, ... ],
    "sales.Invoice":         [ {...}, ... ],
    "sales.InvoiceLine":     [ {...}, ... ],
    "sync.DebtMovement":     [ {...}, ... ],
    "production.ProductionSession": [ {...}, ... ],
    "...": [...]
  }
}
```

- Chaque enregistrement conserve son `id` (UUID généré localement), son `node_origin`, ses
  horodatages `created_at`/`updated_at` d'origine (pour l'audit — le Cloud ne les réutilise pas comme
  clé d'ordonnancement arbitral, voir §3.5).

### 3.3 Idempotence

- **Clé d'idempotence double** :
  1. Chaque enregistrement est identifié par son UUID (`id`) → le Cloud fait un **upsert** :
     `get_or_create` puis, si déjà existant et objet immuable par nature (ex. `InvoiceLine`,
     `DebtMovement`), **ignore silencieusement** un doublon identique (idempotence stricte) ; pour un
     objet mutable mais toujours sous contrôle exclusif du nœud émetteur (ex. `Invoice.status` qui
     passe de `PENDING` à `DELIVERED`), **mise à jour** si `updated_at` entrant > `updated_at` connu
     côté Cloud pour ce champ précis (voir §3.5 dépendances de statut).
  2. Chaque **lot** porte un `batch_id` (UUID généré au moment de la constitution du lot côté nœud,
     stocké dans `sync.SyncBatchLog` côté Cloud avec le résultat complet renvoyé). Si le même
     `batch_id` est repoussé (ex. coupure réseau juste après l'envoi, avant réception de l'accusé —
     le nœud ne sait pas si ça a été reçu), le Cloud renvoie **le même résultat déjà calculé** sans
     retraiter, garantissant qu'un rejeu de lot identique ne produit jamais de doublon même si,
     improbable mais possible, un enregistrement individuel avait une règle de fusion non strictement
     idempotente.
- **Jamais d'ID auto-incrémenté dans le sens Local→Cloud** : confirmé conforme à `SyncableModel`
  existant, rien à changer sur ce point précis.

### 3.4 Échecs partiels (certaines lignes acceptées, d'autres rejetées)

- La réponse `push` est **ligne par ligne**, pas tout-ou-rien au niveau du lot :

```json
{
  "batch_id": "b1f2...-uuid",
  "results": {
    "sales.Invoice": [
      {"id": "uuid-1", "status": "ACCEPTED"},
      {"id": "uuid-2", "status": "REJECTED", "reason": "client introuvable : uuid du client non encore synchronisé"}
    ]
  }
}
```
- Un enregistrement `REJECTED` reste `is_synced=False` localement avec un motif stocké
  (`sync.SyncConflictLog`, §4.5) affiché dans le bandeau desktop (« 3 éléments en attente, 1 en
  erreur — voir détail ») ; il est **retenté au prochain cycle** (les dépendances amont, elles,
  arrivent généralement dans le même lot ou le précédent, donc l'échec se résorbe de lui-même dans la
  grande majorité des cas). Un rejet qui persiste après N tentatives (ex. 10) déclenche une
  `SystemNotification` visible au siège (anomalie à traiter manuellement, ex. contrainte métier
  violée — montant négatif impossible, etc.).
- Chaque modèle traité **dans sa propre transaction atomique** côté Cloud (pas une transaction globale
  pour tout le lot) : un échec sur `ProductionSessionLine` n'annule jamais les `Invoice` déjà acceptées
  dans le même lot.

### 3.5 Ordre des dépendances

Ordre fixe imposé par le protocole, **au sein d'un même lot et entre lots successifs** (un nœud ne
doit jamais pousser une facture avant son client si celui-ci est nouveau — en pratique le payload du
lot contient les deux et le Cloud les traite dans cet ordre interne) :

1. `core.User` (si création locale exceptionnelle — normalement descend plutôt que monte, cf. §1.2)
2. `clients.Client` (création/mise à jour d'identité)
3. `sync.DebtMovement` **avant** la facture qui l'a généré n'est pas nécessaire — ils montent
   ensemble, mais le Cloud traite toujours : `Client` → `Invoice` → `InvoiceLine` → `DebtMovement` →
   recalcul `current_debt`, dans cet ordre, **au sein du traitement d'une même facture**.
4. `production.ProductionSession` → `ProductionSessionLine` → `ConsumableMovement`
5. `production.BreadTransfer` → `BreadTransferLine` (voir §5 pour le cas où un des deux nœuds est
   hors-ligne)
6. `treasury.LocalExpense`, `FacturierReport`, `CashClosure` (déclenche l'écriture Cloud-only dans
   `CashbookEntry`, §0), `DisbursementVoucher`
7. `clients.SocialContribution` / `SocialDistribution` / `SocialDistributionLine`
8. `core.ActivityLog` (purement informatif, aucune dépendance, peut être traité en dernier/en tâche de
   fond basse priorité)

Si un enregistrement référence un `id` non encore vu côté Cloud (ex. ligne de facture arrivée avant
sa facture dans un lot mal formé), le serveur **ne devine jamais** : il rejette cette ligne précise
avec `reason="dépendance manquante"` (§3.4) plutôt que de créer un objet partiel.

### 3.6 Reprise après coupure au milieu d'un lot

- Le client (service de sync du nœud) envoie le lot en une seule requête HTTP, mais marque chaque
  enregistrement `is_synced=True` **uniquement après avoir reçu et validé la réponse `push`** (jamais
  avant, jamais de manière optimiste).
- Si la connexion tombe **pendant** l'envoi (pas de réponse reçue) : au prochain cycle, le nœud
  **reconstruit un lot avec le même `batch_id`** s'il l'a persisté localement avant l'envoi
  (`sync.OutboxBatch`, table locale), sinon avec un nouveau `batch_id` mais les mêmes enregistrements
  (toujours `is_synced=False`). Dans les deux cas, l'upsert par UUID (§3.3) garantit l'absence de
  doublon côté Cloud, que la coupure ait eu lieu avant ou après que le Cloud ait effectivement
  persisté tout ou partie du lot.
- Si la connexion tombe **après** réception complète par le Cloud mais **avant** que le nœud ne reçoive
  la réponse : au reprise, le nœud rejoue le même `batch_id` → le Cloud détecte le `batch_id` déjà
  traité (`sync.SyncBatchLog`) et renvoie directement le résultat archivé sans ré-exécuter la logique
  métier (évite par exemple de recalculer deux fois `current_debt` ou de renvoyer deux notifications).

---

## 4. Protocole Cloud → Local (handshake descendant)

### 4.1 Ce qui redescend

- `Config` (plafond par défaut, seuils, taux), `BreadPrice` (grille de prix), `ExpenseCategory`,
  `ConsumableType`, `Node` (liste des boulangeries actives, utile pour les transferts), `User`
  (comptes + rôle + **hash** de mot de passe — jamais le mot de passe en clair, cf. note déjà présente
  dans `core/models.py::User`), permissions effectives.
- `Client` créés par d'autres nœuds (lecture seule locale), et surtout **la valeur recalculée de
  `current_debt`/`category`** pour tout client déjà connu localement (§2.2 point 3).
- `SystemNotification` ciblées à ce nœud (ex. alerte « dépassement de plafond détecté a posteriori »,
  « falsification détectée côté Cloud »).
- Métadonnées de version attendue (pour `electron-updater`, DESKTOP.md §11).

### 4.2 Fréquence et curseur

- Appelé systématiquement **juste après** un `push` réussi (cycle push-puis-pull dans la même
  requête logique de synchronisation), et aussi seul, toutes les 5 minutes si le nœud est en ligne
  mais n'a rien à pousser (pour recevoir les mises à jour de configuration même un jour sans vente).
- Curseur : chaque nœud stocke localement `last_pull_cursor` = le plus grand
  `(updated_at, id)` déjà reçu **par type de modèle** (pas un cursor global — un `Config` mis à jour
  très rarement ne doit pas forcer à retélécharger tous les `BreadPrice`). Le `pull` est un `GET`
  paramétré :

```
GET /api/sync/pull/?since_config=2026-10-20T08:00:00Z&since_breadprice=...&since_user=...&since_client_debt=...
```

- Réponse : uniquement les objets dont `updated_at` (horodatage **serveur**, pas celui du nœud
  émetteur d'origine) est strictement postérieur au curseur fourni, plus le nouveau curseur à
  mémoriser pour le prochain appel (évite de rater un enregistrement créé exactement à la même
  milliseconde que le curseur précédent — curseur toujours accompagné de l'`id` pour désambiguïser
  une égalité stricte d'horodatage).

---

## 5. Résolution de conflits — cas concrets tranchés

### 5.1 Règle générale par catégorie de modèle

| Catégorie | Règle |
|---|---|
| Objets immuables après création (`InvoiceLine`, `DebtMovement`, `ConsumableMovement`, `ActivityLog`) | Jamais de conflit possible : upsert idempotent, aucune mise à jour après coup. |
| Objets mutables sous contrôle exclusif d'un seul nœud à la fois, avec machine à états (`Invoice.status`, `BreadTransfer.transfer_status`) | Le nœud qui a le droit de faire la transition suivante est défini par la machine à états elle-même (ex. seul `to_node` peut passer `PENDING`→`RESPONDED`) — pas de conflit possible **si le workflow métier est respecté**, mais un conflit est **détecté et journalisé** si deux transitions incompatibles arrivent (ex. annulation locale pendant qu'une livraison vient d'être confirmée ailleurs) → `sync.SyncConflictLog`, résolution manuelle au siège, jamais automatique. |
| `Client.current_debt`/`category` | Jamais transporté comme valeur figée à fusionner : toujours recalculé au Cloud (§2.2). Pas de « conflit » au sens classique — juste une somme. |
| `Client` (identité : nom, téléphone, plafond) | Dernier écrivain gagne, **mais seulement le nœud propriétaire ou le Cloud peuvent écrire** (§1.3) ; si un autre nœud tente une modification d'identité, le Cloud la rejette (`REJECTED`, raison « nœud non propriétaire de ce client ») plutôt que de l'accepter silencieusement. |
| `CashbookEntry` | Jamais de conflit : n'existe qu'au Cloud (§0). |
| Configuration (`Config`, `BreadPrice`, etc.) | Cloud = autorité unique, aucune écriture locale acceptée en push (rejet systématique si un nœud tentait d'en envoyer un — ne doit normalement jamais arriver, cf. §6 H3). |

### 5.2 Journal des conflits consultable au siège

Nouveau modèle `sync.SyncConflictLog` : `{id, node_origin, model_label, object_id, conflict_type,
detail_json, detected_at, resolved_at, resolved_by, resolution_note}`. Exposé en lecture (et
résolution manuelle) via `/api/sync/conflicts/` à l'ADMIN/DIRECTION. Toute `REJECTED` répétée au-delà
du seuil (§3.4) y crée automatiquement une entrée.

### 5.3 Transferts inter-boulangeries pendant une désynchronisation prolongée

- Le flux métier (CLAUDE.md §5.4) est déjà en 3 temps et **ne requiert pas que les deux nœuds soient
  en ligne simultanément** : `from_node` crée le `BreadTransfer` en `PENDING` (monte au Cloud dès que
  `from_node` resynchronise) ; le Cloud le redescend vers `to_node` au prochain `pull` de celui-ci (il
  fait partie des objets « Client des autres nœuds en lecture » élargis : en réalité, tout objet dont
  `to_node == ce_nœud` ou `from_node == ce_nœud` est descendu à ce nœud, même créé par l'autre) ;
  `to_node`, quand il resynchronise à son tour, répond localement (`RESPONDED`, quantité reçue) et ce
  changement remonte au Cloud au push suivant ; enfin `from_node` confirme (`CONFIRMED`) ou ouvre un
  litige (`DISPUTED`) au vu de l'écart, lui aussi remonté en différé.
- Donc : **chaque étape attend simplement son tour au prochain cycle de sync de chaque nœud
  concerné**, sans jamais nécessiter de connexion simultanée. Le risque réel est l'incohérence de
  stock local pendant l'attente (le nœud émetteur a déjà décrémenté son stock physique en créant le
  transfert ; le nœud récepteur ne voit l'entrée qu'après son propre pull) — déjà le comportement
  attendu même en ligne (délai de transport physique du pain), donc pas un problème nouveau introduit
  par le hors-ligne.
- Somme nulle au niveau groupe (CLAUDE.md §5.4) : garantie dès que les deux moitiés de l'opération ont
  fini de monter, peu importe le délai — le Cloud ne recalcule rien lui-même ici (contrairement à
  `current_debt`), il consolide simplement deux mouvements locaux déjà correctement signés (−N / +N)
  chacun sur son propre nœud.

### 5.4 Mise à jour de configuration pendant qu'un nœud local est hors-ligne depuis plusieurs jours

- Confirmé (§1.2, §6 H3) : **aucune configuration n'est modifiable en local**, donc il n'y a jamais
  de conflit entrant à résoudre dans ce sens — uniquement un **retard d'application** : le nœud
  continue de facturer avec l'ancienne grille de prix jusqu'à son prochain `pull` réussi. C'est un
  risque métier (facturation à un prix obsolète) à documenter côté exploitation (§6 H4), pas un
  problème de conception de synchro à proprement parler.
- Cas particulier : une facture créée localement avec l'ancien prix, alors que le Cloud a déjà changé
  le prix avant que le nœud ne resynchronise → la facture monte avec `unit_price` déjà figé au moment
  de la création (comportement actuel de `InvoiceLine.save()`, CLAUDE.md §4 « les prix... fige
  `unit_price` »). Le Cloud **ne corrige jamais après coup** le prix d'une ligne de facture déjà
  émise — ce serait falsifier un document commercial déjà remis au client avec son reçu imprimé. Le
  nouveau prix ne s'applique qu'aux factures créées après que ce nœud a reçu la mise à jour.

---

## 6. Points d'arbitrage — décisions du client (2026-10-22)

Les points H1 à H3 ci-dessous ont été soumis au client (M. NDUNGA NSAYI PIERRE) et **tranchés** le
2026-10-22, avant le début de l'implémentation V1 (§11). Ils ne sont plus des points ouverts ; ils
sont documentés ici avec leur décision pour mémoire et pour que `packaging-desktop`/les futurs
agents n'aient pas à les rouvrir.

- **H1 — TRANCHÉ, accepté tel que proposé.** Une clôture de caisse locale (`CashClosure`) saisie
  hors-ligne reste *provisoire* (non inscrite au Livre de Caisse Direction officiel) jusqu'à la
  prochaine synchronisation réussie — conséquence directe de la décision §0 (le Livre de Caisse
  Direction reste une table exclusivement Cloud). Implémenté : `sync.services._push_cash_closure`
  appelle `treasury.services.promote_closure_to_cashbook` uniquement au moment où la clôture est
  effectivement reçue par le Cloud (push ou saisie directe en ligne), jamais avant.
- **H2 — TRANCHÉ.** Décision : réduire automatiquement le plafond de crédit local effectif à **80 %**
  du plafond nominal pendant le mode dégradé (nœud qui a déjà synchronisé puis a cessé de le faire
  au-delà de `Config.degraded_sync_threshold_hours`, 24 h par défaut), en plus de la notification a
  posteriori déjà prévue (§2.2 point 4). Implémenté : `Config.offline_credit_limit_ratio` (0.80 par
  défaut), `Node.is_sync_degraded()`, `sales/views.py::_effective_credit_limit` — voir §11.
  **Précision de mise en œuvre non couverte explicitement par la décision du client, tranchée par
  l'implémentation** : un nœud qui n'a **jamais** synchronisé (`last_sync` NULL, cas de tous les
  nœuds existants avant le déploiement réel du module de sync) n'est PAS considéré dégradé par
  défaut — seul un nœud qui a déjà prouvé qu'il savait se synchroniser puis a cessé de le faire
  l'est. Sans cette précision, le simple déploiement du code mettrait tous les nœuds existants en
  mode dégradé permanent (plafond à 80 % partout, y compris en plein fonctionnement normal en ligne),
  ce qui n'est manifestement pas l'intention de la décision. À confirmer/infirmer explicitement par
  le client si ce n'est pas la lecture voulue.
- **H3 — TRANCHÉ, confirmé.** Aucune configuration (prix, plafond par défaut, catégories de
  consommables) n'est modifiable depuis l'interface d'un nœud local, y compris par un ADMIN local de
  secours créé pendant une coupure prolongée (DESKTOP.md §7 étape 5) : ce compte sert uniquement à
  continuer à facturer/livrer, jamais à changer la configuration. Aucun code de ce dépôt backend
  n'expose de route de modification de `Config`/`BreadPrice`/etc. à un jeton de nœud
  (`sync.permissions.IsValidNodeToken`) — seules les routes `/api/core/*` protégées par JWT
  utilisateur + permissions RBAC existantes le permettent, et restent hors du périmètre
  d'authentification de nœud.
- **H4 (exploitation, pas conception) — hypothèse par défaut conservée**, non rouverte par le client :
  combien de temps maximum un nœud peut-il rester hors-ligne avant qu'un retard de prix/config
  devienne un problème opérationnel réel ? `Config.degraded_sync_threshold_hours` (24 h) sert aussi de
  valeur par défaut raisonnable ici, à affiner avec le client une fois un usage réel observé.
- **H5 (périmètre V1) — hypothèse par défaut conservée**, non rouverte par le client : le siège est
  toujours considéré « en ligne avec lui-même » (il EST le Cloud) ; `sync_now` n'a d'effet utile que
  lancé depuis un nœud local.

---

## 7. Impact sur `SyncableModel` et nouveaux modèles

### 7.1 `SyncableModel` actuel — suffisant pour l'essentiel, avec un ajout

Champs actuels : `id` (UUIDv4), `node_origin`, `is_synced`, `created_at`, `updated_at`. **Suffisants**
pour tous les modèles de la catégorie « montée pure » (§1.2) : au volume réel (8 boulangeries, pas de
méga-concurrence au sein d'un même nœud), un simple « dernier écrivain gagne horodaté par updated_at
serveur » est largement suffisant pour les rares objets mutables multi-étapes (statuts), et aucun
vector clock n'est nécessaire — ce serait une complexité disproportionnée par rapport au volume et au
nombre de nœuds (8, pas 800).

**Un ajout nécessaire, pas sur `SyncableModel` lui-même mais en modèles compagnons** :
- `sync.DebtMovement(SyncableModel)` : `client (FK)`, `invoice (FK, null si origine non-facture)`,
  `amount (Decimal, signé)`, `kind (ORDER|PAYMENT|REPAYMENT)`. Nouveau modèle, cœur de la solution
  §2.2.
- `sync.NodeAuthToken` : jeton de nœud (voir §8), distinct de `User`/JWT. `node (OneToOne vers
  Node)`, `token_hash`, `issued_at`, `revoked_at`, `last_used_at`. Jamais exposé en clair après
  émission (affiché une seule fois au siège lors de la création, comme un token GitHub).
- `sync.SyncBatchLog` : `batch_id (UUID, unique)`, `node (FK)`, `received_at`, `result_json`, pour
  l'idempotence de lot (§3.3, §3.6).
- `sync.SyncConflictLog` : voir §5.2.
- `sync.OutboxBatch` (côté nœud local uniquement, pas synchronisé lui-même) : persistance locale du
  lot en cours de construction/envoi pour permettre la reprise exacte après coupure (§3.6).

### 7.2 Pas de vector clock, décision justifiée

Un vector clock protégerait contre des conflits de mise à jour concurrente sur le **même objet** par
deux nœuds différents — scénario qui, par construction (§1.3, §5.1), ne devrait jamais se produire
légitimement dans ce système : chaque objet mutable a *un seul* nœud autorisé à le modifier à la
fois (machine à états ou propriété exclusive). Le seul cas où deux nœuds affectent réellement « la
même valeur logique » est `current_debt`, déjà résolu par la sommation (§2.2), pas par un
timestamp. Ajouter un vector clock serait de la complexité sans bénéfice mesurable au volume annoncé.

---

## 8. Endpoints API et authentification du nœud

```
POST   /api/sync/handshake/     # vérifie le jeton de nœud, renvoie l'état serveur (version attendue,
                                 # horodatage serveur, statut du nœud actif/suspendu)
POST   /api/sync/push/          # voir §3
GET    /api/sync/pull/          # voir §4
GET    /api/sync/conflicts/     # ADMIN/DIRECTION uniquement, lecture + résolution (§5.2)
GET    /api/sync/status/        # pour le bandeau frontend : dernier push/pull réussi, nb en attente
```

- **Authentification du nœud, distincte de l'authentification utilisateur** : un `NodeAuthToken`
  (§7.1) assigné depuis le menu « Nœuds » du siège (confirme cahierDesCharges.md §6.3.1 — jeton de
  nœud fourni par le siège, déjà mentionné dans DESKTOP.md §7 étape 3). Transporté en
  `Authorization: Bearer <jeton_de_nœud>` sur les routes `/api/sync/*` uniquement — **jamais** le même
  jeton que les JWT utilisateur (qui authentifient une personne, pas une machine). Un utilisateur
  individuel ne peut jamais appeler ces routes avec son propre JWT : middleware dédié qui exige
  spécifiquement un `NodeAuthToken` valide et non révoqué.
- **HTTPS obligatoire** sur toutes les routes `/api/sync/*`, confirmé par le réglage HSTS déjà posé
  par `nettoyeur-securite` (BUG-005) — aucune route de sync ne doit être accessible en HTTP clair, y
  compris en developpement (utiliser un tunnel HTTPS local si besoin de tester le mode desktop avant
  déploiement cloud réel).
- **Révocation** : un nœud suspendu (PC volé, boulangerie fermée) voit son `NodeAuthToken` révoqué
  depuis le siège ; `handshake` renvoie alors 403 et le nœud local repasse en mode strictement
  dégradé (facturation locale continue, plus aucune sync tant qu'un nouveau jeton n'est pas fourni).

---

## 9. Mode hors-ligne frontend

- **Le frontend web pur (navigateur, pas desktop) ne gère pas le hors-ligne en V1.** Aucun Service
  Worker, aucune file IndexedDB côté React web. La continuité de service (objectif n°4 du cahier des
  charges) est assurée **exclusivement par le poste desktop** : c'est le backend Django local
  (SQLite) qui encaisse l'écriture immédiatement, pas le navigateur qui la mettrait en attente. Le
  même code React tourne dans les deux cas (Electron et navigateur), mais seul le premier a un
  backend local à portée de `127.0.0.1` capable de répondre hors-ligne.
- Ce que ça implique concrètement pour `dev-frontend` (à coordonner) : aucune logique de file
  d'attente ni de détection de connectivité réseau à écrire côté composants React eux-mêmes — ils
  continuent d'appeler l'API comme aujourd'hui via `src/api/services.ts`. Le bandeau
  « 🟢 En ligne / 🟠 Hors-ligne — N en attente / 🔴 Erreur de synchronisation » (DESKTOP.md §9) est
  alimenté par un nouvel endpoint **local** `GET /api/sync/status/` exposé par le backend desktop
  lui-même (reflète son propre état de connexion au Cloud, pas celui du navigateur), interrogé par
  polling léger (ex. toutes les 10 s) depuis un composant `SyncStatusBadge` unique dans
  `src/components/layout/`. En contexte web pur (pas de backend local), cet endpoint renvoie
  simplement `{mode: "CLOUD_DIRECT"}` et le composant n'affiche rien.
- Conséquence pour `testeur-charge` : les scénarios de coupure réseau à tester sont des coupures entre
  le **backend desktop et le Cloud**, jamais entre le navigateur et le backend desktop (qui restent
  sur le même PC, donc toujours joignables localement sauf panne totale du poste, hors périmètre
  sync).

---

## 10. Numérotation des reçus hors-ligne

- Déjà conforme en pratique : `sales/views.py::_make_receipt_number` génère
  `"{node_code}-{YYYYMMDD}-{compteur_du_jour_pour_ce_nœud:04d}"`, où le compteur est local à la base
  du nœud (`Invoice.objects.filter(node__code=..., invoice_date=...).count()`). Comme chaque nœud a sa
  propre base en mode desktop, ce numéro est **déjà unique de facto** sans aucune coordination avec le
  Cloud — aucune collision possible entre K1 et K4 même tous deux hors-ligne, le préfixe `node_code`
  suffit. **Aucun changement requis sur ce point pour la synchronisation elle-même.**
- Point de vigilance distinct (hors périmètre sync, à signaler à `dev-backend`/`testeur-ventes`) :
  `count() + 1` n'est pas protégé par un verrou — un risque de collision existe déjà **au sein d'un
  même nœud** en cas de double-clic/requêtes concurrentes sur le même poste, indépendamment de toute
  synchronisation multi-nœuds. Recommandation : remplacer par une séquence locale verrouillée
  (`select_for_update()` sur un compteur dédié par nœud+jour) — **ticket à ouvrir séparément**, ce
  n'est pas un problème de sync.

---

## 11. Plan de mise en œuvre par étapes

### V1 — minimal, codable et testable en une itération raisonnable

1. App `sync/` : modèles `DebtMovement`, `NodeAuthToken`, `SyncBatchLog`, `SyncConflictLog`,
   `OutboxBatch` (ce dernier seulement côté desktop).
2. Endpoints `handshake`, `push`, `pull`, `status`, `conflicts` (lecture seule pour `conflicts` en V1
   — résolution manuelle via `/admin/` plutôt qu'une UI dédiée).
3. Recalcul de `current_debt` au Cloud à la réception de `DebtMovement` (§2.2) — **le scénario de
   test obligatoire le plus important** (deux nœuds facturant le même client hors-ligne).
4. `CashClosure`/`DisbursementVoucher` synchronisés Local→Cloud ; le Cloud appelle
   `append_cashbook_entry()` lui-même à réception (§0) — aucune écriture locale du Livre de Caisse.
5. Signal/`save()` générique sur `SyncableModel` pour marquer `is_synced=False` à chaque création ou
   modification locale (actuellement absent — confirmé par lecture du code, c'est la cause directe de
   BUG-004 au niveau modèle).
6. Commande `manage.py sync_now` (un cycle push+pull manuel) + tâche périodique (service en tâche de
   fond côté desktop, DESKTOP.md §9).
7. Transferts inter-boulangeries : aucun changement de modèle (déjà en 3 temps), seulement
   l'inclusion dans le protocole push/pull standard (§5.3).
8. Frontend : `SyncStatusBadge` unique (§9), pas de logique de file d'attente côté navigateur.

### V2 — après retour d'usage réel, pas bloquant pour le pilote

- UI dédiée de résolution de conflits au siège (au lieu de `/admin/`).
- Compression/delta des payloads `pull` si la volumétrie de `Client`/`BreadPrice` devient significative.
- Chiffrement de la base locale (SQLCipher, déjà évoqué DESKTOP.md §13) — indépendant du protocole de
  sync, mais à coordonner avec `packaging-desktop`.
- Politique de plafond local réduit en mode dégradé prolongé (H2) si le client le demande.
- Option multi-postes par boulangerie en tant que nœuds indépendants (DESKTOP.md §14, explicitement
  « à éviter en V1 » — non traité ici).

---

## 12. Scénarios de test obligatoires (repris de la mission, précisés)

1. **Deux nœuds simulés facturant le même client hors-ligne** → après synchronisation des deux, la
   dette au Cloud est la somme exacte des deux mouvements, indépendamment de l'ordre d'arrivée des
   deux pushes (test à exécuter dans les deux ordres pour prouver la commutativité).
2. **Push rejoué deux fois** (même `batch_id`, ou même objets avec un nouveau `batch_id`) → aucun
   doublon dans aucun modèle, `SyncBatchLog` confirme la détection du rejeu.
3. **Coupure au milieu d'un lot** → simuler une coupure après que le Cloud a persisté une partie des
   enregistrements mais avant que le nœud ne reçoive la réponse → reprise sans perte ni doublon.
4. **Changement de prix au Cloud pendant qu'un nœud est hors-ligne** → reçu par le nœud au premier
   `pull` suivant la reconnexion, les factures créées hors-ligne avant restent au prix figé au moment
   de leur création (non rétroactif).
5. *(Ajout recommandé par cette conception, pas dans la liste initiale mais nécessaire pour couvrir
   §0)* : une clôture de caisse créée hors-ligne, synchronisée après coup, produit bien une
   `CashbookEntry` dont le hash chaîne correctement sur la dernière entrée globale existante au moment
   de la synchronisation (pas au moment de la création locale) — preuve que le choix §0 élimine
   effectivement tout risque de fourche.

---

## 13. Ce que ce document ne tranche pas (volontairement, à signaler)

- Le détail d'implémentation exact du throttling/anti-rejeu abusif d'un nœud compromis qui spammerait
  `push` (hors périmètre conception, relève de la sécurité réseau générale déjà traitée en partie par
  `nettoyeur-securite`).
- Le format exact de la barre de progression de la première synchronisation descendante (DESKTOP.md
  §7 étape 4) — relève de `dev-frontend`/`packaging-desktop`, pas de l'architecture de sync elle-même.
