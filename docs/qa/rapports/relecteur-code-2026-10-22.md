# Rapport — relecteur-code — 2026-10-22

Mission : (1) confirmer/infirmer la profondeur de couverture des tests (BUG-008), (2) quantifier la
dette technique frontend (BUG-011), (3) relire la cohérence des diffs des phases 1-4 entre agents
ayant travaillé en parallèle, (4) documenter la dérive de migrations récurrente. Aucun fichier de
code applicatif n'a été modifié ; seules des modifications de `docs/qa/REGISTRE_BUGS.md` et ce
rapport ont été écrites.

## 1. BUG-008 — Aucun test automatisé → **VÉRIFIÉ**

Le constat du coordinateur (« 17 fichiers ») était en réalité dépassé par le travail des phases 2-4 :
inventaire réel = **25 fichiers** (`find backend -name "test_*.py"`, hors `.venv`), répartis sur les
8 apps (`blockchain` 1, `clients` 5, `commissions` 3, `core` 2, `production` 4, `sales` 1, `sync` 1,
`treasury` 5).

Vérification de profondeur (pas seulement de présence) :
- Échantillonnage lignes/tests/assertions : `sales/tests/test_invoices.py` (707 lignes, 32 tests, 70
  assertions), `core/tests/test_permissions.py` (643/34/53), `sync/tests/test_sync.py` (424/18/46),
  `treasury/tests/test_cashbook_level3.py` (302/10/42) — aucun fichier n'est un squelette.
- `grep -rn "@expectedFailure"` sur tout `backend/` (hors `.venv`) → **aucune occurrence active** : le
  protocole « test `@expectedFailure` avant correction, décorateur retiré après » a été correctement
  suivi partout (seuls des imports désormais inutiles et des commentaires de traçabilité subsistent
  dans `clients/tests/test_models.py`, `test_social.py`, `commissions/tests/test_generate.py`,
  `production/tests/*.py`, `sales/tests/test_invoices.py`, `treasury/tests/test_scope_gaps.py` — dette
  de style mineure, imports à nettoyer, sans impact fonctionnel).
