# architecte-sync d50 (2026-11-23) : BUG-1007

Cause : `stale` (poste en retard) comparait `Node.last_sync` (posé aussi par chaque push) à `transfer.updated_at`.

Correctif :
- Nouvelle table additive `sync.TransferPull(node, transfer_id, pulled_at)` (migration 0006). Une colonne sur `TransferMirror` aurait cassé `A17Migration0005` (qui lit le modèle courant au schéma 0005) ; table séparée = test intact.
- `PullView` pose `pulled_at = now` (pris avant les lectures) pour chaque transfert livré, en fin de réponse.
- `_store_mirrors` : poste en retard = transfert jamais livré par un pull, ou `pulled_at < updated_at`. Un poste honnête qui n'a pas tiré peut rejouer son marqueur sans alerte.
- Ligne migrée en 0005 (pic vide) : `_bump_peaks` (appelé au push et au pull, avant la comparaison) initialise le pic à la valeur courante des lignes cloud.
- Strict conservé : poste à jour (pull postérieur à la ligne) + marqueur au-dessus de la borne -> MIRROR_OUT_OF_BOUNDS.
- `@expectedFailure` de test_BUG_1007 retiré, assertions inchangées. BUG-1006 non touché (À CLARIFIER).

Tests (log $TEMP/d50.log) : a17+a16+a15+a14+d43+sync v5 = 120 tests OK (1 échec attendu = BUG-1006). makemigrations --check : aucun changement.
