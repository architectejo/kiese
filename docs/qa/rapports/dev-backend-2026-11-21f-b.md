# Rapport dev-backend (B) - 2026-11-21f

## Traité
- BUG-410 : CORRIGÉ. Cause : copie de sécurité nommée à la seconde, écrasée par `os.replace`. Correctif : `backup_database(unique=True)` dans `backend/desktop_server.py` (suffixe -2, -3…), utilisé par `restore_database`. Nom toujours conforme à `BACKUP_NAME_RE` / `backupNames.ts` (inchangé).
- Tests : `backend/core/tests/test_bug410_safety_copy_collision.py` (3 tests). Suite ciblée : 59 tests, seul résultat « unexpected success » = `test_restauration_deux_fois_de_suite`.

## Action testeur
Retirer `@expectedFailure` de `test_restauration_deux_fois_de_suite` et vérifier.

## Risques / limites
- Je n'ai pas pu exécuter mes tests sur le code non corrigé (git stash refusé) ; l'ancien nom identique les fait échouer par construction.
- Sauvegardes ordinaires (à la minute) inchangées.
