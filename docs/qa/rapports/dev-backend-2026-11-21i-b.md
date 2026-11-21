# Rapport dev-backend (B) 2026-11-21i

## Ticket traité
BUG-416 [Mineur, tests production] : tests CUMP instables sous Windows (égalité de `created_at`). Statut : CORRIGÉ.

## Cause
Horloge grossière : des `ConsumableMovement` créés coup sur coup ont le même `created_at`. L'ordre `('created_at','pk')` retombe sur le pk UUID, aléatoire. Environ 1 échec sur 4 sur 5 tests.

## Correction (tests uniquement, assertions inchangées)
- `production/tests/test_bug357_recompute_cump.py` : helper `_stamp`, appelé par `_mv`.
- `production/tests/test_verif_bug357_147_c.py` : `_mv` impose `created_at` croissant.
- `production/tests/test_verif_bug402_a.py` : `Base.move` impose `created_at` croissant.
- Méthode : `update(created_at=base + n s)` avec compteur de module, puis `refresh_from_db()`.
- Autres tests de production (grep) : `test_bug402_cump_stock_negatif`, `test_bug123`, `test_bug126`, etc. référencent les mouvements par variable/pk, pas par ordre. Non modifiés.

## Preuve
3 fichiers x 6 exécutions consécutives : 18/18 OK (log : `%TEMP%\bug416.log`). Les 3 fichiers ont 6, 36 et 32 tests.

## Pour A (non corrigé)
`recompute_cump` rejoue par (`created_at`, pk UUID). Sur des données réelles où deux mouvements ont le même instant, le rejeu peut les inverser et produire un CUMP différent du CUMP en ligne. À envisager : ordre de rejeu stable, avec une séquence ou un horodatage plus fin.

## Registre
Ligne du tableau et fiche BUG-416 ajoutées, CRLF conservé (`git diff --stat` : 9 insertions).

## Risques
La suite complète n'a pas été relancée (seuls les 3 fichiers ont été exécutés). Rien n'est commité.
