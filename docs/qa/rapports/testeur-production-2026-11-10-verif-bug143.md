# Rapport testeur-production — 2026-11-10 — Vérification BUG-143

## Mission

Vérifier indépendamment la correction de **BUG-143** livrée par `dev-backend` (stock de
consommable autorisé à devenir négatif plutôt que de bloquer l'enregistrement d'une fournée —
ANNULE explicitement BUG-041), examiner la conséquence signalée mais non tranchée sur
`sync/services.py::_push_consumable_movement`, et décider du statut final du ticket.

## 1. Relecture critique indépendante

Relu intégralement :
- `backend/production/models.py::ConsumableMovement.save()` (branche `EXIT`/`is_new`, lignes
  563-614).
- `backend/production/views.py::ProductionSessionViewSet.perform_create()`,
  `_record_consumable_exits()`, `_check_overconsumption()`, `ConsumableMovementViewSet.perform_create()`.
- `backend/sync/services.py::_push_consumable_movement`.

Confirmé : le `raise ValidationError(...)` posé par BUG-041 a bien été retiré sans rien laisser en
place qui bloquerait encore une sortie pour stock insuffisant. Les `try/except
DjangoValidationError` restants dans `production/views.py` sont inertes pour ce motif précis (ils
ne peuvent se déclencher que pour une AUTRE validation de modèle, qui n'existe pas aujourd'hui pour
ce chemin). Le verrou `select_for_update()`, la valorisation au CUMP (`average_unit_cost`, BUG-123)
figée **avant** la mise à jour `F('quantity') - quantity`, et la notification `WARNING` en cas de
passage en négatif sont tous intacts et corrects.

## 2. Scénario bout-en-bout construit indépendamment

Fichier : `backend/production/tests/test_verif_bug143_testeur_production.py` (3 classes, 3 tests,
tous construits moi-même, pas une relecture des tests de dev-backend) :

1. **`NormalPathStillDecrementsStockTests`** — contrôle positif, cas réel du client reproduit à ma
   façon : `ConsumableStock.quantity=0` pour FLOUR, déclaration de fournée
   `POST /api/production/sessions/` avec `flour_sacks_used=4.50` → `201`, stock → `-4.500`,
   `ConsumableMovement.unit_price` figé au CUMP déjà en place (`210000.0000`, BUG-123 intact),
   `SystemNotification` WARNING créée sans bloquer. Confirme exactement le comportement attendu.

