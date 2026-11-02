# Rapport dev-backend — Chantier C : Rapport de clôture consolidé — 2026-11-02

## Contexte

Mission : réunir, dans un seul endpoint backend en lecture seule, les données du vrai rapport de
clôture journalier du client (`data_kiese/EXTRAIT RAPPORT DE CLOTUREOCTOBRE 2026.xlsx`,
`data_kiese/daja_analysé/DOC 1 - RAPPORT  CLOTURE PAR GERANT  AOUT  2026.xlsx`), aujourd'hui éclatées
entre Production, Ventes/Clients et Clôture & Caisse. Ticket : **BUG-120** (docs/qa/REGISTRE_BUGS.md).

Périmètre respecté : aucune modification de `backend/treasury/` (Chantier D séparé, BUG-033) ; aucune
modification de données réelles (`data_kiese/`, `db.sqlite3`) ; aucune modification frontend.

## Ticket traité

- **BUG-120** — Rapport de clôture journalier consolidé par catégorie de pain. Statut : **CORRIGÉ**.
  Détail complet (cause, décisions de conception, ambiguïtés signalées) dans
  `docs/qa/REGISTRE_BUGS.md`.

## Ce qui a été fait

1. Nouvel endpoint en lecture seule : `GET /api/production/daily-closure/?node=<code ou pk>&date=<AAAA-MM-JJ>`
   - Implémenté comme `APIView` dédié `DailyClosureReportView` dans `backend/production/views.py`
     (plus approprié qu'une action sur `ProductionSessionViewSet` : ce rapport n'est rattaché à
     aucune session précise, il agrège plusieurs modules pour un couple nœud/date).
   - Routé en littéral dans `backend/production/urls.py`, avant le routeur DRF.
   - Permissions : `IsGerant` (couvre déjà ADMIN/DIRECTION/COMPTABLE/GERANT, donc HQ inclus) ; dans
     la vue, un non-HQ est toujours restreint à son propre nœud (le paramètre `node` du payload est
     ignoré, même motif que `get_queryset()` partout ailleurs dans ce module) ; un HQ doit préciser
     `node` explicitement (code ou PK).
2. Correctif connexe minimal : `BreadTransferViewSet.confirm_reception()` persiste désormais
   `updated_at` (`update_fields`) — ce champ `auto_now` n'était jamais écrit en base à cette étape
   (bug latent, sans incidence fonctionnelle connue avant ce ticket, mais bloquant pour filtrer les
   « transferts confirmés ce jour », `BreadTransfer` n'ayant pas d'autre champ de date de
   confirmation).
3. Tests : `backend/production/tests/test_daily_closure_report.py` (5 tests) — scénario avec 2
   catégories de pain (300 FC / 500 FC), les 2 équipes (A/B), 1 régularisation, 1 transfert
   inter-boulangeries confirmé ; tous les totaux dérivés sont recalculés à la main en `Decimal` dans
   le test (jamais une constante recopiée depuis la vue). 3 tests de permission complémentaires.
4. `python manage.py test production sales` → 130 tests, OK.
5. `python manage.py test` (suite complète) → en cours au moment de la rédaction, voir note ci-dessous.
6. `python manage.py makemigrations --check --dry-run` → `No changes detected` (vue d'agrégation pure,
   aucun nouveau modèle, aucun champ persistant ajouté — hormis le correctif `update_fields` qui ne
   change pas le schéma).
7. `PRAGMA integrity_check` sur `backend/db.sqlite3` (lecture seule, aucune donnée modifiée) → `ok`.

## Contrat d'API (pour dev-frontend — mission séparée)

### Requête

```
GET /api/production/daily-closure/?node=<code boulangerie ou PK>&date=AAAA-MM-JJ
```

- `date` (requis) : `AAAA-MM-JJ`.
- `node` : requis pour un utilisateur HQ (ADMIN/DIRECTION/COMPTABLE) — accepte le **code**
  boulangerie (ex. `K1`, insensible à la casse) ou la **PK numérique** du nœud. Pour un GERANT
  (non-HQ), ce paramètre est **ignoré** — le rapport porte toujours sur sa propre boulangerie.
