# Rapport — Passage de non-régression complet, module Production/Stocks

- Par : testeur-production, le 2026-10-29.
- Périmètre : `backend/production/`, `frontend/src/pages/dashboard/Production.tsx`, interaction avec `treasury` (BUG-037, BUG-086).

## 1. Suite de tests `production`

`python manage.py test production` (relancé deux fois, environnement propre, base de test en mémoire) :

```
Ran 31 tests in 121.194s
OK
```

**31/31 verts, 0 échec, 0 erreur.** Aucun `@expectedFailure` actif n'est appliqué dans `backend/production/tests/` : les imports `from unittest import expectedFailure` subsistants dans `test_consumables.py`, `test_disposal_reconciliation.py` et `test_transfers.py` sont des reliquats documentaires (commentaires expliquant l'historique des bugs déjà corrigés — BUG-038 à BUG-043) ; seul `test_transfers.py` importe encore le symbole sans aucune occurrence du décorateur `@expectedFailure` dans tout le dossier (confirmé par `grep -rn "@expectedFailure"` → 0 résultat). Tous les scénarios historiquement rouges sont maintenant verts sans marquage spécial.

- BUG-068/BUG-084 (date codée en dur `'2026-10-22'`) : concernent exclusivement `treasury/tests/test_cashbook_level3.py` et `treasury/tests/test_reports_closures.py`, **pas `production`**. Non reproduits dans cette session (`test production` seul, aucun test treasury lancé). Statuts inchangés (OUVERT / REJETÉ doublon), hors périmètre, confirmés sans rapport avec Production.
- BUG-057 (dérive de migrations) : reproduit à l'identique (voir §3) — même cause (`AlterField id`/`transfer_status`, `unique_together` sur `production`/`clients`/`treasury`), aucune dérive nouvelle. Pas une régression, conforme au ticket déjà documenté.

## 2. Couverture des règles CLAUDE.md §5.4

Relecture ligne à ligne de §5.4 face aux fichiers de test existants :

| Règle | Test(s) couvrant | Statut |
|---|---|---|
| Sacs décimaux, pains par catégorie, équipe A/B | `test_fournees.py::FourneeValeurTests` | OK |
| Valeur théorique = sacs × valeur du sac, manquant/excédent signés | `FourneeValeurTests::test_theoretical_yield_uses_node_sac_value`, `test_excedent_is_positive` | OK |
| Changement de valeur du sac sans fausser l'historique | `test_sac_value_change_does_not_corrupt_historical_session_on_unrelated_edit` (BUG-038, VÉRIFIÉ) | OK |
| Catégorie de pain configurable (ajout/suppression, ex. 200 FC) | `BreadCategoryConfigurableTests` (BUG-039, VÉRIFIÉ) | OK |
| Consommables décimaux (sel g, levure 0,25, huile 0,33), décrémentés par la fournée | `FourneeConsumablesTests::test_salt_yeast_oil_decimal_quantities_are_decremented` | OK |
| Stock de pains incrémenté par la fournée | `test_bread_stock_incremented_by_fournee` | OK |
| Stock restant = initial + entrées − utilisé | `StockRestantSequenceTests` | OK |
| Liste des consommables disponible à l'approvisionnement | `ApprovisionnementConsumableListTests` (remarque.md l.22) | OK |
| Inventaire physique, écart calculé | `ConsumableCountGapTests` | OK |
| Alerte de surconsommation vs moyenne/sac | `OverconsumptionAlertTests` (BUG-040, VÉRIFIÉ) | OK |
| Stock négatif refusé/signalé | `NegativeConsumableStockTests` | OK (comportement tolérant documenté : refus ou signalement, les deux acceptés) |
| Transfert 3 temps (demande → réponse → confirmation) | `ThreeStepTransferWorkflowTests::test_full_three_step_flow_with_matching_quantities` | OK |
| Écart de validation → alerte + blocage clôture | `test_partial_validation_creates_dispute_and_notification`, `test_disputed_transfer_blocks_daily_closure_of_concerned_bakery` (BUG-037, VÉRIFIÉ) | OK |
| Somme groupe inchangée | vérifié dans `test_full_three_step_flow_with_matching_quantities` | OK |
| Seul K2/siège valide la réception, K1 ne peut pas | `test_source_bakery_cannot_confirm_its_own_shipment`, `test_destination_bakery_cannot_respond_to_its_own_request` | OK |
| Double validation → un seul mouvement | `test_double_confirmation_creates_only_one_stock_movement` | OK |
| Transfert multi-lignes | `test_multiline_transfer` | OK |
| Pains non valorisés (soldé/déclassé/invendu/don/reste à vendre) | `BreadDisposalCategorizationTests` | OK |
| Réconciliation production − (ventes + retours), pains et FC | `ProductionSalesReconciliationTests` (BUG-043, VÉRIFIÉ), avec vérification indépendante des chiffres (`test_reconciliation_values_are_correct_with_real_sale_and_disposal`) | OK |
| Isolation par nœud (`node` forgé) | `test_bug056_forged_node.py`, `test_bug056_verification_20261023.py` (BUG-056, VÉRIFIÉ) | OK |

**Aucun scénario de la section 5.4 n'est non couvert ou cassé.** Aucun nouveau test n'a été nécessaire.

## 3. Vérification spécifique du changement BUG-086 dans `test_transfers.py`

