# Testeur trésorerie, cycle 9 (2026-11-23)

Fichier de tests : `backend/treasury/tests/test_verif_tresorerie_c9_v8.py` (30 tests, OK, 10 échecs attendus).
Commande : `manage.py test treasury.tests.test_verif_tresorerie_c9_v8 --noinput` (SQLite, log `$TEMP/c9.log`).

## Vérification
- BUG-900 VÉRIFIÉ : sous-centime refusé au push LocalExpense ; 2 décimales, zéros finaux, notation 1E2 acceptés.

## Nouveaux tickets (5)
| Ticket | Sévérité | Objet |
|---|---|---|
| BUG-910 | Mineur | Push FacturierReport : totaux négatifs et chiffres non ASCII acceptés |
| BUG-911 | Majeur | Push FacturierReport : équipe hors A/B acceptée ; doublon de vacation (id différent) créé |
| BUG-912 | Majeur | Push : dates futures acceptées (rapport, clôture, bordereau) |
| BUG-913 | Mineur | Push CashClosure : total_entries/total_expenses négatifs ou non ASCII |
| BUG-914 | Majeur | Push DisbursementVoucher : bon à 0 FC accepté ; bon orphelin si solde insuffisant |

Numérotation 910+ (901-909 pris en parallèle par d'autres testeurs).

## Sondes vertes
Rejeu idempotent, états validés non modifiables, périmètre du nœud, double clôture, bordereau réservé au siège, billets invalides refusés, totaux de clôture forgés non crédités au livre, chaîne valide après push + REST, modèles non supportés rejetés sans 500.
