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
