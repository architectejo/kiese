# dev-frontend — 2026-11-10 — BUG-150 : bouton Superuser « Réinitialiser les données »

## Contexte

Ticket ouvert par `dev-backend` (BUG-149, `CORRIGÉ`) pour consommer le nouvel endpoint
`GET/POST /api/core/reset-data/` depuis le frontend, sans toucher au backend. Contrat lu en
entier dans `docs/qa/rapports/dev-backend-2026-11-10-bug149-reset-superuser.md` avant de
commencer.

## Ce qui a été fait

### 1. `frontend/src/api/services.ts`

- Nouveau type `ResetDataCounts` : toutes les clés exactes du contrat documenté par
  `dev-backend` (`invoices`, `production_sessions`, `cashbook_entries`, `clients_to_reset`, etc.),
  aucun `any`.
- `coreApi.resetData.preview()` → `GET /api/core/reset-data/`.
- `coreApi.resetData.execute({ confirm_phrase, password })` → `POST /api/core/reset-data/`.
- Seul point d'appel HTTP pour ce nouvel endpoint, conformément à CLAUDE.md §4.

### 2. `frontend/src/components/settings/ResetDataModal.tsx` (nouveau composant)

Nouveau fichier plutôt qu'ajout direct dans `Settings.tsx` (1106 lignes avant modification,
> ~1000 lignes → extraction obligatoire, CLAUDE.md §4). Flux en plusieurs étapes
(`loading` → `confirm`/`submitting`/`submit-error` → `success`, ou `preview-error`) :

1. À l'ouverture, appelle `GET` pour afficher un aperçu en lecture seule — tableau des
   catégories non nulles (libellés français, ex. « Factures », « Sessions de production »,
   « Écritures du livre de caisse ») avec décompte et total, avant tout champ de confirmation.
   Rappelle explicitement ce qui est conservé (Config/boulangeries/utilisateurs/clients) et
   précise le nombre de fiches clients dont les champs dérivés seront remis à zéro
   (`clients_to_reset`), sans confondre avec une suppression.
2. Double confirmation : champ texte devant correspondre EXACTEMENT à `SUPPRIMER TOUT`
   (comparaison stricte, re-vérifiée côté serveur de toute façon) + champ mot de passe
   (`type="password"`).
3. Bouton rouge (`hsl(var(--color-danger))`) « Supprimer définitivement », désactivé tant que la
   phrase ou le mot de passe manquent, et pendant l'envoi (empêche tout double clic/double-frappe
   de déclencher deux requêtes).
4. Pendant l'envoi, fermeture de la boîte désactivée (Échap, clic sur le fond, bouton croix) —
   `Modal` reçoit `closeOnBackdropClick={false}` / `showCloseButton={false}` / `onClose={() => {}}`
   tant que `step === 'submitting'`.
5. Succès → décompte de ce qui a été réellement supprimé, la boîte reste ouverte jusqu'au clic
   explicite sur « Fermer » (pas de fermeture automatique, conformément à la consigne).
6. Échec (phrase/mot de passe incorrect, 400) → message `detail` de l'API affiché clairement,
   boîte NON fermée, champs toujours modifiables pour corriger et réessayer.
7. `Modal` existant réutilisé (portail sous `document.body`, `maxHeight: 90vh` +
   `overflowY: auto` sur le corps) → la boîte reste visible sans défilement de la PAGE, seul le
   tableau interne des catégories défile si long (`maxHeight: 260px`), conformément au problème
   signalé par le client sur les modales.

### 3. `frontend/src/pages/dashboard/Settings.tsx`

- Import du nouveau composant + état local `showResetModal`.
- Nouvelle section « Zone dangereuse — Superuser » (bordure rouge, icône `FiShield`) affichée
  uniquement si `user?.is_superuser === true` (champ déjà présent dans `UserProfile`,
  `frontend/src/store/authStore.ts` — aucun ajout de type nécessaire, déjà exposé par
  `/api/core/auth/me/` côté backend).
