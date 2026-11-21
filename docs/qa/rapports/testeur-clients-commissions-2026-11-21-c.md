# Vérification croisée Dev C : BUG-511, BUG-412, BUG-413 (2026-11-21)

Verdicts : BUG-511 VÉRIFIÉ, BUG-412 VÉRIFIÉ, BUG-413 VÉRIFIÉ (testeur-clients-commissions, Dev C).

## BUG-511 (backend)
Tests : `backend/commissions/tests/test_verif_bug511_c.py` (11, verts) : mois/année non numériques (400), hors plage (vide ou 400, jamais 500), valeurs vides ignorées, sans filtre = tout, combinaison mois+année exacte, union des périodes = ensemble, isolation gérant (même avec `period__node` d'une autre boulangerie), `page_size` honoré avec `count` conservé et pages disjointes, requêtes SQL constantes selon la taille de page (après échauffement des caches) : pas de N+1.
Suites complètes `commissions` + `clients` : 216 tests, OK.

## BUG-412 et BUG-413 (frontend)
- `npx tsc --noEmit` : 0 erreur ; `npm run build` : OK.
- Filtre via `commissionsApi.periods.list` (services.ts), aucun axios direct, aucun nouveau `any` dans le diff.
- 413 : `getErrorDetail` gère `detail`, erreurs de champ DRF (`champ : message`), erreur réseau/Error (message) et repli.
- Remarque (non bloquante) : l'écran Commissions filtre encore via les périodes + filtre client par `period` ids ; il n'utilise pas `period__month/year` désormais disponibles (BUG-511). Fonctionnel, mais le filtre côté client sur pages de 100 reste en place.
- Le message de repli de Users.tsx mentionne toujours « nom d'utilisateur unique » quand l'API ne renvoie rien d'exploitable (comportement acceptable).

## Limite
412 et 413 n'ont PAS de contrôle navigateur (relecture + compilation seulement).
