# testeur-production — 2026-11-22 (a3, Dev A)

DB isolée (scratchpad), sans --parallel, aucun code applicatif modifié, pas de commit.

## Vérifications
- **BUG-388 : VÉRIFIÉ** (contrat backend rejoué, code de `DirectionSupplyForm`/`GlobalConsumablesSection` lu, `tsc --noEmit` exit 0 ; rendu navigateur non contrôlé). Réserve : BUG-625.
- **Sync ConsumableInventory (BUG-386) : VÉRIFIÉ avec réserve BUG-626** (12 tests de B verts, 3 rejeux idempotents).
- **BUG-612 : ROUVERT** — `POST transfers/` `from_node: 1.5` ou `"१"` -> 201 (tronqué en pk 1). Le reste du périmètre est bon (bool, géant, `1_0`, négatif, liste sur demande/réponse/confirmation/envoi direct/dispatch/`?node=`).
- BUG-540/541/562 : non touchés (consigne). BUG-382 déjà VÉRIFIÉ (relecteur-code), 526-529 déjà VÉRIFIÉS.

## Tickets ouverts
| Ticket | Gravité | Sujet |
|---|---|---|
| BUG-620 | Majeur | `confirm_reception` ignore une ligne absente/inconnue -> CONFIRMED, somme du groupe ≠ 0, clôture non bloquée (demande et envoi direct) |
| BUG-621 | Mineur | `approved: "false"` traité comme acceptation |
| BUG-622 | Mineur | 500 : lignes dupliquées (POST/PATCH sessions), PATCH date vers une session existante |
| BUG-623 | Mineur | 500 : quantité de ligne 10^17, disposal 10^9 × 5000 |
| BUG-624 | Mineur | le fournisseur peut PATCH/DELETE la demande en attente du demandeur |
| BUG-625 | Mineur, À CLARIFIER | COMPTABLE peut approvisionner le stock SIEGE (API) |
| BUG-626 | Mineur (sync, B) | ligne d'inventaire rejouée avec autre quantité dupliquée ; inventaire futur accepté |
| BUG-627 | Mineur | demande de transfert vers SIEGE / nœud inactif acceptée |
(numéros 600-602 laissés au testeur-ventes, qui les utilise dans ses tests)

## Nouveaux angles couverts et verts
Séquence 98 -> 105 -> 98 -> 100 (somme groupe constante, 4e validation refusée), blocage de clôture puis résolution (siège seul, pas le récepteur), rôles et 3e boulangerie, quantités invalides, double réponse, valeur du sac figée après changement, levure 0,25 cumulée, dispositions (stock par type, PATCH/DELETE, rôles), envoi direction atomique + CUMP, inventaire (rôles, écart, une fois par jour, isolation, valeurs invalides), équation de stock sur mouvements.
Note : rien d'anormal sur négatifs/stock négatif (décisions client BUG-216/143). Observation : `respond_to_request` accepte une quantité > stock (stock négatif) alors que `send/` la refuse ; à arbitrer (cohérent avec remarque l.194).

## Tests
`test_production_v2_a3.py`, `test_sync_inventaire_v2_a3.py`, `test_verif_bug612_a3.py` : 39 tests, OK (expected failures = 17, un par assertion de ticket). Série complète `manage.py test production` lancée en arrière-plan (code en mouvement par dev-backend) : non terminée à la rédaction, à relancer après les corrections.
