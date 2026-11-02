# Rapport — architecte-sync — 2026-11-02 — Extension BUG-004 (PUSH_HANDLERS)

## Mission

Étendre `sync.services.PUSH_HANDLERS` (et le pull correspondant si
applicable) aux modèles synchronisables restés hors périmètre de la V1
(documenté comme un périmètre volontairement limité dans
`docs/architecture/SYNC.md` §11, pas un oubli) :

- `production.ProductionSession`, `production.BreadTransfer`,
  `production.BreadDisposal`, `production.ConsumableMovement`
- `treasury.LocalExpense`, `treasury.FacturierReport`,
  `treasury.DisbursementVoucher`
- `clients.SocialContribution`, `clients.SocialDistribution`

Contrainte : ne pas changer le mécanisme déjà conçu (ordre de dépendance,
idempotence, gestion des rejets), seulement l'étendre modèle par modèle.

## Résumé du résultat

| Modèle | Statut |
|---|---|
| `production.ProductionSession` | **Câblé** |
| `production.ProductionSessionLine` | **Câblé** (dépendance de `ProductionSession`, non listée explicitement dans la mission mais nécessaire pour que les lignes remontent — sans elle, `ProductionSession` serait synchronisée sans son détail par catégorie de pain) |
| `production.BreadDisposal` | **Câblé** |
| `production.ConsumableMovement` | **Câblé** |
| `production.BreadTransfer` | **Câblé** |
| `production.BreadTransferLine` | **Câblé** (même remarque que `ProductionSessionLine`) |
| `treasury.LocalExpense` | **Câblé** |
| `treasury.FacturierReport` | **Câblé** |
| `treasury.DisbursementVoucher` | **Câblé** |
| `clients.SocialContribution` | **HORS PÉRIMÈTRE** — voir « Contradiction signalée » ci-dessous |
| `clients.SocialDistribution` / `SocialDistributionLine` | **HORS PÉRIMÈTRE** — idem |

Tous les nouveaux handlers suivent exactement le mécanisme déjà en place
(upsert par UUID, rejet explicite « dépendance manquante » jamais deviné,
chaque enregistrement dans sa propre transaction, `_sync_bypass=True` pour
ne jamais re-marquer `is_synced=False` un enregistrement qu'on vient
d'accepter côté Cloud). Aucun changement structurel au protocole, à
`PushView`/`PullView`, ni à `SyncBatchLog`/`SyncConflictLog`.

## Contradiction signalée au coordinateur (ne pas trancher seul, CLAUDE.md §7 règle 6)

`clients.SocialContribution`, `clients.SocialDistribution` et
`clients.SocialDistributionLine` (`backend/clients/models.py` lignes
194-250) sont des `models.Model` **ordinaires**, avec une clé primaire
`BigAutoField` — **pas des `SyncableModel`** (pas d'UUID, pas de
`node_origin`, pas de `is_synced`). Ce n'est pas un oubli de ma part : je
l'ai vérifié directement sur le code (`id` de type `BigAutoField` confirmé
via `_meta.get_fields()`).

Or CLAUDE.md §4 est explicite : *« Les modèles métier synchronisables
héritent de `core.models.SyncableModel` : clé UUIDv4... Ne jamais introduire
d'ID auto-incrémenté sur une entité synchronisable. »*

Les intégrer dans `PUSH_HANDLERS` telles qu'elles sont aujourd'hui
exposerait exactement le risque que cette règle interdit : une PK entière
auto-incrémentée **locale à chaque nœud** poussée vers le Cloud comme
identifiant cross-nœud produirait des collisions garanties dès que deux
boulangeries créeraient chacune leur `SocialContribution` n°1, n°2, etc. —
contrairement à `Client`/`Invoice`/`DebtMovement`/..., dont l'UUID est
globalement unique par construction.

Deux options existent, et je ne tranche pas seul laquelle retenir
(contradiction entre « étendre la sync à ces modèles » demandé par la
mission et « ne jamais introduire d'ID auto-incrémenté sur une entité
synchronisable » imposé par CLAUDE.md §4) :

1. **Convertir `SocialContribution`/`SocialDistribution`/
   `SocialDistributionLine` en `SyncableModel`** (migration de schéma +
   migration de données pour réécrire les PK existantes en UUID, et mettre
   à jour toutes les FK qui pointent vers elles). C'est un changement de
   modèle, pas une extension du protocole de sync — explicitement hors du
   cadre « ne pas changer l'architecture existante, seulement l'étendre »
   donné par cette mission.
