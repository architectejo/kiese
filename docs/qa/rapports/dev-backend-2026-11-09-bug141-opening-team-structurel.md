# Rapport dev-backend — 2026-11-09 — BUG-141

## Ticket traité

**BUG-141** — `opening_team` (introduit par BUG-139/140 dans
`DailyOpeningConfirmationView.get()`) était calculé via `Node.active_team_at()`
(« qui travaille EN CE MOMENT ? ») au lieu du premier créneau structurel de la
journée. Testé en direct par le client à 21h sur K1 (hors des deux créneaux
configurés, 06:00-11:30 et 14:30-20:00) : la boîte modale ne présélectionnait
plus aucune équipe, alors que remarque.md l.398 désigne le **premier créneau**
(toujours A pour K1), indépendamment de l'heure de connexion du gérant/facturier.

### Cause

`active_team_at()` et « premier créneau de la journée » sont deux questions
différentes. BUG-139/140 avait besoin de la seconde mais utilisait la première,
qui renvoie `None` dès que l'heure d'appel tombe hors des deux créneaux.

### Correction

1. `backend/core/models.py` : nouvelle méthode `Node.opening_team()`, purement
   structurelle (horaires configurés comparés entre eux, jamais l'heure
   courante) :
   - deux créneaux configurés → celui dont `start_time` est le plus tôt (`'A'`
     par convention stable en cas d'égalité exacte) ;
   - un seul créneau configuré → celui-là ;
   - aucun créneau configuré → `None` (filet de sécurité inchangé).
   `Node.active_team_at()` n'a pas été touchée (toujours utilisée ailleurs pour
   « qui travaille EN CE MOMENT ? », hors périmètre de ce ticket).

2. `backend/production/views.py::DailyOpeningConfirmationView.get()` :
   `opening_team = node.active_team_at()` → `opening_team = node.opening_team()`.
   Docstring de la vue et commentaire mis à jour pour expliciter la distinction
   entre les deux méthodes et éviter une confusion future.

