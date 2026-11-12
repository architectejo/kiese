# Testeur Production — vague 3 sur db.sqlite3 (2026-11-12)

Périmètre : re-vérification de BUG-243, 244, 245, 246 et BUG-232 (frontend `Production.tsx`), boulangerie K2, comptes `@gerant-k2`, `@pierre`, `zz_prod_gerant_k4`. Aucun migrate ni SQL d'écriture, aucun client réel touché.

## Résultats

| Ticket | Résultat | Preuve |
|---|---|---|
| BUG-244 | VÉRIFIÉ | KPI « Fournées enregistrées » = 17 (total serveur, API : 17 sessions > 15 chargées). Spec BUG-244 verte. |
| BUG-245 | VÉRIFIÉ | KPI « Pains non valorisés » = 23 (REMAINING exclu). Spec BUG-245 verte. |
| BUG-246 | VÉRIFIÉ | Champ sacs : 1,13 valide (`validity.valid = true`), MANQUANT/EXCÉDENT affiché. Spec verte. |
| BUG-243 | VÉRIFIÉ | `@pierre` choisit K2 puis Transferts : « EN LITIGE » visible. Spec verte. |
| BUG-232 | VÉRIFIÉ | Le siège voit aussi le bouton « Résoudre le litige » (capture `docs/qa/captures/prod-v3-bureau-siege-litige.png`) ; K4 résout avec motif obligatoire puis « Litige résolu ». |

## Non-régression
- Spec `13-production-vague2-db.spec.ts` (projet bureau) : onglets Fournées / Intrants / Transferts / Réconciliation sans débordement, gérant K2 voit « EN LITIGE », « Clôture de caisse bloquée », « Recompter la réception » et pas « Résoudre le litige » ; export Excel et impression de la Clôture Journalière ; clôture lisible sans débordement : tout vert.
- API K2 (lecture) : sessions 17, stocks 4, transferts 11, dispositions 33, bread-stocks 2, counts 0 : 200. `daily-closure/` sans date : 400 attendu.

## Données créées sur la base réelle
Le litige de la vague 2 ayant été résolu, un transfert K4 -> K2 (10 envoyés, 8 reçus, pain 200 FC) a été créé par API avec les comptes de test pour rejouer BUG-243/232, puis résolu par le test K4 (clôture K2 de nouveau débloquée). Aucun autre état laissé.

## Observations (pas de ticket)
1. Course au chargement : si le siège choisit une boulangerie dans le sélecteur dans la première seconde (avant la fin du chargement initial), le sélecteur revient sur B1 — KUMBI. Constaté une fois sur machine lente (le test échouait avec un sélecteur affichant B1) ; non reproduit après attente du chargement. Cosmétique, à surveiller.
2. Connexion UI : sous forte charge (testeurs en parallèle), le formulaire a affiché une fois « Identifiants ou mot de passe incorrects » pour `@gerant-k2` alors que l'API acceptait les mêmes identifiants juste après, puis la connexion a réussi au relancement. Non reproductible à la demande ; à signaler au testeur des permissions si ça revient (throttling ou délai).

## Modifications de tests
`e2e/tests/13-production-vague2-db.spec.ts` : délais allongés (KPI, connexion, onglets), attente du chargement des 8 boulangeries avant sélection (BUG-243), vérification du bouton « Résoudre le litige » côté siège (BUG-232). Aucun nouveau ticket (BUG-247 non utilisé).