2. **`NoStockRowAtAllTests`** — scénario que je n'ai pas vu couvert par dev-backend : AUCUNE ligne
   `ConsumableStock` n'existe du tout pour (nœud, FLOUR) (pas même à quantité 0) — situation
   possible si personne n'a encore visité la page « Stocks Consommables »
   (`ConsumableStockViewSet._ensure_stock_accounts()` est le seul endroit qui crée cette ligne, et
   `ProductionSessionViewSet.perform_create()` ne l'appelle jamais). Résultat : la fournée est bien
   enregistrée (`201`, conforme à BUG-143), **mais** `_record_consumable_exits()`
   (`ConsumableStock.objects.filter(...).first()` → `None` → `if stock:` faux → `continue`) ne crée
   ni ligne de stock, ni `ConsumableMovement`, ni notification — la consommation de farine disparaît
   silencieusement. **Ce n'est pas une régression de BUG-143** : j'ai vérifié que ce chemin produisait
   déjà exactement ce même silence avant la correction (avec BUG-041, le `if stock:` empêchait déjà
   d'atteindre le `raise`). C'est un bug distinct, plus grave qu'un simple stock négatif puisqu'il n'y
   a même pas de trace à corriger après coup. Ouvert séparément : **BUG-147**.

3. **`SyncConsumableValuationRiskTests`** — reproduction du risque signalé par dev-backend sur
   `sync/services.py::_push_consumable_movement` : un EXIT Cloud de farine arrivant avant son ENTRY
   correspondante est accepté avec `unit_price=0.0000` (CUMP d'une ligne `ConsumableStock` Cloud
   créée paresseusement par `get_or_create`). Une fois l'ENTRY réellement synchronisée, le **stock**
   redevient correct en quantité (déjà testé par dev-backend dans
   `sync/tests/test_sync_bug004_extension.py`, vérifié indépendamment ici aussi), mais le
   `unit_price` du `ConsumableMovement` EXIT déjà écrit **reste figé à 0** pour toujours — rien ne le
   recalcule rétroactivement. Confirmé **réel au niveau du code**, pas seulement une crainte
   théorique.

## 3. Impact réel du risque sync — ouvert séparément en BUG-146

- `backend/finance/views.py` (lignes 51-63) agrège directement
  `Σ(ConsumableMovement.quantity × ConsumableMovement.unit_price)` sur tous les mouvements `EXIT` de
  l'année pour calculer le COGS (BUG-123) — ce risque touche donc potentiellement des calculs déjà
  vérifiés par `auditeur-comptable`/finance, pas seulement la production.
- **Le module sync n'est pas une fonctionnalité théorique ou abandonnée** : `backend/sync/`
  (handshake/push/pull/status/conflicts), le client desktop (`backend/sync/desktop_client.py`,
  `desktop_status.py`) et l'application Electron (`desktop/`, avec `desktop/dist-installer/` déjà
  généré, `packaging-desktop` et `testeur-installation` ayant déjà livré des rapports d'installation
  réels le 2026-10-23, `architecte-sync` ayant étendu le périmètre jusqu'au 2026-11-02) sont
  construits et testés activement. L'item n°4 du backlog initial de CLAUDE.md §6
  (« synchronisation nœud local ↔ cloud non implémentée ») est **obsolète** — je le signale pour
  mémoire (pas une contradiction entre documents de référence à arbitrer, simplement un backlog de
  départ déjà largement dépassé par le travail ultérieur).
- **Mais à ce jour (2026-11-10), aucun nœud desktop n'est synchronisé en continu contre la base
  réelle.** Vérifié directement en lecture seule sur `backend/db.sqlite3` (`sqlite3` en mode `ro`,
  sans passer par l'ORM pour ne pas risquer d'interférer avec la session client active) :
  `sync_syncbatchlog`, `sync_syncconflictlog` et `sync_nodeauthtoken` sont tous à **0 ligne**. Le test
  en direct du matin qui a motivé BUG-143 se faisait directement sur le Cloud, pas via un nœud
  desktop. Le risque est donc réel pour le déploiement multi-boulangeries à venir, mais n'affecte
  **personne aujourd'hui**.
- **Conclusion** : ce point ne bloque pas la vérification de BUG-143, qui est strictement scopé sur
  l'enregistrement local d'une fournée et fonctionne comme demandé. Ouvert séparément en **BUG-146**
  (Majeur, OUVERT, assigné implicitement à `architecte-sync`/`auditeur-comptable` — à traiter avant
  la mise en service réelle de la synchronisation multi-nœuds, pas avant).

## 4. Non-régression

```
backend/.venv/Scripts/python.exe manage.py test production sales finance sync
→ Ran 303 tests in 731.580s — OK
```
(dev-backend n'avait testé que `production sales finance`, 231/231 ; j'ai ajouté `sync` à la demande
de la mission — 72 tests supplémentaires, tous passent.)

```
backend/.venv/Scripts/python.exe manage.py makemigrations --check --dry-run
→ No changes detected
```

Aucun processus de test n'a touché `backend/db.sqlite3` (base de test éphémère en mémoire
`memorydb_default`). Le serveur de dev préexistant sur le port 8000 (mauvais interpréteur, session
client) n'a pas été touché.

## 5. Tickets ouverts dans `docs/qa/REGISTRE_BUGS.md`

- **BUG-146** (Sync / Finance, Majeur, OUVERT) : valorisation COGS incorrecte et non corrigée
  rétroactivement sur un `ConsumableMovement` EXIT synchronisé avant son ENTRY — réel mais non
  bloquant aujourd'hui (aucun nœud desktop synchronisé en continu). Pour `architecte-sync` /
  `auditeur-comptable`, à traiter avant mise en service réelle de la synchronisation multi-nœuds.
- **BUG-147** (Production, Majeur, OUVERT) : si aucune ligne `ConsumableStock` n'existe du tout pour
  un (nœud, consommable), `_record_consumable_exits()` perd silencieusement toute trace de la
  consommation (ni mouvement, ni stock créé, ni notification) lors d'une déclaration de fournée.
  Préexistant à BUG-143 (pas une régression de cette correction), pour `dev-backend`.

## 6. Décision finale

**BUG-143 passé à VÉRIFIÉ** dans `docs/qa/REGISTRE_BUGS.md` (table de suivi + fiche détaillée avec
section Vérification ajoutée). La correction fonctionne exactement comme demandé par le client :
plus aucune fournée n'est bloquée pour stock de consommable insuffisant, le stock négatif est
valorisé correctement (CUMP intact) et signalé par notification sans bloquer. Non-régression
confirmée sur `production sales finance sync` (303/303). Les deux découvertes connexes (BUG-146,
BUG-147) sont documentées séparément et ne remettent pas en cause cette vérification.

## Fichiers

- Créé : `backend/production/tests/test_verif_bug143_testeur_production.py`
- Modifié : `docs/qa/REGISTRE_BUGS.md` (statut BUG-143 → VÉRIFIÉ + section Vérification ; nouvelles
  fiches BUG-146 et BUG-147 + lignes dans le tableau de suivi)
- Ce rapport : `docs/qa/rapports/testeur-production-2026-11-10-verif-bug143.md`