- Permissions : `GERANT` et au-dessus (couvre ADMIN/DIRECTION/COMPTABLE/GERANT, ou superuser).
- Codes d'erreur : `400` si `date` manquant/invalide, si `node` manquant pour un HQ, ou si `node`
  introuvable ; `400` si un GERANT n'a aucune boulangerie assignée.

### Réponse (200)

```jsonc
{
  "node": "K1",                    // code boulangerie résolu
  "date": "2026-10-15",
  "categories": [
    {
      "bread_price": 3,             // PK de core.BreadPrice
      "label": "Pain 300 FC",
      "unit_price": 300,
      "produit": { "quantity": 140 },                 // ProductionSessionLine du jour, toutes équipes
      "facture_jr": { "quantity": 30, "fc": "9000.00" },      // vente normale livrée (hors soldée/ajustement/NS/MVM)
      "commission_jr": { "fc": "2250.00" },                   // Σ(line_total × invoice.commission_rate)
      "reste_du_jour": { "A": 20, "B": 10 },           // DailyBreadStockSnapshot.reste_du_jour, null si l'équipe n'a pas clôturé ce jour
      "reste_du_hier":  { "A": -15, "B": 0 },          // DailyBreadStockSnapshot.reste_du_hier
      "appro_effectue": { "quantity": 0 },             // BreadTransferLine envoyées, transfert CONFIRMED ce jour (from_node = ce nœud)
      "appro_recu":     { "quantity": 15 },            // idem, reçues (to_node = ce nœud)
      "non_servi": { "quantity": 0, "fc": "0.00" },    // factures special_code=NS
      "regularisation": { "quantity": 10, "fc": "3000.00" },  // Σ signée (adjustment_sign) des factures is_adjustment=True
      "vente_cash_soldee": {
        "quantity": 10, "fc": "2250.00", "perte_fc": "750.00"  // is_soldee=True ; perte = Σ InvoiceLine.loss
      },
      "facture_mvm_interne": { "quantity": 0, "fc": "0.00" },  // TOUJOURS VIDE EN PRATIQUE — voir limite #1 ci-dessous
      "non_vendu_nv":      { "quantity": 0 },          // BreadDisposal UNSOLD (hors REMAINING)
      "declasses":         { "quantity": 5 },          // BreadDisposal DECLASSED
      "sorties_gratuites": { "quantity": 0 }           // BreadDisposal FREE_DIST
    }
    // ... une entrée par catégorie BreadPrice active, plus toute catégorie
    // inactive ayant eu une activité ce jour (produit/vendu/disposé/transféré)
  ],
  "totals": {
    "total_du_jour_fc": "24250.00",          // facture_jr + vente_cash_soldee + regularisation + facture_mvm_interne (FC, sommé toutes catégories)
    "net_produit_fc": "67000.00",            // Σ ProductionSession.total_fc_produced du jour (toutes équipes)
    "ecart_facture_fc": "42750.00",          // net_produit_fc − total_du_jour_fc
    "nombre_sacs_produits": "3.00",          // Σ ProductionSession.flour_sacks_used du jour
    "moyenne_produit_par_sac_fc": "22333.33",// net_produit_fc / nombre_sacs_produits (null si 0 sac)
    "tarif_vente_moyen_fc": "346.43",        // total_du_jour_fc / total_breads_billed (null si aucun pain facturé)
    "ecart_production_fc": "-533000",        // Σ ProductionSession.yield_gap du jour (global, PAS par catégorie — voir limite #2)
    "total_breads_produced": 190,
    "total_breads_billed": 70,               // pains facturés (facture_jr + soldée + régularisation + mvm)
    "repartition_pct": [
      { "bread_price": 3, "label": "Pain 300 FC", "pct": "73.68" },
      { "bread_price": 5, "label": "Pain 500 FC", "pct": "26.32" }
    ]                                         // part de chaque catégorie dans total_breads_produced (PAS billed)
  }
}
```

Tous les montants FC sont des chaînes `Decimal` à 2 décimales (sauf `ecart_production_fc`, entier
signé, et `nombre_sacs_produits`, `Decimal` à 2 décimales). Jamais de `float`.

