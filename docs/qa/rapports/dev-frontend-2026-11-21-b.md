# Rapport dev-frontend (dev B) — 2026-11-21

BUG-400, volet frontend : CORRIGÉ (à vérifier par testeur-clients-commissions).

Fichiers : frontend/src/api/services.ts (types ClientHistory, clientsApi.history),
frontend/src/components/clients/ClientHistoryModal.tsx (nouveau),
frontend/src/pages/dashboard/Commissions.tsx (clic client + tri alphabétique + modale),
frontend/src/pages/dashboard/Clients.tsx (clic nom + modale), docs/qa/REGISTRE_BUGS.md (fiche BUG-400).

Résultat : npm ci, npx tsc --noEmit sans erreur, npm run build OK (seul avertissement existant : taille de chunk).
Aucun test frontend automatisé (pas d'infra), pas d'E2E ; procédure manuelle dans la fiche BUG-400.
Non vérifié en navigateur ni à 360 px (pas de backend lancé).
