# Rapport — Vérification finale groupée du cluster Trésorerie

Date : 2026-11-02
Agent : testeur-tresorerie
Demandeur : coordinateur (passe de vérification groupée)

## Contexte

Un cluster de tickets trésorerie était resté au statut `CORRIGÉ` dans
`docs/qa/REGISTRE_BUGS.md` alors que `testeur-tresorerie` y est déjà listé
comme vérificateur prévu sur la plupart d'entre eux : **BUG-033, BUG-034,
BUG-035, BUG-036, BUG-037, BUG-044, BUG-045, BUG-046, BUG-048, BUG-119**.

Constat préalable important (documenté avant de commencer) : BUG-033 à
BUG-037 et BUG-044/045/046/048 avaient en réalité déjà fait l'objet d'une
vérification narrative complète et indépendante le **2026-10-22** (sections
« Vérification de phase 4 » du registre), chacune conclue « VÉRIFIÉ » point
par point avec reproduction de scénarios (pas une simple relecture). Le
problème n'était donc pas l'absence de vérification mais un **oubli de
synchronisation** : la colonne `Statut` du tableau de suivi n'avait jamais
été mise à jour pour refléter ces conclusions. **BUG-119**, en revanche,
n'avait strictement jamais été vérifié, ni côté backend (`ingenieur-blockchain`)
ni côté frontend (`dev-frontend`) — conformément à la consigne reçue, ce
ticket a été traité comme une vérification complète de zéro, sans aucune
présomption.

Je n'ai pris aucun des deux constats pour acquis : j'ai rejoué/reproduit
moi-même chaque scénario avec de vraies assertions avant de clore quoi que
ce soit.

## Méthode

1. Exécution réelle de `backend/.venv/Scripts/python.exe manage.py test
   treasury blockchain` → **106/106 tests OK**, 0 échec (≈356 s).
2. Lecture critique indépendante du code réellement en place (pas les notes
   de ticket) pour chaque bug du cluster :
   - `backend/treasury/views.py::CashClosureViewSet.perform_create/
     perform_update/push_to_cashbook`, `_unresolved_incoming_transfer_gap`,
     `DirectionCashCountViewSet`.
   - `backend/treasury/models.py::FacturierReport` (champs de détail par
     catégorie) et `DirectionCashCount` (comptage physique Direction).
   - `frontend/src/pages/dashboard/Treasury.tsx` et
     `frontend/src/api/services.ts` (masquage par rôle, détail par
     catégorie, désactivation d'édition sur clôture confirmée, lien de
     transfert litigieux, sous-section comptage Direction).
3. `cd frontend && npx tsc --noEmit` → 0 erreur. `npm run build` → succès
   (seul avertissement pré-existant, taille de chunk > 500 kB, sans lien).
4. `backend/.venv/Scripts/python.exe manage.py test` (suite complète du
   dépôt) → **477/477 tests OK**, 0 échec (≈1179 s).

## Résultats détaillés

### BUG-033 — `FacturierReport` Niveau 1, détail par catégorie de pain
**VÉRIFIÉ** (confirmé, non-régression depuis le 2026-10-22). Les 4 champs
`sacks_consumed`/`breads_produced_by_category`/`breads_sold_by_category`/
`sacks_value_gap` existent sur le modèle, calculés par vacation dans
`generate()`, exposés en lecture seule par le serializer. Test dédié :
`treasury/tests/test_reports_closures.py::FacturierReportDetailFieldsTests`.