Changement examiné : ajout dans `ThreeStepTransferWorkflowTests.setUp` de :
```python
config = Config.get_instance()
config.allow_backdated_sales = True
config.save(update_fields=['allow_backdated_sales'])
```
accompagné d'un commentaire explicite référençant BUG-086.

**Analyse** : BUG-086 (fiche détaillée consultée dans `docs/qa/REGISTRE_BUGS.md`, statut VÉRIFIÉ par testeur-tresorerie le 2026-10-29) a ajouté une validation de date sur `CashClosureViewSet.perform_create`/`perform_update` : une date de clôture passée est désormais refusée par défaut, sauf si `Config.allow_backdated_sales=True`. Le test `test_disputed_transfer_blocks_daily_closure_of_concerned_bakery` cible spécifiquement BUG-037 (blocage de clôture pour transfert en écart non résolu) et pose volontairement une date de clôture passée (`'2026-10-05'`, antérieure à la date système réelle 2026-10-29). Sans l'activation de `allow_backdated_sales`, la requête serait désormais rejetée en 400 **avant même** d'atteindre le contrôle BUG-037 — le test réussirait toujours (assertion tolérante `assertIn(status, (400, 403))`) mais ne prouverait plus la bonne chose (confusion entre deux motifs de rejet distincts).

Confirmé :
- Le réglage activé ne supprime ni n'affaiblit aucune assertion existante : le test vérifie toujours `transfer.transfer_status == 'DISPUTED'` puis que la clôture est refusée.
- Ce n'est pas un contournement généralisé : seul ce test (dont le sujet n'est pas la validation de date) active le réglage dans son `setUp` ; les tests `test_bug086_*.py` (treasury, hors périmètre production) testent eux-mêmes le comportement de `allow_backdated_sales=False` sans jamais l'activer artificiellement.
- C'est une mise en situation légitime (précondition pour isoler la variable testée), pas un affaiblissement caché du test — conforme au commentaire inline, lui-même précis et vérifiable.
- Le reste du fichier (6 autres tests) n'a pas été touché.

**Conclusion : changement légitime, approprié, ne masque aucune régression.**

## 4. Parcours normal (non-régression fonctionnelle)

Les 31 tests couvrent le parcours complet fournée → consommables → stock de pains → transferts (3 temps) → inventaires → dispositions → réconciliation, exactement comme avant les changements récents (aucune régression détectée, aucune anomalie de comportement constatée par rapport aux rapports précédents du 2026-10-22).

## 5. Vérification manuelle navigateur

Non effectuée dans cette session : le port 8000 (backend) et 5173 (frontend) sont tous deux actuellement `LISTENING` avec des connexions `ESTABLISHED` actives (un autre processus/agent semble interagir avec l'application en ce moment). Par prudence (consigne de mission : ne pas tester manuellement si un autre agent travaille déjà sur l'application), je me suis abstenu de manipulation UI en direct pour ne pas interférer. À la place :
- `npx tsc --noEmit` (frontend) : **0 erreur**.
- Relecture de `frontend/src/pages/dashboard/Production.tsx` (1502 lignes) : les sections transferts/consommables/dispositions/réconciliation sont bien présentes et branchées sur les mêmes endpoints couverts par les tests backend ci-dessus (87 occurrences combinées de `transfer`/`disposal`/`consumable`/`reconciliation`).

Recommandation : un passage manuel UI (bureau + 360 px) reste à faire par le coordinateur/testeur-e2e dès que la fenêtre applicative est libre, mais rien dans le code ou les tests n'indique une régression visuelle liée aux changements récents (seul `treasury/views.py` a été modifié pour BUG-086, aucun fichier `production/` ni `Production.tsx` n'a changé).

## 6. État des migrations (base réelle)

```
python manage.py showmigrations   → aucune migration en attente ([ ] absent de la sortie)
python manage.py makemigrations --check --dry-run →
  production : 0013_alter_breadtransfer_transfer_status_and_more (AlterField transfer_status/id)
  clients    : 0007_remove_socialcontribution_unique_... (unique_together → UniqueConstraint)
  treasury   : 0012_remove_dailysavings_unique_daily_savings_node_date_and_more
```
Dérive identique, mot pour mot, à celle déjà documentée sous **BUG-057** (OUVERT, Mineur, assigné pour une fenêtre dédiée hors urgence). **Aucune dérive nouvelle.** Base réelle à jour (migrations appliquées), aucune action requise.

## 7. Anomalie trouvée

**Aucune nouvelle anomalie découverte.** Aucun ticket ouvert dans cette session.

## 8. Verdict

**Module Production/Stocks : PRÊT à présenter au client**, sous réserve des deux points déjà connus et hors périmètre bloquant :
- BUG-057 (dérive de migrations, Mineur, OUVERT, sans impact fonctionnel, affecte aussi `clients`/`treasury`) — à planifier, ne bloque rien.
- Aucun ticket Bloquant ou Majeur ouvert sur Production à ce jour.

Tous les scénarios de CLAUDE.md §5.4 sont couverts par des tests automatisés qui passent (31/31), le changement de setUp lié à BUG-086 dans `test_transfers.py` a été vérifié comme une précondition légitime (pas un affaiblissement), `npx tsc --noEmit` passe sans erreur, et aucune migration n'est en attente sur la base réelle. Seule réserve : la vérification manuelle navigateur n'a pas pu être menée dans cette session (application en cours d'utilisation par un autre agent) — à compléter dès disponibilité, sans qu'aucun indice ne laisse présager une régression.
