# Rapport auditeur-comptable (Dev C) — 2026-11-22-c

Périmètre : migration `sales/0011`, impact comptable de BUG-513, inventaire des lectures du tarif courant.
Lecture seule du code applicatif ; aucune donnée réelle (`data_kiese/` non utilisé). Un seul fichier de test ajouté : `backend/finance/tests/test_verif_bug513_c.py` (5 tests : 3 verts, 2 `@expectedFailure`).

## 1. Migration `sales/0011_bug508_full_unit_price`

Opérations : `AddField(full_unit_price, PositiveIntegerField null=True)` puis `RunPython(backfill, noop)`.

| Point | Constat |
|---|---|
| Valeur donnée aux lignes existantes, vente normale | `full = unit_price` (prix figé à la création = prix plein). Exact : aucune dépendance au tarif courant. |
| Vente soldée | Si `round(0,75 x tarif_courant) == unit_price` : `full = tarif_courant` ; sinon `full = round(unit_price / 0,75)`. Heuristique en deux temps. |
| Un tarif passé est-il reconstituable ? | Non, il n'existe aucun historique de tarifs. Pour une ligne soldée dont le tarif a changé depuis, la déduction `unit_price / 0,75` est exacte quand le plein est un multiple de 4 (300 -> 225 -> 300) ; sinon ±1 FC (ex. plein 150 -> 113, retour 151). Plusieurs pleins voisins donnent le même 75 % (150 et 151 -> 113), donc la valeur est ambiguë à 1 FC près. Collision théorique : tarif courant dont le 75 % égale par hasard le prix figé d'un autre plein (écart ≤ 1 FC aussi). |
| Risque de fausser des factures historiques | Faible : la migration n'écrit QUE `full_unit_price` via `.update()` (historical model, pas de `save()`), donc `unit_price`, `line_total`, `order_total`, BP, caisse ne bougent pas. Seule la colonne « perte » (`loss = full - unit_price`) d'une ligne soldée peut dévier de ≤ 1 FC/pain. Ce n'est pas bloquant mais la valeur est une estimation, à documenter (docstring le dit déjà). |
| Sens avant | Idempotent : filtre `full_unit_price__isnull=True`, relançable. |
| Sens arrière | Réversible : `RemoveField` (inverse de AddField) + `noop`. Après retour arrière, le code précédent relit le catalogue (BUG-508 réapparaît, sans perte de données comptables). |
| Verrou / grosse table | Point d'attention. (a) PostgreSQL : AddField nullable = instantané, mais la migration est atomique : le `ACCESS EXCLUSIVE` sur `sales_invoiceline` est conservé pendant TOUT le rétro-remplissage, qui fait 1 `UPDATE` par ligne (après `select_related`, y compris pour les ventes normales). Sur ~10^5 lignes cela se compte en dizaines de secondes à minutes de blocage des ventes au cloud. (b) SQLite (nœud local) : reconstruction de table, écrivain unique ; acceptable à l'échelle d'une boulangerie. |
| Amélioration proposée (non appliquée) | Scinder en deux migrations (schéma / données) ; ventes normales : un seul `UPDATE ... SET full_unit_price = unit_price WHERE full_unit_price IS NULL AND invoice.is_soldee = false` (`F('unit_price')`, ou sous-requête) ; boucle par lots seulement pour les soldées ; `atomic = False` sur la migration de données avec lots. |

## 2. Impact comptable de BUG-513 sur les états financiers N / N-1

Exemple fictif : 100 pains MINI livrés à 300 FC (30 000 FC), puis tarif MINI -> 400 FC.