2. **Ne pas synchroniser ces deux modèles en V1** (statu quo) : la caisse
   sociale (cotisations/distributions annuelles) est, dans la pratique
   observée (`cahierDesCharges.md`, `adaptes.md`), une opération à
   périodicité mensuelle/annuelle gérée au siège ou fortement supervisée —
   le risque d'un nœud qui saisirait une cotisation hors-ligne avant une
   distribution annuelle calculée au Cloud est significativement plus
   faible que pour les ventes/production quotidiennes. Si c'est le cas,
   la mission devrait être amendée pour exclure ces deux modèles
   explicitement (comme documenté plus haut dans ce rapport), avec un
   ticket séparé pour la migration de schéma le jour où le besoin réel
   (saisie locale hors-ligne de cotisations) se confirme.

**Décision prise pour cette session** : par prudence (CLAUDE.md §7 règle 6 —
signaler une contradiction au coordinateur plutôt que trancher seul), je
n'ai **pas** modifié le schéma de `SocialContribution`/`SocialDistribution`.
Le lot `push` qui contiendrait ces modèles reçoit un rejet explicite et
documenté (`"modèle non supporté en V1"`, comportement déjà existant du
code pour tout modèle absent de `PUSH_HANDLERS`, SYNC.md §3.4) — testé par
`UnsupportedModelsAreExplicitlyRejectedTests` dans le nouveau fichier de
tests. Rien n'est silencieusement ignoré.

## Détail des handlers ajoutés (`backend/sync/services.py`)

Ordre de traitement ajouté à `PUSH_MODEL_ORDER`, conforme à SYNC.md §3.5
points 4 à 6 :

```
clients.Client
sales.Invoice
sales.InvoiceLine
sync.DebtMovement
production.ProductionSession
production.ProductionSessionLine
production.BreadDisposal
production.ConsumableMovement
production.BreadTransfer
production.BreadTransferLine
treasury.LocalExpense
treasury.FacturierReport
treasury.CashClosure
treasury.DisbursementVoucher
```

### `ProductionSession` / `ProductionSessionLine`

- Upsert par UUID. Transition idempotente `is_closed: False → True`
  (jamais de régression), symétrique à `Invoice.status`.
- `ProductionSessionLine` dépend de `ProductionSession` (rejet explicite
  « dépendance manquante : session » si absente) et de `BreadPrice`
  (référentiel descendant du Cloud, résolu par id entier comme pour
  `InvoiceLine`).