- Bouton rouge « Réinitialiser les données » qui ouvre `ResetDataModal`.

## Vérifications

- `npx tsc --noEmit` (`frontend/`) : aucune erreur.
- `npm run build` : succès, `vite build` (117 modules transformés). Aucun nouvel avertissement
  par rapport à l'état précédent du dépôt (seuls les avertissements préexistants, sans rapport
  avec ce ticket, subsistent : minifier `oxc` non supporté pour les chunks legacy, taille de
  chunk > 500 kB).
- Vérification manuelle du contrat réel, **GET uniquement** (jamais de `POST` destructeur contre
  `backend/db.sqlite3`, conformément à la consigne) : requête faite via `django.test.Client`
  forcé (`force_login`) sur un compte réel `is_superuser=True`, avec
  `override_settings(ALLOWED_HOSTS=['*'])` pour contourner uniquement la vérification d'hôte du
  client de test Django (aucun réglage d'application modifié, aucune donnée altérée — `GET` est
  en lecture seule par construction côté backend) :
  ```
  GET /api/core/reset-data/ → 200
  {'sync_conflict_logs': 0, 'sync_batch_logs': 0, 'debt_movements': 5, 'tamper_alerts': 0,
   'blockchain_snapshots': 0, 'client_commissions': 0, 'commission_periods': 0,
   'financial_years': 0, 'direction_cash_counts': 0, 'cashbook_entries': 0, 'journal_entries': 0,
   'daily_savings': 0, 'disbursement_vouchers': 0, 'cash_closures': 0, 'facturier_reports': 0,
   'local_expenses': 0, 'consumable_movements': 4, 'consumable_stocks': 4, 'consumable_counts': 0,
   'bread_disposals': 3, 'production_session_lines': 7, 'production_sessions': 1,
   'bread_transfer_lines': 0, 'bread_transfers': 0, 'bread_stocks': 4,
   'daily_opening_confirmation_lines': 4, 'daily_opening_confirmations': 1,
   'daily_bread_stock_snapshots': 0, 'invoice_lines': 11, 'invoices': 5,
   'social_distribution_lines': 0, 'social_distributions': 0, 'social_contributions': 0,
   'colis_distributions': 0, 'activity_logs': 65, 'system_notifications': 12,
   'clients_to_reset': 4}
  ```
  Toutes les clés correspondent exactement au type `ResetDataCounts` ajouté dans
  `services.ts` — aucune divergence entre le contrat documenté et la réponse réelle de
  l'API en cours d'exécution.
- Aucun test E2E existant pour ce parcours (`e2e/tests/` ne contient aucun fichier dédié à
  Configuration/Superuser) — étapes de vérification manuelle détaillées dans la fiche
  `docs/qa/REGISTRE_BUGS.md` (BUG-150) pour le testeur.
- Aucun fichier backend ouvert ni modifié (BUG-149 déjà clos par `dev-backend`).

## Registre

- `BUG-150` passé de `OUVERT` à `CORRIGÉ` dans `docs/qa/REGISTRE_BUGS.md` (ligne de synthèse +
  fiche détaillée complétée sous la fiche BUG-149 existante, pas de nouvelle fiche créée).
- Pas de passage à `VÉRIFIÉ` (CLAUDE.md §7 règle 3 — réservé au testeur d'origine ou au
  coordinateur).

## Fichiers modifiés/créés

- `frontend/src/api/services.ts` (type `ResetDataCounts`, `coreApi.resetData`).
- `frontend/src/components/settings/ResetDataModal.tsx` (nouveau).
- `frontend/src/pages/dashboard/Settings.tsx` (bouton + section « Zone dangereuse », état local,
  import du composant).
- `docs/qa/REGISTRE_BUGS.md` (BUG-150 → `CORRIGÉ`).
