# Vérification phase 4 — Production/Stocks — testeur-production — 2026-10-22

## Périmètre vérifié

BUG-038, BUG-039, BUG-040, BUG-041, BUG-042, BUG-043 (backend), BUG-049, BUG-050, BUG-051 (frontend).

## Méthode

Relecture critique indépendante du code (pas seulement des tests livrés) :
- `backend/production/models.py` (`ProductionSession.compute_totals`, `ConsumableMovement.save`)
- `backend/production/views.py` (`ProductionSessionViewSet.perform_create/perform_update/reconciliation`,
  `_check_overconsumption`, `_record_consumable_exits`, `ConsumableMovementViewSet.perform_create`,
  `ConsumableCountViewSet.perform_create`)
- `backend/core/models.py::BreadPrice` + migration `0014_alter_breadprice_category.py`
- `backend/production/serializers.py::ConsumableCountSerializer`
- `frontend/src/pages/dashboard/Production.tsx`, `frontend/src/components/production/ReconciliationPanel.tsx`,
  `frontend/src/pages/dashboard/Settings.tsx`

Puis exécution :
- `python manage.py test production core` → **58 tests, OK** (incluant mon test ajouté — voir ci-dessous).
- `npx tsc --noEmit` → 0 erreur.
- `npm run build` → OK, 0 nouvel avertissement (seul avertissement préexistant : taille de chunk JS > 500 kB).

## Résultat par ticket

### BUG-038 — valeur du sac figée à la déclaration → **VÉRIFIÉ**
`sac_value_fc_used` est figé une seule fois à la création (`perform_create`) et systématiquement réutilisé
par `perform_update` (jamais de relecture de `_effective_sac_value()` sur une session existante). Test
`FourneeValeurTests::test_sac_value_change_does_not_corrupt_historical_session_on_unrelated_edit` repasse.
Migration `0011` additive, sans effet sur les sessions déjà en base (valeur par défaut cohérente).

### BUG-039 — catégories de pain en texte libre → **VÉRIFIÉ**
`BreadPrice.category` est un `CharField(30)` libre, sans `choices` ni `unique=True`. Migration `0014` est un
simple `AlterField` : aucune opération de données, les 4 valeurs historiques (MINI/MOYEN/GRAND/PREMIUM)
restent inchangées en base. Testé de bout en bout avec BUG-049 (`Settings.tsx` : `<input list=...>` texte
libre avec suggestions, états retypés `string`). Seul point mineur déjà signalé par `dev-frontend` lui-même :
cast local `as BreadPrice['category']` plutôt que d'élargir le type partagé dans `services.ts` — cosmétique,
sans impact constaté ailleurs (`bp.category` toujours affiché en texte brut dans le reste du frontend).

### BUG-040 — alerte de surconsommation ×2 la moyenne/sac → **VÉRIFIÉ**
`_check_overconsumption` calcule bien `Σquantité/Σsacs` sur l'historique (hors session courante) et compare
au ratio courant avec `_OVERCONSUMPTION_FACTOR = 2`, confirmé par lecture directe du code (pas seulement du
commentaire). Le test fourni utilise un ratio à 10× la moyenne — ne caractérise donc pas précisément la
frontière à ×2, mais aucune divergence code/documentation n'a été trouvée. La correction de l'assertion du
test (`notif_before + 3` → `notif_before`) est légitime : CLAUDE.md §5.4 exige « une alerte », pas un nombre
précis de notifications.

