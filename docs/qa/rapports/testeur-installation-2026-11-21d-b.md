# Rapport testeur-installation (dev B) - 2026-11-21d - BUG-404/408/409

Commande : suites `test_bug403_404_backup_restore`, `test_verif_bug403_404_testeur_installation`, `test_verif_bug408_409_testeur_installation` -> 56 tests, OK (expected failures=1).
Nouveau fichier : `backend/core/tests/test_verif_bug408_409_testeur_installation.py` (en-tête SQLite tronqué, base tronquée, gz corrompu / CRC altéré / double compression / autre contenu, base sans table, vue seule, noms avec LF/CR/espaces/tab/../chemins absolus/UNC/casse, double restauration, échec du remplacement, échec de la copie de sécurité).

## Verdicts
- BUG-409 : VÉRIFIÉ. `fullmatch` refuse tous les noms hostiles testés (35). Côté TypeScript, `$` sans flag `m` ne matche pas avant un LF final : pas de défaut.
- BUG-408 : VÉRIFIÉ avec limite connue. 0 octet, gzip vide, base sans table, vue seule, en-tête tronqué (1 à 100 octets), base tronquée au milieu, gz corrompu, CRC altéré, contenu texte/zip/nul : tous refusés AVANT la copie de sécurité, base courante identique à l'octet, aucun résidu `.tmp`.
  Limite : une base SQLite valide non KIESE avec au moins une table est acceptée (test `test_LIMITE_CONNUE...`). Jugement : acceptable. La sauvegarde vient d'un dossier géré par l'application (nom en liste blanche), la copie de sécurité est créée avant le remplacement et permet le retour (testé). Pas de rouverture. Amélioration possible hors périmètre : exiger `django_migrations` en adaptant les fixtures.
  Observation : un fichier tronqué d'un seul octet en fin de dernière page est accepté par SQLite ; seulement atteignable par un gz fabriqué (une vraie troncature de gz lève EOFError, refusée).
- BUG-404 : VÉRIFIÉ. Ordre validation du nom, décompression temporaire, integrity_check, contenu non vide, copie de sécurité, remplacement atomique. Si le remplacement échoue, la copie de sécurité est conservée, la base courante intacte, restaurable. Si la copie de sécurité échoue, rien n'est touché.

## Nouveau ticket
- BUG-410 (Mineur, OUVERT) : deux restaurations dans la même seconde écrasent la copie de sécurité de la première. Test `test_restauration_deux_fois_de_suite` en `expectedFailure`.

## Environnement
Disque C: saturé pendant la session (une écriture a échoué une fois) ; rien d'installé.
