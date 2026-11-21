# Testeur-installation (B) - 2026-11-21e - Verification BUG-410

Resultat : **BUG-410 VERIFIE**. Suite ciblee (5 modules) : 66 tests, OK.

- `@expectedFailure` retire de `test_restauration_deux_fois_de_suite` (passe).
- Preuve que le test a un sens : `test_ancien_comportement_simule_ecrase_la_copie` force `unique=False` par mock, meme seconde -> noms identiques, copie d'origine (20 lignes) ecrasee.
- Nouveau fichier `backend/core/tests/test_verif_bug410_testeur_installation.py` : 6 restaurations meme seconde (noms -2 a -6, 1re copie = donnees d'origine), conformite `BACKUP_NAME_RE` et `validate_backup_file_name`, listing (glob `kiese-*.sqlite3.gz`, il n'existe pas d'autre fonction de listing cote Python/TS), copie -2 restaurable, rotation 30 j ne supprime que l'ancienne, pas de collision avec la sauvegarde quotidienne ni entre labels, regex de `desktop/src/backupNames.ts` executee sous Node (accepte `-2`/`-12`, rejette `..`, `.part`).
- Limite : pas de suppression des copies de securite au-dela de 30 jours distincte (comportement existant, hors BUG-410).
