# Rapport — dev-frontend — 2026-11-02 — Volet frontend BUG-119

## Mission

Consommer côté frontend le contrat d'API déjà livré par `ingenieur-blockchain`
(`POST/GET /api/treasury/direction-cash-counts/`) pour le comptage physique de
billets du Livre de Caisse Direction (Niveau 3, CLAUDE.md §5.5), sans modifier
le backend. Le ticket BUG-119 reste au statut global `CORRIGÉ` (en attente de
vérification groupée finale par le testeur d'origine) — seule une note de
volet frontend a été ajoutée à la fiche.

## Vérification préalable du contrat d'API (pas de supposition)

Lu directement avant de coder :
- `backend/treasury/serializers.py::DirectionCashCountSerializer` (champs
  exacts : `id, date, counted_by, counted_by_display, bills_20000..bills_50,
  physical_cash_total, reference_entry, theoretical_balance, cash_gap, notes,
  created_at` ; champs serveur `read_only_fields`).
- `backend/treasury/views.py::DirectionCashCountViewSet` : `IsHeadquarters`
  uniquement, `mixins.CreateModelMixin + ListModelMixin + RetrieveModelMixin`
  (pas de `update`/`destroy`), route `/api/treasury/direction-cash-counts/`
  (`backend/treasury/urls.py`), `filterset_fields = ['date']`.
- `backend/treasury/models.py::DirectionCashCount` : `cash_gap =
  physical_cash_total - theoretical_balance`, `theoretical_balance` figé au
  moment du comptage.

## Fichiers modifiés

1. `frontend/src/api/services.ts`
   - Nouveau type `DirectionCashCount` (aucun `any`).
   - `treasuryApi.directionCashCounts.list()` / `.create()`.
2. `frontend/src/pages/dashboard/Treasury.tsx`
   - Nouvelle sous-section « Comptage Physique de Caisse — Direction » dans
     la carte §5.1.3 (Livre de Caisse Direction), gardée par
     `user?.can_access_all_nodes` (même garde que le reste de la carte,
     IsHeadquarters côté API depuis BUG-026/BUG-044).
   - Formulaire de billetage réutilisant la constante module `BILLS` déjà
     définie en tête de fichier (8 dénominations, même motif visuel que le
     formulaire de Bordereau de Versement existant juste au-dessus dans la
     même page).
   - Historique des comptages (liste filtrée sur `dateFrom`/`dateTo`, mêmes
     bornes que le reste de la carte) avec écart coloré : vert si
     `cash_gap === 0`, rouge sinon (+ libellé « excédent »/« manquant »),
     même convention que l'écart physique/théorique déjà affiché pour
     `CashClosure` (§5.2) ailleurs dans cette page.
   - États gérés : chargement, liste vide, erreur serveur (`detail` affiché
     tel que renvoyé par l'API, jamais inventé côté client).
   - Montants formatés via la fonction `fmt()` déjà présente dans le fichier
     (`12 500 FC`).
3. `docs/qa/REGISTRE_BUGS.md` — note « Volet frontend — dev-frontend,
   2026-11-02 » ajoutée à la fiche BUG-119 (statut global laissé à
   `CORRIGÉ`, non modifié).

Aucun autre fichier touché : ni la section §5.1.1 de `Treasury.tsx`, ni les
autres onglets de la page, ni aucun fichier backend.

## Pas d'extraction en composant

Pas de nouveau composant créé dans `frontend/src/components/treasury/` : la
sous-section ajoutée est petite (un formulaire inline + une liste) et
réutilise entièrement l'état et les motifs déjà en place dans `Treasury.tsx`
(même approche non extraite déjà utilisée pour la sous-section Bordereaux de
Versement, structurellement identique). Aucun composant de billetage partagé
n'existait avant ce ticket à réutiliser tel quel.

## Vérifications effectuées

- `cd frontend && npx tsc --noEmit` → OK, aucune erreur.
- `cd frontend && npm run build` → build OK. Seul avertissement : taille du
  chunk `index-legacy` > 500 kB — préexistant, sans lien avec ce ticket.
- Aucun test E2E Playwright existant pour ce parcours (le Livre de Caisse
  Direction n'est couvert par aucun fichier dans `e2e/`) : étapes de
  vérification manuelle documentées dans la fiche BUG-119 du registre pour
  le testeur (connexion HQ, création d'un comptage, doublon de date → 400,
  masquage pour rôles non-HQ, rendu 360 px).

## Points pour le coordinateur / testeur

- Aucune contradiction entre documents de référence rencontrée.
- Le statut global de BUG-119 reste `CORRIGÉ` : seul le testeur d'origine
  (ou le coordinateur) peut le faire passer à `VÉRIFIÉ`, conformément à
  CLAUDE.md §7.
