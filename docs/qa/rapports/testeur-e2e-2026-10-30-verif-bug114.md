# Vérification BUG-114 — testeur-e2e — 2026-10-30

## Objet

Vérification du correctif `dev-backend` apporté au ticket **BUG-114** (`JournalEntryViewSet` :
année hors bornes non validée côté serveur → `500` au lieu de `400`), ouvert par ce même agent le
2026-10-30 lors d'une découverte incidente (voir fiche détaillée dans `docs/qa/REGISTRE_BUGS.md`).

## Correctif revu

- `backend/treasury/views.py` : nouvelle fonction module-level `_validate_month_year(month, year)`
  (année 2000-2100, mois 1-12), appelée dans `JournalEntryViewSet.get_queryset()` (juste après le
  filtrage par nœud BUG-113, avant les `qs.filter(date__month=...)`/`date__year=...)`) et dans
  `.monthly_report()` (juste après la lecture de `month`/`year`, avant le filtrage par nœud
  BUG-113). Renvoie `400 {"detail": "..."}` en français au lieu de laisser la `ValueError` de
  `year_lookup_bounds_for_date_field` remonter en `500`.
- `frontend/src/pages/dashboard/Treasury.tsx` : `onChange` du champ `journalYear` clampe désormais
  la saisie entre les bornes déjà affichées sur l'`<input min={2024} max={2035}>` —
  `Math.min(2035, Math.max(2024, Number(e.target.value) || 2024))`.
- Nouveau fichier de test : `backend/treasury/tests/test_bug114_journal_year_validation.py` (8
  scénarios : année/mois hors bornes et non entiers sur les deux endpoints → `400` ; valeurs
  plausibles → `200`, non-régression explicite de BUG-113).

## Vérifications effectuées

1. **Relecture de code** des 2 fichiers applicatifs + du nouveau fichier de test : conformes à la
   description ci-dessus et à la fiche du registre, rien à redire.
2. **Reproduction en direct** (serveur de dev réel sur le port 8001, pas seulement l'`APIClient`
   des tests unitaires) : un compte de démonstration (`demo_gerant_k1_e2e`) a reçu un mot de passe
   temporaire pour obtenir un jeton JWT, immédiatement remis à `set_unusable_password()` après le
   test (aucune donnée applicative modifiée) :
   - `GET /api/treasury/journal/?month=10&year=20000` → `HTTP 400`,
     `{"detail":"Le paramètre 'year' doit être compris entre 2000 et 2100."}`
   - `GET /api/treasury/journal/monthly_report/?month=10&year=20000` → même `HTTP 400`.
   - Plus aucune trace de `500`/`ValueError` sur les deux scénarios exacts de la découverte
     originale.
3. **Non-régression BUG-113** (isolation par nœud) : relecture confirmée — le filtrage qui ignore
   tout `?node=` forgé par un utilisateur non-HQ et impose `user.node` est strictement inchangé
   dans `get_queryset()`/`monthly_report()` ; le correctif n'ajoute que l'appel à
   `_validate_month_year()` à l'endroit indiqué, sans toucher aux lignes BUG-113 adjacentes.
4. **Volet E2E** : `e2e/tests/10-regression-remarque-2026-10-30.spec.ts` ne cible plus le champ
   Année (le sélecteur avait déjà été corrigé côté test lors de la découverte initiale — c'est
   précisément cette correction de sélecteur qui avait révélé le défaut) ; il n'existe donc pas de
   scénario E2E dédié reproduisant `year=20000` depuis l'UI à rejouer. Vérification faite par
   lecture de code à la place : le clamp `onChange` est bien présent et ramène toute saisie/collage
   hors plage dans `[2024, 2035]` avant tout appel réseau — aucun `year` hors bornes ne peut plus
   atteindre l'API depuis ce champ. Défense en profondeur côté UX uniquement ; le serveur reste la
   garantie réelle (vérifiée au point 2).
5. `cd frontend && npx tsc --noEmit` → aucune erreur.
6. `cd frontend && npm run build` → succès (`tsc && vite build`), seul avertissement pré-existant
   sur la taille du chunk legacy (`polyfills-legacy`/`index-legacy`), sans rapport avec ce ticket.
7. `python manage.py test treasury` → **83 tests, OK**, 0 échec.
8. `python manage.py test` (suite complète) → **399 tests, OK**, 0 échec — confirme exactement le
   chiffre annoncé par dev-backend.
9. `python manage.py makemigrations --check --dry-run` → « No changes detected » (aucune migration
   manquante, cohérent avec un correctif purement applicatif sans changement de schéma).
10. `PRAGMA integrity_check` sur `backend/db.sqlite3` (pas `data_kiese/`) → `ok`.

## Conclusion

Correctif conforme à la fiche, aucune régression détectée (BUG-113 en particulier). Ticket
**BUG-114 passé à VÉRIFIÉ** dans `docs/qa/REGISTRE_BUGS.md` (table récapitulative + fiche détaillée).

## Nettoyage

- Serveur de développement temporaire (port 8001, lancé pour la reproduction en direct) arrêté
  (`taskkill`) avant de rendre la main.
- Mot de passe temporaire du compte `demo_gerant_k1_e2e` retiré (`set_unusable_password()`).
- Aucun fichier applicatif modifié par ce testeur — seuls `docs/qa/REGISTRE_BUGS.md` et ce rapport
  ont été touchés.
