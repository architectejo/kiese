# Rapport testeur-tresorerie — vague 1 sur la base réelle (K3) — 2026-11-12

Périmètre : module Trésorerie, API `http://localhost:8000` (base `backend/db.sqlite3`), boulangerie K3 uniquement ; UI `http://localhost:5173/treasury` (Playwright, 360 px et 1366 px). Aucune écriture SQL, aucun `migrate`/`flush`/reset, aucun git.

## 1. Ce qui a été exécuté (API réelle)

Journées de test K3 : 2026-11-10 (ventes + rapports + dépenses, clôture impossible : voir BUG-201), 2026-11-09 (journée complète), 2026-11-08 et 2026-11-07 (clôtures légères).

- Niveau 1 : 2 facturiers (A, B) x 10 factures mixtes (cash, crédit à paiement nul/partiel, plusieurs catégories) livrées par le facturier ou le livreur ; `reports/generate` : cash 10 200 / crédit 6 000 par équipe, égaux à la somme des factures ; régénération idempotente ; facture tardive après rapport -> rapport A recalculé (11 200). Un FACTURIER ne peut pas générer (403). Génération sans date sur K3 (rotation, journée de travail 2026-11-11) : « aucune facture ».
- Dépenses locales : 3 catégories, FACTURIER refusé (403) ; montants négatif/nul acceptés (BUG-205).
- Niveau 2 : `caisse nette = cash - dépenses` (20 400 - 2 500 = 17 900) ; billetage (écart +100) ; billets négatifs/texte refusés (400) ; double clôture même jour refusée (400) ; recalcul automatique quand une vente arrive après la préparation (20 900) ; PATCH du billetage avant confirmation recalcule l'écart ; après confirmation : PATCH/PUT 400, DELETE 403 (BUG-198 OK, y compris Direction) ; clôture de jour sans vente, clôture avec dépenses seules (net -800 -> écriture de sortie) ; confirmation par le comptable avec note.
- Niveau 3 : versement `VC-K3-20261109` (18 400), `VC-K3-20261107` (0, saisi avant 11-08), `VC-K3-20261108` (sortie 800) : solde = précédent + entrée - sortie, chaînage par ordre d'insertion malgré des dates désordonnées (BUG-199 OK) ; double versement 400 ; API cashbook POST/PUT/PATCH/DELETE = 405 ; lecture refusée au gérant (403) ; `integrity_check` et `run_check`/`global_status` rendent le même verdict (intègre) après chaque étape ; filtres de date ; vente rétroactive après versement -> écriture `CORR-K3-...` +600, solde 18 200, chaîne intègre.
- Journal de caisse K3 : CA pré-rempli (`suggested_ca` = 20 400), confrontation (écart 0 puis -400 signalé, BUG-091 OK), non-CA, solde progressif.
- UI : `Treasury.tsx` rendu sans débordement horizontal (scrollWidth = 360 / 1366) pour gérant K3 et Direction, aucune erreur console ni réponse API >= 400 ; la machine très chargée a empêché d'attendre la fin du chargement progressif (état « Chargement… » encore affiché après 60 s sur la liste des clôtures) : parcours critiques (saisie billetage, versement) non rejoués dans l'UI. Captures : scratchpad de session (non versionnées).
- Non exécuté sur la base réelle (règles de la mission) : altération directe en base (écriture SQL interdite), 30 écritures chaînées, bons de décaissement (le livre est global : seuls des versements K3 y sont admis), transfert inter-boulangeries non résolu (nécessite une autre boulangerie), fenêtre minuit-01:00 (il est 04:xx), activation de la rotation (K3 était déjà en rotation à l'état initial, non modifiée).
- Test automatisé : `backend/treasury/tests/test_vague1_db_testeur_tresorerie.py` — journée complète (2 x 10 factures -> rapports -> dépense -> clôture avec billets -> confirmation -> versement -> solde, double clôture/double versement refusés, intégrité des deux endpoints) : PASSE ; 17 tests `@expectedFailure` pour BUG-200 à BUG-207.

## 2. Tickets ouverts (registre `docs/qa/REGISTRE_BUGS.md`)

| ID | Titre | Gravité |
|---|---|---|
| BUG-200 | Le gérant confirme sa propre clôture et la verse au Livre de Caisse (`get_permissions` écrase `IsHeadquarters`) | Bloquant |
| BUG-201 | Billetage démesuré : 500, clôture illisible et non supprimable par l'API | Bloquant |
| BUG-202 | Journal de caisse modifiable/supprimable par un facturier, montants négatifs | Majeur |
| BUG-203 | Totaux du rapport facturier modifiables, même validé | Majeur |
| BUG-204 | N° de pièce de correction de 31 caractères (max 30, PostgreSQL) et non distinct | Majeur |
| BUG-205 | Dépense locale négative ou nulle acceptée | Mineur |
| BUG-206 | Épargne journalière : `?node=` inter-nœuds, valeurs non bornées, LIVREUR autorisé | Majeur |
| BUG-207 | `period_summary` en flottants JSON | Mineur |

Observations non ouvertes en ticket : `POST /closures/` exige `date` (le défaut `work_date_for` du serveur est du code mort) ; une clôture confirmée et versée voit son écart recalculé par une vente rétroactive (décision BUG-083, en tension avec « écart non modifiable ») ; versement d'un net de 0 FC crée une écriture à 0 ; la liste du livre trie par date décroissante alors que le solde suit l'ordre d'insertion.

## 3. ACTION REQUISE (donnée à réparer)

La clôture K3 du 2026-11-10 (id `6e20b78091c6420fac579e69e49b4f08`) est une ligne corrompue créée par le test de BUG-201 : elle fait échouer `GET /api/treasury/closures/` sans filtre de date, `journal/suggested_ca` et la saisie d'une écriture CA K3 du 2026-11-10. Elle ne peut être supprimée que hors API (suppression de la ligne par un administrateur autorisé). Les écrans filtrés par date (comme l'UI) ne sont pas affectés.