- Les fiches de vérification déjà présentes dans le registre (ex. BUG-001/002/003 par
  `testeur-tresorerie`, BUG-038..051 par `testeur-production`) documentent elles-mêmes des relectures
  indépendantes ligne à ligne, avec au moins un cas où un testeur a détecté et corrigé une faiblesse
  de couverture (`BUG-043` : le test initial ne vérifiait pas les valeurs numériques malgré l'affirmation
  de la fiche — `testeur-production` l'a complété lui-même). C'est le niveau de rigueur attendu.
- Exécution réelle, par moi, de la suite complète par lot (la machine a connu une contention de
  ressources empêchant un seul run global dans le temps imparti — deux interruptions de session en
  cours de mission, sans rapport avec le code) : `blockchain sync` → 20 tests OK ; `clients commissions
  core` → OK (exit 0) ; `production sales` → OK (exit 0) ; `treasury` → OK (exit 0). Les 8 apps sont
  couvertes sans aucun échec, en plus des runs déjà documentés par les testeurs eux-mêmes dans le
  registre (136 tests `core production sales treasury`, 108 `core clients production`, 31/31
  `treasury blockchain`).
- `npx tsc --noEmit` et `npm run build` (frontend) passent sans erreur ni nouvel avertissement (seul
  avertissement préexistant : taille de chunk > 500 kB, sans rapport).

**Conclusion : BUG-008 passé à `VÉRIFIÉ`** dans le registre, avec fiche détaillée. Non couvert (hors
périmètre de ce ticket, déjà signalé ailleurs) : E2E Playwright (`testeur-e2e`).

## 2. BUG-011 — Pages React géantes et `any` → **reste OUVERT, quantifié**

Mesures (`wc -l`, comptage `: any`/`as any`/`<any>`) :

| Page | Lignes | `any` |
|---|---|---|
| Clients.tsx | 2596 | 19 |
| Treasury.tsx | 2230 | 25 |
| Production.tsx | 1502 | 12 |
| Settings.tsx | 1055 | 13 |
| Sales.tsx | 845 | 6 |
| Dashboard.tsx | 805 | 4 |
| Commissions/Finance/Users/Nodes | 447-693 | 1 chacune |
| Activities/Blockchain | 137/246 | 0 |

Total `any` dans tout `src/` : **87**, dont 82 concentrés dans les 6 pages ci-dessus. `src/api/services.ts`
(996 lignes) et `src/api/client.ts` (0 `any`) sont propres — point positif, conforme à CLAUDE.md §4.
Aucun appel `axios` direct trouvé dans `src/pages/` : la règle « tous les appels HTTP passent par
`services.ts` » est respectée partout.

Un seul composant extrait cette session : `src/components/production/ReconciliationPanel.tsx` (152
lignes, 0 `any`, `catch (err: unknown)` correctement typé) — bon précédent, mais n'a pas réduit la
taille de `Production.tsx` de façon significative (le reste de la page n'a pas été touché).
`src/components/` ne contient que 5 fichiers en tout.

Nature des `any` restants (deux familles dominantes, pas du bruit aléatoire) :
1. `catch (err: any)` / `(err as any)?.response?.data?.detail`, dupliqué quasi à l'identique dans
   chaque gestionnaire d'action de chaque page.
2. `payload as any` pour contourner un type de payload `services.ts` plutôt que de l'élargir (ex.
   `treasuryApi.closures.update(..., { ...bills } as any)`), et quelques lectures de champs absents du
   type partagé (`(cl as any).gerant_display`, `(c as any).is_rejected`) qui indiquent un type
   `CashClosure`/`User` en retard sur la réalité de l'API plutôt qu'une vraie incertitude de type.

Plan d'extraction priorisé (livré dans la fiche BUG-011 du registre, non implémenté) :
1. **S** — fonction utilitaire `getErrorDetail(err: unknown, fallback: string): string` dans
   `src/api/` : éliminerait mécaniquement la majorité des 87 `any` en une seule PR à risque nul.
2. **M** — `Treasury.tsx` : extraire par niveau (§5.1.1-5.1.5 CLAUDE.md) — `FacturierReportPanel`,
   `CashClosureForm`, `CashbookLedgerPanel`.
3. **M** — `Clients.tsx` (la plus grosse page) : `SocialFundPanel`, `BulkImportModal`,
   `ClientFormModal`.
4. **S/M** — `Settings.tsx` : `BreadPriceSettings`, `ConsumableSettings`, `ColisSettings`.
5. **S** — `Production.tsx` : poursuivre dans l'esprit de `ReconciliationPanel` avec `FourneeForm`,
   `TransferPanel`, `ConsumableCountForm`.

Gravité laissée `Mineur` (aucun risque fonctionnel avéré, `tsc`/`build` propres) — ticket laissé
`OUVERT`, quantifié, avec plan de découpage dans la fiche.

## 3. Relecture transversale des diffs phases 1-4

### 3.1 Cohérence du motif « non-HQ → `node = user.node` imposé, jamais lu depuis le payload »

Vérifié sur l'ensemble de `backend/*/views.py` (pas seulement les fichiers explicitement cités par un
ticket) :
- **Lecture (`get_queryset`)** : le motif `if not user.can_access_all_nodes and user.node_id: qs =
  qs.filter(node=user.node)` (ou équivalent via une relation) est appliqué de façon cohérente dans
  `clients`, `core`, `treasury`, `commissions`, `production`, `sales` — aucune incohérence trouvée.
- **Écriture (`perform_create`/`perform_update`)** : le motif correctif de BUG-022/025/030 (ignorer le
  payload et imposer `user.node` pour un non-HQ) est appliqué correctement sur `ClientViewSet` (create
  **et** update, BUG-025), `InvoiceViewSet.create` (BUG-030), `ColisDistributionViewSet`,
  `SocialContributionViewSet`, `SocialDistributionViewSet`, `ConsumableMovementViewSet`,
  `SystemNotificationViewSet` (BUG-022, reprise écriture), `ConsumableCountViewSet` (BUG-042),
  `BreadDisposalViewSet` et `BreadTransferViewSet` (toujours forcés sur `user.node`, jamais
  d'alternative, donc jamais vulnérables).
- **Faille trouvée (nouvelle, ticket `BUG-056` ouvert)** : `ProductionSessionViewSet.perform_create`
  **et** `.perform_update` (`backend/production/views.py` ~l.153-164 et ~l.209-227) n'appliquent
  **jamais** ce motif — `node = serializer.validated_data.get('node') or user.node` sans condition sur
  `can_access_all_nodes`. Un GERANT non-HQ peut donc, en forgeant `"node"` dans le payload,
  déclarer/modifier une fournée pour une autre boulangerie, avec impact réel sur le stock de pains
  (`_adjust_bread_stock(session.node, ...)` utilise bien le nœud forgé) et sur les rapports en aval
  (BUG-033/BUG-043). Cette vue n'a jamais été dans le périmètre explicite de BUG-022 (qui citait 5
  ViewSets précis) ni de BUG-038 (qui portait sur `sac_value_fc_used`, pas sur `node`) — c'est
  exactement le type d'angle mort inter-agents que cette mission demandait de chercher. Aucun test
  existant ne couvre ce cas (contrairement aux 4 autres ViewSets de BUG-022, couverts par
  `core/tests/test_permissions_verif_2026_10_22.py::ForgedNodeOnWriteTests`).

