# Rapport — testeur-clients-commissions — 2026-10-30

## Mission : vérification indépendante de BUG-097

Le coordinateur m'a demandé de vérifier indépendamment la correction BUG-097 (corrections de
commande via facture d'ajustement liée, « grande trace »), implémentée par dev-backend. Ce rapport
couvre uniquement cette vérification (pas de nouvelle campagne de tests Clients/Commissions au-delà
de la suite existante relancée dans ce cadre).

## Ce qui a été vérifié

1. **Relecture du diff réel** :
   - `backend/sales/models.py` (lignes 75-98) : `Invoice.adjusts` (FK self, `on_delete=PROTECT`,
     `null=True`), `Invoice.is_adjustment` (bool), `Invoice.adjustment_sign` (`SmallIntegerField`,
     choix `[(1, 'Augmentation'), (-1, 'Diminution')]`). `InvoiceLine.quantity` inchangé
     (`PositiveIntegerField`) — confirmé conforme à la décision : les lignes d'un ajustement portent
     la magnitude, le signe est uniquement au niveau de la facture.
   - `backend/sales/views.py` (`InvoiceViewSet.adjust`, lignes 565-751) :
     - Permission : `@action(..., permission_classes=[IsGerant])` — confirmé, aucune nouvelle classe
       de permission créée.
     - Refus propre (400) : facture `CANCELLED`, remboursement BP (`is_debt_repayment`), facture déjà
       elle-même un ajustement (`is_adjustment`) — pas de chaîne d'ajustements possible.
     - Stock : `_adjust_bread_stock(original.node, line.bread_price, sent=adjustment_sign *
       line.quantity)` (ligne 716) — confirmé que le stock est décrémenté/restitué selon le signe, au
       même moment que la création de la facture d'ajustement (pas à une « livraison » séparée — la
       facture d'ajustement est créée directement au statut `DELIVERED`). Cohérent avec le
       comportement déjà existant pour une facture normale : stock décrémenté dès `_create_once`
       (ligne 450), jamais à `deliver()`.
     - BP : `order_total`/`payment_amount` reçoivent `adjustment_sign * magnitude`, puis
       `compute_debt_after()` (formule standard) est appelé — confirmé. Trace additive
       `DebtMovement(kind=ADJUSTMENT)` créée via `_record_debt_movement_after_commit` si
       `net_delta != 0`.
     - Validation de non-dépassement (lignes 640-666) : calcule le solde net déjà facturé par
       catégorie de pain (original + ajustements précédents déjà appliqués) et refuse (400) toute
       diminution qui le dépasserait. Message d'erreur en français, cite la quantité restante exacte.
     - Commission déjà clôturée : `_warn_if_commission_period_locked` (BUG-083) appelé
       systématiquement, jamais de blocage — confirmé par relecture et par test.
   - `backend/sales/serializers.py` (`InvoiceAdjustSerializer`, lignes 125-142) :
     `adjustment_sign` en `ChoiceField([1, -1])`, `payment_amount` en `DecimalField` avec
     `min_value=Decimal('0.00')` (magnitude uniquement, jamais de signe côté serializer), `lines`
     requiert au moins un élément.
   - `InvoiceSerializer` expose bien `adjusts`, `is_adjustment`, `adjustment_sign`,
     `adjustments_count` (lignes 37-60) — trace consommable côté frontend (objet du ticket lié
     BUG-109, hors périmètre).

2. **Tests automatisés relancés moi-même** (pas seulement rapportés par dev-backend) :
   - `python manage.py test sales.tests.test_bug097_invoice_adjustment -v 2` → **11/11 `OK`**
     (diminution, augmentation, période clôturée [avertissement, jamais blocage], permissions
     GERANT/FACTURIER/LIVREUR, refus facture annulée/ajustement-d'ajustement, dépassement de
     quantité).
   - `python manage.py test sales core commissions` → **162 tests, `OK`**, confirme exactement le
     chiffre rapporté par dev-backend (aucune régression).

3. **Reproduction de bout en bout via l'API directement**, dans un fichier de test temporaire
   (`sales/tests/test_bug097_manual_repro_scratch.py`, supprimé après vérification — ne fait pas
   partie de la suite permanente, déjà couverte par ailleurs) :
   - Facture originale 10 pains (500 FC) livrée → stock `qty_sent = 10`.
   - Ajustement `-3` (motif retour) → stock `qty_sent = 7` (restitué), `adjusts` pointe vers
     l'originale, facture d'origine jamais mutée.
   - Ajustement `+2` chaîné sur la **même** facture d'origine → stock `qty_sent = 9` (décrémenté
     comme une vente additionnelle).
   - Tentative de diminution excessive `-15` (solde net restant après -3+2 = 9) → **400** avec
     message exact (« il n'en reste que 9 net sur la facture... »).
   - Tentative d'ajustement par un FACTURIER → **403**.
   - Tentative d'ajustement d'une facture `CANCELLED` (facture PENDING annulée) → **400**.
   - Tentative d'ajustement d'une facture d'ajustement elle-même (chaîne) → **400**.
   - Tous les résultats correspondent exactement aux décisions du coordinateur.

4. **`python manage.py makemigrations --check --dry-run`** : la migration `sales/0007_bug097_...`
   est complète et appliquée (aucune dérive signalée pour `sales`). Seule la dérive déjà connue et
   documentée **BUG-057** (`production`/`clients`/`treasury` : `AlterField id`, `transfer_status`,
   `unique_together`) réapparaît — sans rapport avec BUG-097, conforme à l'attendu de la mission.

5. **`PRAGMA integrity_check` sur `backend/db.sqlite3`** → `ok`.

## Conclusion

Aucun défaut constaté. BUG-097 passé à **`VÉRIFIÉ`** dans `docs/qa/REGISTRE_BUGS.md` (section tableau
ligne 48, et section détail `### BUG-097`, avec le détail complet de la vérification ajouté sous
« Statut »). Le ticket lié **BUG-109** (consommation frontend du nouvel endpoint/des nouveaux champs)
reste `OUVERT`, hors périmètre de cette vérification — signalé au coordinateur comme déjà documenté
dans le registre.

## Fichiers concernés

- `D:\Projects\kiesse\backend\sales\models.py` (lignes 75-98, 126-150)
- `D:\Projects\kiesse\backend\sales\views.py` (lignes 211-350 pour `_create_once`, 440-460 pour le
  déstockage à la création, 565-751 pour `adjust`)
- `D:\Projects\kiesse\backend\sales\serializers.py` (lignes 37-60, 125-142)
- `D:\Projects\kiesse\backend\sales\migrations\0007_bug097_invoice_adjustment_fields.py`
- `D:\Projects\kiesse\backend\sales\tests\test_bug097_invoice_adjustment.py` (11 tests, relancés avec
  succès — aucune modification apportée)
- `D:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` (BUG-097 : `CORRIGÉ` → `VÉRIFIÉ`)
