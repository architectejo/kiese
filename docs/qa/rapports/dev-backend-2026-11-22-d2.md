# Rapport dev-backend, 2026-11-22 (ronde d2, partie Sync)

Source : `docs/qa/rapports/testeur-charge-2026-11-22-b2.md`, tickets BUG-720 à BUG-733 (hors 734 à 736, autre agent).
Périmètre touché : `backend/sync/` uniquement (services, views, models, serializers, `sync_now.py`, migration 0002). `clients/` non modifié.

## Tickets corrigés (12)

| Ticket | Correction |
|---|---|
| BUG-722 (bloquant) | `_preflight` : `node` et `node_origin` du payload doivent égaler le nœud du jeton (Client, Invoice, DebtMovement, CashClosure, ProductionSession, dépenses, rapports, social...). Propriété d'un enregistrement déjà connu contrôlée (conflit `NON_PROPRIETAIRE`). Lignes (facture, session, distribution, transfert) rattachées uniquement aux parents du nœud. Clôture d'une autre boulangerie : rejetée, aucune `CashbookEntry`. |
| BUG-721 (bloquant) | `_validate_fields` : plage, longueur, énumération de chaque champ du modèle présent (via `field.clean`), identique à PostgreSQL. `DebtMovement` : `abs(montant) < 10^12` et cumul client borné ; `line_total` borné. Rejet REJECTED avec motif français. |
| BUG-726 | Migration `sync/0002` : `SyncBatchLog` unique sur (nœud, batch_id), champ `fingerprint` (SHA-256 des `records`). Même batch_id et contenu différent : 409 ; batch_id d'un autre nœud : traité normalement, aucune fuite. Anciens lots (fingerprint vide) : rejeu accepté comme avant. |
| BUG-730 | Clé (inventaire, type) ; second jeu de valeurs : REJECTED + conflit `CONSUMABLE_COUNT_DUPLICATE`. |
| BUG-731 | Résultat de ligne porte `inventory` ; `apply_push_response` ne marque pas un inventaire synchronisé si une de ses lignes est rejetée. |
| BUG-725 | Statut et mode de paiement validés par énumération ; `order_total`, `payment_amount`, `initial_order_total` négatifs rejetés. |
| BUG-728 | `apply_debt_movement` calcule la dette d'ouverture (dette stockée moins somme des mouvements) sous `select_for_update` et la conserve ; rejeu idempotent. `recompute_client_debt(client_id)` inchangé sans `opening`. |
| BUG-720 | Valeur de modèle non liste, enregistrement non objet : REJECTED ; id UUID strict (entier, booléen, flottant refusés) ; corps non objet : 400 ; `batch_id` non chaîne : 400. |
| BUG-723 | `_log_conflict` dédoublonne ; champ `occurrences` (migration 0002, exposé dans le serializer). |
| BUG-724 | Collision de code : conflit `CODE_CLIENT_DUPLIQUE` journalisé ; motif du repli `except Exception` générique (détail au journal serveur). |
| BUG-727 | Mouvement rejoué avec un autre montant, client ou nœud : REJECTED + conflit `MOUVEMENT_IMMUABLE_MODIFIE`. |
| BUG-733 | `apply_push_response` tolère toute réponse malformée. |

Les marques `@expectedFailure` des 29 tests correspondants ont été retirées dans les deux fichiers `_v2`.

## Laissés OUVERTS (partiellement corrigés)

- BUG-729 : date future et quantité négative corrigées. Reste `consumable_type` inconnu : les codes seedés de `ConsumableType` sont FLOUR/SALT/YEAST/OIL (migration 0010), alors que les tests existants (BUG-386, v2) utilisent FARINE/SEL/LEVURE/HUILE. Impossible de rejeter `ZZZ` sans rejeter FARINE. Décision métier : quel est le référentiel officiel des codes ? Test conservé en `@expectedFailure`.
- BUG-732 : (a) et (b) corrigés. Reste (c) cohérence `order_total` / somme des lignes : contredit `test_bug519_invoice_line_prices` (facture à 0, ligne de 3 000 acceptée) et l'ordre d'arrivée en-tête puis lignes. Test conservé en `@expectedFailure`.

## Résultats

- `manage.py test sync` : 166 tests, `OK (expected failures=2)` (les 2 ci-dessus). Première passe : 2 anomalies sur des suites existantes (BUG-146 isolation des stocks, BUG-004 rejeu de transfert) qui poussent un autre nœud avec un seul jeton, d'où l'exemption ci-dessous.
- `manage.py test clients.tests.test_volumetrie_v2` : 11 tests, `OK (expected failures=1)` (BUG-734, autre agent).
- `makemigrations --check --dry-run` : aucun changement. `manage.py check` : 0 problème.
- Suite complète non lancée (consigne).

## Risques et points à arbitrer

1. Contrôle de portée non appliqué à `production.ConsumableMovement` et `production.BreadTransfer` (`SCOPE_EXEMPT_MODELS`) : des tests existants poussent ces modèles pour un autre nœud. Un nœud peut donc encore écrire des mouvements de consommables au nom d'un autre. Pas d'effet sur dette ni livre de caisse. À ticketer avec le propriétaire du module production (adapter les tests puis retirer l'exemption).
2. `DisbursementVoucher` : tout nœud authentifié peut pousser un bordereau (`node_origin='CLOUD'` toléré, test BUG-004 existant) qui écrit une SORTIE au livre de caisse direction. Même classe de faille que BUG-722, mais contrat documenté (SYNC.md §1.2). Proposition : réserver ce handler au nœud SIEGE. À valider.
3. Livre de caisse : une clôture validée du PROPRE nœud poussée reste promue avec `node_origin='CLOUD'` (comportement SYNC.md §0, tests existants). Seule la forgerie inter-nœuds est interdite.
4. Contrat API : nouveau code 409 sur `/api/sync/push/` (même batch_id, contenu différent). `sync.desktop_client` traite déjà les 4xx comme définitifs (abandon du batch_id). Pas d'impact frontend.
5. BUG-728 : la dette d'ouverture est déduite de l'écart dette stockée / mouvements ; une dérive manuelle de `current_debt` est donc conservée, plus « guérie » par recompute (elle ne l'était qu'accidentellement). À rejouer sous PostgreSQL (verrous réels).
6. Validation générique : un champ décimal avec trop de décimales est arrondi à la précision du champ (non rejeté) ; plage entière dépassée = rejet. Une valeur d'énumération ancienne (hors `choices` actuels) venant d'un nœud non mis à jour serait rejetée.
7. Migration `sync/0002` modifie l'unicité de `SyncBatchLog` (index composite) ; réversible.

## Fichiers modifiés

`backend/sync/services.py`, `backend/sync/views.py`, `backend/sync/models.py`, `backend/sync/serializers.py`, `backend/sync/management/commands/sync_now.py`, `backend/sync/migrations/0002_batchlog_fingerprint_conflict_occurrences.py` (nouveau), `backend/sync/tests/test_hostile_payloads_v2.py` et `test_consumables_prices_resilience_v2.py` (retrait de `@expectedFailure` uniquement), `docs/qa/REGISTRE_BUGS.md` (statuts).