| État / ligne | Source | Avant | Après | Verdict |
|---|---|---|---|---|
| Compte de résultat : `revenue_300`, `total_revenue` | `Sum(line_total)` figé, regroupé par `bread_price.category` | 30 000 | 30 000 | Stable (test vert). |
| Compte de résultat : charges matières, dépenses, commissions | CUMP figé, `LocalExpense`, `ClientCommission` | inchangé | inchangé | Stable. |
| Balance / cash-flow / solde livre de caisse | `CashbookEntry` (hash) | inchangé | inchangé | Stable : ne lit aucun tarif. |
| Bilan : stock de consommables, créances (`current_debt`) | CUMP, BP | inchangé | inchangé | Stable. |
| DOC 1 `qty_300` / `qty_400` (finance l.309, l.386) | `bread_price.unit_price` courant | 100 | 0 (et aucune colonne 400) | **Dérive** : BUG-518. Les montants (`order_total`) restent justes. |
| Clôture journalière d'un jour passé : `produit.fc` | `qty x catalog_price` (production/views.py l.2836) | 30 000 | 40 000 | Dérive +10 000 (BUG-513). |
| Clôture journalière : `reste_du_jour_fc`, `reste_du_hier_fc`, `appro_*_fc`, `mvm_interne_fc`, `total_du_jour` | idem l.2779-2810 | 100 pains = 30 000 | 40 000 | Dérive ; `facture_mvm_interne`/`total_du_jour` et l'« Écart / Production » du jour passé bougent donc, alors que `facture_fc`/`soldee_fc` (figés) ne bougent pas : l'identité du rapport est faussée. |
| `ProductionSession.total_fc_produced`, `yield_gap` (`compute_totals`, models.py l.120) | `qty x bread_price.unit_price` | écart 0 (si 1 sac = 150 000... valeur théorique inchangée) | écart +10 000 (excédent fictif) | Dérive à chaque nouveau `save()`/`compute_totals()` d'une fournée passée. |
| `delivered_value_fc` (services.py l.54) | tarif au moment de la livraison, ensuite cumulé | figé | figé | Fige (écrit une fois). |

Conclusion : les états financiers du module `finance/` (N et N-1) ne sont PAS impactés par BUG-513, le CA vient de `line_total` figé. L'impact est confiné à la clôture journalière, aux écarts de rendement (« manquant / excédent ») et au DOC 1 (quantités). Sur un exercice N-1 rouvert après hausse de tarif, la clôture journalière d'un jour de N-1 afficherait +33 % de valeur produite/reste (400/300) sans que le CA N-1 ait bougé.

Défauts annexes trouvés au passage dans `finance/` : le CA agrège seulement 4 catégories codées en dur (BUG-520), et DOC 1 ne connaît que les paliers 200/300/500/1000 (BUG-518).

## 3. Lieux de lecture du tarif courant (non-test, `backend/`)

