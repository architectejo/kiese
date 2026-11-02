# Rapport — ingenieur-blockchain — 2026-11-01 — Chantier A : écart Caisse Direction (BUG-119)

## Contexte

Analyse du vrai Livre de Caisse Direction du client (`data_kiese/D1-4...xlsx`), validée avec le
client. Le Livre de Caisse GÉRANT (`D1-3...xlsx`) a déjà son équivalent chez nous (`CashClosure`,
Niveau 2, billetage 8 dénominations + écart physique/théorique, CLAUDE.md §5.5). Le Livre de Caisse
Direction (`D1-4...xlsx`) applique exactement la même logique de billetage/écart, mais ça n'existait
pas encore au Niveau 3 (`treasury.CashbookEntry`) : lecture seule, uniquement un solde progressif
chaîné par hash SHA-256, sans aucun comptage physique ni écart.

## Décision de conception

**Modèle séparé `DirectionCashCount`**, non lié à la chaîne de hash de `CashbookEntry`, plutôt
qu'une extension des champs de `CashbookEntry` elle-même. Raisonnement (détaillé en docstring dans
`backend/treasury/models.py` et dans la fiche BUG-119 de `docs/qa/REGISTRE_BUGS.md`) :

- Un comptage physique de billets est un **contrôle annexe** — un constat ponctuel sur l'état de
  la caisse à un instant donné, potentiellement recorrigé dans le temps pour un même jour en cas
  d'erreur de saisie. Ce n'est PAS un *mouvement* d'argent (entrée/sortie), ni une classification
  qui changerait le sens comptable d'un mouvement existant.
- CLAUDE.md §5.5 protège par chaînage le **mouvement** comptable (montants, imputation, nœud,
  clôture source, classification `is_correction`) — pas son contrôle physique.
- Même raisonnement déjà appliqué par BUG-083/085 : `correction_reason`/`corrected_by`/
  `correction_source_invoice` sont hors formule de hash (texte/référence d'audit annexe), tandis
  que `is_correction` (classification comptable binaire) y a été intégré. Un comptage physique
  n'entre dans aucune des deux catégories qui justifieraient de toucher au hash.
- Étendre `CashbookEntry` aurait nécessité une nouvelle `HASH_FORMAT_VERSION = 4` et une migration
  de données de recalcul (modèle `0014_bug085_recompute_hash_is_correction`), pour une donnée qui
  ne renforce en rien l'intégrité déjà garantie par le chaînage existant — coût et risque non
  justifiés.

Conséquence directe : **`treasury/hashing.py` n'a pas été touché** (`HASH_FORMAT_VERSION` reste à
`3`), aucune migration de recalcul de hash n'était nécessaire.

## Implémentation

### Modèle (`backend/treasury/models.py`)

`DirectionCashCount` :
- `date` (unique — un comptage consolidé par jour pour toute la Direction, pas par boulangerie :
  contrairement au Niveau 2, la Direction gère une seule caisse consolidée).
- Billetage identique aux 8 dénominations déjà en place pour `CashClosure`/`DisbursementVoucher`
  (20000/10000/5000/1000/500/200/100/50 FC).
- `physical_cash_total` : calculé par `compute_physical_cash()` (même motif que les deux autres
  modèles de billetage existants).
- `reference_entry` (FK `CashbookEntry`, `on_delete=SET_NULL`) : traçabilité de l'écriture ayant
  servi de référence théorique.
