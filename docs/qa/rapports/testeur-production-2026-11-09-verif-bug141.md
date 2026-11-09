# Rapport testeur-production — 2026-11-09 — Vérification BUG-141

## Ticket vérifié

**BUG-141** — `opening_team` doit être le premier créneau structurel de la
journée, pas l'équipe active à l'instant présent. Signalé par le client en
test direct à 21h sur K1 (hors des deux créneaux configurés : 06:00-11:30
pour A, 14:30-20:00 pour B) : la boîte modale de confirmation du stock de
départ (remarque.md l.398) ne présélectionnait plus aucune équipe.

## Méthode

1. Relecture indépendante de `Node.opening_team()`
   (`backend/core/models.py:202-232`) : la méthode compare uniquement
   `team_a_start_time`/`team_b_start_time` entre eux (`'B' if b_start <
   a_start else 'A'`), n'appelle `localtime()` ni aucune heure courante à
   aucun moment — purement structurelle. `Node.active_team_at()` n'a pas été
   touchée et reste utilisée ailleurs pour sa question propre.
2. Relecture indépendante de `DailyOpeningConfirmationView.get()`
   (`backend/production/views.py:1565-1581`) : appelle bien
   `node.opening_team()`, et `needs_confirmation` dérive uniquement de la
   confirmation de cette équipe (filet de sécurité A-ou-B inchangé pour un
   nœud sans créneaux).
3. **Relecture ciblée, comme explicitement demandé**, du test modifié par
   dev-backend dans mon propre fichier
   `backend/production/tests/test_opening_confirmation_verification.py`
   (`OpeningConfirmationFinalVerificationBug137To140Tests::
   test_bug141_real_time_slots_opening_team_is_first_slot_not_current_time`,
   ex-`test_bug139_real_time_slots_only_active_team_confirmation_required`).
   Vérification indépendante : avec les horaires réels du `setUp` (A
   06:00-13:00, B 13:00-20:00), A démarre bien avant B — donc A est
   structurellement le premier créneau de la journée, quelle que soit
   l'heure figée (14h dans ce test, créneau B actif selon l'horloge).
   L'ancienne assertion (`opening_team == 'B'` à 14h) encodait exactement
   le comportement bogué signalé par le client : elle supposait que
   `opening_team` suit l'équipe en service au moment de l'appel. La
   nouvelle assertion (`'A'`) est la lecture correcte de remarque.md l.398.
   La portée et la rigueur du test (intégration avec de vrais horaires de
   nœud, parcours POST B puis POST A pour prouver que seule la
   confirmation de l'équipe d'ouverture suffit) sont restées intactes —
   **ce n'est pas un affaiblissement du test**, seule l'assertion
   initialement erronée a été corrigée. Confirmation que l'affirmation de
   dev-backend est exacte.
4. Test indépendant ajouté (pas une simple relecture) : nouveau fichier
   `backend/production/tests/test_bug141_opening_team_after_hours.py`
   (`Bug141AfterHoursOpeningTeamTests`), deux tests :
   - `test_connection_at_21h_after_both_slots_still_preselects_opening_team_a` :
     reproduit le scénario réel du client — nœud configuré comme K1 (A
     06:00-11:30, B 14:30-20:00), heure figée à 21h00 (après fermeture des
     deux créneaux). Preuve en deux temps : (a) `node.active_team_at()`
     renvoie bien `None` à cette heure (cause du bug confirmée
     indépendamment, preuve que le scénario reproduit réellement la
     régression) ; (b) `GET /api/production/opening-confirmation/` renvoie
     malgré tout `opening_team == 'A'` (jamais `None`), et la confirmation
     de A à 21h lève correctement `needs_confirmation`.
   - `test_facturier_also_sees_opening_team_a_after_hours_at_22h` : même
     garantie pour un rôle FACTURIER (remarque.md l.398), à 22h (heure
     distincte de celle déjà couverte par dev-backend à 21h, pour éviter
     un faux-positif lié à une valeur d'heure particulière).
5. `backend/.venv/Scripts/python.exe manage.py test production sales finance`
   → **212 tests, OK** (210 tests existants + 2 nouveaux tests
   indépendants ajoutés par moi), aucune régression.

## Conclusion

Le correctif BUG-141 est confirmé indépendamment correct : `Node.
opening_team()` et son usage dans `DailyOpeningConfirmationView` sont
purement structurels, conformes à remarque.md l.398. Le test modifié dans
mon propre fichier de vérification est une correction légitime du contrat
(pas un affaiblissement) — vérifié personnellement, pas seulement sur la
base de l'affirmation de dev-backend. Le nouveau test indépendant à 21h/22h
reproduit fidèlement le cas réel signalé par le client et passe.

**BUG-141 passé à `VÉRIFIÉ`** dans `docs/qa/REGISTRE_BUGS.md` (tableau
récapitulatif + fiche détaillée, section « Vérification » ajoutée).

## Fichiers

- Lus (aucune modification de code applicatif) :
  - `D:\Projects\kiesse\backend\core\models.py`
  - `D:\Projects\kiesse\backend\production\views.py`
  - `D:\Projects\kiesse\backend\production\tests\test_opening_confirmation_verification.py`
  - `D:\Projects\kiesse\docs\qa\rapports\dev-backend-2026-11-09-bug141-opening-team-structurel.md`
  - `D:\Projects\kiesse\remarque.md` (l.398)
- Créé : `D:\Projects\kiesse\backend\production\tests\test_bug141_opening_team_after_hours.py`
- Modifié : `D:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` (BUG-141 → VÉRIFIÉ, tableau + fiche)

## Hors périmètre (non retouché, comme demandé)

BUG-133/134/135/136/137/138/139/140 : déjà VÉRIFIÉ, non impactés par ce
changement ciblé — pas de relance de l'E2E complet.
