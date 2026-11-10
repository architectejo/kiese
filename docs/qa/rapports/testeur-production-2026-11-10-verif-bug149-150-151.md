# testeur-production — 2026-11-10 — Vérification BUG-149 / BUG-150 / BUG-151

## Mission

Vérifier trois tickets `CORRIGÉ` (jamais `VÉRIFIÉ`), au statut `CORRIGÉ` par `dev-backend`/
`dev-frontend` :
- **BUG-149** (backend) : endpoint `GET/POST /api/core/reset-data/`, réservé au flag technique
  `request.user.is_superuser`, suppression globale des données transactionnelles.
- **BUG-150** (frontend) : bouton + boîte modale « Réinitialiser les données » (écran
  Configuration) consommant cet endpoint.
- **BUG-151** (frontend, sujet distinct) : zone manuelle « Confirmer le reste d'hier d'une autre
  équipe » dans « Production & Stocks ».

## BUG-149 — vérifié

Relecture complète de `backend/core/reset.py`, `backend/core/permissions.py::IsSuperuser`,
`backend/core/views.py::reset_data_view`, `backend/core/urls.py`.

Points de conception confirmés corrects :
- `IsSuperuser` exige strictement `request.user.is_superuser` (flag technique Django) — un rôle
  métier `ADMIN`/`DIRECTION` sans ce flag est bien refusé (403), contrairement à
  `IsAdmin`/`IsDirection`/`IsHeadquarters` qui acceptent l'un ou l'autre.
- `GET` est en lecture seule (`preview_counts()`, aucune écriture). `POST` exige
  `confirm_phrase == "SUPPRIMER TOUT"` (strict, après `.strip()`) et `password` revérifié via
  `user.check_password(...)` (jamais le JWT seul) ; tout refus renvoie `400` sans rien supprimer.
  Toute la suppression a lieu dans un seul `transaction.atomic()`.
- Liste conservée : `Config`, `Node`, `User`, `BreadPrice`, `ExpenseCategory`, `Client` (fiche,
  champs dérivés `current_debt`/`total_breads_received`/`category` remis à zéro/`NORMAL` via
  `.update(...)` en masse), `ClientCodeSequence`, `sync.NodeAuthToken`.
- Liste supprimée : `sales.Invoice/InvoiceLine`, tout `production.*` transactionnel, tout
  `treasury.*`, `commissions.*`, `finance.FinancialYear`, `blockchain.*`,
  `clients.SocialContribution/SocialDistribution/SocialDistributionLine`, `core.ActivityLog`,
  `core.SystemNotification`, `core.ColisDistribution`, `sync.DebtMovement/SyncBatchLog/
  SyncConflictLog`. Ordre de suppression respecte les contraintes `PROTECT` existantes
  (`Invoice.adjusts` cassé par `update(adjusts=None)` avant suppression des factures ;
  `ConsumableMovement` avant `ConsumableStock`).

### Vérification indépendante (au-delà de la suite `test_bug149_reset_superuser.py` de dev-backend)

