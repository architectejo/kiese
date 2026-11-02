# Rapport — dev-backend, 2026-11-02

## Mission

Corriger BUG-120 (`docs/qa/REGISTRE_BUGS.md`) suite aux réponses du client sur Q-006/Q-007
(`docs/qa/QUESTIONS_CLIENT.md`), transmises par le coordinateur. Quatre points laissés `AMBIGU`/
`À CORRIGER` par l'audit comptable (`docs/qa/rapports/auditeur-comptable-2026-11-02-audit-bug120.md`) :
`facture_mvm_interne`/`total_du_jour_fc` (Q-006), `ecart_facture_fc` (Q-007.1), `tarif_vente_*`
(Q-007.2), `repartition_pct` (Q-007.3).

Fichier modifié : `backend/production/views.py` (`_build_daily_closure_report`), rien d'autre dans
le code applicatif — endpoint lecture seule, aucune écriture, aucun nouveau modèle, aucune migration.

## Corrections appliquées

### Q-006 — `facture_mvm_interne` et `total_du_jour_fc`

Preuve chiffrée de l'audit : `K6!L21 = SUM(L8:L20)` = RESTE DU JOUR + RESTE DU HIER + APPRO EFFECTUE +
APPRO REÇU + NON SERVI + RÉGULARISATION + VENTE CASH + VENTE SOLDE + NON VENDU(NV) + DÉCLASSÉS +
EXCÉDENT PAINS + MANQUANT PAINS. `K6!L132 = L128 (facturation clients) + L21 (ce sous-total) = 840000`.

`facture_mvm_interne` n'est donc **plus** une facture distincte portant un `special_code` = code
boulangerie (interprétation initiale de dev-backend, invalidée par l'audit — de toute façon
irréalisable : `InvoiceCreateSerializer.special_code` n'accepte que `['', 'NV', 'RG', 'NS']`). C'est
désormais, **par catégorie de pain**, la somme en FC de :

- `reste_du_jour` (toutes équipes confondues) × prix catalogue
- `reste_du_hier` (toutes équipes confondues) × prix catalogue
- `appro_effectue` × prix catalogue
- `appro_recu` × prix catalogue
- `non_servi` (déjà en FC)
- `regularisation` (déjà en FC)
- `vente_cash_soldee` (déjà en FC — un seul bucket `is_soldee` couvre VENTE CASH et VENTE SOLDE dans
  le modèle actuel, voir limite ci-dessous)
- `non_vendu_nv` (déjà en FC, `BreadDisposal.total_value`)
- `declasses` (déjà en FC)
- EXCÉDENT/MANQUANT : **0** — aucune donnée source par catégorie dans le modèle actuel (audit point 2,
  confirmé non bloquant : l'écart théorique/réel n'existe qu'au niveau global de la session,
  `ProductionSession.yield_gap`)

`reste_du_jour`/`reste_du_hier`/`appro_effectue`/`appro_recu`/`non_vendu_nv`/`declasses` exposaient déjà
une `quantity` mais pas de `fc` — ajouté (valorisé au prix catalogue `BreadPrice.unit_price`, seule
source de prix disponible pour ces rubriques).

`total_du_jour_fc` = facturation normale (`FACTURE/JR`, ventes nommées à un client) + la somme de
`facture_mvm_interne.fc` sur toutes les catégories — reproduit exactement la structure
`L132 = L128 + L21` de la pièce réelle.

### Q-007.1 — `ecart_facture_fc`

Réponse client : « commandes, paiements sur commande » (montants FC). Remplacé par :

```
ecart_facture_fc = Σ(Invoice.order_total) − Σ(Invoice.payment_amount)
```

sur toutes les factures `DELIVERED` du nœud/jour (régularisations et ventes soldées incluses — ce sont
des factures comme les autres ; les remboursements BP ont `order_total`/`payment_amount` toujours nuls
par construction, CLAUDE.md §5.2, donc neutres sans exclusion explicite nécessaire). Calcul agrégé en
base avec `Sum()`, normalisé en `Decimal` via `_m()` — jamais de `float` (CLAUDE.md §4).

### Q-007.2 — `tarif_vente_fc`

Réponse client : « saisi par vous par boulangerie » — valeur fixe, pas une moyenne. Remplacé l'ancien
`tarif_vente_moyen_fc` (moyenne `total_du_jour_fc / pains facturés`) par `tarif_vente_fc`, lu
directement via `_effective_sac_value(node, config)` (déjà utilisée ailleurs dans ce fichier pour
« Valeur Théorique par Sac de Farine ») : `Node.sac_value_fc` si renseigné, sinon
`Config.sac_value_fc`. Aucun recalcul à partir des ventes du jour. Nom de champ changé (l'ancien nom
contenait « moyen », trompeur) — voir contrat ci-dessous.

### Q-007.3 — `repartition_pct`

Réponse client : « fait les deux, on va choisir ». Remplacé l'unique `repartition_pct` (par quantité
produite) par deux clés toujours présentes simultanément :

