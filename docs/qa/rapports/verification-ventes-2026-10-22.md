# Vérification — Ventes et Facturation — 2026-10-22

Agent : `testeur-ventes` (phase 4, vérification indépendante des corrections `dev-backend`/`dev-frontend`).
Périmètre : BUG-028 à BUG-032 (ouverts par moi-même en phase 2) et BUG-047 (frontend, conséquence de BUG-036/trésorerie).

## Méthode

- Relecture critique et indépendante du code **actuel** (pas seulement des rapports d'agents précédents) : `backend/sales/views.py`, `backend/sales/serializers.py`, `backend/sales/models.py`, `backend/core/permissions.py`, `frontend/src/pages/dashboard/Sales.tsx`, `frontend/src/api/services.ts`.
- `python manage.py test sales` relancé deux fois (32/32, `OK`), puis `python manage.py test sales -v 2` pour confirmer le détail de chaque test.
- `npx tsc --noEmit` côté frontend : aucune erreur.
- Vérification manuelle en base (`backend/db.sqlite3`, règle §0.1 du plan) pour nettoyer les données `ZZ3-*` laissées en phase 2.

## Résultats

### BUG-028 — `commission_rate=0` forcé pour vente soldée/occasionnelle
**VÉRIFIÉ.** `InvoiceViewSet.create` force `Decimal('0.00')` dès que `is_soldee` est vrai **ou** `client is None`, sans jamais lire le payload dans ces deux cas. Le flux client régulier non soldé continue de lire `commission_rate` avec le même fallback qu'avant — pas de régression. Tests dédiés verts sans `@expectedFailure`.

### BUG-029 — `cleanup_expired` restitue le stock
**VÉRIFIÉ.** La boucle `for line in inv.lines.all(): _adjust_bread_stock(inv.node, line.bread_price, sent=-line.quantity)` est bien présente avant la suppression, avec `prefetch_related('lines__bread_price')` ajouté au queryset. Comportement cohérent avec `cancel()`.

### BUG-030 — `node` forcé côté serveur pour non-HQ
**VÉRIFIÉ.** Pour tout utilisateur `not can_access_all_nodes`, `node_id = request.user.node_id` est imposé, toute valeur `node` du payload est ignorée sans erreur. Seul un utilisateur HQ peut encore préciser un `node` différent du sien.
- Bug annexe signalé (`InvoiceCreateSerializer.node` : `UUIDField` → `IntegerField`) : confirmé cohérent avec `core.models.Node` (`BigAutoField`). Vérifié par grep exhaustif que `frontend/src/api/services.ts` et `Sales.tsx` n'envoient jamais ce champ à la création — aucun risque de régression de contrat côté frontend actuel.
- `CrossNodeFacturationTests` (facturer un **client** d'une autre boulangerie depuis son propre nœud, remarque.md l.10-12) toujours vert — confirmé non cassé, ce flux ne dépend que de `client`, jamais de `node`.

### BUG-031 — `get_permissions()` respecte les `@action(permission_classes=...)`
**VÉRIFIÉ, avec une observation documentée (pas une faille bloquante).**
- Mécanisme DRF vérifié : `get_permissions()` lit bien `getattr(self, self.action).kwargs.get('permission_classes')`, les branches codées en dur restantes ne sont pas élargies au-delà de ce qui existait.
- **Cas limite explicitement demandé par la mission, testé** : un FACTURIER peut-il annuler la facture d'un **autre** facturier du même nœud ? Réponse après lecture du code (`IsFacturier` n'implémente pas `has_object_permission`, qui retombe à `True` ; `get_object()` ne filtre que par nœud) : **oui, c'est possible**. Je ne rouvre pas le ticket pour autant : ce comportement n'élargit rien par rapport au modèle préexistant pour `IsGerant` (un GERANT pouvait déjà annuler la facture de n'importe quel facturier de son nœud, sans contrôle de propriétaire avant cette correction) — BUG-031 étend ce même modèle (rôle + nœud, sans propriétaire) au rôle FACTURIER, conformément au texte littéral de remarque.md l.200 (« le gérant ou le facturier doit avoir la possibilité d'annuler une commande », pas « la sienne »). Un contrôle de propriétaire strict serait un changement de périmètre fonctionnel nouveau, pas une correction de régression — à qualifier avec le coordinateur/client si souhaité.
- Cas cross-node confirmé bloqué (404 via `get_queryset()`, cohérent avec le reste du module).

### BUG-032 — Libellé « Imprimer le reçu »
**VÉRIFIÉ.** Libellé exact confirmé dans `Sales.tsx`, action inchangée, `tsc` propre.

### BUG-047 — Bandeau d'erreur sur `confirmDelivery` (vacation déjà rapportée)
**VÉRIFIÉ.** État `deliveryError` correctement rattaché à `item._apiId` (pas de pollution entre cartes de la file), bandeau affiché dans la vue principale et la modale « Voir plus » (même fonction de rendu). Format `{"detail": "..."}` du backend confirmé compatible avec le `catch`.
- **Point annexe découvert en reproduisant le scénario de bout en bout** (facture → rapport Niveau 1 → nouvelle livraison bloquée) : `Invoice.deliver()` sauvegarde `client.total_breads_received`/`category` **avant** `self.save()` — qui est précisément l'étape que bloque le signal de BUG-036. Une livraison rejetée laisse donc une mise à jour fantôme du client. J'ai reproduit ce comportement indépendamment avec un test ad hoc (confirmé en échec) avant de découvrir qu'il est **déjà ticketé par `testeur-tresorerie` sous BUG-052** (« Livraison bloquée (BUG-036) laisse une mise à jour fantôme du client »), avec sa propre preuve (`backend/treasury/tests/test_bug036_signal_side_effects.py::DeliveryBlockedSideEffectTests`). Je n'ai pas ouvert de second ticket (évite un doublon, CLAUDE.md §7 règle 1) ; mon test ad hoc a été supprimé après confirmation plutôt que versionné en double. Ce point ne remet pas en cause BUG-047 lui-même.

## Anomalie de registre signalée au coordinateur (non tranchée seule)

**Collision de numérotation : deux tickets distincts portent le numéro `BUG-052`** dans `docs/qa/REGISTRE_BUGS.md` :
1. `testeur-clients-commissions` : « Aucun moyen explicite de forcer CM = 0 sur une facture normale... » (module Ventes, reprise de BUG-021).
2. `testeur-tresorerie` : « Livraison bloquée (BUG-036) laisse une mise à jour fantôme du client... » (module Trésorerie/Ventes).

Je n'ai pas renuméroté l'un des deux (pas mon rôle de trancher unilatéralement sur un ticket d'un autre testeur en cours de rédaction concurrente — le fichier a été modifié sur disque plusieurs fois pendant ma session, signe d'une édition concurrente par `testeur-tresorerie`). À renuméroter par le coordinateur (ex. le second en `BUG-054`) dès que les deux agents ont fini d'écrire leurs fiches.

## Nettoyage `backend/db.sqlite3` (règle §0.1 du plan)

Données fictives `ZZ3-*` laissées par moi en phase 2 (un `Client` `ZZ3-0001` et sa facture `PENDING` `ZZ3-20261022-0001`, plus un `DebtMovement` associé) : **supprimées** pendant cette session (plus besoin pour la vérification). Confirmé après coup : `Client.objects.filter(code__startswith='ZZ3').count() == 0` et `Invoice.objects.filter(receipt_number__startswith='ZZ3').count() == 0`.

## État des tests

- `python manage.py test sales` : **32/32, OK** (rejoué deux fois).
- `npx tsc --noEmit` (frontend) : aucune erreur.
- Aucun fichier de code applicatif modifié. Un test ad hoc temporaire a été écrit puis supprimé après avoir confirmé un doublon avec BUG-052 (trésorerie) — aucun nouveau fichier de test laissé dans `backend/sales/tests/`.

## Tickets passés à VÉRIFIÉ dans le registre

BUG-028, BUG-029, BUG-030, BUG-031, BUG-032, BUG-047 — chacun avec une section « Vérification » complète ajoutée à sa fiche dans `docs/qa/REGISTRE_BUGS.md`. Une erreur d'insertion que j'ai moi-même commise en éditant le registre (bloc de vérification BUG-047 collé par erreur au milieu de la fiche BUG-048) a été repérée et corrigée dans la même session — les deux fiches sont désormais intactes et correctement séparées.
