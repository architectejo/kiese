# Rapport testeur-production — 2026-11-10 — Vérification BUG-155 / BUG-156

## Tickets traités

- **BUG-155** (backend, `dev-backend`) — `CORRIGÉ` → reste **`CORRIGÉ`** (1 défaut réel trouvé,
  ouvert séparément sous **BUG-158**, voir ci-dessous).
- **BUG-156** (frontend, `dev-frontend`) — `CORRIGÉ` → **`VÉRIFIÉ`**.
- **BUG-158** (nouveau) — `OUVERT`, backend, ouvert par ce testeur.

Statuts mis à jour dans `docs/qa/REGISTRE_BUGS.md` (tableau de suivi + fiches détaillées BUG-155,
BUG-156, nouvelle fiche BUG-158).

## Contexte

BUG-155/156 implémentent la demande client remarque.md l.414 : calcul/clôture automatique du reste
du jour à l'heure de fin de créneau d'une équipe, en plus de la saisie manuelle existante
(BUG-152/154). Backend : nouvel endpoint `GET /api/production/sessions/shift-end-status/`, avec
délai de grâce de 30 min (`SHIFT_END_GRACE_MINUTES`) avant clôture forcée. Frontend : polling
intégré au cycle de notifications existant dans `DashboardLayout.tsx`, modale forcée
(`CloseSessionModal` en mode forcé) ou toast selon la réponse.

## Méthode

Lu intégralement les deux fiches `CORRIGÉ` dans `docs/qa/REGISTRE_BUGS.md`, puis le code source
(`backend/production/views.py` lignes ~204-770, `frontend/src/components/production/
CloseSessionModal.tsx`, `frontend/src/store/shiftEndStore.ts`, `frontend/src/components/layout/
DashboardLayout.tsx`, `frontend/src/api/services.ts`) — pas seulement le test déjà écrit par
`dev-backend` (`test_bug155_shift_end_auto_closure.py`, 7 tests, tous lus mais pas réutilisés comme
seule preuve).

### Backend — scénarios indépendants écrits

Nouveau fichier `backend/production/tests/test_bug155_qa_production_review.py` (6 tests, fabriques
fictives via `core.testing`, aucune donnée de `data_kiese/`) :

| Test | Résultat |
|---|---|
| Les deux équipes A et B en attente simultanément sur le même nœud : un seul appel ne traite/signale que A, jamais les deux à la fois ; un second appel résout ensuite B | **OK** — comportement documenté respecté |
| Isolation : un FACTURIER non-HQ envoyant `?node=<autre boulangerie>` est ignoré, seul son propre nœud est évalué | **OK** |
| Multi-catégories (2 catégories, une épuisée à 0) : une ligne `REMAINING` par catégorie, y compris celle à 0 | **OK** |
| Non-régression BUG-152/154 : `close()` volontaire avec `remaining` explicitement différent du stock physique courant (12 déclaré vs 300 en stock) — valeur déclarée respectée, jamais « corrigée » silencieusement par la factorisation BUG-155 | **OK** |
| Clôture forcée avec `BreadStock.qty_available` **négatif** sur une catégorie (via une disposition DECLASSED dépassant le produit, aucun clamp existant — même principe que BUG-143 côté consommables) | **Défaut réel** → **BUG-158** (test marqué `@unittest.expectedFailure`, référence BUG-158) |

Détail du défaut (BUG-158) : `shift_end_status()` construit `remaining_entries` directement depuis
le stock physique courant, SANS repasser par la validation `qty_int < 0 → HTTP 400` qui protège
l'appel volontaire `close()`. Avec un stock à -20, l'écriture du `BreadDisposal` (`PositiveIntegerField`,
contrainte CHECK ajoutée par Django côté SQLite) lève `IntegrityError`, non interceptée → HTTP 500
brut. La transaction s'annule (session non close), donc le polling suivant replante à l'identique :
blocage indéfini et silencieux (le frontend avale l'erreur en `console.error`, rien à l'écran) de la
clôture automatique de cette fournée. Fiche détaillée avec pistes de correction dans le registre.

