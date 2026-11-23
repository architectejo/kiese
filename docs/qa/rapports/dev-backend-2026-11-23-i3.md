# dev-backend (Dev B) — lot I-3 : statistiques mensuelles de la farine (2026-11-23)

Ticket : BUG-1110 (CORRIGÉ backend, frontend à faire).

## Fichiers
- `backend/production/flour_month_stats.py` (nouveau) : vue `FlourMonthStatsView`.
- `backend/production/urls.py` : import + 1 ligne `consumables/flour-month-stats/`.
- `backend/production/tests/test_dev_i3_flour_month_stats.py` (nouveau, 12 tests, données fictives).
- Ni `views.py`, ni `flour_history`, ni sync/commissions/clients, ni frontend, ni migration.

## Structure du fichier du client (feuille ENTREE FARINE)
Colonnes : DATE, K1..K6, B1 (consommation du jour), vente, TOTAL (somme), ENTREE, PU, PT (= entrée x PU), SOLDE (N = N-1 + entrée − total ; le premier jour est codé en dur). Bas de feuille : total, « Tot passé » saisi à la main, ÉCART MOIS (= total − Tot passé), Moyenne/Jr (= total / 31), accroissement.

## Règles retenues
- Consommation : `ProductionSession.flour_sacks_used` par boulangerie et `date`, fournées ouvertes et clôturées (`open_sessions` indique les ouvertes du jour). Boulangeries actives hors SIEGE.
- Achats : mouvements `ENTRY` de farine du nœud SIEGE ; jour local (Africa/Kinshasa) ; PT = quantité x PU ; PU du jour = PT / quantité.
- Solde : initial + entrées cumulées − consommation cumulée (règle du fichier). Initial reconstitué = stock direction actuel − (entrées − sorties SIEGE depuis le 1er du mois).
- Moyenne/jour = total / jours avec consommation > 0 ; la règle du fichier (÷ jours du mois) est fournie en plus.
- Écart du mois : omis (pas de référence dans l'application).
- Mois : `AAAA-MM` chiffres ASCII, 2000-2200, au plus 12 mois dans le futur ; sinon 400 `{"detail": ...}`.
- `?node=` (siège seulement) : id ou code ; SIEGE, inactive ou inconnue : 400. Gérant : node ignoré, pas de bloc direction.

## Contrat
`GET /api/production/consumables/flour-month-stats/?month=2026-11` (ADMIN/DIRECTION/COMPTABLE ; GERANT limité ; FACTURIER/LIVREUR 403 ; anonyme 401)

```json
{
  "month": "2026-11", "days_in_month": 30,
  "bakeries": [{"code": "Q1", "name": "Fictive 1"}, {"code": "Q2", "name": "Fictive 2"}],
  "rows": [
    {"date": "2026-11-01", "consumption": {"Q1": "2.00", "Q2": "1.00"}, "total": "3.00", "open_sessions": 0,
     "entry_quantity": "0.00", "unit_price": null, "total_price": "0.00", "balance": "97.00"},
    {"date": "2026-11-02", "consumption": {"Q1": "2.00", "Q2": "0.00"}, "total": "2.00", "open_sessions": 1,
     "entry_quantity": "50.00", "unit_price": "1040.00", "total_price": "52000.00", "balance": "145.00"}
  ],
  "summary": {
    "total": {"Q1": "4.00", "Q2": "5.00", "total": "9.00"},
    "average_per_day": {"Q1": "2.00", "Q2": "2.50", "total": "3.00"},
    "average_per_calendar_day": {"Q1": "0.13", "Q2": "0.17", "total": "0.30"},
    "active_days": {"Q1": 2, "Q2": 2, "total": 3}
  },
  "purchases": {"quantity": "50.00", "total_price": "52000.00", "average_unit_price": "1040.00"},
  "opening_balance": "100.00", "closing_balance": "141.00",
  "direction_visible": true,
  "notes": ["Écart du mois non calculé : ...", "Colonne « vente » du fichier non reprise : ..."]
}
```
(`rows` tronqué ; 30 lignes réelles.) Pour un gérant : `direction_visible=false`, pas de `entry_quantity/unit_price/total_price/balance` par ligne, pas de `purchases/opening_balance/closing_balance`. Aucun float.

## Résultats RÉELS (log `$TEMP/i3.log`)
- `production.tests.test_dev_i3_flour_month_stats` + `test_verif_production_a19_v19` + `test_verif_production_a20_v20` : **Ran 52 tests, OK** (45 s).
- `makemigrations --check --dry-run` : No changes detected.
- Performance : 30 jours x 8 boulangeries = 7 requêtes SQL (6 de la vue + 1 lecture Config du middleware), 3 pour un gérant.
- Incident : un premier lancement a échoué sur `NameError: timedelta` dans `sync/views.py` (fichier d'un autre agent, en cours d'édition) ; relancé après, sans lien avec ce lot. Au passage, tests : les boulangeries semées par les migrations (B1, B2) sont désactivées dans le setUp du test.
- Suite complète `manage.py test` non lancée (périmètre demandé : mes tests + a19/a20).

## À confirmer par le client
Règle de la moyenne (÷ 31 du fichier ou jours actifs), colonne « vente », solde initial (stock direction reconstitué ; le solde ne retranche pas les envois direction vers boulangeries), écart du mois (valeur de référence), ligne « accroissement ».

## Risques
Le solde dépend de la justesse de `ConsumableStock` SIEGE ; un mouvement supprimé ou modifié après coup décale l'ouverture reconstituée. Frontend (`FlourMonthStats.tsx`, `services.ts`) à faire.
