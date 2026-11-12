# Rapport testeur-trésorerie — 2026-11-12

## Vérification BUG-189 et volet trésorerie de BUG-161/B3

Verdict : **BUG-189 VÉRIFIÉ** ; volet trésorerie de B3 conforme. BUG-161 reste ouvert. Deux défauts non liés à B3 : BUG-198, BUG-199.

### Exécutions (un processus à la fois, base de test en mémoire)
- 4 tests cités + `test_bug189_vacation_lock_local_date` (27 tests) avec `timezone.now` simulé à 00:30, 12:00 et 23:30 locales : OK x3 (1 attendu préexistant).
- `manage.py test treasury blockchain` : 146 tests OK, 3 échecs attendus (1 préexistant, 2 sondes de ce rapport). Suites BUG-033/034/035/036/037/083/086/091/100/178 inchangées et vertes.
- Nouveau `backend/treasury/tests/test_verification_b3_tresorerie_2026_11_12.py` : 17 tests, OK (2 `expectedFailure`).

### Scénarios
1. Verrou BUG-036 à 00:30 et midi, avec/sans `allow_backdated_sales` : refus. OK.
2. Rotation (relève 12:00) : vente 03:00 et 11:59 -> rapport J ; 12:00 -> J+1 ; clôture net 2100-400=1700, billets 2600, écart +900 ; écart négatif et nul ; double clôture 400 ; PATCH après validation 400 ; recalcul ; `suggested_ca` = total_entries. OK.
3. Livre : date de l'écriture = date de la clôture, `VC-K1-20261111`, soldes, 30 écritures à cheval sur minuit/relève, falsification en base détectée par `integrity_check` et `run_check`, fonction de hash unique (mêmes objets). OK.
4. Rétroactif en rotation : plafond = journée de travail (J+1 calendaire refusé à 03:00) ; livraison rétroactive d'un jour versé -> 1 correction +300, original intact, chaîne valide. OK.
5. Défauts mois/année : 1er du mois 00:30 hors rotation -> mois courant ; rotation avant relève -> mois précédent. OK. `date` obligatoire dans le serializer de clôture : la valeur par défaut de `perform_create` est du code mort (sans effet).
6. Équivalence hors rotation : OK (00:30 et 03:00 -> date calendaire locale).
7. Deux nœuds (relève 12:00 / 06:00) : journées de travail distinctes à 08:00. OK.
8. Audit `date.today()` / `.date()` (hors tests/migrations) : `core/workday.py` (local), `production/views.py:834` et `sales/views.py:90` (sur `localtime()`), `__date` ORM (conversion locale), `timezone.localdate()` partout ailleurs : aucun usage fautif. `scripts/charge/volumetrie.py`, `seed_from_excel.py`, `desktop_server.py` (nom de sauvegarde) : hors logique métier. Nuance connue : `bread_summary`/appro filtrent sur la date calendaire (cf. BUG-193).

### Tickets
- BUG-198 (Majeur) : DELETE d'une clôture validée/versée accepté (écarts effacés, `source_closure` NULL, chaîne rompue).
- BUG-199 (Majeur) : versement de la journée J après J+1 d'une autre boulangerie -> fausse falsification (tri `(date, created_at)` vs ordre d'insertion).