- `repartition_pct_par_quantite` : part de chaque catégorie dans le total de pains **produits** ce
  jour (identique à l'ancien calcul, jamais trois).
- `repartition_pct_par_valeur` : part de chaque catégorie dans la valeur produite totale en FC (prix
  catalogue × quantité produite).

Aucun choix n'est fait côté backend entre les deux variantes — réservé à un futur sélecteur frontend.

## Contrat d'API final — `GET /api/production/daily-closure/?node=<code ou pk>&date=<AAAA-MM-JJ>`

Permissions : `IsGerant` (GERANT et au-delà). Un non-HQ (`user.can_access_all_nodes=False`) ne consulte
toujours que `user.node` — `?node=` est silencieusement ignoré. HQ doit fournir `?node=`. `?date=`
toujours requis (400 sinon). Lecture seule, aucun effet de bord.

### Réponse 200

```json
{
  "node": "K1",
  "date": "2026-11-02",
  "categories": [
    {
      "bread_price": 12,
      "label": "Pain 300 FC",
      "unit_price": 300,
      "produit": {"quantity": 140, "fc": "42000.00"},
      "facture_jr": {"quantity": 30, "fc": "9000.00"},
      "commission_jr": {"fc": "2250.00"},
      "reste_du_jour": {"A": 20, "B": 10},
      "reste_du_hier": {"A": -15, "B": 0},
      "appro_effectue": {"quantity": 0, "fc": "0.00"},
      "appro_recu": {"quantity": 15, "fc": "4500.00"},
      "non_servi": {"quantity": 0, "fc": "0.00"},
      "regularisation": {"quantity": 10, "fc": "3000.00"},
      "vente_cash_soldee": {"quantity": 10, "fc": "2250.00", "perte_fc": "750.00"},
      "facture_mvm_interne": {"fc": "14250.00"},
      "non_vendu_nv": {"quantity": 0, "fc": "0.00"},
      "declasses": {"quantity": 5, "fc": "0.00"},
      "sorties_gratuites": {"quantity": 0, "fc": "0.00"}
    }
  ],
  "totals": {
    "total_du_jour_fc": "38250.00",
    "net_produit_fc": "67000.00",
    "ecart_facture_fc": "3000.00",
    "nombre_sacs_produits": "3.00",
    "moyenne_produit_par_sac_fc": "22333.33",
    "tarif_vente_fc": "200000",
    "ecart_production_fc": "-533000",
    "total_breads_produced": 190,
    "total_breads_billed": 70,
    "repartition_pct_par_quantite": [
      {"bread_price": 12, "label": "Pain 300 FC", "pct": "73.68"},
      {"bread_price": 13, "label": "Pain 500 FC", "pct": "26.32"}
    ],
    "repartition_pct_par_valeur": [
      {"bread_price": 12, "label": "Pain 300 FC", "pct": "62.69"},
      {"bread_price": 13, "label": "Pain 500 FC", "pct": "37.31"}
    ]
  }
}
```

(Valeurs d'exemple reprises du scénario de test `test_daily_closure_report_aggregates_exact_totals`.)

### Détail des champs

Par catégorie (`categories[]`, triées par `unit_price` croissant, une entrée par `BreadPrice` actif ou
concerné par une donnée du jour) :

| Champ | Type | Formule / source |
|---|---|---|
| `bread_price` | int | PK `BreadPrice` |
| `label` | str | `BreadPrice.label` |
| `unit_price` | int | prix catalogue |
| `produit.quantity` | int | Σ `ProductionSessionLine.quantity` (sessions du nœud/jour) |
| `produit.fc` | str (Decimal) | `produit.quantity × unit_price` |
| `facture_jr.quantity`/`.fc` | int / str | Σ `InvoiceLine` des factures normales livrées (ni ajustement, ni soldée, ni NS) |
| `commission_jr.fc` | str | Σ `line_total × invoice.commission_rate` |
| `reste_du_jour` | `{équipe: int\|null}` | `DailyBreadStockSnapshot.reste_du_jour` par équipe (Chantier B) — **inchangé, pas de `fc` par équipe** |
| `reste_du_hier` | `{équipe: int\|null}` | `DailyBreadStockSnapshot.reste_du_hier` par équipe — **inchangé** |
| `appro_effectue.quantity`/`.fc` | int / str | `BreadTransferLine.quantity_sent` (transferts `CONFIRMED` ce jour, `from_node=nœud`) ; `fc` = `quantity × unit_price` **(nouveau)** |
| `appro_recu.quantity`/`.fc` | int / str | idem, `to_node=nœud`, `quantity_received` ; `fc` **(nouveau)** |
| `non_servi.quantity`/`.fc` | int / str | factures `special_code=NS` |
| `regularisation.quantity`/`.fc` | int / str | factures d'ajustement, signées par `adjustment_sign` |
| `vente_cash_soldee.quantity`/`.fc`/`.perte_fc` | int / str / str | factures `is_soldee=True` ; `perte_fc` = Σ `InvoiceLine.loss` |
| `facture_mvm_interne.fc` | str | **(formule changée, Q-006)** somme en FC de reste_du_jour+reste_du_hier+appro_effectue+appro_recu+non_servi+regularisation+vente_cash_soldee+non_vendu_nv+declasses (EXCÉDENT/MANQUANT=0) — **ne porte plus de `quantity`** |
| `non_vendu_nv.quantity`/`.fc` | int / str | `BreadDisposal` type `UNSOLD` ; `fc` **(nouveau)** |
| `declasses.quantity`/`.fc` | int / str | type `DECLASSED` ; `fc` **(nouveau)** |
| `sorties_gratuites.quantity`/`.fc` | int / str | type `FREE_DIST` ; `fc` **(nouveau)** |

`totals` :

| Champ | Formule |
|---|---|
| `total_du_jour_fc` | **(formule changée, Q-006)** Σ `facture_jr.fc` + Σ `facture_mvm_interne.fc` (toutes catégories) |
| `net_produit_fc` | Σ `ProductionSession.total_fc_produced` du nœud/jour |
| `ecart_facture_fc` | **(formule changée, Q-007.1)** Σ `Invoice.order_total` − Σ `Invoice.payment_amount`, factures `DELIVERED` nœud/jour |
| `nombre_sacs_produits` | Σ `ProductionSession.flour_sacks_used` |
| `moyenne_produit_par_sac_fc` | `net_produit_fc / nombre_sacs_produits` (ou `null` si 0 sac) — **inchangé** |
| `tarif_vente_fc` | **(renommé + formule changée, Q-007.2)** `Node.sac_value_fc` ou `Config.sac_value_fc` par défaut — valeur fixe, jamais recalculée. Remplace `tarif_vente_moyen_fc` (supprimé). |
| `ecart_production_fc` | Σ `ProductionSession.yield_gap` — **inchangé**, toujours global (jamais par catégorie, confirmé conforme par l'audit) |
| `total_breads_produced` | Σ `ProductionSession.total_breads` |
| `total_breads_billed` | pains facturés (normal + soldée + régularisation) — **inchangé** |
| `repartition_pct_par_quantite` | **(remplace `repartition_pct`, Q-007.3)** `[{bread_price, label, pct}]`, % du nombre de pains produits par catégorie |
| `repartition_pct_par_valeur` | **(nouveau, Q-007.3)** `[{bread_price, label, pct}]`, % de la valeur produite en FC par catégorie |

### Changements de contrat par rapport à la version initiale du ticket

L'endpoint `GET /api/production/daily-closure/` est entièrement neuf (livré dans la même session que
ce correctif) — aucun frontend ne le consomme encore, donc **aucun ticket `dev-frontend` séparé n'est
nécessaire** ; le développement frontend de ce rapport s'appuiera directement sur le contrat ci-dessus.
Pour mémoire, les changements effectifs par rapport à la toute première version (jamais exposée à un
consommateur) :

- `facture_mvm_interne` : `{quantity, fc}` → `{fc}` (perte de `quantity`, dimensionnellement incohérent
  entre les rubriques sommées).
- `appro_effectue`/`appro_recu`/`non_vendu_nv`/`declasses`/`sorties_gratuites`/`produit` : ajout de
  `fc` (absent avant).
- `totals.tarif_vente_moyen_fc` supprimé → `totals.tarif_vente_fc` (nom et formule différents).
- `totals.repartition_pct` supprimé → `totals.repartition_pct_par_quantite` +
  `totals.repartition_pct_par_valeur` (toujours les deux).
- `totals.ecart_facture_fc` : même nom, formule différente.
- `totals.total_du_jour_fc` : même nom, formule différente (inclut désormais `facture_mvm_interne`).

## Limites et ambiguïtés résiduelles (non tranchées seul)

- **EXCÉDENT/MANQUANT par catégorie** : toujours 0 dans `facture_mvm_interne` — aucune donnée source
  par catégorie n'existe dans le modèle actuel (confirmé non bloquant par l'audit comptable, point 2 :
  l'écart théorique/réel du vrai document n'est calculé qu'au niveau global de la session). Si le
  client confirme un jour vouloir une vraie décomposition par catégorie, cela nécessitera une évolution
  de schéma (hors périmètre de ce correctif).
- **VENTE CASH vs VENTE SOLDE** : un seul bucket (`Invoice.is_soldee`) couvre les deux dans le modèle
  actuel — `facture_mvm_interne` les additionne donc ensemble, sans jamais les dupliquer ni les
  distinguer. À signaler si le client confirme qu'il s'agit de deux flux à tracer séparément.

## Tests

- `backend/production/tests/test_daily_closure_report.py` : scénario de données **inchangé** (même
  fixtures, mêmes appels API) — toutes les valeurs attendues recalculées à la main en `Decimal` selon
  les 4 nouvelles formules ; nouvelles assertions sur les champs `fc` désormais exposés
  (`produit`/`appro_effectue`/`appro_recu`/`non_vendu_nv`/`declasses`) et sur `facture_mvm_interne`
  (nouvelle structure `{fc}`).
- `python manage.py test production.tests.test_daily_closure_report -v 2` → **5/5 OK**.
- `python manage.py test production sales` (toutes les apps directement concernées/dépendantes de ce
  correctif — `production/views.py` importe `sales.models` en interne) → **130/130 OK**.
- `python manage.py makemigrations --check --dry-run` → « No changes detected » (endpoint lecture
  seule, aucune migration créée par ce correctif).
- `PRAGMA integrity_check` sur `backend/db.sqlite3` → `ok`.
- `python manage.py test` (suite complète, ~1489 méthodes de test sur l'ensemble du dépôt) : **lancée
  mais non terminée dans le temps de cette session**. L'environnement a connu un ralentissement
  inhabituel pendant cette tentative (déjà documenté par le passé pour BUG-118/BUG-119 : « contention
  CPU côté outillage ») — certains tests individuels ont pris jusqu'à plusieurs minutes chacun, rendant
  une exécution complète impraticable dans le temps disponible. Les ~200 premiers tests exécutés
  (`blockchain`, `clients`, `commissions`, une partie de `core` — tous des modules **non modifiés** par
  ce correctif) sont passés avec **0 `FAIL`/`ERROR`** observé avant l'arrêt de l'observation. Le
  périmètre de ce correctif est strictement limité à une fonction de `backend/production/views.py` et
  à son fichier de test — aucune modification de modèle, de migration, ni d'un autre module — ce qui
  limite fortement le risque de régression ailleurs. **Action restante pour le testeur/coordinateur** :
  relancer `python manage.py test` en entier (idéalement hors heures de forte charge de l'outillage)
  pour obtenir la confirmation finale « 0 échec » exigée par la mission — non obtenue à 100 % par
  dev-backend à la clôture de ce ticket, malgré plusieurs heures de tentative dans cette session.
