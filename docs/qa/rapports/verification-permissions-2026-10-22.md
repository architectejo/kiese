# Rapport de vérification — testeur-permissions — 2026-10-22

Vérification indépendante et critique (CLAUDE.md §7 règle 3) des corrections apportées par
`dev-backend`/`dev-frontend` sur les tickets BUG-022 à BUG-027, ouverts par moi-même en
phase 2. Méthode : relecture de code + contournement actif systématique (IDs forgés,
payload avec `node`/`node_origin` falsifié, test du cas limite « transfert entre deux
nœuds tiers ») plutôt que simple relecture, conformément à la consigne reçue.

Tous les tests exclusivement via `python manage.py test` (base de test éphémère),
conformément à PLAN_2026-10-22.md §0.1. Aucun fichier applicatif modifié ; seul un fichier
de test a été ajouté : `backend/core/tests/test_permissions_verif_2026_10_22.py` (complète
`backend/core/tests/test_permissions.py`, ne le remplace pas).

## Résultat global

| Ticket | Statut avant | Verdict | Statut après |
|---|---|---|---|
| BUG-022 | CORRIGÉ | Faille résiduelle confirmée (écriture) | **ROUVERT** |
| BUG-023 | CORRIGÉ | Aucune faille | **VÉRIFIÉ** |
| BUG-024 | CORRIGÉ | Aucune faille | **VÉRIFIÉ** |
| BUG-025 | CORRIGÉ | Faille résiduelle confirmée (update) | **ROUVERT** |
| BUG-026 | CORRIGÉ | Aucune faille, décision justifiée | **VÉRIFIÉ** |
| BUG-027 | CORRIGÉ | Aucune faille | **VÉRIFIÉ** |

Commande de non-régression relancée deux fois : `python manage.py test core production`
→ 68 tests, `FAILED (failures=5)` — les 5 échecs sont exactement les 5 tests que j'ai
écrits pour prouver les failles résiduelles de BUG-022 (4) et BUG-025 (1) ; **aucune
régression** sur les tests livrés en phase 2/3 (tous passent toujours).

## BUG-022 — ROUVERT (fuite inter-nœuds en écriture, sur les 5 ViewSets eux-mêmes)

La correction de `dev-backend` a bien ajouté le filtrage en **lecture** (`get_queryset()`)
sur les 5 ViewSets cités par le ticket. Mais je me suis demandé : si on peut forger un
`node` en lecture, peut-on aussi le forger en **écriture** — exactement le motif que
BUG-025 corrige par ailleurs sur `ClientViewSet` ? Réponse : oui, sur 4 des 5 ViewSets, le
motif vulnérable `node = serializer.validated_data.get('node') or user.node` (ou son
équivalent `obj = serializer.save()` sans forcer `node`) est resté intact :

1. `POST /api/core/colis/` avec `node=<K2>` par un GERANT K1 → `ColisDistribution` créée
   sur K2.
2. `POST /api/clients/contributions/` avec `node=<K2>` par un GERANT K1 → `SocialContribution`
   créée sur K2.
3. `POST /api/clients/distributions/` avec `node=<K2>` par un GERANT K1 → `SocialDistribution`
   créée sur K2.
4. `POST /api/production/movements/` avec `node=<K2>`/`stock=<stock K2>` par un GERANT K1 →
   `ConsumableMovement` créé sur K2, **et le stock réel de consommable de K2 est modifié**
   depuis un compte K1.
