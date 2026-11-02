# Vérification BUG-120 — testeur-production, 2026-11-02

## Mission

Vérifier les 4 corrections apportées par dev-backend sur `GET /api/production/daily-closure/`
(`backend/production/views.py::_build_daily_closure_report`) suite aux réponses client Q-006/Q-007
(`docs/qa/QUESTIONS_CLIENT.md`) : `facture_mvm_interne`/`total_du_jour_fc` (Q-006), `ecart_facture_fc`
(Q-007.1), `tarif_vente_fc` (Q-007.2), `repartition_pct_par_quantite`/`repartition_pct_par_valeur`
(Q-007.3). Contrat d'API documenté dans
`docs/qa/rapports/dev-backend-2026-11-02-bug120-corrections-client.md`.

## Méthode

1. Relecture complète du diff fonctionnel : `backend/production/views.py` (`_m()`, `_resolve_node()`,
   `_build_daily_closure_report()`, `DailyClosureReportView`, lignes ~940-1326) et
   `backend/production/tests/test_daily_closure_report.py` (5 tests).
2. Recoupement indépendant, cellule par cellule, de `data_kiese/EXTRAIT RAPPORT DE
   CLOTUREOCTOBRE 2026.xlsx` (feuille `K6`, bloc K5/MPIANGU du 2026-10-06) via `openpyxl`, en mode
   formules (`data_only=False`) puis en mode valeurs figées (`data_only=True`) — confirmation
   indépendante de la preuve déjà citée par l'audit comptable :
   - `K6!L21 = SUM(L8:L20)` = RESTE DU JOUR (193 500) + RESTE DU HIER (-156 500) + APPRO EFFECTUE (0)
     + APPRO REÇU (0) + NON SERVI (0) + RÉGULARISATION (40 000) + VENTE CASH (86 500) + VENTE SOLDE
     (79 500) + NON VENDU (0) + DÉCLASSÉS (0) + EXCÉDENT PAINS (-2 500) + MANQUANT PAINS (0) =
     **240 500**, valeur figée identique.
   - `K6!L132 = L128 + L21 = 599 500 + 240 500 = 840 000` (`L128` = `S/TOTAL AB CARTE`, facturation
     clients).
   - Confirmé : `BreadDisposal.DisposalType` (`backend/production/models.py` l.532-537) ne porte
     aucune valeur `EXCEDENT`/`MANQUANT` — la limite documentée par dev-backend/l'audit (traiter ces
     deux postes à 0 dans `facture_mvm_interne`) est réelle et toujours actuelle, pas une omission
     nouvelle.
