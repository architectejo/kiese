# Rapport dev-backend (dev A) — 2026-11-21

## Traité
- BUG-402 (constat 1) : CORRIGÉ. `production/models.py::ConsumableMovement.save()` : `base_qty = max(old_qty, 0)` dans le CUMP (numérateur et dénominateur). Test `production/tests/test_bug402_cump_stock_negatif.py` : avant 3 échecs sur 4 (200000 au lieu de 100000), après 4/4.
- Tests liés relancés (test_bug123, test_consumables, test_bug143, test_verif_bug143, test_bug126) : 22 tests OK. `manage.py check` OK ; `makemigrations --check --dry-run` : aucun changement.

## En attente / risques
- Constat 2 (test BUG-143 « stale_unit_price ») : laissé au testeur-production ; il passait au moment du lancement.
- Les CUMP déjà gonflés en base ne sont pas recalculés (pas de migration de données).
- Run complet de `production` non lancé.
- Rien commité.