### BUG-034 — Clôture confirmée non modifiable par le gérant
**VÉRIFIÉ**. `CashClosureViewSet.perform_update` lève `ValidationError`
(400) si `serializer.instance.is_validated` est vrai, avant tout
`serializer.save()`. Test :
`test_closure_still_editable_by_gerant_after_comptable_confirmation`
(assertion 400/403 sur PATCH d'une clôture confirmée).

### BUG-035 — Double clôture (même nœud/jour) → 400 propre
**VÉRIFIÉ**. `transaction.atomic()` + `try/except IntegrityError` traduit
en `ValidationError` (400). Test :
`test_double_closure_same_day_same_node_is_refused`.

### BUG-036 — Verrouillage de vacation après rapport Niveau 1
**VÉRIFIÉ**. Signal `pre_save` ne réagit qu'à la transition vers
`DELIVERED`, message `{"detail": "Vacation déjà rapportée..."}`
exploitable. Scénario de bout en bout : facture PENDING → livraison →
rapport Niveau 1 → nouvelle livraison bloquée
(`test_scope_gaps.py::FacturierSessionLockTests`). L'effet de bord
non-atomique découvert le 2026-10-22 (`Invoice.deliver()`) reste traité
séparément sous **BUG-053** (déjà `VÉRIFIÉ`), non-régression confirmée par
`test_bug053_signal_side_effects.py` (toujours au vert dans la suite
complète).

### BUG-037 — Clôture bloquée par transfert entrant en écart non résolu
**VÉRIFIÉ**. `_unresolved_incoming_transfer_gap(node)` interroge
`BreadTransferLine` en lecture seule, exclut les transferts `CANCELLED`,
appelée dans `perform_create` et `push_to_cashbook` (double filet). Test :
`test_scope_gaps.py::CashClosureBlockedByUnresolvedTransferGapTests`
(transfert K2→K1, 100 envoyés/80 reçus, clôture refusée 400/409). Le point
déjà signalé au coordinateur le 2026-10-22 (aucune action `production`
exposée pour « résoudre » un transfert `DISPUTED` autrement qu'en
l'annulant) reste d'actualité et n'est pas re-signalé en doublon — il ne
remet pas en cause BUG-037 lui-même.

### BUG-044/045/046/048 — Conséquences frontend (`Treasury.tsx`)
**VÉRIFIÉS**, tous les quatre.
- BUG-044 : section Livre de Caisse + bouton d'intégrité masqués si
  `!user?.can_access_all_nodes` (`isHq` gate), aucun appel réseau qui
  échouerait en 403.
- BUG-045 : détail par catégorie rendu uniquement si au moins un des 4
  champs est présent (pas de ligne vide pour un rapport pré-existant).
- BUG-046 : `handleCreateClosure` refuse le PATCH côté client si
  `editingClosure?.is_validated`, champs de billetage/Notes `disabled`,
  bouton de soumission masqué.
- BUG-048 : message serveur affiché tel quel (jamais reformulé) + lien
  `<Link to="/production">` affiché si le message contient « transfert »
  et « écart ». Le compromis déjà documenté (lien générique plutôt qu'un
  lien profond vers le transfert précis, faute d'identifiant dans le
  message serveur) reste valide et n'est pas rouvert.

### BUG-119 — Comptage physique de billets au niveau Direction
**VÉRIFIÉ, des deux côtés — première vérification réelle de ce ticket.**

Backend :
- Modèle séparé `DirectionCashCount`, **volontairement exclu** de la
  chaîne de hash de `CashbookEntry`. J'ai examiné cette décision de
  conception avec scepticisme (demande explicite de la mission) et je la
  confirme pertinente : un comptage physique est un constat annexe,
  répétable/recorrigeable dans le temps pour une même date, pas un
  mouvement comptable classé — CLAUDE.md §5.5 protège par chaînage le
  mouvement (`entry_amount`/`exit_amount`/`running_balance`), pas son
  contrôle physique. Un `HASH_FORMAT_VERSION = 4` + migration de
  recalcul aurait été un coût et un risque non justifiés pour une donnée
  qui ne protège rien de plus.
- Test dédié confirmant qu'un comptage **n'altère jamais**
  `running_balance`/`block_hash` de la dernière `CashbookEntry`, ni le
  nombre d'écritures, et que `verify_cashbook_chain` reste intégralement
  valide après le comptage
  (`test_direction_cash_count_never_alters_cashbook_balance_or_chain`).
- Calcul de l'écart : `theoretical_balance` = `running_balance` de la
  dernière `CashbookEntry` à la date ou avant (0 si aucune) ; `cash_gap =
  physical_cash_total - theoretical_balance`. Tests sur écart nul, non nul,
  et absence totale de `CashbookEntry`.
- Permissions `IsHeadquarters` strictes : GERANT → 403 sur `create` et
  `list` ; ADMIN/DIRECTION → 201/200. `ViewSet` volontairement limité à
  `Create`/`List`/`Retrieve` : aucun `update`/`destroy` exposé (405
  confirmé par test). Double comptage même date → 400 propre
  (`UniqueValidator` + filet `IntegrityError`).
- Je n'ai trouvé aucune faille dans la séparation délibérée du hash : le
  chemin `DirectionCashCountViewSet.perform_create` n'écrit jamais sur
  `CashbookEntry`.

Frontend :
- Sous-section « Comptage Physique de Caisse — Direction » dans la carte
  §5.1.3, masquée pour les rôles non-HQ (même garde que le reste de la
  carte). Formulaire de billetage réutilisant les 8 dénominations déjà
  standardisées ; total calculé côté client affiché à titre indicatif
  seulement, le solde théorique et l'écart réels restant calculés et
  figés par le serveur. Historique filtré par période, code couleur
  vert/rouge cohérent avec le reste de la page (`cash_gap === 0`). Type
  `DirectionCashCount` et `treasuryApi.directionCashCounts.list()/.create()`
  correctement typés dans `services.ts`, sans nouveau `any`, pas d'appel
  `update`/`delete` exposé côté client.
- `npx tsc --noEmit` → 0 erreur. `npm run build` → succès.

## Registre mis à jour

Les lignes du tableau de suivi de `docs/qa/REGISTRE_BUGS.md` pour BUG-033,
BUG-034, BUG-035, BUG-036, BUG-037, BUG-044, BUG-045, BUG-046, BUG-048 et
BUG-119 sont passées de `CORRIGÉ` à **`VÉRIFIÉ`** (colonne « Vérifié par »
renseignée à `testeur-tresorerie` pour BUG-044/045/046/048/119, qui ne
l'étaient pas encore). Une nouvelle section narrative datée 2026-11-02 a
été ajoutée en fin de fichier avec le détail complet de cette passe.

## Anomalies trouvées

**Aucune régression ni anomalie nouvelle** n'a été trouvée sur l'ensemble
de ce cluster. Aucun nouveau ticket ouvert.

Point procédural à signaler au coordinateur (pas une anomalie
applicative) : la désynchronisation entre les notes narratives
« Vérification de phase 4 » du 2026-10-22 (concluant explicitement
« VÉRIFIÉ ») et la colonne `Statut` du tableau de suivi (restée à
`CORRIGÉ`) est la cause racine de cette demande de passe finale. Il
pourrait être utile que la mise à jour du tableau de suivi et la rédaction
de la note narrative soient faites dans le même geste à l'avenir, pour
éviter qu'un ticket déjà vérifié en substance ne reste visible comme « en
attente de vérification ».

## Commandes exécutées (preuve)

```
cd backend
./.venv/Scripts/python.exe manage.py test treasury blockchain
# Ran 106 tests ... OK

./.venv/Scripts/python.exe manage.py test
# Ran 477 tests ... OK

cd ../frontend
npx tsc --noEmit        # 0 erreur
npm run build           # succès
```

## Conclusion

Cluster entièrement vérifié avec des tests réellement exécutés (pas une
relecture seule). `python manage.py test` (477 tests) et `npm run build`
passent. Aucun code applicatif n'a été modifié par ce testeur.
