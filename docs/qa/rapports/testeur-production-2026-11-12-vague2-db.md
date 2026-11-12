# Testeur Production — vague 2 sur la base réelle (K2) — 2026-11-12

Périmètre : `backend/db.sqlite3` via l'API `localhost:8000` et l'interface `localhost:5173`, boulangerie K2 (transferts K2 <-> K4 et K2 <-> K1). Aucun code applicatif modifié. Aucun client réel touché, aucun `reset-data`, `migrate`, SQL ni git.

## 1. Exécuté

### A. Re-vérification des tickets corrigés (reproductions exactes, stocks recalculés à la main)
| Ticket | Résultat |
|---|---|
| BUG-217 | VÉRIFIÉ : message de stock négatif lisible (5000.000 disponibles, stock -1000.000) |
| BUG-218 | VÉRIFIÉ : 1,13 sac x 210 000 = 237 300 ; excédent +12 700 |
| BUG-219 | VÉRIFIÉ : 5 corps invalides -> 400, aucune écriture ; pas de double production |
| BUG-220 | VÉRIFIÉ : PATCH sacs régularise la farine (19,370 -> 18,500 -> 19,370) |
| BUG-221 | VÉRIFIÉ : PATCH/DELETE de disposition régularisent `qty_disposed` (7 contrôles chiffrés) |
| BUG-222 | VÉRIFIÉ : PATCH = delta, DELETE inverse (levure, sel, huile) ; quantités 0/-5 acceptées (décision BUG-216) |
| BUG-223 | VÉRIFIÉ : résolution émetteur/siège, récepteur 403, tiers 404, somme du groupe = 800 avant/après, blocage de clôture K2 levé (clôture test créée puis supprimée) |
| BUG-224 | VÉRIFIÉ : 5 entrées invalides -> 400, aucun transfert fantôme |
| BUG-225 | VÉRIFIÉ : `2026-13-45` et `abc` -> 400 sur les 4 routes |
| BUG-226 | VÉRIFIÉ : fournée B du 11/11 clôturée automatiquement en mode classique (REMAINING 708/270) |
| BUG-227 | VÉRIFIÉ (après 12:00 sur l'horloge réelle ; avant 12:00 par lecture du code et test dev) |
| BUG-232 | RESTE CORRIGÉ : récepteur et émetteur OK en UI (360 et 1440 px) ; le siège ne voit pas la carte -> BUG-243 |

Tests dev rejoués (base de test, ciblés) : `production.tests.test_vague1_corrections_production` + `test_vague1_db_production_2026_11_12` = 54 tests OK.

### B. Non-régression
Consommables (stock restant = initial + entrées - utilisé, sel g, levure 0,25, huile 0,33), fournée (valeur théorique, manquant/excédent, valeur du sac figée), stock de départ (confirmation, correction -5 tracée, lignes CARRYOVER), reste/clôture manuelle et automatique, rotation 24 h (désignation par un facturier, équipe C et date passée refusées, fournée de l'équipe non désignée refusée, restes -> départ confirmé), Stock Pains du Jour (`by-date` live/snapshot), transferts, dispositions (déclassés, gratuits, invendus ; le soldé est refusé en Production par conception), Clôture Journalière (colonnes Non Servi/Régularisation, appro effectué/reçu, restes). Alerte de surconsommation (levure 2/sac vs moyenne 0,16) : conforme. Non rejouable : `PREVIOUS_WORKDAY_OPEN` (la journée du 12/11 avait déjà une désignation, posée par un autre testeur sur K2 ; la correction d'une désignation existante reste permise par conception).

### C. Nouveau
- Clôture Journalière : export Excel (3 feuilles, valeurs identiques à l'API, nombres natifs) et impression (fenêtre avec indicateurs et colonnes Sorties Grat.) fonctionnent.
- Transferts K2 <-> K4 (multi-lignes, refus, recomptage, excédent 22/20 résolu par le siège) et K2 <-> K1 (aller-retour de 10 pains, solde K1 inchangé).
- UI `Production.tsx` à 360 px et 1440 px : aucun débordement horizontal (Fournées, Intrants, Transferts, Réconciliation, Clôture Journalière).
- Chargement progressif / totaux : anomalies BUG-244 et BUG-245.

## 2. Données de test créées (K2 / K4 uniquement)
- Comptes : `zz_prod_gerant_k4`, `zz_prod_gerant_k1`, `zz_prod_gerant_k3`, `zz_prod_facturier_k2`, `zz_prod_livreur_k2`, `zz_prod_comptable` (mot de passe commun fictif, voir `scratchpad/tp2/hp.py`).
- K2 : 18 fournées (12/11 A et B, 11/11 B, 10/11 A, 09/11 A, 12 fournées du 20 au 31/10), mouvements de consommables, transferts (K2/K4/K1, tous CONFIRMED ou CANCELLED, litiges résolus), dispositions de test (déclassés 8, gratuits 12, invendus 3).
- État initial rétabli : rotation K2 désactivée, relève 12:00, créneaux 06:00-11:30 / 14:30-20:00, valeur du sac 210 000 FC.

## 3. Tickets
- VÉRIFIÉS : BUG-217 à 227.
- Reste CORRIGÉ : BUG-232 (dépend de BUG-243).
- Ouverts (frontend, tests `e2e/tests/13-production-vague2-db.spec.ts` avec `test.fail`) :
  - BUG-243 Majeur : filtres de transferts du siège cassés (identifiant numérique contre chaîne du `<select>`).
  - BUG-244 Majeur : KPI « Fournées enregistrées » / « Valeur FC produite » partiels (15 sur 17).
  - BUG-245 Majeur : KPI « Pains non valorisés » compte le stock restant (47 306 au lieu de 23).
  - BUG-246 Mineur : champ sacs de farine en `step=0.5` (1,13 refusé).
- BUG-228 (prénom en double encodage « GÃ©rant Coq ») toujours OUVERT (donnée, visible dans la barre latérale).

## 4. Fichiers
- `e2e/tests/13-production-vague2-db.spec.ts`, captures `docs/qa/captures/prod-v2-*`, `prod-v2-cloture.xlsx`.
- Les tickets frontend n'ont pas de test dans `backend/production/tests/` (défauts d'interface).