## Limites et ambiguïtés signalées (ne pas trancher côté frontend sans confirmation client)

1. **`facture_mvm_interne` sera toujours vide** en pratique aujourd'hui : interprété comme une facture
   dont `special_code` est un code boulangerie (CLAUDE.md §5.1), mais
   `InvoiceCreateSerializer.special_code` (`backend/sales/serializers.py`) est un `ChoiceField` limité
   à `['', 'NV', 'RG', 'NS']` — aucune facture ne peut recevoir cette valeur via le flux de création
   standard. Nécessite une décision produit + une évolution de `sales/` avant que ce bucket contienne
   jamais une donnée réelle.
2. **`ecart_production_fc` est un total global, pas par catégorie** — la mission le rattache à
   `BreadDisposal` (EXCEDENT/MANQUANT), mais ces types n'existent pas dans `DisposalType` et aucune
   répartition par catégorie de la valeur théorique (sacs × valeur sac) n'existe dans le modèle
   actuel. Si le client confirme vouloir une décomposition par catégorie, il faudra d'abord décider la
   règle de répartition (saisie manuelle supplémentaire ? pro-rata de la production réelle ?).
3. **`ecart_facture_fc`, `tarif_vente_moyen_fc`, `repartition_pct`** : formules interprétées
   (documentées ci-dessus et dans le ticket BUG-120) en l'absence de définition littérale dans
   CLAUDE.md/cahierDesCharges.md au niveau de ce détail de calcul — à faire valider par
   testeur-production/le coordinateur contre un vrai extrait Excel avant tout usage comptable réel
   (recoupement chiffré, pas seulement une relecture du code).
4. Le rapport liste **toutes les catégories `BreadPrice.is_active=True`**, même sans aucune activité
   ce jour (valeurs à zéro/null), pour un affichage frontend stable jour après jour — plus toute
   catégorie inactive ayant eu une activité résiduelle ce jour précis.

## Fichiers modifiés/créés

- `backend/production/views.py` — `_resolve_node()`, `_m()`, `_build_daily_closure_report()`,
  `DailyClosureReportView` (nouveaux) ; `BreadTransferViewSet.confirm_reception()` (persistance de
  `updated_at`).
- `backend/production/urls.py` — route `daily-closure/`.
- `backend/production/tests/test_daily_closure_report.py` (nouveau).
- `docs/qa/REGISTRE_BUGS.md` — entrée BUG-120 (tableau + section détaillée).
- `docs/qa/rapports/dev-backend-2026-11-02-chantier-c-cloture-consolidee.md` (ce rapport).

Aucun fichier de `backend/treasury/`, `backend/sales/` (hors lecture), `data_kiese/`, `db.sqlite3` ou
frontend n'a été modifié.

## Risques / suites à donner

- Les 4 limites ci-dessus doivent être rapprochées d'un vrai extrait Excel du client par
  `auditeur-comptable`/testeur-production avant tout usage en production (CLAUDE.md §7, définition de
  « terminé » pour un module financier).
- Aucun ticket `dev-frontend` ouvert à ce stade (mission explicitement backend seul) — le frontend
  devra être développé contre le contrat figé ci-dessus ; si ce contrat évolue après rapprochement
  comptable, un ticket `dev-frontend` devra être ouvert à ce moment-là.
- Le point 1 (`facture_mvm_interne`) mériterait un ticket dédié si le client confirme que ce flux est
  réellement utilisé — actuellement aucun moyen de le produire via l'API.

## État des tests (final)

- `python manage.py test production sales` → **130 tests, OK**.
- `python manage.py test` (suite complète) → **446 tests, OK** (0 échec). Quelques lignes
  `NodeAuthToken.authenticate() : échec de la mise à jour de last_used_at après 150 tentatives —
  database table is locked` apparaissent dans la sortie : c'est un avertissement de contention SQLite
  déjà connu/pré-existant (retries épuisés sur un `UPDATE` non critique), sans rapport avec ce ticket
  et sans effet sur le résultat final (`OK`, code de sortie 0).
- `python manage.py makemigrations --check --dry-run` → `No changes detected`.
- `PRAGMA integrity_check` (`backend/db.sqlite3`, lecture seule) → `ok`.
