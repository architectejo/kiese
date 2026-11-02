# Rapport dev-frontend — BUG-074 (2026-10-23)

## Résumé
BUG-074 (Majeur, frontend) corrigé : création d'un écran « Administration → Sauvegarde &
Restauration » qui consomme le pont Electron déjà exposé et testé côté `desktop/`
(`window.kiese.backup.list/createNow/restore`), sans modifier aucun fichier de `desktop/` ni
`backend/`.

## Fichiers créés
- `frontend/src/types/kiese.d.ts` — typage global de `window.kiese` (interface `KieseBridge`
  calquée sur `desktop/src/preload.ts`, `KieseBackupEntry`, `KieseBackupResult`).
- `frontend/src/components/admin/BackupManager.tsx` — composant listant les sauvegardes,
  déclenchant une sauvegarde immédiate, et restaurant une sauvegarde choisie avec confirmation
  explicite (action destructive). Dégrade proprement hors Electron.
- `frontend/src/pages/dashboard/Administration.tsx` — page fine qui monte `BackupManager`.

## Fichiers modifiés
- `frontend/src/api/client.ts` — suppression de la déclaration locale partielle de
  `window.kiese` (devenue redondante/conflictuelle avec `kiese.d.ts`) ; comportement runtime
  inchangé.
- `frontend/src/App.tsx` — route protégée `/admin/backups`.
- `frontend/src/components/layout/DashboardLayout.tsx` — entrée de navigation « Sauvegarde &
  Restauration », réservée aux rôles `ADMIN`/`DIRECTION` (même filtrage que Succursales,
  Personnel, Configuration).

## Vérifications effectuées
- `npx tsc --noEmit` : aucune erreur.
- `npm run build` : succès (le seul avertissement est le message pré-existant « chunk > 500 kB »
  de Vite, déjà présent avant cette modification — bundle unique de ~840 Ko non lié à cette
  correction).
- Aucun nouveau `any` introduit.
- Aucun appel HTTP direct ajouté (cette fonctionnalité passe uniquement par l'IPC Electron
  `window.kiese.backup.*`, pas par `src/api/services.ts`, puisqu'il ne s'agit pas d'un appel
  REST — cohérent avec le périmètre du pont desktop).
- Pas de test E2E existant pour ce parcours (`e2e/` ne contient aucun scénario
  backup/administration) : étapes de vérification manuelle détaillées dans la fiche BUG-074 du
  registre.

## Limite résiduelle (hors périmètre frontend, documentée dans le code et le registre)
Le marqueur `.last_pre_migration_backup` (`backend/desktop_server.py`) n'est pas exposé par
`window.kiese.backup.list()` côté Electron (`desktop/src/backup.ts`). L'écran mis en place met
donc en évidence la sauvegarde **la plus récente** (badge « Plus récente »), qui correspond au
cas pratique le plus fréquent juste après un échec de migration, mais sans garantie absolue
d'identité avec la sauvegarde pré-migration si une sauvegarde manuelle plus récente existe. Pour
une distinction fiable, il faudrait modifier `desktop/src/backup.ts` pour lire le marqueur et
l'exposer dans la réponse de `list()` (hors périmètre de cette tâche frontend — à ouvrir en
ticket séparé pour `dev-backend`/`packaging-desktop` si le client le demande).

## Statut du ticket
BUG-074 passé à **CORRIGÉ** dans `docs/qa/REGISTRE_BUGS.md` (fiche détaillée complétée). Non
passé à VÉRIFIÉ, conformément à CLAUDE.md §7 règle 3 — à valider par `packaging-desktop` (auteur
du ticket) ou le coordinateur.
