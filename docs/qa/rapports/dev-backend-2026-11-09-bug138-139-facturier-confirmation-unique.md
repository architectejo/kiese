# Rapport dev-backend — 2026-11-09 — BUG-138 / BUG-139

## Contexte

`testeur-production` a ouvert deux tickets en vérifiant le lot BUG-133/134/135/136 (boîte modale
« stock de départ du jour ») : BUG-138 (OUVERT) et BUG-139 (À CLARIFIER), tous deux lus de
remarque.md l.398. Le client (ADG, ETS. KIESE) a tranché BUG-139 directement avec le coordinateur
le 2026-11-09, en ajoutant lui-même la ligne remarque.md l.398 :

> « Après confirmation des restes d'hier, les valeurs renseignées doivent remplacer les valeurs
> qu'il a déjà dans "Production & Stocks" et non additionner [— déjà fait, BUG-136, non retouché],
> on le fait une fois le matin, pour l'équipe A ou B, juste une fois au créneau d'ouverture
> (premier créneau), le facturier peut aussi faire ça. »

BUG-139 n'est donc plus « À CLARIFIER » : le point central (une confirmation suffit, pour l'équipe
du créneau d'ouverture quand elle est déterminable) est tranché. Les deux tickets ont été corrigés
ensemble (même zone de code, `backend/production/views.py::DailyOpeningConfirmationView`).

## Tickets traités

### BUG-138 — Accès FACTURIER (CORRIGÉ, backend)

- **Cause** : `DailyOpeningConfirmationView.permission_classes = [IsGerant]` excluait FACTURIER.
- **Correctif** : remplacé par `permission_classes = [IsFacturier]`. `IsFacturier`
  (`backend/core/permissions.py`, déjà existant, inchangé) autorise déjà « FACTURIER ou
  supérieur » (ADMIN/DIRECTION/COMPTABLE/GERANT/FACTURIER) — exactement le besoin (GERANT+
  FACTURIER), sans créer de nouvelle classe de permission. `_opening_confirmation_resolve_node`
  (inchangée) applique la même règle d'isolation par nœud à FACTURIER qu'à GERANT : les deux ont
  `User.can_access_all_nodes == False`, donc tout `node` envoyé dans le payload/query est ignoré et
  remplacé par `user.node` — un FACTURIER de K1 ne peut jamais agir sur K2.