- **Point de vigilance documenté dans le code et les tests** :
  `ProductionSessionLine` (comme `InvoiceLine`, précédent déjà existant
  dans la V1) est une PK entière auto-incrémentée **locale au nœud**, pas
  un `SyncableModel`. Le payload ne pousse donc **jamais** cette PK locale
  comme identifiant cross-nœud ; l'idempotence repose sur la contrainte
  `unique_together (session, bread_price)` (capture d'`IntegrityError`).
  Cette limitation est héritée telle quelle du mécanisme déjà en place
  pour `InvoiceLine` — je ne l'ai pas introduite, je l'ai reproduite à
  l'identique pour rester cohérent avec l'architecture existante. Elle
  mériterait un ticket séparé (hors périmètre de cette extension) si l'on
  souhaite un jour permettre la mise à jour d'une ligne déjà poussée par
  son identifiant exact plutôt que par sa combinaison unique.

### `BreadDisposal`

- Dépend de `ProductionSession` et `BreadPrice`. `total_value` est
  recalculé par `BreadDisposal.save()` lui-même (déterministe,
  `quantity × unit_price_sold`) — aucun conflit possible, objet immuable
  après création (SYNC.md §5.1).

### `ConsumableMovement`

- `ConsumableStock` **n'est pas lui-même synchronisé** (confirmé par
  SYNC.md §2.4 : « aucun changement de modèle requis », recalculé/consolidé
  côté Cloud à partir des mouvements uniquement, jamais une valeur
  transportée). Le handler résout/crée donc une ligne `ConsumableStock`
  **consolidée côté Cloud** par `(node, consumable_type)`, alimentée
  paresseusement au premier mouvement vu pour cette paire
  (`node_origin='CLOUD'`, car cette ligne est une construction du Cloud,
  pas la remontée d'un objet créé localement) — le payload transporte donc
  le code `consumable_type` (référentiel stable, descendant du Cloud) en
  plus de l'UUID local du `stock`, qui lui n'est jamais réutilisé comme clé
  de résolution côté Cloud.
- BUG-041 (refus d'un stock négatif) s'applique aussi côté Cloud : si
  l'ENTRÉE correspondante n'est pas encore synchronisée, la SORTIE est
  **rejetée comme une dépendance manquante classique** (jamais acceptée
  silencieusement, jamais devinée) — retentée automatiquement au prochain
  cycle. Testé explicitement
  (`ConsumableMovementSyncTests.test_exit_without_matching_entry_is_rejected_as_missing_dependency_then_retried`).

### `BreadTransfer` / `BreadTransferLine`

- **Point d'architecture important, conforme à la contrainte donnée par la
  mission** (« assure-toi que la sync ne contourne pas la validation
  métier — somme nulle au niveau du groupe, écart bloquant la clôture ») :
  le handler ne rejoue **jamais** `production._adjust_bread_stock()`. Les
  effets sur le stock (déduction chez `from_node` à `RESPONDED`, crédit
  chez `to_node` à `CONFIRMED`/litige si écart) ont déjà eu lieu
  **localement**, au moment de l'action réelle du gérant sur son propre
  nœud (`production/views.py::BreadTransferViewSet.respond_to_request` /
  `confirm_reception`). Le Cloud ne fait que **consolider l'état final**
  du transfert pour reporting — exactement ce que documente SYNC.md §5.3 :
  « le Cloud ne recalcule rien lui-même ici, il consolide simplement deux
  mouvements locaux déjà correctement signés ». Rejouer l'ajustement de
  stock côté Cloud aurait doublé l'effet sur un stock qui, de toute façon,
  n'est pas partagé entre nœud et Cloud en V1 — j'ai donc délibérément
  choisi de ne PAS le faire, ce qui préserve la propriété de somme nulle
  au niveau groupe sans jamais la recalculer ni la revalider côté Cloud
  (elle est garantie par construction du protocole en 3 temps, pas par une
  vérification supplémentaire ici).
- Machine à états : seules les transitions avant (`PENDING→RESPONDED`,
  `PENDING→CANCELLED`, `RESPONDED→CONFIRMED`, `RESPONDED→DISPUTED`) sont
  appliquées ; toute régression est silencieusement ignorée (pas d'erreur,
  comme `Invoice.status`).
- `BreadTransferLine` a la même limitation de PK locale que
  `ProductionSessionLine` (voir ci-dessus) — idempotence par
  `unique_together (transfer, bread_price)`.

### `LocalExpense` / `FacturierReport`

- Dépendance dure sur `ExpenseCategory` (référentiel Cloud) pour
  `LocalExpense` — rejet explicite si absente.
- `FacturierReport` : transition idempotente `is_validated: False → True`
  (le gérant valide après coup une vacation déjà remontée), même principe
  que `ProductionSession.is_closed`.

### `DisbursementVoucher`

- Symétrique exact de `_push_cash_closure` (SYNC.md §0) : c'est le Cloud,
  jamais le nœud, qui appelle `append_cashbook_entry()` à réception — testé
  avec vérification de la chaîne de hash globale après coup
  (`verify_cashbook_chain`), et testé non dupliqué sur rejeu.
- Aujourd'hui, `DisbursementVoucher` est toujours créé avec
  `node_origin='CLOUD'` (`DisbursementVoucherViewSet.perform_create`,
  `IsHeadquarters` uniquement) : ce handler couvre donc, en l'état actuel
  du produit, un cas qui ne se présente pas encore en pratique, mais qui
  est explicitement anticipé par SYNC.md §1.2 (« si un poste direction
  local existe ») — aucune régression, pur ajout de capacité dormante.

## `build_outbound_payload` (`sync_now.py`)

Étendu en miroir exact des nouveaux handlers (mêmes champs, même
dénormalisation `consumable_type`/`unit` pour `ConsumableMovement`), pour
que la commande `sync_now`/le futur service desktop poussent réellement ces
modèles sans action supplémentaire de `packaging-desktop`. Aucun
changement côté `pull` : tous les modèles étendus sont « montée pure »
(Local → Cloud uniquement, SYNC.md §1.2), aucune descente Cloud → Local
n'était attendue pour eux.

## Tests

Nouveau fichier `backend/sync/tests/test_sync_bug004_extension.py` — 15
tests, tous passent (confirmés avant/après : ils échouaient tous avant ce
changement puisque les modèles n'étaient pas dans `PUSH_HANDLERS`, soit
rejetés `"modèle non supporté en V1"`, soit absents du payload de test).

Couverture :
- `ProductionSession`/`ProductionSessionLine` : ordre de dépendance,
  rejet/retry sur dépendance manquante, transition `is_closed` idempotente
  et sans régression, rejeu sans doublon.
- `BreadDisposal` : acceptation + recalcul serveur de `total_value`,
  rejeu sans doublon.
- `ConsumableMovement` : ENTRY puis EXIT consolidés correctement
  (`ConsumableStock` Cloud), EXIT sans ENTRY préalable rejeté puis accepté
  après coup sans jamais passer en négatif.
- `BreadTransfer`/`BreadTransferLine` : cycle complet
  PENDING→RESPONDED→CONFIRMED poussé par deux nœuds différents (K1/K4)
  dans l'ordre réel du protocole (SYNC.md §5.3), jamais de régression sur
  rejeu tardif, mise à jour d'une ligne sans duplication.
- `LocalExpense` : acceptation/idempotence, rejet sur catégorie manquante.
- `FacturierReport` : transition `is_validated` idempotente et sans
  régression.
- `DisbursementVoucher` : promotion unique au Livre de Caisse Direction,
  chaîne de hash vérifiée intègre après coup, rejeu sans deuxième écriture.
- `SocialContribution` : confirmation explicite du rejet
  `"modèle non supporté en V1"` (pas un oubli silencieux).

Commande exécutée : `backend/.venv/Scripts/python.exe manage.py test
sync.tests.test_sync_bug004_extension` → 15/15 OK.

Suite complète relancée après les changements :
`backend/.venv/Scripts/python.exe manage.py test` → **461 tests, OK**,
aucune régression sur les modules déjà couverts par les autres agents
(durée ~14 min sur cette machine).

`backend/.venv/Scripts/python.exe manage.py makemigrations --check
--dry-run` → « No changes detected » : confirmé que cette extension n'a
nécessité **aucune** migration de schéma (purement additive au niveau de
la couche `sync.services`/`sync_now`, conformément à la contrainte « ne pas
changer l'architecture existante »).

## Ce qui reste HORS PÉRIMÈTRE après cette extension

- `clients.SocialContribution`/`SocialDistribution`/`SocialDistributionLine`
  — voir « Contradiction signalée » ci-dessus. Nécessite une décision du
  coordinateur/client avant tout code : migrer leur PK vers UUID (coûteux,
  changement de modèle) ou documenter explicitement leur exclusion
  définitive du périmètre de synchronisation V1/V2.
- Tout ce qui était déjà hors périmètre avant cette session et que je n'ai
  pas touché : bandeau frontend `SyncStatusBadge`, `sync.OutboxBatch` côté
  desktop réel, UI dédiée de résolution de conflits (reste `/admin/`),
  deuxième base de données réellement séparée pour un vrai test de charge
  réseau (`testeur-charge`).

## Statut du ticket

**BUG-004 reste à `CORRIGÉ`** (pas de passage à `VÉRIFIÉ` par moi-même,
conformément à la consigne de cette mission — la vérification sera faite
dans une passe finale groupée par `testeur-charge`/le coordinateur). Fiche
détaillée du registre mise à jour avec le sous-périmètre couvert par cette
extension et la contradiction signalée pour `SocialContribution`/
`SocialDistribution`.

## Fichiers modifiés/créés

- `backend/sync/services.py` — `PUSH_MODEL_ORDER` étendu, 9 nouveaux
  handlers, `PUSH_HANDLERS` étendu.
- `backend/sync/management/commands/sync_now.py` —
  `build_outbound_payload` étendu en miroir.
- `backend/sync/tests/test_sync_bug004_extension.py` — nouveau, 15 tests.
- `docs/qa/REGISTRE_BUGS.md` — fiche BUG-004 mise à jour.
- `docs/qa/rapports/architecte-sync-2026-11-02-bug004-extension.md` — ce
  rapport.