### 3.2 Dérive de migrations pré-existante (`BUG-057`, nouveau ticket)

`python manage.py makemigrations --check --dry-run` détecte systématiquement 3 migrations non
appliquées sur `production` (`AlterField transfer_status` sur `breadtransfer`, `AlterField id` sur
`breadtransferline`/`consumablecount`), `clients` (suppression + réécriture de 3 contraintes
`unique_together`, `AlterField id` sur les 3 modèles de caisse sociale) et `treasury` (idem sur
`DailySavings`/`JournalEntry`). Cette dérive a été repérée indépendamment par au moins 3 agents
(`dev-backend` sous BUG-022, `dev-backend` sous BUG-038, `testeur-production` en vérification phase 4)
— chacun a correctement choisi de ne pas la corriger hors périmètre (bonne discipline), mais aucun
n'a ouvert le ticket dédié qu'il appelait lui-même, d'où la répétition.

Cause probable documentée dans `BUG-057` : ces modèles n'ont pas de PK UUID (pas des
`SyncableModel`) ; leurs migrations initiales datent probablement d'avant la fixation de
`DEFAULT_AUTO_FIELD='django.db.models.BigAutoField'` dans `settings.py` (ou d'une version de Django
antérieure à la 5.2.18 installée ici, dont la normalisation interne de `unique_together` différait).
Aucun impact fonctionnel constaté sur les bases déjà migrées (contraintes toujours actives), mais
violation littérale de CLAUDE.md §3 et risque réel à moyen terme : masquer une future vraie dérive
sous l'étiquette « c'est la dérive connue ». Ticket ouvert avec piste de résolution (générer, relire
et appliquer la migration dans une fenêtre dédiée isolée) pour qu'un futur agent la résolve au lieu de
la redécouvrir une 4ᵉ fois.

### 3.3 Autres observations de cohérence

- Aucune autre incohérence trouvée dans le traitement des permissions/`node` sur les ViewSets audités.
- Le motif de gestion d'erreur frontend (`catch (err: any)`) est dupliqué de façon cohérente (même
  style partout) mais jamais factorisé — voir plan BUG-011 point 1.
- La discipline du cycle `OUVERT → EN COURS → CORRIGÉ → VÉRIFIÉ` et la règle « le dev ne valide pas sa
  propre correction » ont été visiblement respectées dans toutes les fiches lues (chaque correction
  est suivie d'une vérification signée par un agent différent).

## 4. Tickets ouverts par le relecteur

- **BUG-056** (Majeur, backend) — `ProductionSessionViewSet` ne reprend pas le motif anti-forgeage de
  `node` (BUG-022/025/030). Suite attendue : `dev-backend` + test, vérifié par `testeur-permissions`
  ou `testeur-production`.
- **BUG-057** (Mineur, backend) — dérive de migrations récurrente documentée (cause probable,
  risque, piste de résolution). Suite attendue : `dev-backend` dans une fenêtre dédiée, critère de
  clôture = `makemigrations --check --dry-run` revenant à vide.

## 5. Registre mis à jour

- `BUG-008` : `CORRIGÉ (de facto)` → **`VÉRIFIÉ`** (fiche ajoutée en fin de registre).
- `BUG-011` : reste `OUVERT`, note enrichie dans le tableau de suivi + fiche détaillée (quantification
  + plan de découpage) ajoutée en fin de registre.
- `BUG-056`, `BUG-057` : nouvelles lignes dans le tableau de suivi + fiches détaillées.

Fichiers modifiés par cette mission : `docs/qa/REGISTRE_BUGS.md` (uniquement), `docs/qa/rapports/relecteur-code-2026-10-22.md` (ce rapport). Aucun fichier de code applicatif modifié, conformément au mandat.