## 4. Données de test créées

Comptes : `zz_treso_facturier_a` (K3, A), `zz_treso_facturier_b` (K3, B), `zz_treso_livreur` (K3), `zz_treso_comptable` (sans nœud), mots de passe = identifiant.
Clients : `ZZTEST Treso 1/2/3` (K3-0068, K3-0069, K3-0070).
Factures K3 : 21 le 2026-11-10 (dont 1 tardive) et 22 le 2026-11-09 (dont 2 tardives), livrées ; rapports facturier 2026-11-10 (A, B ; A validé) et 2026-11-09 (A, B) ; dépenses `ZZTEST ...` : 2026-11-10 (1 500, 700, 300), 2026-11-09 (1 500, 700, 300), 2026-11-08 (800) ; clôtures 2026-11-09 (versée), 2026-11-08 (versée), 2026-11-07 (versée), 2026-11-10 (corrompue, voir §3) ; journal K3 : 2026-11-08 (2 écritures + 1 modifiée par un facturier) et 2026-11-09 (2 écritures CA) ; épargne K3 : 2026-11-08 et 2026-11-07 (valeurs de test, dont une négative). Aucune des suppressions de nettoyage n'a été autorisée par l'environnement : ces lignes restent.

### Écritures du livre de caisse direction (chaîné, non nettoyable) — toutes K3

| Rang | Date | Pièce | Entrée | Sortie | Solde |
|---|---|---|---|---|---|
| 1 | 2026-11-09 | `VC-K3-20261109` | 18 400 | 0 | 18 400 |
| 2 | 2026-11-07 | `VC-K3-20261107` | 0 | 0 | 18 400 |
| 3 | 2026-11-08 | `VC-K3-20261108` | 0 | 800 | 17 600 |
| 4 | 2026-11-12 | `CORR-K3-20261109-20261112000000` (correction) | 600 | 0 | 18 200 |

Solde final du livre : 18 200 FC ; chaîne intègre (`integrity_check` et `run_check`). Réglages globaux non modifiés ; stocks de pains K3 décrémentés par les ventes de test (stock négatif possible).

## 5. Vérification des correctifs de `ingenieur-blockchain`

BUG-198 (suppression d'une clôture versée/confirmée refusée, 403) et BUG-199 (versements désordonnés chaînés par `chain_seq`, verdicts identiques des deux endpoints) : vérifiés sur la base réelle K3 ; passage à `VÉRIFIÉ` laissé au coordinateur après exécution de la suite complète.