J'ai construit mon propre scénario bout-en-bout dans un fichier de test TEMPORAIRE
(`backend/core/tests/test_verif_bug149_extra_TEMP.py`, supprimé après exécution — jamais livré,
n'apparaît pas dans `git status`), couvrant des catégories NON exercées par le scénario de
dev-backend : `CashClosure`, `JournalEntry`, `DailySavings`, `DisbursementVoucher`,
`FinancialYear`, `TamperAlert`, `BlockchainSnapshot`, `SocialContribution`, en plus d'un
`DebtMovement` et d'un `Client` avec dette/pains livrés/catégorie non nuls.

Résultats (13/13 tests OK, ma suite temporaire + la suite officielle de dev-backend exécutées
ensemble) :
- Après un `POST` réussi (phrase + mot de passe corrects) : toutes les catégories ci-dessus ont
  disparu, `Client.current_debt` est à `0.00`.
- **Point explicitement demandé par la mission** : un appel direct, après le reset, à
  `sync.services.recompute_client_debt(client.pk)` sur le client conservé **ne ressuscite PAS**
  l'ancienne dette — `current_debt` reste `0.00` après l'appel, confirmant que la purge de
  `DebtMovement` (dans la même transaction que les factures) empêche bien tout recalcul ultérieur
  de reconstituer silencieusement l'ancienne dette.
- Après un `POST` à mot de passe incorrect : aucune des catégories testées (`CashClosure`,
  `FinancialYear`, `TamperAlert`, `SocialContribution`...) n'a bougé — vérifié explicitement
  avant/après, pas seulement via le code HTTP `400`.
- Permission stricte reconfirmée : `DIRECTION`/`ADMIN` sans `is_superuser` → 403 sur GET et POST ;
  anonyme → 401/403 ; superuser réel → 200 sur GET.

Aucun `POST` réel n'a jamais été exécuté contre `backend/db.sqlite3` — exclusivement
`manage.py test` (base éphémère en mémoire), conformément à la consigne explicite de la mission.

### Frontend (BUG-150) — vérifié par lecture de code

`frontend/src/components/settings/ResetDataModal.tsx` et
`frontend/src/pages/dashboard/Settings.tsx` :
- Bouton « Supprimer définitivement » confirmé désactivé tant que
  `confirmText !== 'SUPPRIMER TOUT'` OU `password` vide OU `step === 'submitting'`
  (`disabled={!confirmMatches || !password || step === 'submitting'}`).
- Aucune fermeture automatique après succès : `step === 'success'` affiche le décompte réel et
  attend un clic explicite sur « Fermer » ; aucun `setTimeout`/effet qui appellerait `onClose`
  automatiquement. Pendant `step === 'submitting'`, `Modal` reçoit `closeOnBackdropClick={false}`
  et `onClose={() => {}}` — aucune fermeture accidentelle pendant l'envoi.
- Zone « Zone dangereuse — Superuser » (bouton + boîte) affichée uniquement si
  `user?.is_superuser === true` dans `Settings.tsx` — champ bien exposé par `UserSerializer`
  (`backend/core/serializers.py`) et typé dans `authStore.ts`/`UserProfile`.
- `npm run build` (frontend/) → succès (`tsc && vite build`, exit 0, 117 modules, mêmes
  avertissements préexistants que l'état antérieur du dépôt — taille de chunk/minifier `oxc`,
  sans rapport avec ce ticket).

### Suite complète backend

`backend/.venv/Scripts/python.exe manage.py test` (suite COMPLÈTE) → **`Ran 599 tests in
1544.213s — OK`**, aucune régression sur les autres modules. Aucun processus `runserver`/
`manage.py test` laissé actif par moi à la fin de la session (le processus de test lancé pour
cette vérification s'est terminé normalement).

**BUG-149 → `VÉRIFIÉ`. BUG-150 → `VÉRIFIÉ`.**

## BUG-151 — vérifié (par lecture de code + suite de tests backend existante)

Relecture complète de `OpeningStockConfirmationModal.tsx` (props `forceOpenForTeam`/
`onManualClose`), `openingConfirmationStore.ts`, `OpeningConfirmationManualSection.tsx`,
`DashboardLayout.tsx`, `Production.tsx`.

Confirmé :
- `forceOpenForTeam`/`onManualClose` sont strictement optionnels — `isManualMode = forceOpenForTeam
  != null`, et `isOpen = isManualMode || (automatique inchangé)`. Quand ces props sont omises
  (comportement par défaut), rien ne change par rapport à avant ce ticket.
- `OpeningConfirmationManualSection` interroge le même
  `GET /api/production/opening-confirmation/` que la boîte automatique, propose un bouton PAR
  équipe non encore confirmée aujourd'hui (`!report.teams[team].confirmed`), et affiche le message
  « Stock de départ confirmé aujourd'hui pour les équipes A et B. » quand les deux le sont — pas de
  bouton inutile pour l'équipe déjà confirmée.
- La confirmation manuelle appelle le MÊME endpoint de soumission que la confirmation
  automatique (`productionApi.openingConfirmation.submit`), donc les mêmes effets de bord
  (BUG-136 ajustement de stock, BUG-142 lien à la fournée du jour) sont garantis identiques sans
  code dupliqué.
- Garde de rôle : `DashboardLayout.tsx` (boîte modale automatique, ligne 837) et `Production.tsx`
  (nouvelle zone manuelle, ligne 761) appliquent EXACTEMENT la même condition —
  `(user.role === 'GERANT' || user.role === 'FACTURIER') && !user.can_access_all_nodes` — donc un
  compte Direction/Siège ne voit ni l'une ni l'autre.
- Aucun fichier backend touché par ce ticket (confirmé). L'endpoint backend sous-jacent est
  exercé, inchangé, par les tests `production/tests/test_daily_opening_confirmation.py`,
  `test_bug141_opening_team_after_hours.py`, `test_bug142_fournee_carryover_accumulation.py` —
  tous verts dans la suite complète (599/599 OK) exécutée ci-dessus.
- `npm run build` → succès (même run que BUG-150, aucun avertissement nouveau).

Aucun test E2E Playwright dédié n'existe dans `e2e/` pour ce parcours précis (confirmé par
`dev-frontend`, pas d'exécution E2E réelle de ma part non plus — vérification par lecture de code
ciblée + suite backend existante, le changement étant purement frontend et réutilisant un
endpoint déjà couvert).

**BUG-151 → `VÉRIFIÉ`.**

## Anomalie mineure relevée (documentation, pas de nouveau ticket)

La ligne de synthèse de BUG-151 manquait dans le tableau de suivi de
`docs/qa/REGISTRE_BUGS.md` (seule la fiche détaillée existait, ajoutée directement par
`dev-frontend` sous la section « Fiches détaillées »). Corrigé en ajoutant la ligne manquante en
même temps que le passage à `VÉRIFIÉ` des trois tickets — pas un bug fonctionnel, pas de nouveau
`BUG-NNN` ouvert pour ça.

## Registre mis à jour

- Tableau de suivi (`docs/qa/REGISTRE_BUGS.md`) : BUG-149, BUG-150, BUG-151 passés à `VÉRIFIÉ`
  (colonne « Vérifié par » : `testeur-production, 2026-11-10`). Ligne de synthèse BUG-151 ajoutée
  (absente auparavant).
- Fiches détaillées des trois tickets complétées avec le détail de cette vérification
  (sections « Vérification (`testeur-production`, 2026-11-10) » ajoutées, statut mis à jour).

## Fichiers consultés / modifiés

- Lus (aucune modification applicative) : `backend/core/reset.py`,
  `backend/core/permissions.py`, `backend/core/views.py`, `backend/core/urls.py`,
  `backend/core/tests/test_bug149_reset_superuser.py`,
  `frontend/src/components/settings/ResetDataModal.tsx`,
  `frontend/src/pages/dashboard/Settings.tsx`,
  `frontend/src/components/production/OpeningStockConfirmationModal.tsx`,
  `frontend/src/store/openingConfirmationStore.ts`,
  `frontend/src/components/production/OpeningConfirmationManualSection.tsx`,
  `frontend/src/components/layout/DashboardLayout.tsx`,
  `frontend/src/pages/dashboard/Production.tsx`.
- Créé puis supprimé (vérification uniquement, jamais livré) :
  `backend/core/tests/test_verif_bug149_extra_TEMP.py`.
- Modifié : `docs/qa/REGISTRE_BUGS.md` (statuts + ligne de synthèse BUG-151 + détails de
  vérification).
- Créé : `docs/qa/rapports/testeur-production-2026-11-10-verif-bug149-150-151.md` (ce rapport).

Aucun code applicatif modifié (conformément à CLAUDE.md §7 règle 2).

## Constat (signalé, non traité) — serveurs sur le port 8000

En fin de session, deux processus écoutent sur `127.0.0.1:8000` (`Get-NetTCPConnection -LocalPort
8000`), PID `772` (démarré 17:40:16) et PID `6460` (démarré 15:31:37) — **les deux utilisent
l'interpréteur système `C:\Program Files\Python312\python.exe`, PAS `backend\.venv\Scripts\
python.exe`**. C'est exactement l'incident récurrent signalé dans la mission. Je ne les ai ni
créés, ni arrêtés, ni utilisés pour mes vérifications (qui sont passées exclusivement par
`manage.py test`, jamais par une requête HTTP réelle contre un serveur en cours d'exécution) —
possible session active du coordinateur ou d'un autre agent. À signaler au coordinateur : si
l'un de ces deux processus sert réellement le client en ce moment avec le mauvais interpréteur
(donc potentiellement sans les dernières migrations/dépendances du `.venv`), c'est un risque
opérationnel distinct de ce rapport.
