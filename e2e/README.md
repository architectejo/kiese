# E2E — ETS. KIESE (Playwright)

Parcours Playwright contre le serveur de dev réel (`backend/db.sqlite3` partagé
avec les autres agents de la session — voir `docs/qa/PLAN_2026-10-22.md` §0.1).

## Préalables

1. Backend (depuis `backend/`, `.venv` déjà configuré) :
   ```bash
   .venv/Scripts/python.exe manage.py migrate
   .venv/Scripts/python.exe manage.py seed_kiese   # si la base est vide
   .venv/Scripts/python.exe manage.py runserver 8000
   ```
2. Frontend (depuis `frontend/`) :
   ```bash
   npm run dev   # http://localhost:5173, VITE_API_URL=http://localhost:8000
   ```
3. Comptes de démonstration dédiés aux tests E2E (rôles non couverts par
   `seed_kiese` : COMPTABLE, second nœud K2) — à recréer si absents de la base,
   via `manage.py shell` (données fictives, préfixe `demo_*_e2e`, mot de passe
   `DemoE2E2026!`) :
   ```python
   from django.contrib.auth import get_user_model
   from core.models import Node
   User = get_user_model()
   K1, K2 = Node.objects.get(code="K1"), Node.objects.get(code="K2")
   comptes = [
       ("demo_admin_e2e", "ADMIN", None, ""),
       ("demo_direction_e2e", "DIRECTION", None, ""),
       ("demo_comptable_e2e", "COMPTABLE", K1, ""),
       ("demo_gerant_k1_e2e", "GERANT", K1, ""),
       ("demo_gerant_k2_e2e", "GERANT", K2, ""),
       ("demo_facturier_k1_e2e", "FACTURIER", K1, "A"),
       ("demo_facturier_k2_e2e", "FACTURIER", K2, "A"),
       ("demo_livreur_k1_e2e", "LIVREUR", K1, "A"),
   ]
   for uname, role, node, team in comptes:
       u, _ = User.objects.get_or_create(username=uname, defaults={"role": role, "node": node, "team": team})
       u.set_password("DemoE2E2026!"); u.is_active = True; u.save()
   ```
4. Trois clients fictifs pré-seedés attendus par les tests (recréer/réinitialiser si
   absents ou si leur dette a dérivé d'une exécution précédente — `current_debt` doit
   être réinitialisé à chaque session, un remboursement réel le modifie durablement) :
   - `clients.models.Client` K1, nom "DEMO CrossNodeE2E" (recherche cross-nœud par le facturier K2).
   - `clients.models.Client` K1, nom "DEMO PlafondE2E", `credit_limit=current_debt=50000`
     (blocage plafond — **ne jamais** utiliser ce client pour un remboursement).
   - `clients.models.Client` K1, nom "DEMO RemboursementE2E", `credit_limit=50000`,
     `current_debt=20000` (dédié au test de remboursement, distinct du précédent).

## Lancer la suite

```bash
cd e2e
npm ci
npx playwright test               # toutes tailles d'écran (pos/tablette/bureau/tv)
npx playwright test --project=pos --project=bureau   # les deux tailles critiques
npx playwright show-report
```

Chromium est déjà en cache local (`~/AppData/Local/ms-playwright` sous Windows,
`/opt/pw-browsers` en environnement cloud) : **ne jamais lancer `playwright install`**.

## Limitation du débit de connexion (BUG-006)

Le endpoint `/api/core/auth/login/` est volontairement limité à 5 connexions/minute
par défaut (`DJANGO_LOGIN_THROTTLE_RATE`, voir `backend/kiese/settings.py` et
`docs/qa/REGISTRE_BUGS.md#BUG-006`). La suite E2E complète enchaîne largement plus de
5 connexions/déconnexions en moins d'une minute (un identifiant/mot de passe par test de
`02-connexion-roles.spec.ts`, plus un identifiant par parcours dans les autres fichiers) :
il est normal d'observer, de temps en temps, un test de connexion échouer avec une
redirection vers `/login` sans message d'erreur explicite si le quota est atteint — ce
n'est **pas** un bug applicatif, c'est la protection BUG-006 qui fonctionne comme prévu.
Pour une exécution fiable de la suite complète, démarrer le backend avec un taux plus
généreux réservé à l'environnement de test :

```bash
DJANGO_LOGIN_THROTTLE_RATE=100/min .venv/Scripts/python.exe manage.py runserver 8000
```

## Règles

- Ne jamais modifier le code applicatif (`frontend/src`, `backend/`) depuis ce
  dossier. Toute anomalie réelle découverte est documentée dans
  `docs/qa/REGISTRE_BUGS.md` (ticket `BUG-NNN`) et le test correspondant est
  marqué `test.fixme(...)` avec un commentaire renvoyant au ticket.
- `Config.on_line` est un singleton global partagé par toute la base de dev :
  `tests/01-vitrine.spec.ts` restaure systématiquement l'état lu au départ.
- Captures d'écran, traces et vidéos des échecs : `docs/qa/captures/e2e-results/`
  et `e2e/playwright-report/` (configuré dans `playwright.config.ts`).
