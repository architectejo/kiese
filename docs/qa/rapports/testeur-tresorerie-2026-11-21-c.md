# Rapport testeur-tresorerie (Dev C) - 2026-11-21

Verification independante des tickets Tresorerie au statut CORRIGE. Aucun code applicatif modifie.

## Verdicts

| Ticket | Verdict | Detail |
|---|---|---|
| BUG-199 (ordre de chainage) | VERIFIE | `chain_seq` = ordre unique ; 12 tests independants verts |
| BUG-177 (volet Tresorerie) | VERIFIE (volet Tresorerie seulement) | NS/RG hors rapport facturier, cloture, caisse |
| BUG-175 (`extraReports`) | OUVERT (correctif partiel) | rapport retroactif encore dans les totaux du jour juste apres generation |
| BUG-164 (volet Tresorerie) | NON VERIFIE (bloque par BUG-175) | reste conforme, `tsc` 0 erreur |

## BUG-199
Test : `backend/treasury/tests/test_verif_bug199_c.py` (12 tests). Couvre : fonction de hash unique (identite des objets treasury/blockchain) ; 12 ecritures de meme date sur 3 boulangeries ; 30 ecritures a dates entrelacees/retroactives avec accord des endpoints treasury `integrity_check` et blockchain `run_check` ; `_get_last_balance` suit `chain_seq` et non la date ; collision concurrente simulee (lecture perimee -> retentative, chaine lineaire) ; alteration montant, alteration date, permutation de `chain_seq`, suppression au milieu, suppression de la derniere (ancre de tete), insertion `bulk_create` sans `chain_seq` : tous detectes ; unicite de `chain_seq`.
Limites : concurrence reelle multi-processus non testable sous SQLite. Remarque non bloquante : la liste API est triee `-date,-created_at,-pk` pour l'affichage alors que `running_balance` suit `chain_seq`.

## BUG-177 (Tresorerie)
Test : `test_verif_bug177_c.py` (2 tests) : facture NS (CASH et CREDIT) absente du rapport facturier (cash/credit/theorique/categories), non livrable via l'API (400), sans effet sur la cloture Niveau 2 ; journee avec seulement des NS = rapport a zero. RG deja couvert par BUG-178 (verifie). Pas de colonne « Non Servi » dans `Treasury.tsx` ; la colonne releve de ClotureJournaliere (production, non traitee ici). Note : BUG-318 (sales) a fait evoluer l'expiration des PENDING en statut « Non servi » ; hors perimetre.

## BUG-175
Relecture de `Treasury.tsx` + `npx tsc --noEmit` : 0 erreur. Conforme : `extraReports` vide a chaque `loadData` et au changement de `nodeFilter`/`today`, filtre par boulangerie. Reliquat : apres `handleGenerateReport` retroactif, le rapport d'une autre date reste dans `reports`, que lisent `totalCash/totalCredit/theoreticalCash` (l.576-578), l'impression (l.815, 880), `_pendingReports` et `handleConfirmDay` (l.778-783). Vue direction sans filtre : rapports retroactifs de toutes boulangeries. Ticket repasse a OUVERT avec details dans la fiche (pas de nouveau BUG-5NN : meme defaut).

## BUG-164 (Tresorerie)
`useProgressiveList` (controle `loaded === total`, `isComplete`) et gardes `reportsReady`/`expensesReady`/`savingsReady` sur totaux, impression, validation en masse : conformes. Tri deterministe (BUG-172/176) deja corrige. Volet laisse en attente de BUG-175. Note : BUG-333 (page_size ignore) ouvert par ailleurs.

## Resultats
- `treasury.tests.test_verif_bug199_c` : 12/12 OK ; `treasury.tests.test_verif_bug177_c` : 2/2 OK.
- Suite `treasury blockchain` complete : voir message final (lancee en arriere-plan).
- Registre : lignes BUG-175 (OUVERT), BUG-199 (VERIFIE), BUG-177 et BUG-164 (annotations de volet) + fiches mises a jour.
