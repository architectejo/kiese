# Rapport testeur-clients-commissions — Vérification BUG-083 — 2026-10-29

## Mandat

Vérification indépendante du **volet Clients/Commissions** de BUG-083 (« ventes passées »,
remarque.md l.360), implémenté par dev-backend/dev-frontend le 2026-10-29. Les volets
Trésorerie et Ventes/Facturation sont hors périmètre (vérifiés en parallèle par d'autres
testeurs).

## Ce qui a été vérifié

1. **Lecture** de `sales/views.py::_warn_if_commission_period_locked` et de
   `commissions/models.py` (`CommissionPeriod.is_closed`/`close()`,
   `ClientCommission.is_paid`/`mark_paid()`/`compute()`). Confirmé : la notification se déclenche
   uniquement sur `period.is_closed` ; sa sévérité (`WARNING`/`DANGER`) dépend de l'existence d'une
   `ClientCommission.is_paid=True` pour ce client sur cette période. Aucune écriture n'est jamais
   faite sur `ClientCommission`/`CommissionPeriod` par cette fonction.
2. **Tests écrits indépendamment** (nouveau fichier, non copié depuis la suite de dev-backend) :
   `backend/commissions/tests/test_bug083_verification_2026_10_29.py` — 5 tests, tous verts :
   - `test_a_open_period_triggers_no_warning_notification` : période encore ouverte →
     **aucune** notification de ce type (scénario manquant de la suite dev-backend, qui ne
     testait que les périodes déjà closes).
   - `test_b_closed_but_unpaid_period_warns_and_leaves_commission_untouched` : période close,
     commission non payée → `WARNING`, contenu exploitable vérifié (client, facture, période),
     `net_payable`/`commission_gross` strictement inchangés (`refresh_from_db()`).
   - `test_c_closed_and_paid_commission_raises_danger_and_stays_unchanged` : période close +
     commission déjà payée → `DANGER`, `net_payable`/`paid_at` inchangés.
   - `test_warning_never_creates_a_clientcommission_row_itself` : aucune `ClientCommission`
     n'est créée implicitement par l'avertissement.
3. **Contenu de la notification** : client (nom complet), facture (`receipt_number`), période
   (`MM/AAAA` + code boulangerie) bien présents dans le titre/message. Observation non bloquante :
   aucun montant d'écart chiffré — non exigé littéralement par la décision client, et le calculer
   impliquerait de régénérer la période (contraire au principe « jamais de recalcul silencieux »).
   Pas de ticket ouvert pour ce point, simple note au coordinateur.
4. **Non-régression** : `python manage.py test clients commissions` → **60/60, 100% vert**.
   Aucun `@expectedFailure` actif restant dans ces deux apps. BUG-017 à BUG-021 et BUG-058
   (formule Net à Payer sans déduction REMISE) toujours conformes.
5. **Frontend `Clients.tsx`** : vérifié statiquement uniquement (aucune exécution UI — risque de
   collision avec une autre session agent sur `db.sqlite3`, comme déjà signalé par dev-frontend).
   Code relu : champ `<input type="date">` de la modale « Enregistrer commande » bien conditionné
   à `allowBackdatedSales` (chargé via `GET /api/core/config/`), `max` = aujourd'hui. Conforme.

## Conclusion

Volet Clients/Commissions de BUG-083 : **CONFORME**. Note ajoutée dans
`docs/qa/REGISTRE_BUGS.md` (fiche BUG-083, section « Vérification » → sous-section
« Volet Clients/Commissions »). Le ticket entier reste à son statut actuel (`CORRIGÉ`) — il ne
passe à `VÉRIFIÉ` que lorsque les volets Trésorerie et Ventes/Facturation auront aussi été
confirmés conformes par leurs testeurs respectifs (ou par le coordinateur recoupant les trois
notes).

Aucun ticket `BUG-NNN` ouvert — aucune anomalie de code applicatif détectée dans ce périmètre.

## Fichiers

- Ajouté : `D:\Projects\kiesse\backend\commissions\tests\test_bug083_verification_2026_10_29.py`
- Modifié : `D:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` (fiche BUG-083, section Vérification)
- Lu (aucune modification) : `D:\Projects\kiesse\backend\sales\views.py`,
  `D:\Projects\kiesse\backend\commissions\models.py`,
  `D:\Projects\kiesse\frontend\src\pages\dashboard\Clients.tsx`,
  `D:\Projects\kiesse\backend\sales\tests\test_bug083_backdated_sales.py`,
  `D:\Projects\kiesse\docs\qa\rapports\dev-backend-bug083-2026-10-29.md`
