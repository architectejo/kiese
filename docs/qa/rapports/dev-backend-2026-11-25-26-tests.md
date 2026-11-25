# dev-backend 2026-11-25 : 26 échecs restants (Q-017 / Q-018 / horloge décalée)

Lancement : `KIESE_TEST_CLOCK_SHIFT=1`, modules ciblés. Tous les modules listés repassent au vert. Non commité.

## Vrai défaut applicatif (1)
- `core/workday.py::business_day_bounds` : `work_date + 1 jour` levait `OverflowError` pour `9999-12-31`, d'où HTTP 500 sur
  `GET /api/sales/invoices/daily_summary/?date=9999-12-31` (test `core ... Invalid5xx.test_get_probes_all_roles`, 7 rôles).
  Défaut introduit par le découpage midi à midi (la borne de fin est désormais calculée). Correction : borne haute = `datetime.max`
  si débordement. Test de non-régression : `core/tests/test_bug161_workday.py::ExtremeDatesTests`.

## Défauts du runner d'horloge (2 corrections, `backend/kiese/testrunner.py`)
- `MigrationHygiene.test_makemigrations_check` : avec le décalage, `timezone.now` remplacé par un lambda. Les migrations chargées
  tardivement référencent ce lambda alors que les modèles ont l'original, d'où de faux « changements »
  (`date_joined`, `action_time`). Le runner précharge maintenant les migrations avant le remplacement.
  Hors décalage et `makemigrations --check` direct : propre (sans rapport avec un verrou).
- `time.time` est désormais décalé du même delta (le poste desktop compare `Node.last_sync`, écrit via `timezone.now`, à `time.time()`) :
  corrige `test_node_last_sync_recent_compte`.
- Code applicatif : `sync/desktop_client.py::_valid_cursor_value` comparait le curseur à `datetime.now(utc)` (horloge réelle) ;
  elle utilise maintenant `timezone.now()` (horloge unique du projet, identique en production). Corrige `BouclePull` (2) et
  `CurseurVerif` (2) : le curseur « futur » était rejeté (pull sans fin à 200 pages, curseur vide).

## Tests périmés (corrigés côté test)
- `sales` test_bug197_receipt_unique (3) + test_verif_bug197_c (4) : horloge simulée à 10:00, soit avant la clôture de midi (journée comptable = la veille). Passée à 13:00.
- `treasury` test_bug083_backdated_cashbook_correction (5), test_bug083_verification_2026_10_29 (ERROR + FAIL), test_bug178 Scenario4Retroactive (ERROR) :
  livraisons ORM horodatées à 09:00/10:00 du jour D, donc rattachées à la journée D-1. Passées à 13:00/14:00. **La correction BUG-083 sur clôture verrouillée n'est pas cassée** : les 19 tests passent après ce seul changement d'heure.
- `treasury` test_vague2 MidnightWindowTests (3) : à 00:30 locale la journée comptable est la veille (12-11), plus le 13-11 ; attentes réécrites (et tests renommés « business_day »).
- `clients` test_clients_v14 IsActive : K1 sans `team_rotation_enabled=False` (403 TEAM_NOT_ASSIGNED) ; mis à False dans `Base14.setUp`.

## Fichiers modifiés
backend/core/workday.py, backend/sync/desktop_client.py, backend/kiese/testrunner.py ;
tests : core/tests/test_bug161_workday.py, sales/tests/test_bug197_receipt_unique.py, sales/tests/test_verif_bug197_c.py,
treasury/tests/test_bug083_backdated_cashbook_correction.py, test_bug083_verification_2026_10_29.py, test_bug178_verification_2026_11_11.py,
test_vague2_db_testeur_tresorerie.py, clients/tests/test_clients_v14.py.

## Questions métier : aucune. Risques
- Le décalage de `time.time` dans le runner n'a pas été rejoué sur toute la suite (machine lente) : à confirmer par la série finale.
- `datetime.now` direct ailleurs dans le code reste non décalé par le runner (non rencontré dans ces modules).
