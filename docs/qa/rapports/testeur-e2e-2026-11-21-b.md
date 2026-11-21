# Rapport testeur-e2e (dev B) — 2026-11-21 — tâche B-5 (BUG-148)

## Environnement
- Base jetable hors dépôt (`DB_NAME=%TEMP%\b148\e2e.sqlite3`), `migrate`, `seed_kiese`, puis `fixtures/seed/setup1,2,6-9,11,12,15-20`.
  Les scripts API (`seed4/10/13/14`, `fix5`) n'ont pas été rejoués : ils supposent des clients importés (K1-0085, K4-096x, ZZTEST).
- Comptes confirmés dans `setup1.py` : `zz_demo_comptable` (COMPTABLE K1), `zz_demo_direction` (DIRECTION), mot de passe = identifiant.
- Backend `runserver 8000 --noreload` (throttle login 1000/min), frontend `npm run dev` 5173. Serveurs arrêtés en fin de session.
- Navigateur : le headless-shell de `ms-playwright` (1243) est bloqué par l'antivirus du poste ("contient un virus") et `npm ci`
  installe Playwright 1.64 (attend le build 1248) ; contournement : config temporaire `pw.local.config.ts` pointant sur
  `chromium-1243\chrome-win64\chrome.exe` (supprimée après usage, vidéos coupées). `playwright install` non lancé.

## BUG-148 — diagnostic
La modale « Stock de départ » n'est plus la cause (handler « Plus tard » dans `seConnecter`). Causes réelles, côté test :
1. Non idempotent : une fournée par équipe et par jour ; au rejeu, « Fournée en cours » remplace le formulaire
   (12 échecs sur 20 en `--repeat-each=10`, 16 min).
2. Course au chargement : `BatchInProgressPanel` affiche « Déclaration de Fournée » avant la fin du chargement puis bascule
   (échec `getByLabel(Nombre de sacs de farine)` à 30 s en bureau dès la 1re exécution).
3. Démarrage à froid de Vite : login à 16 s > 15 s (pos, 1re exécution).

## Correctif (test uniquement)
- `e2e/tests/05-production.spec.ts` (plage 01-27, minimal) : attente de `GET /api/production/sessions/?date=` + `networkidle`,
  déclaration seulement si « Fournée en cours » absent, assertion finale commune.
- `e2e/fixtures/helpers.ts` : délai post-login 15 s → 30 s (fichier partagé, 1 ligne).
- Preuve : `--project=pos --project=bureau --repeat-each=10` → **20 passés / 0 échec / 20 fixme ignorés, 6 min** (4/4 bureau avant).
- Registre : BUG-148 → CORRIGÉ (à vérifier par testeur-production/coordinateur).

## Parcours de mes pages (pos 360 px et bureau 1440 px)
Commande : `playwright test 32 31 01 03 25 --project=pos --project=bureau` → 44 passés, 2 échecs, 14 non exécutés (7 min 51).

| Spec | pos | bureau | Note |
|---|---|---|---|
| 01-vitrine (Settings, bascule on_line) | vert | vert | |
| 03-clients (3 tests) | vert | vert | création, photo, cross-nœud |
| 31-verif-bug407-dev-b (16 cas x2, comptable/direction) | vert | vert | premier run de ce spec : aucun correctif nécessaire |
| 32-clients-pos-dev-b (nouveau, lecture seule) | vert | vert | liste, recherche, fiche, historique |
| 25-bug301 (1a) | rouge | rouge | données : client K1 d'exemple absent de la base jetable ; (1b)-(4) non exécutés (serial) |
| 04-facturation | 2 verts / 5 rouges (pos) | non rejoué | client `K1-0045` absent de la base jetable (capture : champ client vide) |
| 10-regression, 14, 16 | partiel / rouge | non rejoué | exigent clients ZZTEST/K3-K4 importés |

Aucun échec n'est imputable au découpage de `Clients.tsx` / `Settings.tsx` (commit 2d46389) : les rouges sont des clients
d'exemple manquants (seed API non rejoué), non vérifiables sans la base de test complète. Les parcours Clients 03 et 32
(liste, recherche, fiche, historique, création avec photo) et Settings (01, 31) passent aux deux largeurs.
À rejouer 14/16/25-(3a) sur la base de test complète pour clore le contrôle du découpage.

## Fichiers
- Modifiés : `e2e/tests/05-production.spec.ts`, `e2e/fixtures/helpers.ts`, `docs/qa/REGISTRE_BUGS.md` (fiche + ligne BUG-148).
- Créé : `e2e/tests/32-clients-pos-dev-b.spec.ts` (demande de C, message #11).
- Nettoyés : `e2e/test-results`, `docs/qa/captures/e2e-results`, `e2e/pw.local.config.ts`, captures b301 restaurées (le spec 25 les réécrit).
