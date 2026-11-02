# Rapport — Passage de non-régression complet, module Ventes/Facturation
Testeur-ventes, 2026-10-29

## 1. Suite `sales` complète
`python manage.py test sales` → **58/58 tests, 100% vert** (54 préexistants + 4 ajoutés dans
cette session). Aucun échec, aucun `@expectedFailure` actif. Rejoué deux fois de manière
indépendante (`-v 1` et `-v 2`) avec le même résultat.

Aucun résidu BUG-068/084/057 dans ce module — ces trois tickets concernent exclusivement
`treasury`/`production`/`clients`, jamais `sales` (vérifié par lecture des tickets et par
l'absence de toute référence à ces dates codées en dur dans `backend/sales/tests/`).

## 2. Couverture de CLAUDE.md §5.2, vérifiée scénario par scénario
Tous les points de §5.2 ont un test qui les exerce réellement (pas seulement en théorie) :

- Facture standard, lignes multiples, prix verrouillé sur `BreadPrice` (prix client ignoré),
  `order_total` exact → `test_invoices.py::StandardInvoiceTests`.
- `BP_après = BP_avant + commande − paiement`, cumulatif, jamais remis à zéro (mois) →
  `test_invoices.py::BalancePaiementTests`.
- Blocage crédit (BP ≥ plafond + versement < commande → 403 + notification ; les deux cas
  limites acceptés) → `test_invoices.py::CreditBlockTests`.
- **Contrôle complémentaire du déficit net du mois** (commandé − versé − CM ≥ plafond) :
  mentionné dans CLAUDE.md §5.2 et bien implémenté (`sales/views.py`, variable
  `period_deficit`) mais **sans aucun test dédié avant cette session** — seul le plafond de
  dette brute était couvert par `CreditBlockTests`. Écrit et vérifié
  `sales/tests/test_monthly_deficit_control.py` (3 tests, tous verts) : le déficit bloque
  même quand la dette brute reste sous le plafond (client parti d'un solde très créditeur),
  le versement intégral neutralise le blocage, un déficit négatif ne bloque jamais. **Ce
  n'est pas une anomalie** (le code fonctionne conformément à la règle) — simplement un trou
  de couverture de test comblé, pas de ticket ouvert.
- Remboursement sans ligne (réduit la BP, pas de CA, pas de stock) →
  `test_invoices.py::DebtRepaymentTests`.
- VENTE SOLDE/CASH (CM=0, manquant non ajouté à la BP), client épargne (commande 0, BP
  négative) → `test_invoices.py::SoldeeTests`.
- Codes `NV`/`RG`/`NS`/boulangerie, vente occasionnelle sans client →
  `test_invoices.py::SpecialCodesTests`.
- Livraison par facturier OU livreur, double livraison sans double déstockage, stock
  négatif autorisé (remarque.md) → `test_invoices.py::DeliveryAndCancelTests`.
- Annulation (BP et stock restaurés, journalisé) → même classe.
- Numéro de reçu unique en créations concurrentes → `test_invoices.py::ReceiptNumberTests`.
- BP finale correcte en concurrence (pas de mise à jour perdue) →
  `test_invoices.py::ConcurrentInvoiceBPTests`.
- Isolation `node` (un facturier ne force pas le `node` d'une autre boulangerie) →
  `test_invoices.py::NodeIsolationTests`.
- Équipes A/B uniquement → `test_invoices.py::TeamABOnlyTests`.
- Contenu du reçu (RCCM, Id.Nat, N° Impôt, code boulangerie, « Solde arrêté ce jour », etc.) :
  confirmé présent dans `ThermalReceipt.tsx` (correction BUG-059 déjà vérifiée) et tous les
  champs nécessaires exposés par `InvoiceSerializer` — vérifié explicitement par le nouveau
  test de bout en bout (point 3 ci-dessous).

## 3. Intégration BUG-083/086 — parcours normal non affecté
Nouveau fichier `backend/sales/tests/test_e2e_normal_flow_2026_10_29.py` : simule le parcours
complet d'un facturier normal — création de facture (aucun champ de date dans le payload),
livraison confirmée par le **livreur** (aucun `delivered_at` dans le payload), lecture du
détail consommé par le reçu — avec `Config.allow_backdated_sales` dans son état par défaut
(`False`, jamais modifié). Vérifié explicitement : `invoice_date`/`delivered_at` valent
exactement aujourd'hui sans avoir été fournis, déstockage une seule fois (à la création, pas
à la livraison), BP avant/après exacts, tous les champs du reçu présents. **Résultat : vert,
comportement strictement identique à avant les chantiers BUG-083/086.**

Revu également `sales/views.py` (`_validate_requested_date` → désormais un alias de
`core.utils.validate_requested_date`, BUG-086) et confirmé par lecture que l'appel est
strictement le même qu'avant le déplacement de fonction — aucun changement de comportement.

Revu enfin le code frontend (`Sales.tsx`) : les champs de date rétroactive (`invoiceDate`,
`deliverDate`) sont des états initialisés à `''`/vides et conditionnés à
`allowBackdatedSales` (chargé depuis `GET /api/core/config/`), avec `retroactiveDate`/`d`
valant `null`/`undefined` tant que l'utilisateur ne renseigne rien — confirmé statiquement
qu'aucun payload supplémentaire n'est envoyé pour le flux normal.

## 4. Test manuel navigateur
**Non exécuté.** Au moment de cette session, `netstat` montre le backend (port 8000, PID
13816) et le frontend (port 5173, PID 7692) tous deux déjà actifs avec des connexions
établies depuis un processus tiers (PID 12836) — signe d'une autre session agent déjà en
train d'utiliser la même base `db.sqlite3` partagée. Par prudence (consigne CLAUDE.md : ne
pas perturber le travail d'un autre agent), je n'ai pas créé de facture de test contre cette
base réelle. Le code a été revérifié **statiquement** à la place (section 3). Si un test
navigateur réel est requis, il faudra le refaire quand aucune autre session active n'est
détectée sur ces ports, en préfixant toute donnée créée par `DEMO`/`TEST` et en nettoyant
après coup.

## 5. Anomalie découverte
**Aucune nouvelle anomalie trouvée dans le périmètre Ventes/Facturation.** Un seul point
notable hors périmètre, déjà ouvert par `testeur-clients-commissions` :
**BUG-088** (`ClientCreateSerializer` n'expose ni `id` ni `code` à la création d'un client),
qui casse la création auto du « Client Occasionnel » utilisée par la vente directe au
comptoir (`Clients.tsx`). Je ne l'ai pas rouvert ni dupliqué (déjà `OUVERT`, module Clients,
hors périmètre de ce mandat) — signalé ici pour le coordinateur car il touche indirectement
un parcours de vente.

## 6. Migrations
`python manage.py showmigrations` (base réelle) → **aucune migration en attente**.
`python manage.py makemigrations --check --dry-run` → dérive détectée uniquement sur
`production`/`clients`/`treasury` (BUG-057 déjà documenté, inchangé) — **rien sur `sales`**.

## 7. Verdict
**Le module Ventes/Facturation est prêt à présenter au client.**
- Tous les scénarios de CLAUDE.md §5.2 sont couverts par des tests automatisés qui passent
  (58/58), y compris un trou de couverture comblé cette session (déficit net du mois) sans
  qu'aucune anomalie n'y soit trouvée.
- Aucun ticket bloquant ou majeur ouvert sur le module Ventes lui-même (BUG-088 est un
  ticket Clients, pas Ventes).
- Le parcours de facturation normal (sans date rétroactive) est bit-à-bit identique à avant
  les chantiers BUG-083/086, confirmé par un nouveau test de bout en bout.
- Seule réserve : pas de confirmation en conditions réelles de navigateur cette session
  (base partagée avec une autre session agent) — recommandé avant livraison finale, mais non
  bloquant au vu de la couverture backend et de la relecture statique du frontend.

## Fichiers ajoutés
- `backend/sales/tests/test_monthly_deficit_control.py`
- `backend/sales/tests/test_e2e_normal_flow_2026_10_29.py`
- `docs/qa/rapports/testeur-ventes-passage-complet-2026-10-29.md` (ce rapport)

Aucun fichier applicatif modifié.
