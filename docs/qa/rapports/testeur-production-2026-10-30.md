# Rapport — testeur-production (2026-10-30)

## Mission
Vérification indépendante de BUG-092 (« pain soldé » dupliqué Production/Ventes, perte jamais
calculée) et BUG-096 (ambiguïté terminologique + remise 75 % manquante), après implémentation par
dev-backend et confirmation préliminaire par le coordinateur (session dev-backend interrompue avant
rapport). Voir `docs/qa/REGISTRE_BUGS.md`, section « BUG-092 / BUG-096 — Note du coordinateur » et son
addendum ajouté par cette vérification.

## Verdict
**Ni BUG-092 ni BUG-096 ne sont passés à VÉRIFIÉ.** Les deux restent à **CORRIGÉ**. Un défaut réel a
été trouvé et documenté sous un nouveau ticket **BUG-106** (OUVERT, backend, Majeur), qui bloque la
vérification complète de BUG-092.

## Ce qui a été contrôlé et confirmé conforme (backend)

1. **Calcul du prix soldé et de la perte** (`backend/sales/models.py`)
   - `SOLDEE_PRICE_RATIO = Decimal('0.75')`, appliqué uniquement quand `invoice.is_soldee=True`,
     sinon prix catalogue inchangé. Vérifié en Decimal pur avec `ROUND_HALF_UP` sur plusieurs valeurs
     (400→300, 401→301, 402→302, 403→302, 499→374, 501→376) : arrondi half-up classique, cohérent et
     sans biais systématique.
   - `InvoiceLine.loss` = (prix catalogue − prix facturé) × quantité ; `Invoice.total_loss` = somme
     des pertes de lignes, nulle sur facture non soldée. Exemple vérifié : 2 pains à 500 FC soldés à
     375 FC → perte 250 FC, exposée à la fois sur `invoice.total_loss` (Python) et
     `resp.data['total_loss']`/`resp.data['lines'][0]['loss']` (API).
   - Tests dédiés dans `backend/sales/tests/test_invoices.py::SoldeeTests` couvrent ces cas et une
     non-régression explicite (vente normale, perte nulle, prix plein).

2. **Interaction avec la BP et les commissions** — aucune régression
   - `Invoice.compute_debt_after()` : `debt_after = debt_before` quand `is_soldee=True` (le manquant
     n'est jamais ajouté à la BP, remarque.md l.186) — logique préexistante, non affectée par le
     correctif de prix.
   - `sales/views.py` force `commission_rate=0.00` côté serveur dès `is_soldee=True` (ou client=None),
     indépendamment du payload envoyé par le facturier (BUG-028).
   - `commissions/views.py::CommissionPeriodViewSet.generate()` exclut explicitement les factures
     `is_soldee=True` de l'agrégat `order_value` par client (BUG-020) — une vente soldée n'entre jamais
     dans la base CM, quel que soit son prix réel. Confirmé par
     `commissions/tests/test_generate.py::SoldeeSaleCommissionTests`.

3. **Déstockage normal pour une vente soldée**
   - `InvoiceViewSet.deliver()` appelle `_adjust_bread_stock(node, line.bread_price, sent=line.quantity)`
     sans aucune condition sur `is_soldee` (`sales/views.py` l.450) — une vente soldée déstocke
     exactement comme n'importe quelle vente livrée. Pas de chemin spécial, pas de double comptage.

4. **Restriction `BreadDisposal` SOLD_DISCOUNT — partiellement conforme (voir défaut ci-dessous)**
   - La **création** d'une nouvelle entrée `SOLD_DISCOUNT` via `POST /api/production/disposals/` est
     bien refusée (400), avec message clair orientant vers la facturation.
   - Les **entrées historiques** `SOLD_DISCOUNT` restent lisibles normalement (liste filtrée, détail),
     `total_value` inchangé.
   - Les autres types (`DECLASSED`, `UNSOLD`, `FREE_DIST`, `REMAINING`) restent pleinement
     fonctionnels, stock décrémenté/non décrémenté comme avant (`REMAINING` ne sort pas du stock).

5. **Exécution indépendante des contrôles demandés**
   - `python manage.py test sales production commissions` → **116 tests, OK** (0 échec), confirmant
     le chiffre rapporté par le coordinateur.
   - `python manage.py makemigrations --check --dry-run` → uniquement la dérive déjà connue et
     documentée **BUG-057** (`production`/`clients`/`treasury`, `AlterField id`/`transfer_status`,
     `unique_together`) — rien de nouveau introduit par ce correctif.
   - `PRAGMA integrity_check` sur `backend/db.sqlite3` → `ok`.

## Défaut trouvé — BUG-106 (nouveau ticket, OUVERT, Majeur, backend)

`BreadDisposalViewSet.perform_create` (`backend/production/views.py` ~l.762-778) bloque bien la
**création** d'un `SOLD_DISCOUNT`, mais ce `ModelViewSet` n'a **aucun `perform_update`** qui reprenne
la même règle. Reproduit par requête API directe :

1. `POST /api/production/disposals/` avec `disposal_type=DECLASSED` → `201` (légitime).
2. `PATCH /api/production/disposals/<id>/` avec `disposal_type=SOLD_DISCOUNT, unit_price_sold=300` →
   **`200`**, `total_value` recalculé à 3000 FC pour 10 pains, `disposal_type` en base devient
   `SOLD_DISCOUNT`.

Cette entrée reconstitue exactement la double saisie Production/Ventes que BUG-092 était censé
supprimer, par un chemin détourné (modification au lieu de création). Figé dans un test de
non-régression :
`backend/production/tests/test_disposal_reconciliation.py::test_sold_discount_cannot_be_reintroduced_via_patch`
(`@expectedFailure`, référence BUG-106).

Tant que ce point n'est pas corrigé (ex. : reprendre la même vérification dans `perform_update`, ou
interdire tout changement de `disposal_type` après création), **BUG-092 ne peut pas être vérifié**.

