# Rapport — testeur-tresorerie — 2026-10-22

## Périmètre traité

- Partie 1 : vérification indépendante de BUG-001, BUG-002, BUG-003 (`ingenieur-blockchain`), passés à **VÉRIFIÉ**.
- Partie 2 : audit BUG-015 (`remarque.md` lignes 120, 142, 150-157, 163, 176-178) — passé à **REJETÉ (périmètre couvert, remplacé par BUG-033..037 + lignes `[c]` dans remarque.md)**.
- Couverture générale CLAUDE.md §5.5 (Niveau 1/2/3) au-delà du strict périmètre `remarque.md`, conformément à la mission.

Aucun fichier applicatif modifié. Seuls des tests (`backend/treasury/tests/`), le registre et `remarque.md` ont été touchés.

## Partie 1 — Vérification BUG-001 / BUG-002 / BUG-003

### Méthode
- Lecture critique indépendante de `backend/treasury/hashing.py`, `backend/treasury/views.py` (`append_cashbook_entry`, `_get_last_balance`, `push_to_cashbook`, `DisbursementVoucherViewSet.perform_create`) et `backend/blockchain/views.py` (`_verify_full_chain`, `_verify_chain_for_node`, `run_check`).
- Relance des 10 tests livrés par `ingenieur-blockchain` : `python manage.py test treasury blockchain` → **10/10 OK**.
- Ajout de mes propres tests indépendants (`backend/treasury/tests/test_cashbook_level3.py::TreasuryBlockchainVerdictConsistencyTests`) vérifiant que `/api/treasury/cashbook/integrity_check/` et `/api/blockchain/snapshots/run_check/` donnent **le même verdict** sur une chaîne saine et sur une chaîne falsifiée.
- Scénario de journée complète bout-en-bout (`FullDayIntegrationTests`) se terminant par une vérification de chaîne intacte.

### Constat
- Une seule fonction de hash (`compute_cashbook_entry_hash`) et une seule boucle de vérification (`verify_cashbook_chain`), importées sans duplication par `treasury` et `blockchain` — BUG-001 réellement résolu.
- `append_cashbook_entry` lit le solde/hash précédent et écrit la nouvelle entrée dans la **même transaction**, avec retry sur `IntegrityError`/`OperationalError` ; la contrainte d'unicité DB sur `previous_hash` empêche toute fourche même sous SQLite où `select_for_update()` est inopérant. Testé avec 8 threads concurrents (test déjà fourni, relancé) : aucune fourche, chaîne valide, solde exact.
- Le hash couvre bien `node`, `imputation`, `source_closure` et `source_bordereau` ; confirmé en conditions réelles (pas seulement en lisant le code) que `source_bordereau` est renseigné sur une écriture de sortie créée via un bordereau de versement.
- Migration `0007_recompute_cashbook_hash` prudente, n'écrase jamais une falsification legacy préexistante (vérifié : 0 `CashbookEntry` en base avant la migration).

### Résultat
**BUG-001, BUG-002, BUG-003 → VÉRIFIÉ.** Fiches de vérification ajoutées au registre sous chaque ticket. Aucune faille trouvée, aucune régression.

## Partie 2 — Audit BUG-015 (remarque.md)

### Points conformes (marqués `[c]` dans remarque.md avec note datée)
- l.120 : dépenses locales rattachées et filtrables par boulangerie.
- l.150 : Niveau 1 filtrable par boulangerie.
- l.152 : clôtures du jour agrégées automatiquement à partir du Niveau 1, filtrées par boulangerie.
- l.154 : libellés « Rapport de caisse » / « Versement du jour » dans la boîte modale de clôture.
- l.156 : cycle gérant → comptable (créer → confirmer/infirmer → modifier si infirmée → re-soumettre) fonctionnel pour sa partie principale (nuance signalée, voir BUG-034 ci-dessous).
- l.163 : le gérant voit bien le Niveau 1 restreint à sa boulangerie.
- l.176 : libellés « Versement », « Recette / Paiement », « Solde comptable caisse » (calculé à partir du Niveau 1 du nœud du gérant).
- l.178 : libellé sidebar « Clôture & Caisse ».

### Points non conformes (tickets ouverts)
- **l.142 → BUG-033** (Majeur) : `FacturierReport` n'expose aucun détail par catégorie de pain (200/300/400/500/1000 FC), aucun sac consommé, aucun écart théorique/vente. Uniquement des totaux agrégés cash/crédit/théorique.
- **l.156 (nuance) → BUG-034** (Majeur) : une clôture déjà **confirmée** par le comptable reste modifiable par le gérant (`CashClosureViewSet.perform_update` ne vérifie jamais `is_validated`/`is_rejected`). Seule une clôture infirmée devrait rester modifiable.

### Au-delà de remarque.md — scénarios CLAUDE.md §5.5 / mission testeur-tresorerie
- **BUG-035** (Mineur) : double clôture (même nœud/jour) — la contrainte `unique_together` protège bien les données, mais `CashClosureViewSet.perform_create` ne capture pas l'`IntegrityError` : la seconde tentative remonte en erreur serveur 500 au lieu d'un refus propre 400/409.
- **BUG-036** (Majeur) : aucun verrouillage de vacation après génération du rapport facturier Niveau 1 — une facture peut encore être livrée sur une vacation déjà rapportée, qui n'est repris qu'en régénérant silencieusement le rapport.
- **BUG-037** (Majeur) : la clôture de caisse n'interroge jamais `production.BreadTransfer` — un transfert entrant avec un écart de quantité non résolu (`quantity_gap`) ne bloque ni n'alerte la création/le versement d'une clôture, contrairement à CLAUDE.md §5.4.

