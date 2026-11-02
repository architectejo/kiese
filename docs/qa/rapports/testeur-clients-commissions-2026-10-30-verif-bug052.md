# Rapport — testeur-clients-commissions — Vérification indépendante BUG-052 (backend)

Date : 2026-10-30

## Objet
Vérification indépendante de la correction backend de BUG-052 (« vente sans commission de 25 %
distincte de Vente Soldée »), livrée par `dev-backend` le 2026-10-30 mais jamais auto-vérifiée
(règle CLAUDE.md §7).

## Méthode et résultats

1. **Relecture de code** (`backend/sales/models.py`, `backend/sales/views.py`,
   `backend/commissions/views.py`) :
   - `Invoice.commission_exempt` (nouveau `BooleanField`, défaut `False`) confirmé **jamais lu**
     par `InvoiceLine.save()` (prix catalogue plein toujours appliqué, contrairement à `is_soldee`
     qui remise à 75 %) ni par `Invoice.compute_debt_after()` (BP non gelée, contrairement à
     `is_soldee`).
   - `_create_once` et `_create_adjustment` (`sales/views.py`) forcent un unique `comm_rate=0` via
     la condition combinée `is_soldee or commission_exempt or client is None` — un seul taux par
     facture, donc **aucune double déduction** possible en combinant les deux booléens. La remise
     de prix et le gel de BP restent strictement portés par `is_soldee` seul.
   - `CommissionPeriodViewSet.generate` (`commissions/views.py`) exclut bien aussi
     `commission_exempt=True` de `order_value`, au même filtre que `is_soldee=False` (BUG-019/020),
     sans impact sur la BP/`current_debt` (gérée exclusivement par `sales/views.py`).
   - Conclusion : conforme à la spécification du ticket, aucune incohérence trouvée.

2. **Tests ciblés relancés** :
   `python manage.py test sales.tests.test_invoices.CommissionExemptTests
   commissions.tests.test_generate.CommissionExemptInvoiceCommissionTests -v 2`
   → **6/6 OK**.

3. **Suite complète du projet** (non confirmée par le dev) :
   `python manage.py test` → **372 tests, OK**, 0 échec/erreur. Durée anormalement longue
   (2912 s / ~48 min), due à une forte contention CPU/IO de l'environnement partagé (plusieurs
   autres agents exécutaient des suites de tests Django en parallèle au même moment, confirmé par
   inspection des processus), pas un défaut du code ni de la correction.

4. **Reproduction de bout en bout via `APIClient`** (équivalent HTTP), revérifiée ligne à ligne
   dans les tests du dev :
   - Facture normale `commission_exempt=true`, 1 ligne à prix catalogue plein (2 × 500 FC) :
     `unit_price` inchangé (pas de remise à 75 %), `commission_rate=0.00`, `order_total=1000.00`,
     BP (`current_debt`) = `0 + 1000 − 200 = 800` (suit `order_total` normalement, pas gelée).
   - Non-régression : facture sans aucun flag → CM par défaut (25 %) ; `is_soldee` seul → toujours
     prix réduit à 75 % + CM=0 + BP gelée, inchangé.
   - Combinaison `is_soldee=True` + `commission_exempt=True` → CM=0 par les deux chemins, prix à
     75 % et BP gelée toujours portés uniquement par `is_soldee` — pas d'incohérence.

5. `python manage.py makemigrations --check --dry-run` → `No changes detected` (aucune dérive
   résiduelle constatée au moment du contrôle ; hors périmètre de ce ticket si BUG-057 réapparaît
   plus tard).

6. `PRAGMA integrity_check` sur `backend/db.sqlite3` → `ok`.

## Décision

BUG-052 passé de **CORRIGÉ (backend)** à **VÉRIFIÉ (backend)** dans
`docs/qa/REGISTRE_BUGS.md`. Le volet frontend (case à cocher dédiée dans `Sales.tsx`/`Clients.tsx`,
distincte de « Vente Soldée ») reste explicitement **à faire**, hors périmètre de cette
vérification — non modifié, non vérifié ici.

## Fichiers concernés
- `D:\Projects\kiesse\backend\sales\models.py`
- `D:\Projects\kiesse\backend\sales\views.py`
- `D:\Projects\kiesse\backend\commissions\views.py`
- `D:\Projects\kiesse\backend\sales\tests\test_invoices.py` (classe `CommissionExemptTests`)
- `D:\Projects\kiesse\backend\commissions\tests\test_generate.py` (classe
  `CommissionExemptInvoiceCommissionTests`)
- `D:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` (BUG-052 mis à jour)
