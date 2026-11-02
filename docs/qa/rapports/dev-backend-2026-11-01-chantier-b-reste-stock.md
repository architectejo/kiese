# Rapport dev-backend — Chantier B : historique quotidien du stock de pains (RESTE DU JOUR/HIER)

Date : 2026-11-01
Agent : dev-backend
Périmètre : `backend/production/` uniquement (aucune collision avec le Chantier A en parallèle sur
`backend/treasury/`/`backend/blockchain/`).

## Ticket traité

**BUG-118** — Aucun historique quotidien du stock de pains : impossible de calculer RESTE DU JOUR /
RESTE DU HIER. Statut final : **CORRIGÉ** (en attente de vérification par un testeur, conformément à
CLAUDE.md §7 — un développeur ne valide pas sa propre correction).

Détail complet (reproduction, analyse, correctif, tests) dans
`docs/qa/REGISTRE_BUGS.md` sous l'identifiant `BUG-118`.

## Analyse préalable (étapes 1 et 2 de la mission)

1. Relecture de `backend/production/models.py` (`ProductionSession`, `BreadStock`, `BreadDisposal`)
   et `backend/production/views.py` (`ProductionSessionViewSet.close()`, actions de recoupement
   BUG-093/108) : confirmé que `BreadStock.qty_available` est un solde courant cumulatif
   (`qty_produced + qty_received - qty_sent - qty_disposed`) par nœud+catégorie, sans aucune notion
   de date — aucun historique n'est conservé entre deux clôtures.

2. Lecture directe (via `openpyxl`, `backend/.venv/Scripts/python.exe`) de :
   - `data_kiese/EXTRAIT RAPPORT DE CLOTUREOCTOBRE 2026.xlsx` (feuille K6, un seul jour,
     2026-10-06) : confirme que `RESTE DU HIER/S` n'est pas une copie du `RESTE DU JOUR` de la veille
     ni du jour même (valeurs totalement différentes, signe opposé) — mais un seul jour dans cet
     extrait ne permet pas de reconstituer la relation jour N → jour N+1.
   - `data_kiese/DOC 01- RAPPORT  BOULANGERIES AOUT  2026.xlsx` (feuille ZADIM, couvre plusieurs
     jours consécutifs d'août 2026) : rapprochement ligne par ligne qui a permis d'établir la
     formule retenue — voir le détail du rapprochement (références exactes aux lignes/valeurs) dans
     le ticket BUG-118 du registre.

   **Résultat de l'analyse : une ambiguïté résiduelle a été identifiée** (une seconde chaîne de
   blocs dans le même fichier, probablement liée aux équipes A/B, ne suit pas exactement la même
   règle). Conformément à CLAUDE.md §7 règle 6, cette ambiguïté est **documentée et signalée au
   coordinateur dans le ticket BUG-118** plutôt que tranchée silencieusement. La formule retenue pour
   l'implémentation est celle confirmée sur la chaîne la plus complète et sans contradiction interne
   (8 jours consécutifs) : `reste_du_hier(nœud, catégorie, jour N) = -reste_du_jour(nœud, catégorie,
   dernier snapshot antérieur à N)`, 0 en l'absence de snapshot antérieur.

## Conception et implémentation (étapes 3-4 de la mission)

- Nouveau modèle `backend/production/models.py::DailyBreadStockSnapshot` : `node`, `bread_price`,
  `date`, `qty_at_close`, `unique_together=[node, bread_price, date]`. Méthodes de classe
  `reste_du_jour()`, `reste_du_hier()`, `record_snapshot()`.
- Point de capture choisi : **couplé à `ProductionSessionViewSet.close()`** (BUG-093/108), pas un
  nouveau point de clôture journalière dédié — c'est le seul moment métier actuel où un jour/nœud
  est considéré « arrêté ». Si les deux équipes A/B clôturent le même jour, le snapshot du jour est
  **écrasé (upsert)** par la dernière clôture (le stock de pains n'étant pas tenu par équipe). Ce
  choix et sa limite (le « reste du jour » peut encore bouger jusqu'à la toute dernière clôture du
  nœud pour cette date) sont documentés dans le docstring du modèle et dans le ticket.
- Migration standard : `backend/production/migrations/0015_dailybreadstocksnapshot.py` (nouveau
  modèle, aucune donnée existante à migrer, donc pas de migration de données nécessaire).

## Tests (étape 5)

Nouveau fichier `backend/production/tests/test_daily_stock_snapshot.py`
(`DailyBreadStockSnapshotTests`, 6 tests, **sans** `@expectedFailure` puisque le test n'existait pas
auparavant) :
1. La clôture crée/met à jour un snapshot égal au solde courant `BreadStock.qty_available`.
2. Deux clôtures le même jour (équipe A puis B) : le snapshot est écrasé, pas dupliqué.
3. `reste_du_hier(jour N) = -reste_du_jour(jour N-1)` sur deux jours consécutifs clôturés.
4. `reste_du_hier` = 0 à la première journée d'activité (aucun snapshot antérieur).
5. `reste_du_hier` se réfère au dernier snapshot disponible (pas un jour calendaire fixe) quand un
   jour intermédiaire n'a pas été clôturé.
6. `reste_du_jour` renvoie `None` si la date n'a jamais été clôturée.

## Vérifications (étapes 6-7)

- `python manage.py test production` → **44/44 OK** (dont les 6 nouveaux tests).
- `python manage.py test` (suite complète) → **440/440 OK** (machine partagée très lente : 1627 s,
  ~27 min, d'où les délais d'attente constatés pendant cette session — aucun échec).
- `python manage.py makemigrations --check --dry-run` → « No changes detected ».
- `PRAGMA integrity_check` sur `backend/db.sqlite3` → `ok`.

## Impact API

Aucun contrat d'API existant modifié. Aucun nouvel endpoint exposé (le calcul `reste_du_jour`/
`reste_du_hier` est disponible côté backend via les méthodes de classe du modèle uniquement) — la
mission ne demandait pas d'exposition REST, et l'ambiguïté métier résiduelle sur la formule
déconseille d'anticiper un contrat d'API avant validation client. Aucun ticket `dev-frontend` ouvert
pour cette raison.

## Fichiers modifiés/ajoutés

- `backend/production/models.py` (nouveau modèle `DailyBreadStockSnapshot`)
- `backend/production/views.py` (`ProductionSessionViewSet.close()` : appel à
  `DailyBreadStockSnapshot.record_snapshot()`)
- `backend/production/migrations/0015_dailybreadstocksnapshot.py` (nouveau)
- `backend/production/tests/test_daily_stock_snapshot.py` (nouveau)
- `docs/qa/REGISTRE_BUGS.md` (ticket BUG-118)

## Risques / points à trancher par le coordinateur ou le client

1. **Ambiguïté équipe A/B dans `RESTE DU HIER`** (détail complet dans BUG-118) : la formule retenue
   (négatif du dernier snapshot antérieur, sans distinction d'équipe) est la plus simple et la plus
   cohérente avec l'implémentation actuelle (une seule ligne `BreadStock` par nœud+catégorie, sans
   notion d'équipe), mais une seconde chaîne de données dans le fichier source suggère qu'une
   distinction par équipe pourrait exister dans la pratique réelle du client. À valider avant tout
   usage comptable de cette fonctionnalité (impact potentiel sur le calcul de CM, les colonnes
   `TAUX`/`CM` étant renseignées sur ces lignes dans le fichier source — non repris ici, hors
   périmètre de la mission).
2. Aucune exposition API/frontend pour l'instant — à prévoir dans un chantier ultérieur une fois la
   formule validée avec le client.