### Points vérifiés conformes sans ticket (Niveau 2/3, hors remarque.md strict mais dans le périmètre de la mission)
Tous couverts par des tests qui passent (`backend/treasury/tests/test_reports_closures.py`, `test_cashbook_level3.py`) :
- Caisse nette = ventes cash − dépenses locales.
- Ventilation des billets : total = Σ quantité × valeur ; écart positif/négatif/nul correctement calculé et journalisé (`cash_gap`, non modifiable car recalculé par le serveur, jamais par le client).
- Niveau 3 : versement crée une écriture avec `piece_number = VC-<code>-<AAAAMMJJ>`, `solde = précédent + entrée − sortie`.
- Double versement de la même clôture → refusé (400, `cashbook_entries.exists()`).
- API du Livre de Caisse strictement en lecture seule (POST/PUT/PATCH/DELETE → 405).
- Filtre par période (`date_from`/`date_to`) et solde progressif correct sur plusieurs boulangeries (chaîne globale unique, confirmé par calcul).
- Bons de décaissement : réduisent bien le solde, refusés si le montant dépasse le solde disponible (vérification dans la même transaction verrouillée que l'écriture, pas de fenêtre de course).
- Scénario de journée complète (2 facturiers équipes A/B × 10 factures mixtes → rapports → dépenses → clôture avec billetage → versement → vérification chaîne) : passe de bout en bout, chaîne intacte confirmée par `treasury` **et** `blockchain`.

## Fichiers livrés

- `backend/treasury/tests/test_reports_closures.py` (Niveau 1/2 : génération, filtrage par nœud, caisse nette, billetage, écarts, workflow confirmer/infirmer/resubmit, double clôture) — 9 tests, 3 `@expectedFailure` (BUG-033, BUG-034, BUG-035).
- `backend/treasury/tests/test_cashbook_level3.py` (Niveau 3 : versement, double versement, lecture seule, solde progressif multi-nœuds, filtre par période, bordereaux de décaissement, cohérence treasury/blockchain, scénario de journée complète) — 10 tests, tous verts.
- `backend/treasury/tests/test_scope_gaps.py` (verrouillage de vacation, blocage clôture sur écart de transfert) — 2 tests, tous `@expectedFailure` (BUG-036, BUG-037).

**Total ajouté : 21 tests** (dont 5 `@expectedFailure` documentant des anomalies réelles, confirmées par du code qui échoue avant correction).

## Exécution finale

```
python manage.py test treasury blockchain
```
→ **31/31 tests** (10 de `ingenieur-blockchain` + 21 des miens), **OK (expected failures=5)**.

Remarque d'environnement : `backend/.env` est toujours le dossier venv historique (BUG-007 non encore clôturé côté humain) — j'ai dû positionner `DJANGO_DEBUG=True` en variable d'environnement pour pouvoir lancer `manage.py test` localement (sinon `ImproperlyConfigured` levée par le garde-fou BUG-005, correctement intransigeant). Aucune donnée réelle touchée ; je n'ai pas eu besoin d'utiliser `backend/db.sqlite3` pour une démonstration manuelle (les écritures `DEMO-INGBLOCKCHAIN-00/01/02` laissées par `ingenieur-blockchain` sur le nœud K1 restent en place, inchangées — je ne les ai pas supprimées, à la discrétion du coordinateur).

## Registre

- BUG-001, BUG-002, BUG-003 → **VÉRIFIÉ** (fiches de vérification ajoutées).
- BUG-015 → **REJETÉ (périmètre couvert, remplacé par BUG-033..037 + lignes `[c]` dans remarque.md)**.
- Nouveaux tickets ouverts : **BUG-033, BUG-034, BUG-035, BUG-036, BUG-037** (tous assignés à `dev-backend`, vérificateur désigné `testeur-tresorerie`).

Note de coordination : au moment d'ouvrir mes tickets, les numéros BUG-017 à BUG-032 étaient déjà réservés par `testeur-clients-commissions`/`testeur-ventes`/`testeur-permissions` (agents concurrents sur cette même session) — j'ai relu le registre avant d'écrire et utilisé la première plage libre (BUG-033 à BUG-037) pour éviter toute collision.

## Points signalés au coordinateur (non tranchés seul)

1. **BUG-026** (ouvert par `testeur-permissions`) chevauche mon périmètre : `CashbookEntryViewSet` (Livre de Caisse Direction) est lisible par tout utilisateur authentifié, sans filtre par nœud. Je n'ai pas dupliqué ce ticket — je le mentionne ici pour que la correction soit coordonnée avec `dev-backend` sur le même fichier (`backend/treasury/views.py`) que mes tickets BUG-034/035/037.
2. Le scénario « clôture bloquée par écart de transfert non résolu » (BUG-037) touche à la fois `treasury` et `production` (`BreadTransfer.quantity_gap`) : la correction nécessitera probablement une coordination entre les deux modules plutôt qu'une modification isolée de `treasury/views.py`.
3. Aucune contradiction trouvée entre `remarque.md`, `CLAUDE.md` et `cahierDesCharges.md` sur mon périmètre — rien à signaler de ce côté.

## Fichiers pertinents

- `backend/treasury/tests/test_reports_closures.py`
- `backend/treasury/tests/test_cashbook_level3.py`
- `backend/treasury/tests/test_scope_gaps.py`
- `docs/qa/REGISTRE_BUGS.md` (BUG-001/002/003 → VÉRIFIÉ ; BUG-015 → REJETÉ ; BUG-033..037 ajoutés)
- `remarque.md` (lignes 120, 150, 152, 154, 156, 163, 176, 178 marquées `[c]` ; ligne 142 annotée NON CONFORME avec renvoi vers BUG-033)
