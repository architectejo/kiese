# Rapport testeur-production — 2026-11-10 — Vérification BUG-144 / BUG-145 (sélecteur de date, Production & Stocks)

## Contexte

Demande client (remarque.md, ligne ajoutée après l.396) : pouvoir sélectionner un jour dans
« Production & Stocks » pour « Stock Pains Actuel » (renommée « Stock Pains du Jour ») et
« Historique des Fournées ». Traité en deux tickets liés :
- **BUG-144** (backend, `dev-backend`) : nouvel endpoint `GET
  /api/production/bread-stocks/by-date/?node=&date=`.
- **BUG-145** (frontend, `dev-frontend`) : sélecteur de date (`StockDuJourSection.tsx`,
  `CalendarPicker`/`Modal` de BUG-128), renommage, filtrage de l'historique des fournées.

Les deux ont été vérifiés **ensemble**, de bout en bout, conformément à la mission.

## Méthode

1. Relecture complète du code final (pas seulement les rapports) : `backend/production/views.py`
   (`BreadStockByDateView`), `backend/production/urls.py`, `frontend/src/components/production/
   StockDuJourSection.tsx`, `frontend/src/pages/dashboard/Production.tsx`, `frontend/src/api/
   services.ts`.
2. Vérification des comptes `demo_*_e2e` : confirmés recréés et utilisables (login réel via API et
   via l'UI pour `demo_gerant_k1_e2e`, `demo_gerant_k2_e2e`, `demo_direction_e2e`).
3. Vérification backend bout en bout contre le serveur de dev réel (`:8000`, déjà lancé par une
   autre session — non relancé, non perturbé) : création de données fictives isolées (catégorie
   `BreadPrice` « E2E_BUG144 », 2 `ProductionSession` passées sur K1 avec leurs
   `DailyBreadStockSnapshot`), tests directs de l'endpoint `by-date` (live, snapshot une/deux
   équipes, date future, isolation par nœud GERANT/HQ), puis **suppression complète** de toutes les
   données fictives après usage (vérifié par requête de contrôle).
4. Vérification frontend E2E réelle (Playwright, comptes démo, serveurs de dev existants non
   relancés) : script temporaire non committé reproduisant le parcours complet décrit dans la
   mission (sélecteur de date, badge « Historique (reconstitué) », filtrage de l'historique des
   fournées, retour à aujourd'hui, affichage 360 px). Supprimé après usage.
5. `backend/.venv/Scripts/python.exe manage.py test production sales finance` et `cd frontend && npm
   run build`.

## Résultat

**BUG-144 et BUG-145 fonctionnent exactement comme spécifié dans les deux rapports de correction.**
Tous les scénarios demandés par la mission ont été vérifiés avec succès :

- `GET .../by-date/?date=<passée>` → `source: "snapshot"`, somme correcte des deux équipes
  (vérifié : 5 + 2 = 7, et `7 × 123 FC = 861 FC` affiché correctement côté UI).
- `GET .../by-date/` sans date ou avec la date du jour → `source: "live"`, identique à l'ancien
  comportement (`BreadStockViewSet`), non-régression confirmée en conditions réelles (pas seulement
  par relecture de code ou tests unitaires).
- `GET .../by-date/?date=<future>` → `400` en français.
- Isolation par nœud : un GERANT K2 forgeant `node=K1` reste cantonné à K2 (valeur forgée ignorée,
  confirmé en direct contre le serveur réel) ; un compte HQ doit préciser `node` explicitement
  (`400` sinon) et peut alors lire n'importe quel nœud.
- `GET /api/production/sessions/?date=&node=` (déjà existant, non modifié par BUG-144) renvoie bien
  les fournées du jour sélectionné.
- Côté UI : titre « Stock Pains du Jour — <date> », bouton « Choisir un jour », boîte modale
  calendrier (réutilise bien `CalendarPicker`/`Modal` de BUG-128), badge « Historique (reconstitué) »
  pour une date passée, « Historique des Fournées » piloté par le MÊME sélecteur et filtré en
  conséquence, retour à aujourd'hui qui restitue le comportement « live » sans badge. Affichage à
  360 px (POS) vérifié sans chevauchement.

Both tickets passés à **VÉRIFIÉ** dans `docs/qa/REGISTRE_BUGS.md`.

## Point découvert en marge (BUG-148, nouveau ticket, non bloquant pour BUG-144/145)

En relançant la suite E2E officielle du module (`e2e/tests/05-production.spec.ts`, premier scénario,
non modifié par BUG-144/145), le test échoue de façon reproductible : la boîte modale « Stock de
départ du jour » (`OpeningStockConfirmationModal.tsx`, BUG-133/134, sans rapport avec BUG-144/145)
peut apparaître avec un léger délai après que la page soit déjà interactive — intercepte alors le
clic sur « Enregistrer la Fournée » par `.modal-backdrop`, provoquant un timeout. Reproduit aussi
dans mon propre script de vérification temporaire ; contournable par un sondage répété de la boîte
modale avant d'interagir avec le formulaire (ce que fait ma vérification manuelle). N'affecte ni
BUG-144 ni BUG-145 eux-mêmes. Ouvert séparément sous **BUG-148** (Mineur, OUVERT) — n'impacte qu'un
utilisateur réel négativement si le même genre de race condition se manifestait, mais un humain n'a
pas de contrainte de timeout de 10 s ; priorité laissée au coordinateur.

## Tests

- `backend/.venv/Scripts/python.exe manage.py test production sales finance` → **246 tests, OK**
  (0 échec, 0 erreur — 243 de dev-backend + 3 tests de vérification déjà présents dans cette session
  pour BUG-142/143, antérieurs à ce ticket).
- `cd frontend && npm run build` → build réussi (avertissements pré-existants sans rapport : taille
  du bundle legacy, minifieur `oxc` non supporté pour les chunks legacy).
- E2E manuel Playwright (script temporaire, supprimé après usage) : scénario complet BUG-144/145
  passé au vert sur les projets `bureau` et `pos` (360 px).

## Données de test

Toutes les données fictives créées pour cette vérification (catégorie `BreadPrice` « E2E_BUG144 »,
2 `ProductionSession` K1/2026-11-07, leurs `ProductionSessionLine`/`BreadDisposal`, les 2
`DailyBreadStockSnapshot`) ont été **supprimées après usage** — base remise dans l'état où elle a
été trouvée, vérifié par requête de contrôle (`BreadPrice.objects.filter(category='E2E_BUG144')
.count() == 0`, `ProductionSession.objects.filter(date='2026-11-07').count() == 0`). Aucune donnée
`@gerant-kX`/`@pierre` réelle n'a été touchée. Le serveur de dev existant (`:8000`) n'a pas été
relancé ni perturbé.

## Fichiers concernés (lecture seule, aucune modification de code applicatif)

- `backend/production/views.py::BreadStockByDateView`
- `backend/production/urls.py`
- `frontend/src/api/services.ts`
- `frontend/src/components/production/StockDuJourSection.tsx`
- `frontend/src/pages/dashboard/Production.tsx`
- `docs/qa/REGISTRE_BUGS.md` (BUG-144 → VÉRIFIÉ, BUG-145 → VÉRIFIÉ, BUG-148 → nouveau ticket OUVERT)