- **Fichiers modifiés** :
  - `backend/production/views.py` : import `IsFacturier` ; `permission_classes` de
    `DailyOpeningConfirmationView` ; docstring complétée (section « BUG-138 »).
  - `backend/production/tests/test_daily_opening_confirmation.py` : remplace
    `test_facturier_cannot_access_opening_confirmation` (qui testait l'ANCIEN contrat, 403) par
    `test_facturier_can_access_opening_confirmation_on_own_node` (200 GET+POST sur son nœud, node
    forgé toujours ignoré).
  - `backend/production/tests/test_opening_confirmation_verification.py` : remplace
    `test_facturier_post_refused_entirely_no_side_effect` par
    `test_facturier_post_allowed_on_own_node_refused_on_other_node` (effet de bord réel sur son
    propre nœud ; `node` forgé vers un autre nœud toujours sans effet).
- **Test de non-régression** : les deux tests remplacés ont été exécutés avant le correctif (403
  puis échec attendu sur le nouveau contrat 200) et passent maintenant. `LIVREUR` reste refusé
  (`test_livreur_post_refused_entirely`, inchangé) ; le périmètre HQ/COMPTABLE est inchangé
  (`test_hq_role_comptable_is_treated_as_headquarters_not_refused_but_cannot_act_implicitly`,
  inchangé).
- **Impact API** : `GET`/`POST /api/production/opening-confirmation/` acceptent désormais
  FACTURIER (200 au lieu de 403 systématique). Ticket lié ouvert pour `dev-frontend` : **BUG-140**
  (monter la boîte modale aussi pour FACTURIER dans `DashboardLayout.tsx`).

### BUG-139 — Une seule confirmation par jour (CORRIGÉ, backend)

- **Cause** : le modèle de données (`DailyOpeningConfirmation`, clé `[node, team, date]`) et
  `_build_daily_closure_report`/BUG-135 étaient déjà corrects et n'ont **pas** été touchés — le
  stockage par équipe reste utile (le rapport de clôture continue, par équipe, à préférer la
  valeur confirmée de CETTE équipe si elle existe, sinon l'auto-dérivé BUG-118). Le seul défaut
  réel était le **signal** exposé au frontend pour savoir quand fermer la boîte modale : le GET ne
  renvoyait que `teams.A.confirmed`/`teams.B.confirmed`, ce qui avait conduit l'implémentation
  frontend (BUG-134) à exiger les DEUX confirmations avant de fermer la modale — alors que le
  client veut qu'UNE SEULE confirmation (celle de l'équipe du créneau d'ouverture) suffise.
- **Correctif** : `DailyOpeningConfirmationView.get()` calcule et renvoie deux champs
  supplémentaires, sans toucher au reste de la réponse :
  - `opening_team` : `"A"` ou `"B"`, déterminé via `Node.active_team_at()` (BUG-130, créneaux
    horaires configurés du nœud) évalué au moment de l'appel ; `null` si le nœud n'a pas de
    créneaux configurés (cas réel pour les boulangeries non encore configurées, BUG-130/131).
  - `needs_confirmation` (booléen) :
    - `opening_team` déterminé → `not teams[opening_team].confirmed` (seule l'équipe active du
      créneau d'ouverture doit avoir confirmé — l'autre équipe peut ne jamais confirmer).
    - `opening_team` est `null` (filet de sécurité) → `not teams.A.confirmed and
      not teams.B.confirmed` (UNE confirmation, A OU B, suffit — jamais les deux exigées).
  - Docstring de la vue complétée (section « BUG-139 ») précisant explicitement que
    `needs_confirmation` est désormais le **seul** signal que le frontend doit utiliser pour
    décider d'afficher la boîte modale — `teams.A/B.confirmed` restent dans la réponse
    (informatifs, toujours consommés par ailleurs dans la boîte modale elle-même pour afficher le
    détail par équipe) mais ne doivent plus servir à ce calcul côté client.
- **Fichiers modifiés** :
  - `backend/production/views.py` (`DailyOpeningConfirmationView.get()` et docstring).
  - `backend/production/tests/test_daily_opening_confirmation.py` : nouvelle classe
    `OpeningConfirmationNeedsConfirmationTests` (4 tests, utilise `unittest.mock.patch.object(Node,
    'active_team_at', ...)` pour contrôler l'équipe active sans dépendre de l'heure réelle
    d'exécution des tests) :
    - créneaux configurés, équipe B active : A seule ne suffit pas, B (active) seule suffit même
      si A ne confirme jamais ;
    - créneaux configurés, équipe A active : symétrique (A seule suffit) ;
    - nœud sans créneaux configurés : une seule confirmation (A ou B) suffit ;
    - nœud sans créneaux configurés, aucune confirmation : modale requise.
  - `backend/production/tests/test_opening_confirmation_verification.py` : ajoute
    `test_build_daily_closure_report_unaffected_by_bug139_change` — non-régression explicite
    confirmant que `_build_daily_closure_report`/BUG-135 reste identique (par équipe, valeur
    confirmée si elle existe sinon auto-dérivé).
- **Test de non-régression** : les 4 nouveaux tests de `OpeningConfirmationNeedsConfirmationTests`
  échouaient avant l'ajout de `needs_confirmation`/`opening_team` (champs absents de la réponse,
  `KeyError`) et passent après.
- **Impact API** : changement **additif** (aucun champ retiré/renommé) sur
  `GET /api/production/opening-confirmation/` : `opening_team` et `needs_confirmation` en plus.
  Ticket lié ouvert pour `dev-frontend` : **BUG-140** (remplacer
  `!teams.A.confirmed || !teams.B.confirmed` côté frontend par la lecture directe de
  `needs_confirmation`).
- **Ambiguïté résiduelle signalée** (non centrale, non tranchée ici) : `needs_confirmation` est
  recalculé « à la volée » à chaque GET (pas mémorisé), cohérent avec le reste de la vue
  (`qty_proposed` est également recalculé à chaque appel) — à confirmer seulement si un cas réel
  différent se présente (ex. `active_team_at()` change de valeur en cours de journée pour un nœud
  qui se voit configurer des créneaux après qu'une équipe a déjà confirmé).

## Contrat API pour dev-frontend (BUG-140, ticket ouvert)

`GET /api/production/opening-confirmation/?node=<code, HQ seulement>&date=<AAAA-MM-JJ, défaut
aujourd'hui>` renvoie désormais :

```json
{
  "node": "K1",
  "date": "2026-11-09",
  "categories": [...],
  "teams": {
    "A": {"confirmed": true, "confirmed_at": "...", "confirmed_by": "...", "lines": [...]},
    "B": {"confirmed": false, "confirmed_at": null, "confirmed_by": null, "lines": null}
  },
  "opening_team": "A",          // "A" | "B" | null — nouveau
  "needs_confirmation": false   // booléen — nouveau, SEUL signal à utiliser pour la boîte modale
}
```

- `opening_team` : équipe du créneau d'ouverture selon `Node.active_team_at()` (BUG-130) ; `null`
  si le nœud n'a pas de créneaux horaires configurés.
- `needs_confirmation` : remplace le calcul frontend `!teams.A.confirmed || !teams.B.confirmed`.
  Désormais : si `opening_team` est connu, seule cette équipe doit avoir confirmé ; sinon (nœud non
  configuré), une confirmation de A OU B suffit.
- `POST /api/production/opening-confirmation/` : contrat inchangé (toujours `{"node"?, "team",
  "date"?, "lines": [...]}` → `{"detail", "node", "team", "date", "stock_adjustments"}`).
- Accès : FACTURIER autorisé désormais sur GET et POST (son propre nœud uniquement, comme GERANT).

Tâches frontend restantes (détaillées dans BUG-140) :
1. Monter `OpeningStockConfirmationModal` aussi pour `user.role === 'FACTURIER'` dans
   `DashboardLayout.tsx`.
2. Remplacer le calcul local de `needsConfirmation` par la lecture directe de
   `response.needs_confirmation`.
3. Vérifier l'ergonomie du sélecteur d'équipe de la boîte modale pour un FACTURIER (qui n'a qu'une
   équipe assignée, `user.team`).
4. Étendre les types TypeScript de la réponse (`src/api/services.ts`/`src/types/`).

## Tests exécutés

- `backend/.venv/Scripts/python.exe manage.py test production sales finance` → **204 tests, OK**.
- `backend/.venv/Scripts/python.exe manage.py test
  production.tests.test_daily_opening_confirmation
  production.tests.test_opening_confirmation_verification` → **42 tests, OK**.
- `backend/.venv/Scripts/python.exe manage.py makemigrations --check --dry-run` → aucune migration
  (correctif purement API, aucun changement de schéma).

## Registre

- BUG-138 : `OUVERT` → `CORRIGÉ` (volet backend). Volet frontend transféré en **BUG-140** (nouveau
  ticket, OUVERT, pour `dev-frontend`).
- BUG-139 : `À CLARIFIER` → `CORRIGÉ` (volet backend). Le registre note explicitement que le client
  a tranché directement le point avec le coordinateur (plus « À CLARIFIER »). Volet frontend
  transféré dans le même **BUG-140**.
- Ni BUG-138 ni BUG-139 ne sont passés à `VÉRIFIÉ` (CLAUDE.md §7 règle 3 : seul le testeur
  d'origine ou le coordinateur peut le faire).

## Fichiers modifiés (résumé)

- `backend/production/views.py`
- `backend/production/tests/test_daily_opening_confirmation.py`
- `backend/production/tests/test_opening_confirmation_verification.py`
- `docs/qa/REGISTRE_BUGS.md` (BUG-138, BUG-139 → CORRIGÉ ; nouveau BUG-140 pour dev-frontend)

## Risques / points d'attention pour la suite

- BUG-133, BUG-134, BUG-135, BUG-136 restent au statut `CORRIGÉ` (non `VÉRIFIÉ`) — leur
  vérification complète dépend maintenant aussi de BUG-140 côté frontend (CLAUDE.md, les tickets
  sont fonctionnellement liés selon la note de clôture de session testeur-production 2026-11-09).
- Aucune modification du modèle de données ni de `_build_daily_closure_report` : risque de
  régression jugé faible, confirmé par la suite complète `production` (204 tests) et le test de
  non-régression dédié.