3. `backend/production/tests/test_daily_opening_confirmation.py` —
   `OpeningConfirmationNeedsConfirmationTests` :
   - Les deux tests qui patchaient `Node.active_team_at` directement (la vue ne
     l'appelle plus, donc ce patch n'avait plus aucun effet sur `opening_team`)
     ont été adaptés pour configurer directement les horaires réels du nœud
     (`team_a_start_time`/`team_b_start_time`), renommés
     `test_with_configured_slots_only_the_opening_team_confirmation_is_required`
     et `test_with_configured_slots_opening_team_confirmation_alone_suffices`.
     Même comportement attendu qu'avant (confirmation de l'équipe d'ouverture
     seule suffit), toujours vert.
   - Les tests « filet de sécurité » (nœud sans créneaux configurés) étaient
     déjà corrects sans modification : `opening_team()` renvoie `None` dans ce
     cas, comme `active_team_at()`.
   - Nouveau test ajouté (créé directement vert après correctif, pas sous
     `@expectedFailure`) :
     `test_bug141_opening_team_is_first_slot_regardless_of_current_time` — nœud
     avec A 06:00-11:30 / B 14:30-20:00, heure courante simulée à 21h00 (hors
     des deux créneaux). Vérifie d'abord, par contraste, que
     `node.active_team_at()` renvoie bien `None` à cette heure (preuve du
     bug), puis que `opening_team` dans la réponse du `GET` vaut `"A"`
     (comportement corrigé, indépendant de l'heure). Ce test échouait avec le
     code d'avant correctif (`opening_team` valait `None`).

### Impact API / contrat

Aucun changement de contrat : le champ `opening_team` garde le même nom, le
même type (`"A" | "B" | null`) et la même sémantique documentée côté frontend
(BUG-140) — seule la VALEUR renvoyée change de logique de calcul dans les cas
où elle différait de l'ancien comportement (hors créneau actif au moment de
l'appel). Le frontend (`OpeningStockConfirmationModal.tsx`) consomme déjà ce
champ tel quel, aucune modification nécessaire. **Aucun ticket frontend lié
ouvert.**

4. `backend/production/tests/test_opening_confirmation_verification.py`
   (`OpeningConfirmationFinalVerificationBug137To140Tests`, fichier de
   vérification du testeur, BUG-139/140) : la première exécution complète de
   la suite a révélé que `test_bug139_real_time_slots_only_active_team_
   confirmation_required` encodait l'ancien comportement incorrect (créneaux
   réels A 06:00-13:00 / B 13:00-20:00, heure figée à 14h, attendait
   `opening_team == 'B'` car `active_team_at()` y voyait B active). Ce test
   échouait après le correctif (`'A' != 'B'`), **ce qui était attendu** :
   l'assertion elle-même contredisait le contrat corrigé (opening_team
   structurel = `'A'`, A démarrant avant B à 06:00). Renommé
   `test_bug141_real_time_slots_opening_team_is_first_slot_not_current_time`
   et corrigé pour attendre `opening_team == 'A'` à 14h, confirmation de A
   (équipe d'ouverture) seule suffisante, celle de B seule insuffisante —
   même esprit de test (intégration avec de vrais horaires de nœud, pas de
   mock), assertions alignées sur le contrat corrigé. Docstring de la classe
   mise à jour en conséquence. Ce n'est pas une atténuation du test : la
   correction du contrat `opening_team` (demandée explicitement par ce
   ticket BUG-141, tranchée côté client) rendait cette assertion précise
   obsolète, au même titre que les deux tests de
   `test_daily_opening_confirmation.py` déjà adaptés au point 3.

### Tests de non-régression

- `backend/.venv/Scripts/python.exe manage.py test production sales finance`
  — **210 tests, OK** (confirmé après correction du test de vérification
  ci-dessus ; Ran 210 tests in 402.862s).
- `backend/.venv/Scripts/python.exe manage.py makemigrations --check --dry-run`
  — `No changes detected` : changement purement logique (aucune modification
  de schéma, `Node.opening_team()` est une méthode Python, pas un champ).

## Fichiers modifiés

- `D:\Projects\kiesse\backend\core\models.py` (nouvelle méthode `Node.opening_team()`)
- `D:\Projects\kiesse\backend\production\views.py` (usage + docstring/commentaires)
- `D:\Projects\kiesse\backend\production\tests\test_daily_opening_confirmation.py`
  (tests adaptés + nouveau test BUG-141)
- `D:\Projects\kiesse\backend\production\tests\test_opening_confirmation_verification.py`
  (un test du testeur corrigé pour le contrat BUG-141, voir ci-dessus)
- `D:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` (fiche BUG-141, tableau + détail,
  statut `CORRIGÉ`)

## En attente

- Vérification par testeur-production (ou le coordinateur) — je n'ai pas
  passé le ticket à `VÉRIFIÉ` (CLAUDE.md §7 règle 3). En particulier, le
  testeur devra relire la correction apportée à son propre fichier
  `test_opening_confirmation_verification.py` (point 4 ci-dessus) : son
  assertion initiale testait exactement le comportement que le client a
  signalé comme bogué (BUG-141) — je l'ai corrigée dans le même esprit que
  le reste du lot, mais une revalidation indépendante reste utile.
- Suite complète confirmée verte : `manage.py test production sales finance`
  → 210 tests, OK.

## Risques

- Aucun autre appelant de `active_team_at()` dans le code applicatif n'a été
  identifié en dehors de celui déjà documenté par BUG-130 ; non modifié par ce
  ticket.
- La règle de départage en cas d'égalité exacte des deux `start_time`
  (convention : `'A'` par défaut) est un choix arbitraire mais stable et
  documenté dans le docstring de `Node.opening_team()` — cas limite
  improbable en pratique (deux équipes ne devraient jamais démarrer à la
  même heure), signalé explicitement si jamais jugé insuffisant.
