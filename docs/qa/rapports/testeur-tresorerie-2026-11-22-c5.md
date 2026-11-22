# Rapport testeur-tresorerie — cycle 5 (reprise partie C par Dev B) — 2026-11-22

Périmètre : `backend/treasury/`, `backend/blockchain/`, `frontend/src/pages/dashboard/Blockchain.tsx`.
Tests : `backend/treasury/tests/test_verif_tresorerie_c5_v4.py` (nouveau, 45 tests). Données fictives. Code applicatif non modifié.

## Exécution
`manage.py test treasury.tests.test_verif_tresorerie_c5_v4 treasury.tests.test_cycle3_tresorerie_c treasury.tests.test_bug840_847 blockchain` : 103 tests, OK, 3 échecs attendus (BUG-860, BUG-861 x2). `npx tsc --noEmit` : 0 erreur.

## 1. Vérification des tickets CORRIGÉ
| Ticket | Verdict | Angles testés indépendamment |
|---|---|---|
| BUG-810 (PATCH rapport) | VÉRIFIÉ | PATCH/PUT `node` = true, false, 1.5, 0, 'abc', '1.0', liste, objet, 999999, '' (JSON) et multipart : aucun 500, rapport jamais déplacé ; nœud valide par le gérant ignoré ; totaux/équipe/validation non éditables |
| BUG-840 | VÉRIFIÉ | `generate` refusé (400) un jour confirmé (sans date, avec date, siège avec `node`) ; versement = montant confirmé ; autorisé avant confirmation et après infirmation ; autre boulangerie non gelée |
| BUG-841 | VÉRIFIÉ | PATCH/PUT date vers un jour existant : 400 sans modification ; même date, jour libre, autre équipe : 200 ; date future/illisible/None : aucun 500 ; vers un jour confirmé : 400 |
| BUG-842 | VÉRIFIÉ | 4 appels GET : 1 notification par écriture altérée (cascade comprise), jamais par appel ; tête amputée : 1 notification ; aucune `TamperAlert` créée par un GET ; chaîne saine : rien créé ; verdicts run_check / integrity_check identiques. Réserve : BUG-861 |
| BUG-843 | VÉRIFIÉ | jamais vérifié, vérification partielle (`unchecked_nodes`), complète, nouvelle boulangerie ajoutée ensuite, altération ; dernier snapshot par nœud |
| BUG-844 | VÉRIFIÉ | `ActivityLog` pour rapport (création, suppression), épargne (création, upsert, PATCH), journal (EAU, CA, RATION), dépense, clôture (création, rejet, confirmation, versement), bon, comptage |
| BUG-845 | VÉRIFIÉ | requêtes constantes (3 vs 15 boulangeries à 3 snapshots, plafond 8) et 1er appel à froid (Config supprimée) <= 14 ; le test cycle3 passe désormais |
| BUG-846 (frontend) | VÉRIFIÉ (lecture de code + tsc) | `never_checked`, `unchecked_nodes` typés ; états « JAMAIS VÉRIFIÉ » / « VÉRIFICATION PARTIELLE » (ton avertissement) distincts de « COMPROMIS » (réservé aux snapshots non intègres) ; bandeau neutre. Reliquat cosmétique : BUG-862. Pas de navigateur |
| BUG-847 | VÉRIFIÉ | dépassement positif et négatif : 400 et rien d'écrit ; écriture antidatée qui ferait déborder une ligne postérieure : annulée ; soldes progressifs corrects sur 2 boulangeries |

## 2. Nouveaux tickets (3)
- **BUG-860** (Mineur, backend) : resoumission de clôture sans `log_activity` ni notification du nouvel écart (`perform_update`). Test `@expectedFailure`.
- **BUG-861** (Mineur, backend) : `is_tampered` jamais remis à faux ; après réparation la chaîne est valide mais l'écriture reste marquée, et la 2e altération n'est plus notifiée par `integrity_check` (dédoublonnage de BUG-842 fondé sur ce drapeau). 2 tests `@expectedFailure`.
- **BUG-862** (Mineur, frontend) : `Blockchain.tsx` l.130, bordure du bandeau rouge en état neutre (utiliser `tone`).

## 3. Contrôles verts de la 2e passe (aucun ticket)
- Clôture : champs financiers (`net_cash`, `cash_gap`, `physical_cash_total`, `total_entries`, `is_validated`, `is_rejected`) ignorés dans le corps (POST et PATCH) ; clôture confirmée figée (PATCH/PUT 400, DELETE 403 gérant et direction, rejet/confirmation répétés 400) ; double clôture même jour (gérant et siège) 400 ; notification d'écart : +500 WARNING, -20 000 DANGER, aucun écart = aucune notification.
- Versement : n° `VC-C1-AAAAMMJJ`, double versement 400, une seule écriture.
- Chaîne : altération de chacun des 12 champs (label, pièce, imputation, montants, date, node, source_closure, is_correction, previous_hash, block_hash) détectée puis restauration valide ; écriture ajoutée en base avec un hash valide mais hors circuit : détectée par l'ancre de tête ; suppression d'une écriture : détectée par les deux endpoints ; collision de `previous_hash` simulée : nouvelle tentative, chaîne valide, solde juste ; une seule fonction de hash (ni `hashlib` ni sha256 dans les vues).
- Bons : bon à 0 refusé, bon > solde refusé, bon = solde accepté (solde 0), PUT/PATCH/DELETE 405, pièces distinctes le même jour, rôles non siège 403.
- Livre de caisse API lecture seule (405), filtre de période. Montants négatifs ou aberrants (épargne, journal, dépense) : 400.

## 4. Observations sans ticket
- `FacturierReportViewSet.generate` / `regenerate_facturier_reports` réécrivent un rapport déjà validé (`update_or_create` ignore `is_validated`). Atteignable seulement via la livraison rétroactive (BUG-083, voulue) : la vacation reste verrouillée à la livraison normale (vérifié). À confirmer avec le client si un rapport validé doit rester figé même dans ce cas.
- À la confirmation, un écart recalculé (dépense saisie après la clôture) n'est pas notifié au gérant (il apparaît dans le journal d'activité de confirmation). Voisinage BUG-860, non ouvert.
- BUG-811 (b) reste À CLARIFIER (client).

## Bilan
9 tickets VÉRIFIÉS (810, 840 à 847). 3 nouveaux tickets (860, 861, 862), tous Mineurs, donc ce cycle n'est pas « sans nouveau ticket ».