- `theoretical_balance` : copie figée du `running_balance` de `reference_entry` au moment du
  comptage (`0.00` si aucune `CashbookEntry` n'existe encore) — reste lisible même si
  `reference_entry` devenait un jour inaccessible.
- `cash_gap = physical_cash_total - theoretical_balance` (même convention de signe que
  `CashClosure.cash_gap`).
- `counted_by` (FK utilisateur), `notes`, `created_at`.

### Calcul du solde théorique

`theoretical_balance` = `running_balance` de la dernière `CashbookEntry` dont `date <= date du
comptage` (`CashbookEntry.objects.filter(date__lte=target_date).order_by('-date',
'-created_at').first()`) — la chaîne Direction est continue (report du solde de la veille), pas un
solde journalier remis à zéro, conformément à ce qu'on observe dans le fichier réel du client.

### Permissions et endpoint

`DirectionCashCountViewSet` (`backend/treasury/views.py`), exposé sur
`/api/treasury/direction-cash-counts/` (`backend/treasury/urls.py`) :
- `permission_classes = [IsHeadquarters]` — même niveau que `CashbookEntryViewSet`/
  `DisbursementVoucherViewSet` (ADMIN/DIRECTION/COMPTABLE, BUG-026).
- Volontairement **pas un `ModelViewSet` complet** : uniquement `create`/`list`/`retrieve`
  (`mixins.CreateModelMixin` + `ListModelMixin` + `RetrieveModelMixin` + `GenericViewSet`). Aucun
  `update` ni `destroy` exposé — un comptage déjà enregistré est un constat daté, pas un brouillon
  qu'on retouche après coup (même esprit que « jamais modifier une écriture déjà versée »).
- `perform_create` : valide la date (`validate_requested_date`, même règle que `CashClosure`/
  BUG-086 : date future toujours refusée, date passée seulement si `Config.allow_backdated_sales`),
  calcule `theoretical_balance`/`reference_entry`, enregistre, calcule l'écart, notifie
  (`create_notification`, sévérité `WARNING`/`DANGER` selon le seuil 10 000 FC déjà utilisé par
  `CashClosure`), journalise (`log_activity`). Capture `IntegrityError` → `400` propre en cas de
  double comptage pour la même date (même motif que BUG-035).

### Migration

`backend/treasury/migrations/0015_directioncashcount.py` : migration de schéma standard (nouveau
modèle uniquement, aucune donnée existante touchée, aucun recalcul de hash requis).

### Autres fichiers touchés

- `backend/treasury/serializers.py` (`DirectionCashCountSerializer`).
- `backend/treasury/admin.py` (enregistrement admin, champs calculés en lecture seule).

Aucun changement d'API publique existante — uniquement un nouvel endpoint. Pas de notification
`dev-frontend` nécessaire au sens de CLAUDE.md §7 (aucune route/contrat existant modifié).

## Ancrage externe

Hors périmètre de cette mission (non demandé par le Chantier A). Pour mémoire, le mécanisme déjà
existant au Niveau 3 (`CashbookEntryViewSet.integrity_check`, `verify_cashbook_chain`) reste
inchangé et continue de couvrir les mouvements comptables ; le comptage physique introduit ici est
un contrôle complémentaire, pas un mécanisme d'ancrage de la chaîne.

## Tests

Nouveau fichier `backend/treasury/tests/test_bug119_direction_cash_count.py`
(`DirectionCashCountComputationTests` + `DirectionCashCountPermissionTests`, 9 tests — tous
échouaient avant ce ticket puisque l'endpoint n'existait pas) :

1. `test_cash_gap_is_computed_against_theoretical_running_balance` : écart nul quand le compté
   égale le théorique cumulé.
2. `test_cash_gap_is_non_zero_when_physical_count_differs` : écart négatif correctement calculé
   (manquant).
3. `test_cash_gap_with_no_cashbook_entry_yet_uses_zero_theoretical_balance` : théorique = 0 en
   l'absence de toute `CashbookEntry`.
4. `test_direction_cash_count_never_alters_cashbook_balance_or_chain` : **non-altération** —
   `running_balance`/`block_hash` de la dernière `CashbookEntry` et le nombre total d'écritures
   sont strictement inchangés après un comptage ; `verify_cashbook_chain` reste intégralement
   valide après coup.
5. `test_duplicate_count_for_same_date_is_rejected_cleanly` : double comptage même date → `400`
   propre, un seul enregistrement en base.
6. `test_gerant_cannot_create_direction_cash_count` / `test_gerant_cannot_list_direction_cash_counts`
   : `403` pour un GERANT.
7. `test_headquarters_can_create_and_list` : `201`/`200` pour ADMIN/DIRECTION.
8. `test_no_update_or_delete_endpoint_exposed` : `405` sur `PATCH`/`DELETE`.

Résultat : `python manage.py test treasury.tests.test_bug119_direction_cash_count` → **9/9 OK**.

`python manage.py test treasury blockchain` et `python manage.py test` (suite complète) : voir
section « Vérifications finales » ci-dessous.

## Vérifications finales

- `python manage.py check` → « System check identified no issues (0 silenced) ».
- `python manage.py makemigrations --check --dry-run` → « No changes detected ».
- `PRAGMA integrity_check` sur `backend/db.sqlite3` (pas `data_kiese/`) → `ok`.
- `python manage.py test treasury.tests.test_bug119_direction_cash_count` → **9/9 OK**.
- `python manage.py test treasury blockchain` → **106 tests, OK, 0 échec** (exécuté deux fois,
  séquentiel puis `--parallel 4`, résultat identique).
- `python manage.py test --parallel 4` (suite complète, toutes apps) → **440 tests, OK, 0 échec**
  (622,8 s — machine partagée très chargée par d'autres sessions d'agents en parallèle, même
  phénomène que celui déjà noté sous BUG-115/BUG-117 ; sans rapport avec ce correctif). Aucune
  régression constatée sur le reste du projet.

## Fichiers modifiés/ajoutés

- `backend/treasury/models.py` — `DirectionCashCount`.
- `backend/treasury/serializers.py` — `DirectionCashCountSerializer`.
- `backend/treasury/views.py` — `DirectionCashCountViewSet`.
- `backend/treasury/urls.py` — route `direction-cash-counts`.
- `backend/treasury/admin.py` — enregistrement admin.
- `backend/treasury/migrations/0015_directioncashcount.py` — nouveau.
- `backend/treasury/tests/test_bug119_direction_cash_count.py` — nouveau.
- `docs/qa/REGISTRE_BUGS.md` — ticket BUG-119 (tableau + fiche détaillée), statut `CORRIGÉ`.

## Statut

BUG-119 : **CORRIGÉ**. En attente de vérification par `testeur-tresorerie` (règle CLAUDE.md §7).