5. `POST /api/core/notifications/` avec `node_origin=CLOUD` par un GERANT K1 →
   `SystemNotification` créée avec `node_origin=CLOUD`, visible par **tous les nœuds**
   comme une fausse alerte siège (`SystemNotificationViewSet` est resté un `ModelViewSet`
   complet, la correction n'a touché que `get_queryset`/`mark_read`/`mark_all_read`).

Les 5 scénarios ont été reproduits par des tests qui échouent sur le code actuel :
`backend/core/tests/test_permissions_verif_2026_10_22.py::ForgedNodeOnWriteTests` (4 tests)
et `::NotificationForgedOriginTests` (1 test).

Gravité confirmée **Bloquant**, identique à l'ouverture initiale : c'est le même risque
(fuite/falsification inter-nœuds de données financières/sociales/stock), simplement côté
écriture plutôt que lecture. Correctif suggéré pour la prochaine itération de
`dev-backend` : répliquer sur `ColisDistributionViewSet.perform_create`,
`SocialContributionViewSet.perform_create`, `SocialDistributionViewSet.perform_create`,
`ConsumableMovementViewSet.perform_create` exactement le motif déjà appliqué sur
`ClientViewSet.perform_create` (BUG-025) : pour un utilisateur non-HQ, imposer
`node = user.node` sans jamais lire `validated_data.get('node')`. Pour
`SystemNotificationViewSet`, soit désactiver `create`/`update`/`destroy` pour les non-HQ
(les notifications métier passent normalement par `core.utils.create_notification`, pas
par saisie manuelle), soit forcer `node_origin = user.node.code` côté serveur pour un
non-HQ.

## BUG-023 — VÉRIFIÉ

`get_queryset()` (`Q(from_node=user.node) | Q(to_node=user.node)`) et
`_check_node_involved` relus et confirmés corrects. `perform_create` force
systématiquement `to_node=user.node` — aucune falsification possible à la création,
contrairement aux ViewSets de BUG-022.

Cas limite testé en plus des tests déjà livrés (non explicitement couvert par eux) :
un transfert entre **deux boulangeries tierces** (K2↔K3), avec un GERANT K1 étranger aux
deux. Résultat : liste filtrée (absent), détail par UUID connu → 404, `respond_to_request`
par UUID connu → 403/404. Aucune fuite. Test :
`BreadTransferForgedIdTests::test_unrelated_gerant_gets_404_not_a_leak`.

## BUG-024 — VÉRIFIÉ

Route confirmée : `backend/core/urls.py` expose `TokenRefreshView` exactement à
`/api/core/auth/login/refresh/` (URL attendue par `frontend/src/api/client.ts`).
Rejoué le cycle complet de bout en bout (pas seulement relecture) :
login → `POST .../refresh/` avec le refresh initial → nouvel `access` **réellement
utilisable** (vérifié par un `GET /api/core/auth/me/` → 200 avec ce nouvel access, pas
seulement la présence du champ dans la réponse JSON) → `POST .../logout/` avec ce refresh
→ nouvelle tentative de refresh avec le même token → 401. Test :
`RefreshCycleIndependentTests::test_full_refresh_and_logout_cycle`, passe intégralement.

## BUG-025 — ROUVERT (create corrigé, update toujours falsifiable)

`ClientViewSet.perform_create` est bien corrigé : `node = user.node` est désormais imposé
sans lecture du payload pour un non-HQ. Mais la correction ne touche pas
`ClientViewSet.perform_update` (`client = serializer.save()`, sans filtrage), et
`ClientSerializer` (utilisé pour `update`/`partial_update`) déclare `node` comme un champ
normal, ni `read_only`, ni filtré par rôle.

Test : `ClientNodeMoveViaUpdateTests::test_gerant_k1_cannot_move_its_own_client_to_k2_via_patch`
— un GERANT K1 crée un client sur K1 (légitime), puis `PATCH
/api/clients/clients/<id>/` avec `{"node": "<uuid K2>"}` → HTTP 200, **le client est
effectivement déplacé vers K2** en base. Échoue sur le code actuel.

Gravité confirmée au moins **Majeur** : un GERANT peut déplacer n'importe quel client de
sa propre boulangerie vers une autre à volonté, sans aucune validation de la boulangerie
destinataire (contrairement au transfert de pains, BUG-023), ce qui fausse silencieusement
la répartition de clientèle et, en aval, les commissions par boulangerie (CLAUDE.md §5.3).
Correctif suggéré : dans `perform_update`, pour un utilisateur non-HQ, ignorer toute
valeur de `node` envoyée (conserver `serializer.instance.node`) — symétrique à la
correction déjà faite sur `perform_create`.

## BUG-026 — VÉRIFIÉ (décision cohérente, aucun rôle légitime bloqué)

`CashbookEntryViewSet` confirmé `ReadOnlyModelViewSet` + `permission_classes =
[IsHeadquarters]`, cohérent avec `DisbursementVoucherViewSet` (même fichier, déjà
`IsHeadquarters`). J'ai contre-vérifié la justification directement dans
`cahierDesCharges.md` (pas seulement fait confiance à la fiche de correction) :
- §5.1.3 qualifie explicitement ce registre de « Livre de Caisse Direction (Siège
  Central) ».
- §6.4/schéma des terminaux : « Ordinateur de Bureau : Vue large optimisée pour la
  Direction Générale et le Comptable. Permet l'analyse approfondie du Livre de Caisse... »
  — aucune mention d'un GERANT/FACTURIER/LIVREUR comme destinataire.

Tests : `CashbookHQRoleTests::test_comptable_role_is_allowed` (200) et
`::test_gerant_role_is_forbidden` (403, y compris sur sa propre boulangerie) — les deux
passent, confirmant qu'aucun rôle légitime n'est bloqué par erreur.

## BUG-027 — VÉRIFIÉ

`Nodes.tsx` relu : `maxLength={5}`, troncature défensive `onChange`
(`.toUpperCase().slice(0, 5)`), validation explicite en tête de `handleSubmit` avec
message d'aide clair, texte d'aide permanent sous le champ. Trois protections
indépendantes (HTML, JS, validation avant appel API) — robuste même si l'une des trois
est contournée. Pas de nouveau `any` introduit.

## Fichiers modifiés par cette vérification

- `backend/core/tests/test_permissions_verif_2026_10_22.py` (nouveau, 7 classes de test,
  11 tests) — tests d'attaque indépendants pour BUG-022/023/024/025/026.
- `docs/qa/REGISTRE_BUGS.md` — statuts de BUG-022 (→ ROUVERT) et BUG-025 (→ ROUVERT) dans
  le tableau de suivi et les fiches détaillées ; sections « Vérification » ajoutées pour
  BUG-023, BUG-024, BUG-026, BUG-027 (→ VÉRIFIÉ).

Aucun fichier de code applicatif modifié (conforme à la règle « les testeurs ne corrigent
pas le code applicatif »).

## Suite recommandée

1. `dev-backend` reprend BUG-022 (écriture, 5 ViewSets) et BUG-025 (update) en une seule
   itération, ce sont littéralement le même motif de correction déjà appliqué une fois sur
   `ClientViewSet.perform_create` — à répliquer sur `perform_create`/`perform_update` des
   6 ViewSets concernés (`ColisDistributionViewSet`, `SocialContributionViewSet`,
   `SocialDistributionViewSet`, `ConsumableMovementViewSet`, `SystemNotificationViewSet`,
   `ClientViewSet.perform_update`).
2. Je repasserai BUG-022/BUG-025 en VÉRIFIÉ une fois la correction livrée, en relançant
   exactement les mêmes tests (`test_permissions_verif_2026_10_22.py`), qui devront passer
   sans modification.
3. BUG-023, BUG-024, BUG-026, BUG-027 sont clos de mon côté — aucune action supplémentaire
   attendue sur ces quatre tickets.