## Volet frontend — non traité, confirmé (déjà noté par le coordinateur comme « reste à faire »)

`frontend/src/pages/dashboard/Production.tsx` propose toujours `SOLD_DISCOUNT` (« Pains Soldés »)
comme option par défaut du formulaire de disposition (`dType`, l.101) avec son propre bloc de champs
conditionnels (l.1162). Un GERANT qui l'utilise aujourd'hui obtiendra un 400 du backend sans
explication ni redirection vers la case « Vente Soldée » de Facturation. Je n'ai pas ouvert de
nouveau ticket pour ce point précis (déjà couvert par la phrase du coordinateur « puis le volet
frontend » dans la note de clôture BUG-092/BUG-096) ; je le documente ici pour qu'il soit traité en
même temps que ce volet.

## Décision sur les statuts (registre mis à jour)

- **BUG-106** : créé, `OUVERT`, Majeur, backend, assigné à personne pour l'instant (à envoyer à
  dev-backend).
- **BUG-092** : reste `CORRIGÉ` (pas de passage à `VÉRIFIÉ`) — bloqué par BUG-106.
- **BUG-096** : reste `CORRIGÉ` (pas de passage à `VÉRIFIÉ`) — le correctif de prix/CM lui-même est
  conforme côté backend, mais le périmètre déclaré du ticket inclut `frontend/doc`, non traités.

Détails complets (addendum signé) ajoutés directement sous la note du coordinateur, section
« BUG-092 / BUG-096 — Note du coordinateur », dans `docs/qa/REGISTRE_BUGS.md`.

## Fichiers modifiés par cette vérification
- `backend/production/tests/test_disposal_reconciliation.py` : ajout du test
  `test_sold_discount_cannot_be_reintroduced_via_patch` (`@expectedFailure`, BUG-106).
- `docs/qa/REGISTRE_BUGS.md` : nouvelle ligne BUG-106 dans le tableau de suivi, addendum de
  vérification sous la note du coordinateur BUG-092/BUG-096.
- `docs/qa/rapports/testeur-production-2026-10-30.md` (ce rapport).

Aucun code applicatif n'a été modifié (conformément à la règle « les testeurs ne corrigent pas le
code applicatif »).
