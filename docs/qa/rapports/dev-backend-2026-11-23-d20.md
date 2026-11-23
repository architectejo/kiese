# dev-backend (Dev B) - 2026-11-23 d20

Tickets CORRIGÉ : BUG-686, BUG-687, BUG-688 (tests a7 sans @expectedFailure, assertions inchangées).

- 686 : `_refuse_non_ascii_fields` (production/serializers.py) sur mouvement (quantity, unit_price), comptage (physical_quantity), disposition (unit_price_sold) ; `parse_qty` (consumables_direction.py) pour inventaire et dispatch.
- 687 : `validate_count_date` (work_date_for du nœud) ; opening-confirmation (views.py) refuse une date > jour de travail.
- 688 : `validate_physical_quantity` refuse les valeurs négatives.

Tests : a7_v7 + a6_v6 + d13 : 72 tests OK (1 expectedFailure restant dans a6_v6, hors périmètre) ; makemigrations --check : aucun changement. Pas de changement de contrat hors nouveaux 400.
Risque : count_date future refusée si le nœud est introuvable (comptage sans nœud) : contrôle sauté, perform_create exige déjà un nœud.
