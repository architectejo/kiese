# Rapport dev-backend — 2026-11-10 — BUG-143 (stock de consommable négatif autorisé)

## Contexte

Demande client directe, reçue en test en direct sur la base fraîchement réinitialisée le matin
même (aucun stock de consommable encore saisi), relayée par le coordinateur :

> « Ne pas empêcher l'enregistrement de fournée à cause de "Stock insuffisant pour cette sortie de
> FLOUR : disponible 0.000, demandé ..." fait la négation si il faut. »

Cette demande **ANNULE explicitement BUG-041** (choix délibéré du 2026-10-22 : refuser toute sortie
de consommable qui ferait passer le stock en négatif). CLAUDE.md §1 place une demande client directe
en priorité sur tout document de référence antérieur — aucune ambiguïté à clarifier ici, la consigne
est non équivoque.

## Ticket traité

**BUG-143** — ouvert, corrigé et documenté dans `docs/qa/REGISTRE_BUGS.md` (tableau + fiche détaillée
en fin de fichier). Statut laissé à `CORRIGÉ` (pas `VÉRIFIÉ` — CLAUDE.md §7 règle 3, c'est au
testeur d'origine ou au coordinateur de le vérifier).

## Cause

`ConsumableMovement.save()` (`backend/production/models.py`, branche `EXIT`/`is_new`) comparait
`stock.quantity < self.quantity` et levait `django.core.exceptions.ValidationError` avant toute
écriture — toute la transaction (session de production, lignes, ajustement de `BreadStock`) était
annulée dès qu'un seul consommable manquait, bloquant entièrement l'enregistrement de la fournée.

## Correction

### Fichiers modifiés

- **`backend/production/models.py::ConsumableMovement.save()`**
  - Retiré le `raise ValidationError(...)` sur la branche `EXIT`/`is_new`.
  - Conservé intact : verrou `select_for_update()` dans `transaction.atomic()`, valorisation au CUMP
    (`stock.average_unit_cost`, BUG-123) figée sur `self.unit_price` avant `super().save()`, mise à
    jour atomique `stock.quantity = F('quantity') - self.quantity`.
  - Ajouté : si la sortie fait passer le stock en négatif, une `SystemNotification` (sévérité
    `WARNING`, `node_origin=self.node.code`) est créée — même pattern que l'alerte de manquant de
    rendement (`yield_gap < 0`) déjà en place dans `production/views.py::perform_create`. Ce n'était
    pas obligatoire pour le ticket (laissé à mon jugement) mais c'était nécessaire pour ne pas
    affaiblir le test déjà existant `NegativeConsumableStockTests` (voir plus bas) qui exige soit un
    refus, soit une notification.
  - Suppression de l'import désormais inutilisé `from django.core.exceptions import ValidationError`
    dans `save()`.
  - Commentaire réécrit pour documenter BUG-143 et le fait qu'il annule BUG-041.

- **`backend/production/views.py`** — mise à jour de 3 commentaires qui décrivaient encore le refus
  BUG-041 (`_record_consumable_exits`, `ProductionSessionViewSet.perform_create`,
  `ConsumableMovementViewSet.perform_create`). Les `try/except DjangoValidationError` sont
  **conservés** par prudence (défense en profondeur contre toute AUTRE `ValidationError` du modèle)
  mais ne se déclenchent plus jamais pour un stock insuffisant.

- **`backend/sync/services.py::_push_consumable_movement`** — commentaire mis à jour. Voir section
  « Risque signalé — sync » ci-dessous : conséquence détectée mais **non traitée** dans ce ticket.

- **`backend/sync/tests/test_sync_bug004_extension.py::ConsumableMovementSyncTests`** — le test
  `test_exit_without_matching_entry_is_rejected_as_missing_dependency_then_retried` attendait un rejet
  (`REJECTED`, dépendance manquante) côté Cloud. Comme `ConsumableMovement.save()` est la même
  méthode des deux côtés (local et sync), ce comportement ne peut plus se produire. Remplacé par
  `test_exit_without_matching_entry_is_accepted_and_stock_goes_negative` : vérifie l'acceptation
  immédiate, le stock consolidé négatif, puis sa remise à niveau une fois l'entrée correspondante
  synchronisée (idempotence du rejeu conservée).

- **`backend/production/tests/test_consumables.py::NegativeConsumableStockTests`** — **non modifié**.
  Ce test, écrit à l'origine (avant BUG-041) pour accepter indifféremment un refus OU une
  notification, passe maintenant par la branche « signalé par notification » plutôt que par le
  `return` anticipé sur `ValidationError`. Comportement retrouvé, pas affaibli.

- **`backend/production/tests/test_bug143_consumable_exit_allows_negative_stock.py`** (nouveau) — 3
  tests :
  1. Sortie EXIT sur un stock à 0 (cas réel du client) : acceptée, stock → négatif, CUMP préservé,
     notification créée.
  2. Sortie dépassant un stock positif existant : acceptée, stock → négatif.
  3. Parcours API complet `POST /api/production/sessions/` (déclaration de fournée) avec stock de
     farine à 0 : 201, fournée bien enregistrée, `ConsumableStock.quantity` négatif.

  J'ai vérifié localement (en réintroduisant temporairement le `raise` de BUG-041, puis en le
  retirant à nouveau) que ces 3 tests échouaient bien avant la correction (`ValidationError`/HTTP
  400) et passent après — conformément à CLAUDE.md §7 règle 4 — avant de committer le fichier sans
  `@expectedFailure` (comportement directement implémenté, pas un bug en attente).