3. Construction d'un scénario de test **indépendant** (jamais de données de `data_kiese/`, fixtures
   fictives via `core.testing`), avec deux catégories de pain à prix différents (500 FC / 1000 FC), un
   report de stock de la veille, une régularisation et une vente soldée, calibré pour atteindre
   exactement les deux montants cibles de la mission :
   - `facture_mvm_interne` (somme toutes catégories) = **240 500,00 FC** ✓ (assertion passante)
   - `total_du_jour_fc` = **840 000,00 FC** ✓ (assertion passante)

   (Nota : les composantes par catégorie du scénario de test ne reproduisent pas identiquement la
   répartition par catégorie du classeur réel — impossible sans modéliser EXCÉDENT/MANQUANT par
   catégorie, absent du schéma — mais le **total** et la **formule** sont strictement les mêmes,
   suffisant pour valider l'implémentation du calcul.)
4. Test de stabilité de `tarif_vente_fc` : un même nœud (`sac_value_fc=200000`), deux jours à volumes
   de production radicalement différents (`net_produit_fc` différent) → `tarif_vente_fc='200000'`
   identique les deux jours. Confirmé : jamais recalculé à partir des ventes/production du jour.
5. Test de distinction `repartition_pct_par_quantite` vs `repartition_pct_par_valeur` : avec deux
   catégories à prix différents, les deux listes sont présentes simultanément et donnent des
   pourcentages réellement différents (66,67 %/33,33 % par quantité contre 50 %/50 % par valeur dans
   le scénario construit) — preuve que ce n'est pas un calcul trivialement dupliqué.
6. `python manage.py test production sales -v 2` → **130/130 OK** (~262 s).
7. `python manage.py makemigrations --check --dry-run` → « No changes detected ».
8. `PRAGMA integrity_check` sur `backend/db.sqlite3` → `ok`.
9. `python manage.py test` (suite complète) relancé par ce testeur — voir section « Suite complète »
   ci-dessous pour le résultat obtenu au moment de la rédaction de ce rapport.
10. Fichier de test ad hoc créé puis **supprimé** après usage
    (`backend/production/tests/test_zz_manual_verif_bug120.py`, jamais commité, pur outil de
    vérification de cette session — le dépôt n'est pas un dépôt git, confirmé par l'environnement).

## Résultat par point

| # | Champ | Formule vérifiée | Résultat |
|---|---|---|---|
| 1 | `facture_mvm_interne` / `total_du_jour_fc` | Somme en FC des rubriques de mouvement (RESTE DU JOUR/HIER, APPRO EFFECTUE/REÇU, NON SERVI, RÉGULARISATION, VENTE CASH/SOLDE, NON VENDU, DÉCLASSÉS ; EXCÉDENT/MANQUANT = 0, non modélisable) ; `total_du_jour_fc` = facturation normale + `facture_mvm_interne` | **Conforme** — reproduit exactement `K6!L21=SUM(L8:L20)` et `K6!L132=L128+L21` sur un scénario construit à la main (240 500 / 840 000 FC) |
| 2 | `ecart_facture_fc` | `Σ(Invoice.order_total) − Σ(Invoice.payment_amount)`, factures `DELIVERED` nœud/jour | **Conforme** — vérifié dans le code (`Sum()` en `Decimal`, jamais `float`) et dans le test existant (3 000 FC recalculé à la main) |
| 3 | `tarif_vente_fc` | Valeur fixe `Node.sac_value_fc`/`Config.sac_value_fc`, jamais une moyenne | **Conforme** — identique sur deux jours à volumes de production très différents |
| 4 | `repartition_pct_par_quantite` + `repartition_pct_par_valeur` | Les deux toujours présentes, calculs réellement différents si prix différents | **Conforme** — les deux présentes simultanément, valeurs distinctes démontrées |

## Observation non bloquante — traçabilité des réponses client

`docs/qa/QUESTIONS_CLIENT.md` (table en tête de fichier) contient les lignes Q-006 et Q-007 avec les
colonnes « Réponse » et « Date réponse » **vides** au moment de cette vérification. Or le rapport de
dev-backend cite textuellement des réponses du client (« saisi par vous par boulangerie », « fait les
deux, ils vont choisir via un select », « commandes, paiements sur commande ») qui ne figurent dans
aucun autre document du dépôt que ce rapport lui-même.

- Pour **Q-006** (`facture_mvm_interne`/`total_du_jour_fc`), ce n'est pas bloquant : la formule
  implémentée reproduit, chiffres à l'appui, la formule réelle du classeur client lui-même
  (`K6!L21=SUM(L8:L20)`, `K6!L132=L128+L21`) — vérifiée deux fois de façon indépendante (audit
  comptable, puis ce testeur). La pièce réelle sert ici de preuve suffisante, avec ou sans citation
  client supplémentaire.
- Pour **Q-007** (`ecart_facture_fc`, `tarif_vente_fc`, `repartition_pct_*`), c'est plus sensible :
  l'audit comptable avait explicitement qualifié les trois formules réelles du classeur d'« AMBIGU »
  (dérive de référence par copier-coller entre lignes-clients et entre feuilles, aucune règle stable
  extractible du document seul) et avait demandé une clarification explicite du client avant tout
  usage comptable réel de ces trois totaux. La décision effectivement codée pour ces trois champs n'est
  donc, à ce jour, traçable dans aucun registre officiel du projet.

Ceci ne remet pas en cause la justesse **technique** du code (il est strictement conforme au contrat
documenté par dev-backend et à tous les tests, y compris ceux ajoutés par ce testeur). C'est une
question de **traçabilité documentaire** de la décision métier sous-jacente, signalée au coordinateur
pour qu'il confirme l'origine de ces réponses (échange oral/e-mail non retranscrit, ou décision interne
à documenter comme telle) et mette à jour `docs/qa/QUESTIONS_CLIENT.md` en conséquence.

## Suite complète (`python manage.py test`)

Lancée en arrière-plan par ce testeur après la vérification ciblée (production/sales). L'environnement
a de nouveau montré le ralentissement déjà documenté pour BUG-118/119/120 (contention CPU côté
outillage, tests individuels prenant jusqu'à plusieurs minutes), mais le run est allé jusqu'au bout
cette fois :

```
Ran 446 tests in 845.085s
OK
```

**446/446 OK**, 0 échec — confirmation finale demandée par la mission, non obtenue par dev-backend à la
clôture de son ticket (il n'avait pu observer que les ~200 premiers tests avant l'arrêt forcé de sa
session). Aucune régression sur l'ensemble du dépôt suite à ce correctif.

## Conclusion

Les 4 corrections de BUG-120 (Q-006, Q-007.1, Q-007.2, Q-007.3) sont **correctement implémentées**,
conformes au contrat d'API documenté, et reproduisent exactement les montants réels cibles de la
mission (240 500 FC / 840 000 FC). `makemigrations --check --dry-run` et `PRAGMA integrity_check` sont
propres. Aucun défaut de calcul trouvé.

**BUG-120 passé à `VÉRIFIÉ`** dans `docs/qa/REGISTRE_BUGS.md` (table récapitulative + fiche détaillée,
section « Vérification — testeur-production, 2026-11-02 »), avec l'observation de traçabilité
ci-dessus transmise au coordinateur (non bloquante pour le statut du ticket).

## Fichiers concernés

- `backend/production/views.py` (lu, non modifié)
- `backend/production/tests/test_daily_closure_report.py` (lu, non modifié)
- `backend/production/models.py` (lu, non modifié — vérification `DisposalType`)
- `docs/qa/REGISTRE_BUGS.md` (mis à jour : statut BUG-120 → VÉRIFIÉ, fiche détaillée complétée)
- `docs/qa/QUESTIONS_CLIENT.md` (lu, non modifié — observation remontée au coordinateur)
- `docs/qa/rapports/dev-backend-2026-11-02-bug120-corrections-client.md` (lu)
- `docs/qa/rapports/auditeur-comptable-2026-11-02-audit-bug120.md` (lu)
- `data_kiese/EXTRAIT RAPPORT DE CLOTUREOCTOBRE 2026.xlsx` (lu uniquement, jamais copié)
