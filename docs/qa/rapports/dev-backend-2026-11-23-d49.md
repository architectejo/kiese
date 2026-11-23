# Dev-backend d49 (2026-11-23)

Tickets CORRIGÉ : BUG-999 (majeur), BUG-1004 (mineur), BUG-1005 (nouveau, mineur : test instable = vrai défaut).

## BUG-999
- `sync/views.py` : ligne client + `is_active` (additif). Au pull incrémental seulement (curseur présent, sans `client_after_id`), les clients inactifs d'autres nœuds redescendent (le curseur `updated_at` filtre). Pull initial et pages suivantes : inchangés (BUG-998). La désactivation fait déjà avancer `updated_at` (PATCH -> `perform_update`).
- `sync_now.py` : `_build_pulled_client` lit `is_active` ; un inactif d'une autre boulangerie inconnu n'est pas créé ; `_apply_pulled_client_batch` applique `is_active` sauf édition locale non poussée (BUG-952).
## BUG-1004
- `clients/views.py` : `bulk_move` et `recalculate_category` ajoutent `updated_at`. `bulk_delete` : pas de pierre tombale (limite documentée). `bulk_update` du pull : volontairement sans `updated_at` (test existant).
- `sync_now.py` : application de `node`/`code`/`node_origin` aux clients connus ; code pris par un autre client (local ou du lot) : aucun changement + `SyncConflictLog` CODE_CLIENT_EN_CONFLIT (une fois) ; jamais de doublon.
- Tests : décorateurs `@expectedFailure` retirés (4 tests), `ROW_KEYS` + `is_active` (contrat), test « constat » bulk_move inversé (`assertGreater`).
## BUG-1005 (test instable)
- Pas de threads dans ces tests (séquence simulée) ; non reproduit en 10 runs isolés. Cause : `generate` départage les lignes de même `created_at` par `pk__lt` (UUID aléatoire). Horloge grossière sous charge -> deux lignes ex aequo, aucune ne cède -> retenues doublées. Vrai défaut de code (`commissions/views.py`).
- Correction : à `created_at` égal, cède si l'autre retient déjà ou si son pk est inférieur. Test `commissions/tests/test_commissions_d49.py` (horloge figée + UUID inversés) : échoue avant, passe après.
- Risque résiduel : deux générations strictement simultanées au même instant pourraient céder toutes deux (retenue à saisir à la main, jamais doublée).

## Résultats
clients v13+v12+v11 : 119 OK ; sync v5 + charge v4 + charge v3 + commissions v4 + d49 : 111 OK (1 expected failure préexistant) ; `makemigrations --check` : aucun changement. Logs : `$TEMP/d49.log`, `$TEMP/d49b.log`.
Contrat API : champ `is_active` ajouté aux lignes `clients` du pull (additif, anciens postes l'ignorent). Pas de ticket frontend.