### Registre

- `docs/qa/REGISTRE_BUGS.md` : nouvelle ligne `BUG-143` dans le tableau de suivi (Statut `CORRIGÉ`) +
  fiche détaillée complète en fin de fichier (reproduction, cause, décision, fichiers modifiés, test
  de non-régression, impact API/frontend).

## Tests exécutés

```
backend/.venv/Scripts/python.exe manage.py test production sales finance
→ Ran 231 tests in 687.833s — OK
```

```
backend/.venv/Scripts/python.exe manage.py makemigrations --check --dry-run
→ No changes detected
```

Aucune migration nécessaire pour ce ticket (aucun changement de schéma — `ConsumableStock.quantity`
était déjà un `DecimalField` sans contrainte `>= 0`).

## Impact contrat d'API — sous-ticket proposé pour `dev-frontend`

`POST /api/production/sessions/` et `POST /api/production/movements/` ne renvoient plus **jamais**
`400 {"detail": "Stock insuffisant pour cette sortie de ... : disponible ..., demandé ..."}` pour ce
motif précis — ce cas d'échec n'existe plus.

Conséquence : le traitement spécifique de ce message côté frontend, ajouté sous **BUG-050**
(`frontend/src/pages/dashboard/Production.tsx`, fonction `isStockInsufficientError`, formulaire
« Déclaration de Fournée » et modale « Approvisionnement Consommable »), devient **mort** — il ne se
déclenchera plus jamais, sans pour autant afficher quoi que ce soit de trompeur en l'état (il ne
s'affiche simplement jamais). Je propose à `dev-frontend` (sous-ticket, non ouvert ni implémenté ici
puisque CLAUDE.md m'interdit de toucher au frontend) :
- soit retirer cet affichage devenu sans objet,
- soit le remplacer par l'affichage de la nouvelle notification « Stock négatif » (sévérité
  `WARNING`, déjà consommée par le mécanisme de notifications existant côté frontend) pour que le
  gérant comprenne qu'une fournée a été enregistrée malgré un stock de consommable insuffisant.

Je n'ai ouvert aucun fichier frontend pour ce ticket.

## Risque signalé, non tranché unilatéralement — synchronisation Cloud (CLAUDE.md §7 règle 6)