| Fichier:ligne | Usage | Verdict |
|---|---|---|
| sales/models.py:264-266 | `full_unit_price` figé à la 1re sauvegarde depuis `BreadPrice` | Fige (instant de la création) |
| sales/models.py:286 | `loss` : `full_unit_price`, repli catalogue si NULL | Fige (repli seulement avant 1er save) |
| sales/services.py:86-89 | recalcul `line_total` après livraison partielle avec `line.unit_price` | Fige |
| sales/views.py:617-622 | contrôle de plafond à la création : prix courant | Légitime (fait présent) |
| sales/views.py:1221 | regroupement par `unit_price` figé des lignes | Fige (mais prix 75 % pour les soldées) |
| sync/services.py:494-497 | `_push_invoice_line` : `create()` sans `unit_price`/`full_unit_price` | **Relit** : BUG-519 |
| sync/services.py:477-480 | mise à jour de quantité par `update()` avec `unit_price` de la ligne | Fige |
| production/views.py:2384-2390 | `_full_price_from_frozen_soldee` (RG soldée) | Fige (repli catalogue si NULL) |
| production/views.py:2503-2504 | `line.loss` | Fige |
| production/views.py:2560 | NS statut : `ln.unit_price` | Fige |
| production/views.py:2698 | `catalog_price = Decimal(bp.unit_price)` | **Relit** : BUG-513 |
| production/views.py:2779, 2782, 2783, 2804, 2805, 2809, 2810, 2836 | valorisation reste / appro / produit | **Relit** : BUG-513 |
| production/views.py:2680, 2841, 3456, 2185-2234 | tri / affichage du tarif de catégorie | Affichage du catalogue courant (légitime) ; `unit_price` renvoyé sur un rapport passé = tarif courant |
| production/views.py:399, 3421 | tri / liste catégories actives | Légitime |
| production/models.py:120 | `ProductionSession.compute_totals` : `total_fc_produced`, `yield_gap` | **Relit** (recalculé à chaque appel) : BUG-513. Le nom `total_declared_value` cité dans le ticket n'existe pas, c'est ce calcul |
| production/models.py:143 | `price_map` legacy `breads_300/400...` | **Relit** (champs legacy par prix courant) |
| production/models.py:189 | `ProductionSessionLine.line_fc` | **Relit** |
| production/services.py:54-56 | `delivered_value_fc` à la livraison | Fige (additif à l'instant du fait) |
| production/services.py:256-259 | `finalize_derived_production` : `total_fc_produced` à la clôture | Fige au moment de la clôture, mais sera écrasé par `compute_totals()` si la fournée est réenregistrée |
| production/serializers.py:8, 163, 307 | `unit_price` = `bread_price.unit_price` | Relit (affichage de lignes de production/transfert passées) |
| production/migrations/0026:27 | rétro-remplissage de valeur de fournée au tarif courant | Relit (migration, historique de fait) |
| finance/views.py:41-44 | CA par catégorie (`line_total`) | Fige |
| finance/views.py:309, 386 | paliers DOC 1 par `bread_price.unit_price` | **Relit** : BUG-518 |
| treasury/, commissions/, clients/, blockchain/ | aucune lecture de `BreadPrice`/`unit_price` hors tests | n/a |

Remarque : `total_declared_value`, cité dans le ticket, ne figure nulle part dans le code (0 occurrence hors tests) ; l'équivalent réel est `compute_totals()` / `total_fc_produced`.

## 4. Correctif minimal proposé pour BUG-513 (non implémenté)

Option minimale retenue : figer la valeur au moment du fait, comme `InvoiceLine`, sur les seuls faits de production.
1. `ProductionSessionLine` et `DailyBreadStockSnapshot` (et lignes de confirmation/transfert utilisées dans le rapport) reçoivent `unit_price_frozen` (PositiveIntegerField, NULL), renseigné au 1er `save()` depuis `BreadPrice` ; migration en 2 temps avec rétro-remplissage au tarif courant (seule référence disponible), tracé dans les notes de migration.
2. `compute_totals()` : `quantity * (line.unit_price_frozen or bread_price.unit_price)` ; mêmes lectures dans `line_fc`, `price_map`.
3. `_build_daily_closure_report` : remplacer `catalog_price = bp.unit_price` par un prix par catégorie résolu pour `report_date` = `unit_price_frozen` du premier fait du jour pour cette catégorie, repli tarif courant uniquement si aucune ligne figée (jour sans fait) ; l'identité `total_du_jour` reste alors cohérente.
4. Alternative plus générale (recommandée si le client confirme Q-028) : table `BreadPriceHistory(bread_price, price, valid_from)` alimentée par le signal `post_save` de `BreadPrice` (core/signals.py:75) + fonction `price_on(bp, date)` utilisée partout (production, DOC 1, ventes rétroactives). Un seul point de vérité, couvre aussi les « Ventes Passées ».
5. DOC 1 (BUG-518) : regrouper par `line.full_unit_price`/`unit_price` ou par `bread_price_id` au lieu du tarif courant.
Test à ajouter : celui du ticket (`test_past_day_produced_value_after_tariff_change`) passe sans `@expectedFailure` ; plus un test `compute_totals()` après changement de tarif.

## 5. Contradictions et points non tranchés

- adaptes.md et cadre_comptable.md : aucune règle sur la conservation d'un historique de tarifs ; le cadre exige des états N / N-1 stables mais ne dit pas comment valoriser un stock/une production passée. Question client Q-028 ajoutée (`docs/qa/QUESTIONS_CLIENT.md`).
- remarque.md l.303 impose la modification de la grille tarifaire (rend le problème certain en exploitation) ; remarque.md l.362 « Ventes Passées (saisie rétroactive) » : une facture rétroactive se valorise aujourd'hui au tarif du jour de saisie, pas du jour saisi : cas non spécifié (inclus dans Q-028).
- CLAUDE.md §5.1/§4 : « les prix viennent toujours de `BreadPrice` » et « `InvoiceLine.save()` fige `unit_price` » : cohérents avec le fige ; la lecture courante dans la clôture n'est pas une contradiction mais une lacune du principe « figer » étendu à la production.
- Cadre comptable (TFR) : le compte de résultat actuel regroupe par catégorie `MINI/MOYEN/GRAND/PREMIUM` (BUG-520), ce qui ne correspond à aucune activité du cadre : à traiter avec `ECART_CADRE_COMPTABLE.md`.

## 6. Tickets

| Ticket | Titre | Sévérité | Test |
|---|---|---|---|
| BUG-513 (note d'audit ajoutée) | Clôture journalière / production relisent le tarif courant | Mineur -> à rehausser en Majeur si Q-028 = historique figé (valeur des écarts de rendement faussée) | test existant (production) |
| BUG-518 | DOC 1 classe les quantités par tarif courant ; pains perdus après changement de prix | Majeur | `finance/tests/test_verif_bug513_c.py::...::test_doc1_quantities_stable_after_tariff_change` (`@expectedFailure`) |
| BUG-519 | Push de sync recrée la ligne au tarif du cloud (`full_unit_price`/`unit_price` non transportés) | Majeur | à écrire (testeur-sync) |
| BUG-520 | CA limité à 4 catégories codées en dur, catégories configurées exclues du résultat | Majeur | `finance/tests/test_verif_bug513_c.py::Bug520CustomCategoryRevenueTests::...` (`@expectedFailure`) |
| Q-028 | Question client : tarif figé à la date du fait ou courant ? | À CLARIFIER | — |
| Remarque migration 0011 | Verrou long sur gros volume PostgreSQL (UPDATE par ligne dans une migration atomique) ; non ouvert en BUG car pas encore appliquée en production : à traiter par Dev A avant déploiement cloud | Mineur (préventif) | — |

Exécution : `manage.py test finance.tests.test_verif_bug513_c` -> 5 tests, OK (expected failures = 2). Suite complète non relancée (consigne).

---

# Cycle test 1 (partie C : finance, trésorerie, blockchain) — 2026-11-22

Lecture seule du code applicatif. Données 100 % fictives (`data_kiese/` non utilisé). Tests : `backend/finance/tests/test_audit_c_cycle1_c.py` (34 tests, 27 verts, 7 `@expectedFailure`). `python manage.py test finance` : 75 tests OK (9 échecs attendus au total, tous les anciens et ceux-ci).

## 1. Scénario rejoué (API : factures, livraisons, rapports, dépenses, clôtures avec billetage, validation, versement au livre ; ORM : consommables)
2 boulangeries, 3 jours (K1) et 2 jours (K2) du mois précédent, exercice N-1 avec 1 vente / 1 dépense / 1 versement / 1 sortie de farine. Calcul à la main dans la docstring du fichier.

| Agrégat | Attendu (main) | Application | Verdict |
|---|---|---|---|
| CA GRAND / MINI / PREMIUM | 14 750 / 12 300 / 2 000 | idem | OK |
| CA total (vente soldée à 75 % incluse) | 29 050 | 29 050 | OK |
| Cash facturiers K1 / K2 | 18 800 / 6 500 | idem | OK |
| Crédit (hors soldée) | 7 000 | 7 000 | OK |
| Dépenses locales | 3 300 | 3 300 | OK |
| Net des 5 clôtures | 22 000 | 22 000 | OK |
| Écart de caisse | -50 (1 jour) | -50 | OK |
| Livre de caisse N-1 / N | 1 600 / 23 600 | idem ; chaîne de hash valide | OK |
| Cash-flow N : entrées / sorties / net / clôture | 22 000 / 0 / 22 000 / 23 600 | idem | OK |
| Cash-flow : clôture N = clôture N-1 + net N | 23 600 | 23 600 | OK |
| Créances (BP) | 3 000 | 3 000 | OK |
| CA - cash = créances + manquant soldée | 3 750 = 3 000 + 750 | 3 750 | OK |
| CM brute A/B/E/F (C exclue) | 2 200 / 2 250 / 1 500 / 375 | idem | OK |
| Net à payer A/B/E/F | 200 / 2 250 / 1 500 / -625 | idem | OK |
| Coût farine (CUMP, stock reporté de N-1, SIEGE exclu) | 21 006,8965 | 21 006,8965 | OK (voir BUG-806) |
| Résultat net | 29 050 - 21 006,8965 - 3 950 - 3 300 = 793,1035 | 793,1035 | OK (non arrondi, BUG-806) |
| Bilan N : créances / caisse / actif | 3 000 / 23 600 / 26 600 | idem | OK |
| Bilan N-1 : caisse / actif | 1 600 / 1 600 | 23 600 / 26 600 | ECART : BUG-800 |
| Exercice vide : bilan | 0 | caisse actuelle | ECART : BUG-800 |
| Exercice vide : compte de résultat, cash-flow | 0, croissance None | 0, None | OK |
| CA avec ajustement -2 pains (500) | 4 000 | 6 000 | ECART : BUG-801 |
| CA avec régularisation RG 3 000 | 0 | 3 000 | ECART : BUG-802 |

Note : mon premier calcul à la main du coût farine (21 100) ignorait le stock reporté de N-1 (9 sacs à 4 000) : l'application était juste, l'erreur venait de moi (corrigée).

## 2. Contrôles demandés
- Balance Σ débit = Σ crédit : impossible, il n'existe pas de balance (BUG-808, contradiction avec `cadre_comptable.md`, Q-003).
- Bilan actif = passif : impossible (actif seul), idem BUG-808.
- Résultat cohérent entre états : OK au sens CA - coûts - commissions - dépenses ; identité CA - cash = créances + manquant OK ; cash-flow = variation du livre OK ; bilan N-1 faux (BUG-800).
- Caisse = livre de caisse : OK sur le théorique ; l'écart physique n'est pas au livre (BUG-809, Q-042).
- Fuite entre boulangeries : aucune. Gérant K1 et facturier : 403 sur les 4 états avec ou sans `?node=` et sur le livre ; clôtures et dépenses du gérant limités à son nœud (`?node=<K2>` ignoré), commissions limitées à K1.
- Decimal : montants exacts à 4 décimales, mais non arrondis (BUG-806) et rendus en float JSON (BUG-807) ; CUMP 4 décimales dans une colonne à 2 (BUG-803).
- Exercice N-1 vide : états à zéro, hors bilan (BUG-800).

## 3. Tickets ouverts (BUG-800 à BUG-809)
800 Majeur (bilan N-1), 801 Majeur (ajustement négatif au CA), 802 Majeur (RG au CA), 803 Mineur (CUMP 2/4 décimales), 806 Mineur (arrondi), 807 Mineur (float JSON) : OUVERT. 804, 805, 808, 809 : À CLARIFIER (Q-040, Q-041, Q-003, Q-042).

## 4. Contradictions entre documents (signalées, non tranchées)
1. `cadre_comptable.md` (balance, bilan, TFR, comptes) vs `CLAUDE.md` 5.6 / code actuel (4 catégories de CA codées en dur, bilan à 2 postes) : écart chiffré dans `docs/qa/ECART_CADRE_COMPTABLE.md`, en attente de Q-003 (avenant).
2. `CLAUDE.md` 5.3 (CM brute, retenues, remise annuelle 0,025 x volume) vs `adaptes.md` / classeurs (BUG-058/295 : remise 0,25 % affichée non déduite, remise annuelle par INDICE x TARIF + MÉRITE) : le code suit adaptes.md ; CLAUDE.md 5.3 est périmé sur ce point.
3. `CLAUDE.md` 5.5 (livre de caisse : `solde = précédent + entrée - sortie`, clôture = caisse nette) vs obligation d'écart journalisé : le livre reçoit le théorique (Q-042).
4. Comptabilité d'engagement implicite dans `cadre_comptable.md` (charges à la période) vs charge « commissions » = net payé (Q-041).

## 4 bis. Blockchain / hash
Aucune anomalie nouvelle : la chaîne de 6 écritures du scénario (N-1 puis N, deux boulangeries) se vérifie avec `verify_cashbook_chain`, les soldes cumulés sont recalculés ligne à ligne.

## 5. Limites
Aucun test PostgreSQL (BUG-803 démontré par le schéma, pas par la valeur). Le scénario suppose le mois précédent complet et le même exercice : un seul exercice N et N-1 (pas de clôture d'exercice). Le DOC 1 n'est pas rejoué pour l'ajustement (suspicion notée sur BUG-801).
