# Testeur Clients et Commissions — vérification indépendante, 2026-11-22 (Dev C, état 2fcfa0e)

## Tickets
| Ticket | État au départ | Résultat |
|---|---|---|
| BUG-417 | CORRIGÉ | **VÉRIFIÉ** (réserve BUG-555) |
| BUG-412/413 compléments (filtre mois/année) | VÉRIFIÉ | confirmé : `period__month/year` filtre liste et `summary/` (tests ci-dessous) ; Commissions.tsx les transmet |
| BUG-414, BUG-333, BUG-011, BUG-415, BUG-521 | déjà VÉRIFIÉ | non modifiés ; suites `test_bug414_node_delete_users`, `test_bug333_page_size` rejouées vertes ; `tsc --noEmit` 0, `npm run build` OK, 0 `any` dans Clients.tsx et Settings.tsx |

## BUG-417 : attaques menées (`backend/core/tests/test_verif_bug417_c.py`, 12 tests)
- Migrations 0021 -> 0022 jouées pour de vrai (MigrationExecutor, modèles historiques, pas les modèles courants) : 0 -> 2000/1000 ; 3000, 1500, 2500,50, 999,99 conservés (décimales intactes) et signalés ; valeurs déjà 2000/1000 non signalées ; rejeu après retour arrière OK ; commissions déjà générées inchangées.
- API : création d'une boulangerie sans champ -> 2000 / 1000 ; négatifs refusés (400) ; valeurs Decimal.
- Formules à la main (Decimal) : 100 pains x 500 = 50 000 ; CM 25 % = 12 500 ; retenues 0 + 2 000 + 1 000 = 3 000 ; net 9 500. Taux 0,30 : CM 15 000, net 12 000.
- Cotisation propre au client prime sur celle de la boulangerie ; changement ultérieur du tarif boulangerie et régénération de la période ne modifient pas les retenues figées ; VENTE SOLDE : aucune ligne de commission.
- Totaux verticaux (`summary/`) : commande 70 000, CM 17 500, cotisation 4 000, carte 2 000, net 11 500 ; filtre `period__month=4` isole 1 ligne.
- Frontend : défauts Nodes.tsx = 2000/1000 en FC (pas en %), cohérents avec modèle et API.

## Ticket ouvert
- **BUG-555 (Mineur, frontend)** : `ConfigForm.tsx` expose toujours « Frais d'Imprimés (FC) » (`Config.print_fee`), sans effet depuis BUG-417 (la carte vient de `Node.card_fee_fc`). Preuve : `test_config_print_fee_sans_effet`.

## Observation (pas de ticket, à trancher par le coordinateur)
CLAUDE.md §5.3 (remise annuelle 0,025 x volume, net = CM + remise incorporée - retenues) est contredit par le code, aligné sur adaptes.md (BUG-295 : `annual_bonus = 0`, remise annuelle non ajoutée au net mensuel) ; la CM brute, le total des retenues et le net sans remise sont conformes. Priorité des documents : adaptes.md > CLAUDE.md, donc pas d'anomalie du code.

## Résultats
`python manage.py test core.tests.test_verif_bug417_c core.tests.test_bug417_migration_defauts_partout core.tests.test_bug414_node_delete_users core.tests.test_bug333_page_size commissions clients --noinput` : **283 tests OK**. Rendu navigateur non contrôlé.