En cherchant les dépendants du comportement actuel (étape 3 de la mission), j'ai trouvé que
`sync/services.py::_push_consumable_movement` réutilisait la `ValidationError` de BUG-041 comme
mécanisme de détection d'une **dépendance manquante** : une sortie (EXIT) arrivant côté Cloud avant
son entrée (ENTRY) correspondante (lots désordonnés entre nœuds) était rejetée et **retentée
automatiquement** au cycle suivant, une fois l'entrée synchronisée.

Avec BUG-143, ce mécanisme ne se déclenche plus (même méthode `save()` des deux côtés) : une sortie
sans entrée préalable est désormais **acceptée immédiatement**, valorisée au CUMP courant du stock
consolidé Cloud (0 si la ligne vient d'être créée paresseusement par `get_or_create`), au lieu d'être
mise en attente. Une fois l'entrée réellement synchronisée, le stock redevient correct en quantité
(testé), mais le `ConsumableMovement.unit_price` déjà écrit pour cette sortie reste figé à la valeur
erronée (0 ou une valeur provisoire) — risque de valorisation incorrecte et silencieuse dans
`finance.views` (COGS, BUG-123) tant que les lots arrivent dans le désordre entre nœuds.

Je n'ai **pas** tranché ce point moi-même : c'est une décision d'architecture de synchronisation
(propriété d'`architecte-sync`) distincte de la demande client sur l'enregistrement local d'une
fournée, et je n'ai pas de visibilité sur la fréquence réelle de ce désordre en production (SYNC.md
indique que c'est rare — « arrivent généralement dans le même lot ou le précédent »). J'ai :
- documenté le risque dans la fiche BUG-143 du registre (section Correction) ;
- mis à jour le test de sync concerné pour refléter le nouveau comportement observable (accepté,
  stock négatif) sans masquer le risque de valorisation (qui n'était pas testé avant non plus) ;
- proposé, sans l'implémenter (pour ne pas sur-ingénierer un ticket scopé sur l'enregistrement local),
  une piste pour `architecte-sync`/`auditeur-comptable` : détecter une dépendance manquante en
  vérifiant l'existence d'au moins une `ConsumableMovement` ENTRY déjà synchronisée pour ce stock,
  indépendamment du signe résultant, plutôt que de réutiliser l'ancienne règle de BUG-041.

Ce point reste ouvert pour arbitrage par le coordinateur ; je ne l'ai pas transformé en ticket séparé
de mon propre chef (hors du périmètre explicite de cette mission), mais le signale clairement ici et
dans le registre pour que ce ne soit pas perdu.

## Vérification de l'environnement (incident récurrent connu)

Avant de lancer mes tests, `netstat`/`tasklist` montraient déjà un serveur de développement actif sur
le port 8000 (`pid` variable selon les étapes), utilisant l'interpréteur Python global
(`C:\Program Files\Python312\python.exe`) plutôt que `backend/.venv/Scripts/python.exe` — connexions
établies actives, probablement la session de test en direct du client. **Je ne l'ai pas touché** (pas
démarré par moi, actif, risque de couper le client en plein test). Je signale simplement
l'observation : ce processus préexistant correspond exactement à l'« incident récurrent de serveur
fantôme avec le mauvais interpréteur Python » mentionné dans les consignes — à surveiller par le
coordinateur, pas une conséquence de mon travail. Tous mes propres processus de test
(`backend/.venv/Scripts/python.exe manage.py test ...`) se sont terminés normalement ; `tasklist`
après ma session ne montre plus que les processus préexistants, aucun processus supplémentaire laissé
par moi.

## Statut final

- **BUG-143 : CORRIGÉ**, en attente de vérification par `testeur-production` (ou le coordinateur).
- Suite complète `production sales finance` : 231/231 OK.
- `makemigrations --check --dry-run` : propre.
- Sous-ticket frontend proposé (pas ouvert formellement, à la discrétion du coordinateur) : nettoyer
  ou adapter l'affichage devenu obsolète de BUG-050 dans `Production.tsx`.
- Risque signalé (sync/valorisation Cloud) : non tranché, transmis au coordinateur/`architecte-sync`.