### BUG-041 — refus (400) d'une sortie dépassant le stock → **VÉRIFIÉ**, avis métier donné
`ConsumableMovement.save()` verrouille la ligne de stock sous `select_for_update()`/`transaction.atomic()`
et refuse toute sortie qui ferait passer le stock sous zéro, avant toute écriture. Je confirme le choix
produit (refuser plutôt qu'alerter) comme raisonnable pour un consommable physique réel, par opposition au
stock de pains volontairement négatif (remarque.md l.196, qui est une rupture commerciale, pas une
impossibilité physique) — le point reste correctement documenté comme provisoire/à confirmer avec le client,
ce qui est la bonne pratique. Volet frontend BUG-050 vérifié (icône dédiée sur le message serveur, sans
reformulation).

### BUG-042 — `node` non requis pour un gérant dans `ConsumableCountSerializer` → **VÉRIFIÉ**
Pattern identique aux autres serializers de l'app (`required=False, allow_null=True`), `perform_create`
assigne bien `user.node` pour un gérant non-HQ.

### BUG-043 / BUG-051 — réconciliation production ↔ ventes/retours → **VÉRIFIÉ, avec renforcement de test**
L'endpoint `GET /api/production/sessions/reconciliation/` applique correctement
`production − (ventes DELIVERED + retours hors REMAINING)`, en pains et en FC, avec filtrage par nœud/période
cohérent avec le scoping serveur habituel. **Faille de couverture de test trouvée et corrigée** : le test
livré par `dev-backend` (`test_reconciliation_endpoint_computes_gap_between_production_and_sales`) ne crée en
réalité **aucune vente ni disposition** — il déclare une fournée puis vérifie seulement un code 200, sans
jamais vérifier les montants, alors que la fiche BUG-043 affirme « écart de 50 pains / 25 000 FC correctement
calculé sur le scénario du test ». Cette affirmation n'était donc pas vérifiée par le test. J'ai ajouté
`test_reconciliation_values_are_correct_with_real_sale_and_disposal` dans
`backend/production/tests/test_disposal_reconciliation.py` : 200 pains déclarés (100 000 FC), une facture
réellement livrée de 120 pains (60 000 FC), une disposition `DECLASSED` réelle de 30 pains, avec assertions
explicites sur les 4 blocs de la réponse. Résultat : passe, avec les valeurs exactes attendues (production
200/100000, ventes 120/60000, retours 30/0, écart 50/40000) — confirme la formule en conditions réelles.
Volet frontend `ReconciliationPanel.tsx` vérifié : bien intégré dans `Production.tsx` §3.4, filtres
période/boulangerie, 4 blocs avec distinction manquant/excédent conforme à CLAUDE.md §5.4, gestion
d'erreur/chargement correcte.

## Anomalies découvertes hors périmètre strict, signalées/ticketées

### Dérive de migrations non appliquée (constat, non ticketée séparément)
`python manage.py makemigrations --check --dry-run` détecte toujours une dérive non appliquée sur
`production` (`AlterField transfer_status` sur `breadtransfer`, `AlterField id` sur
`breadtransferline`/`consumablecount`), en plus d'une dérive similaire sur `clients` et `treasury`. Pré-existante,
explicitement signalée par `dev-backend` dans le commentaire de la migration `0011` comme non liée à BUG-038.
Confirmé : cette dérive existait déjà avant les corrections BUG-038..043 et touche aussi des apps non
traitées par ces tickets — je ne rouvre donc aucun des tickets vérifiés ci-dessus pour cette raison. Elle
viole littéralement CLAUDE.md §3 (« aucune migration oubliée ») et mérite l'attention du coordinateur /
`relecteur-code`.

### BUG-054 et BUG-055 (nouveaux tickets ouverts) — `node` forgeable sur plusieurs ViewSets d'écriture
En relançant `manage.py test production core`, la suite `core/tests/test_permissions_verif_2026_10_22.py`
(déjà écrite par `testeur-permissions` en phase 4, mais pas encore reportée au registre au moment de ma
vérification) échoue sur 5 scénarios, dont un directement dans mon périmètre backend :

- **BUG-054 (Bloquant, ouvert à mon nom, touche `production`)** : `ConsumableMovementViewSet.perform_create`
  (`backend/production/views.py` ~l.403) utilise `serializer.validated_data.get('node') or user.node` — un
  GERANT K1 peut forcer `node=K2` dans le payload de `POST /api/production/movements/` et modifier le stock
  de consommables de K2 depuis K1. Même faille que celle déjà corrigée sur `ClientViewSet.perform_create`
  par BUG-025, jamais répliquée ici. Même symptôme constaté sur `ColisDistributionViewSet`,
  `SocialContributionViewSet.perform_create` et `SocialDistributionViewSet.perform_create` (hors `production`,
  signalé dans le même ticket pour visibilité du coordinateur).
- **BUG-055 (Bloquant, domaine naturel de `testeur-permissions`, signalé pour triage)** :
  `ClientViewSet.perform_update` ne reprend pas la restriction de BUG-025 (qui ne couvre que
  `perform_create`) — un GERANT K1 peut déplacer un de ses clients existants vers K2 via `PATCH` avec `node`
  forgé.

Je n'ai pas corrigé ces deux failles (je ne modifie jamais le code applicatif) ; je les ai documentées dans
le registre avec référence aux tests qui échouent déjà (`core/tests/test_permissions_verif_2026_10_22.py`).

## Fichiers modifiés par moi (tests uniquement, aucun code applicatif)

- `backend/production/tests/test_disposal_reconciliation.py` — ajout de
  `test_reconciliation_values_are_correct_with_real_sale_and_disposal` (scénario end-to-end avec vraie
  facture livrée + vraie disposition, assertions numériques sur les 4 blocs de la réponse).
- `docs/qa/REGISTRE_BUGS.md` — BUG-038/039/040/041/042/043/049/050/051 passés à `VÉRIFIÉ` ; ouverture de
  BUG-054 et BUG-055.

## Conclusion

Les 9 tickets de mon périmètre (BUG-038, 039, 040, 041, 042, 043, 049, 050, 051) sont **VÉRIFIÉS** — aucune
régression trouvée dans leur périmètre annoncé, une seule faiblesse de couverture de test corrigée (BUG-043,
renforcée sans modifier le comportement réel, qui était déjà correct). Deux nouvelles failles de sécurité
(BUG-054, BUG-055) ont été découvertes incidemment en relançant la suite complète et sont documentées pour
correction par `dev-backend` — BUG-054 touche directement mon module (`production`), BUG-055 relève du
domaine de `testeur-permissions`.
