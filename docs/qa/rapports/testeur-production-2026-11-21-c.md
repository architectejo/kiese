# Rapport testeur-production — 2026-11-21 (c) — vérification BUG-402

Branche : dev-c (code `production/` du Dev A). Aucun code applicatif modifié, aucun commit.

## Verdict : BUG-402 VÉRIFIÉ (constats 1 et 2)

## Relecture du diff (`ConsumableMovement.save()`, branche ENTRY)
- `base_qty = max(old_qty, Decimal('0'))` borne numérateur et dénominateur du CUMP ; `new_qty` reste la quantité réelle (le négatif est absorbé dans le stock).
- Decimal uniquement ; `transaction.atomic()` + `select_for_update()` conservés.
- Branches EXIT (valorisée au CUMP figé), modification et suppression de mouvement : inchangées.
- Cas `new_qty <= 0` (entrée inférieure ou égale au déficit) : CUMP = prix de l'entrée (comportement existant, sans division par zéro, jamais négatif). Acceptable.

## Tests écrits
`backend/production/tests/test_verif_bug402_testeur_production.py` (16 tests) : retour exact à 0 ; entrée < déficit (stock reste négatif, CUMP = prix de l'entrée) puis seconde entrée ; sorties multiples puis entrée ; stock à 0 ; entrées successives à prix différents après passage en négatif (115 000 puis 107 500) ; valorisation d'une sortie suivant l'entrée et sur stock négatif ; édition d'une entrée ; arrondi 4 décimales (100,5714 / 100,3333) ; sel en g ; levure 0,25 paquet ; huile 0,33 L ; synchronisation (`_push_consumable_movement` sortie avant entrée -> stock 5, CUMP 100 000, sortie ré-estampillée 100 000, `_restamp_orphan_exits` non cassé).

## Résultats
- Avec correctif : 16/16 OK.
- Correctif temporairement retiré (copie sauvegardée puis restaurée, `git diff --stat` identique) : 9/16 échouent (sorties multiples, entrées successives, sel, levure, huile, arrondi, sync, etc.). Les 7 autres (retour à 0, entrée < déficit, stock à 0…) passent des deux côtés, car ils verrouillent des comportements à préserver.
- Lot ciblé : mes tests + test_bug402 + test_consumables + test_bug123 + test_bug126 + test_bug143 + test_verif_bug143 + sync test_bug146 : 42 tests OK.
- Volet 1 (test BUG-143 réécrit `test_exit_synced_before_entry_is_revalued_when_entry_arrives`) : passant.
- Module `production` complet : voir note finale ci-dessous.

## Tickets
- BUG-357 [Mineur, OUVERT] : CUMP déjà gonflé en base non recalculé ; proposition de migration de données (nouvelle) ou commande `recompute_cump`.
- Aucun défaut nouveau sur le correctif lui-même.

## Note module complet
Le lancement `manage.py test production` (lot long) n a pas fini dans le temps imparti : environ 390 tests écoulés sans échec visible (sortie bufferisée, aucun F/E), sans conclusion finale. À relancer par le coordinateur si nécessaire.


---

# Ronde 2 — vérification BUG-357, BUG-147, BUG-129 (testeur-production, Dev C)

Fichier de tests : `backend/production/tests/test_verif_bug357_147_c.py` (32 tests, dont 3 `@expectedFailure`). Lot ciblé (mes tests + tests du dev + test_consumables + test_verif_bug143 + test_bug402 + test_bug129) : 57 tests OK (3 échecs attendus). `npx tsc --noEmit` : OK.

## Verdicts
- **BUG-357 : VÉRIFIÉ** pour le cas visé (CUMP gonflé par stock négatif). Simulation par défaut sans aucune écriture (stock, `unit_price`, `ActivityLog`) ; `--apply` corrige CUMP et sorties, quantité jamais modifiée ; idempotent (2e passage : 0 corrigé, un seul log) ; `--node` limite ; `--apply --dry-run` refusé (CommandError) ; rejeu cohérent avec `ConsumableMovement.save()` sur une séquence mixte avec arrondis (demi-centime 10,005, 100,5714) ; Decimal ; levure 0,25. Réserve : BUG-501 (stock initial non tracé).
- **BUG-147 : VÉRIFIÉ.** Création des 4 stocks (farine, sel, levure 0,25, huile 0,33) avec l'unité du `ConsumableType` (vide si type absent), stock négatif accepté + notification « Stock négatif » (BUG-143), ligne existante ni dupliquée ni écrasée, PATCH signé (+1, -2) sans doublon, aucun stock créé pour un autre nœud (gérant K1 forçant node=K2 ignoré ; siège crée sur la cible seulement), unicité (node, type) en base, course absorbée par `get_or_create`. Pas de `select_for_update` dans le helper, mais l'unicité en base et le verrou de `ConsumableMovement.save()` suffisent. Défaut voisin non causé par ce ticket : BUG-502.
- **BUG-129 : VÉRIFIÉ.** Backend : course `IntegrityError` et session clôturée renvoient 400 `{'detail': ...}` en français (dict JSON). Frontend : `handleAddSession` n'existe plus dans `Production.tsx` ; la déclaration passe par `components/production/BatchInProgressPanel.tsx` qui affiche `getErrorDetail(err, ...)` (lit `detail` ou les erreurs de champs). Types OK.

## Tests réalignés par le dev
- `NoStockRowAtAllTests` (`..._recorded_bug147`) : l'ancien test documentait le défaut (perte silencieuse). Le test inversé affirme le comportement corrigé (ligne FLOUR -2.000 et 1 mouvement). Esprit préservé, pas d'affaiblissement.
- `OverconsumptionAlertTests` : ligne FLOUR à 1000 ajoutée au setUp. Nécessaire car la sortie de farine auto-créée génère une notification de stock négatif qui casserait l'assertion « aucune notification parasite » des 3 fournées de référence. Le cœur (alerte de surconsommation du sel à 10x la moyenne) est inchangé. Réserve ancienne et non causée par le dev : l'assertion finale est `assertGreater(count, before)`, faible (toute notification suffit).

## Nouveaux tickets
- BUG-501 [Majeur, OUVERT] : `recompute_cump --apply` sur stock initial non tracé : CUMP sain 66,6667 écrasé par 100,0000, sorties antérieures revalorisées 0,00. Tests `test_bug501_*` (2).
- BUG-502 [Majeur, OUVERT] : 2e déclaration du jour : farine sortie du total cumulé (2+2 sacs -> 6 sortis). Test `test_bug502_*`.
