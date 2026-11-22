# Rapport relecteur-code — 2026-11-22 (dev-c, état 2fcfa0e)

Relecture seule. `npx tsc --noEmit` : 0 erreur. `npm run build` : OK (avertissement connu : chunks > 500 kB). `any` ajoutés depuis main : 0 (seuls `step="any"` sur des inputs numériques).

- Appels HTTP : aucun axios direct dans les composants/pages découpés (seulement `axios.isAxiosError`). Tout passe par `services.ts`.
- BUG-385 et BUG-533 (découpage) : Production.tsx 544 l., Sales.tsx 646 l., Treasury.tsx 159 l. Ensembles d'appels `xxxApi.*` comparés à l'ancienne version (977aeb0^ et 5cdff28^) : aucun appel perdu. Pas de comparaison ligne à ligne des gros composants. VÉRIFIÉ.
- BUG-382 (DirectSendModal) : quantités entières >= 1, contrôle de stock, récapitulatif, anti double envoi. VÉRIFIÉ (volet backend à vérifier par testeur-production).
- BUG-383 (page Caisse, ClosureVersementReadOnly) : lecture seule, filtres, FC. VÉRIFIÉ.
- BUG-387 (vue consommables direction) : types sans `any`, quantités en chaînes décimales, envoi réservé ADMIN/DIRECTION. VÉRIFIÉ.

Remarques sans ticket : l'envoi de stock direction (GlobalConsumablesSection) n'a pas d'étape de confirmation alors qu'il est irréversible ; ClotureOperations.tsx (1342 l.) reste un candidat au découpage. Responsive vérifié par lecture du code seulement (pas de navigateur).
