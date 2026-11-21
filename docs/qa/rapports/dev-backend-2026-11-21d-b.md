# Rapport dev-backend 2026-11-21d (dev B)
Tickets : BUG-408, BUG-409 -> CORRIGÉ ; BUG-404 reste CORRIGÉ.
- `backend/desktop_server.py` : `fullmatch` pour la liste blanche (BUG-409) ; `_has_tables` + refus d'un contenu de 0 octet ou sans table, base courante intacte (BUG-408).
- `desktop/src/backupNames.ts` : pas de défaut (JS sans flag `m`), inchangé.
- Tests : 35 OK (test_verif_bug403_404_testeur_installation + test_bug403_404_backup_restore), dont `test_gz_vide_zero_octet` et `test_nom_avec_saut_de_ligne_final`.
- Risque / à trancher : le contrôle `django_migrations` n'est pas appliqué (casserait les tests existants à base fictive `t`). Une base SQLite non KIESE avec tables reste acceptée.
