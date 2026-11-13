# Vérification BUG-253 — testeur-permissions, 2026-11-13

Base de test Django éphémère uniquement (db.sqlite3 non touchée).

- Matrice : anonyme + 6 rôles x 15 routes (closures, savings, journal, periods, commissions, détails, monthly_total, suggested_ca, monthly_report, history, payroll_listing). Anonyme 401 ; FACTURIER/LIVREUR 403 ; ADMIN/DIRECTION/COMPTABLE/GERANT 200 (ou 400/404 sans paramètre valide), jamais 500.
- Isolation : gérant K1 ne voit pas la période K2 (liste, `?node=K2`, détail par id -> 404) ; comptable voit les deux ; history filtré par `node` pour le siège.
- Non-régression écrans : Commissions (ADMIN/DIRECTION/COMPTABLE) et Finance (siège, utilise periods/history) OK ; aucun écran facturier/livreur n'appelle ces routes.
- Observation (non bloquante, antérieure) : `periods/history` et `commissions/payroll_listing` renvoient 403 au gérant car `get_permissions` écrase le `permission_classes` de l'@action (IsHeadquarters). Les `IsGerant` ajoutés sur ces actions sont du code mort. Aucun écran gérant concerné.
- Tests : `backend/core/tests/test_bug253_verification.py` (3 OK), `test_vague3_db_permissions` (6 OK).
- Résultat : BUG-253 VÉRIFIÉ.
