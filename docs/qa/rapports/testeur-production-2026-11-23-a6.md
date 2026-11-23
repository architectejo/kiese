# Testeur production (Dev A) - vérification a6, 2026-11-23

Tests : `backend/production/tests/test_verif_production_a6_v6.py` (36 tests dont 8 `@expectedFailure`). Aucun code applicatif modifié, rien commité.

## Verdicts (registre mis à jour)
| Ticket | Verdict | Détail |
|---|---|---|
| BUG-652 | VÉRIFIÉ | catégorie inconnue, tout à 0, sur-stock (même ligne hors corps), valeurs hostiles, rôles, double réponse = une déduction, somme du groupe conservée, aucune écriture partielle |
| BUG-653 | VÉRIFIÉ | J+1, J+400, siège refusés sans fournée ni stock ; passé/aujourd'hui OK ; dates invalides 400 |
| BUG-654 | REJETÉ PARTIEL | `_strict_int` et `flour_sacks_used` OK ; la quantité d'une LIGNE de fournée accepte toujours « ٣ » (201) |
| BUG-626 | VÉRIFIÉ | extraction / renvoi / idempotence / isolation OK ; les 2 tests d'origine (unicité, date future) passent ; voisin BUG-683 (modification non renvoyée) |
| BUG-674 | VÉRIFIÉ | `date`, plage inclusive, plage inversée vide, 400 sur formats invalides, isolation, siège |
| BUG-675 | VÉRIFIÉ | émettrice +5 000 / réceptrice -5 000, somme du groupe nulle, flux demande ou envoi direct ; écart 98/100 non compté avant résolution puis somme nulle |
| BUG-676 | VÉRIFIÉ | repli sur les ventes (30/70 % qté, 20,45/79,55 % valeur), `repartition_base`, jamais négatif |
| BUG-677 | VÉRIFIÉ | visibilité par rôle, filtre `?scope=`, scope invalide 400, écriture siège seul |

## Nouveaux tickets (tous avec `@expectedFailure`, échec vérifié pour la bonne raison)
- BUG-680 : `respond_to_request` accepte deux lignes de même catégorie (la dernière écrase).
- BUG-681 : PATCH de la date d'une fournée vers J+30 accepté (200).
- BUG-682 : chiffres Unicode acceptés dans `consumables_used` et la quantité d'une disposition.
- BUG-683 : PATCH d'un comptage de consommable : `is_synced` reste True (jamais renvoyé) et `gap` pas recalculé (4,5 au lieu de 7).
- BUG-684 (À CLARIFIER) : le siège peut saisir une dépense locale de boulangerie avec une catégorie « direction seule ».
- BUG-685 : export clôture (Excel/HTML) affiche « Appro Reçu » en positif, l'écran en négatif (lecture de code, sans test).

## Point à trancher par le coordinateur
- BUG-625 : `test_production_v2_a3::test_BUG_625_comptable_cannot_supply_direction_stock` est en UNEXPECTED SUCCESS (le COMPTABLE reçoit maintenant 403 sur une entrée de stock direction). Ticket À CLARIFIER : signalé, non tranché (retirer la marque ou rouvrir ?).
- BUG-675 : la formule d'origine `K6!L21 = SUM(L8:L20)` additionnait envoyé et reçu ; remarque.md prime, mais le dev recommande une reconfirmation client avec les Excel d'août.

## Rejeu
- Fichier a6 + d13 + d15 + clôture + sync inventaire a3 + a4 : 101 tests, OK (expected failures=8, tous les miens).
- `test_production_v2_a3` : 27 tests, FAILED uniquement par l'unexpected success BUG-625.
- Non lancés (trop longs, hors consigne) : suites `core` et `treasury` complètes.