`python manage.py test` (suite complète) : **617 tests, OK (expected failures=1)**. Le nombre
correspond exactement à 611 (baseline annoncée par `dev-backend`) + 6 (ce nouveau fichier) — aucune
régression silencieuse détectée ailleurs dans le projet. `python manage.py makemigrations --check
--dry-run` : `No changes detected`.

### Frontend — relecture ciblée (pas de Playwright chronométré, limite documentée et acceptée)

- Mode forcé de `CloseSessionModal` réellement non annulable : pas de bouton « Annuler »,
  `showCloseButton`/`closeOnBackdropClick` désactivés. Point vérifié avec attention : `Modal.tsx`
  appelle `onClose` sur Échap QUEL QUE SOIT `closeOnBackdropClick` — mais `CloseSessionModal` enrobe
  lui-même ce `onClose` d'une garde `!isForced`, donc Échap n'a aucun effet en mode forcé (confirmé
  par lecture du code de `Modal.tsx`, pas supposé).
- Pré-remplissage en mode forcé : bien depuis `forced.remaining[].quantity_suggested`, pas de
  relecture de `REMAINING` existant (cohérent, aucune session forcée n'a pu en avoir).
- Un seul timer : `fetchShiftEndStatus` est appelé dans le MÊME `setInterval` (10 s) que
  `fetchNotifications`, déjà en place — pas de second `setInterval` créé. Le re-sondage immédiat
  après résolution est un appel ponctuel, pas un nouveau timer.
- Gating par rôle : identique à `OpeningStockConfirmationModal` (BUG-130/151) —
  `(GERANT ou FACTURIER) && !can_access_all_nodes` dans les deux cas (petite duplication de la
  condition entre les deux montages dans `DashboardLayout.tsx`, signalée mais non bloquante, pas de
  ticket ouvert pour ce point cosmétique).
- `npx tsc --noEmit` et `npm run build` : passent, exit code 0, seul avertissement préexistant
  (chunk legacy > 500 kB).
- Conclusion : aucun défaut trouvé côté frontend pour ce ticket. Le 500 silencieusement avalé par
  `fetchShiftEndStatus` est un comportement défensif raisonnable pour un endpoint de polling (ne
  jamais planter l'UI sur une erreur de sondage) — la correction de BUG-158 est purement backend.

## Décision

- **BUG-155** : reste `CORRIGÉ`. 5 scénarios sur 6 résistent à une vérification indépendante
  (construite sans réutiliser les tests du développeur), mais un défaut réel et reproductible de
  façon déterministe a été trouvé dans le code même de ce ticket (`shift_end_status`) → pas de
  `VÉRIFIÉ` tant que BUG-158 n'est pas traité.
- **BUG-156** : `VÉRIFIÉ`. Implémentation frontend conforme au contrat et aux patterns existants du
  projet (BUG-130/151) ; aucun défaut trouvé propre à ce ticket. Le défaut découvert est une
  responsabilité backend (BUG-158), pas un manquement de ce ticket.
- **BUG-158** (nouveau, `OUVERT`) : documenté avec reproduction précise, impact et 3 pistes de
  correction possibles (clamp à 0, erreur exploitable dédiée côté API, ou simple `try/except` pour
  éviter le 500 brut) — décision laissée au client/coordinateur avant correction, car le choix a un
  impact métier (masquer vs signaler un stock de pain négatif au moment de la clôture automatique).

Aucun fichier applicatif modifié par ce testeur (CLAUDE.md §7 règle 2) — seuls ajoutés/modifiés :
`backend/production/tests/test_bug155_qa_production_review.py` (nouveau),
`docs/qa/REGISTRE_BUGS.md`, ce rapport.

## Fichiers concernés

- `D:\Projects\kiesse\backend\production\tests\test_bug155_qa_production_review.py` (nouveau, 6 tests)
- `D:\Projects\kiesse\backend\production\views.py` (lu, non modifié — lignes ~204-770, `shift_end_status`/`_close_production_session`/`_current_bread_stocks`)
- `D:\Projects\kiesse\backend\production\models.py` (lu, non modifié — `BreadStock.qty_available`, `BreadDisposal.quantity`)
- `D:\Projects\kiesse\frontend\src\components\production\CloseSessionModal.tsx` (lu, non modifié)
- `D:\Projects\kiesse\frontend\src\store\shiftEndStore.ts` (lu, non modifié)
- `D:\Projects\kiesse\frontend\src\components\layout\DashboardLayout.tsx` (lu, non modifié)
- `D:\Projects\kiesse\frontend\src\api\services.ts` (lu, non modifié)
- `D:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` (mis à jour : BUG-155 reste CORRIGÉ avec note de
  vérification, BUG-156 → VÉRIFIÉ, nouvelle fiche BUG-158)

---

# Section 2 — Vérification du lot BUG-155 / 157 / 158 / 159 / 160 / 162 (2026-11-11)

## Décisions
| Ticket | Statut | Motif |
|---|---|---|
| BUG-155 | VÉRIFIÉ | Chaîne de bout en bout cohérente, idempotence séquentielle ; suivi mineur BUG-165 (concurrence) |
| BUG-158 | VÉRIFIÉ | Contrainte serializer + base (y compris `update()`/`bulk_create`), migration 0022 testée sur copie, lecteurs sains |
| BUG-157 | VÉRIFIÉ (relecture) | Modale non fermable, file persistée, compteur de modales sain ; pas de test navigateur |
| BUG-162 | VÉRIFIÉ | Négatif accepté, qty_adjusted, pas de CARRYOVER négatif, veille intacte |
| BUG-159 | reste CORRIGÉ | `SignedIntegerField` correct, mais BUG-166 (saisie écrasée toutes les 10 s en mode forcé) |
| BUG-160 | reste CORRIGÉ | Attributs relus ; autofill dépend du navigateur, contrôle manuel requis |
| BUG-156 | reste VÉRIFIÉ | Pas de régression, mais défaut latent BUG-166 non vu à ma première vérification |

## Nouveaux tickets
- BUG-165 (Mineur, backend) : double clôture/notification si deux requêtes `shift_end_status` s'entrelacent (pas de verrou). Test `@expectedFailure` (échoue bien sur `2 != 1`).
- BUG-166 (Majeur, frontend) : `CloseSessionModal` forcé, `setShiftEndPending` à chaque tick de 10 s remplace `forced` et l'effet réinitialise `quantities` et `error`.

## Tests ajoutés
`backend/production/tests/test_verif_bug155_162_testeur_production.py` : 12 tests (11 verts + 1 `expectedFailure` BUG-165).

## Incident à signaler
`settings.py` ignore la variable `DB_NAME` : mon premier essai de migration « sur copie » a exécuté `migrate production 0021` puis `migrate production` sur la vraie `backend/db.sqlite3`. Comparaison table par table avec une copie prise juste avant : données identiques, seules `django_migrations` et `sqlite_sequence` diffèrent. La vérification propre a ensuite été faite en forçant le chemin dans le process Python sur la copie.

## Contrôles
`makemigrations --check --dry-run` : propre. `npx tsc --noEmit` : aucune erreur. `npm run build` : OK (avertissement de taille de chunk préexistant). Suite complète (636 tests, lancée avant l'ajout de mon fichier, en 31 min car en concurrence avec mes autres exécutions) : 635 OK, 1 échec `sales.tests.test_charge_morning_peak` (`OperationalError: database table is locked`, test de charge multi-threads SQLite, hors périmètre) ; relancé seul : OK (35 s), donc instable sous charge machine. `manage.py test production` (189 tests, mon fichier inclus) : OK (expected failures=1).
