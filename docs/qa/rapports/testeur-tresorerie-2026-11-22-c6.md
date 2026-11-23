# Rapport testeur-tresorerie — cycle 6 (partie C, Dev B) — 2026-11-22

Tests : `backend/treasury/tests/test_verif_tresorerie_c6_v5.py` (nouveau, 26 tests). Résultat : 26 tests, OK, 1 échec attendu (BUG-863). `npx tsc --noEmit` : 0 erreur. Données fictives. Code applicatif non modifié. Aucun commit.

## 1. Vérification des tickets CORRIGÉ
| Ticket | Verdict | Angles testés indépendamment |
|---|---|---|
| BUG-860 | VÉRIFIÉ | resoumission : 1 ligne « Resoumission Clôture de Caisse » (node_origin C1) et 1 notification de l'écart ; WARNING sous 10 000 FC, DANGER au-delà ; compte exact : tracé mais non notifié ; deux resoumissions successives : deux traces ; resoumission refusée (clôture confirmée, 400) : ni trace ni notification ; drapeau de rejet levé, écart et total physique recalculés |
| BUG-861 | VÉRIFIÉ | 3 cycles altération / GET répétés / réparation : drapeau vrai pendant l'altération, faux après réparation, exactement 1 notification par altération (BUG-842 intact), aucune à la réparation ; même comportement par `run_check` ; réparation vue par `run_check` puis nouvelle altération notifiée par `integrity_check` ; cascade (altération de e1 invalide e2) : seul le drapeau de l'écriture redevenue valide retombe ; chaîne saine : jamais de drapeau ni de notification ; filtre `?is_tampered=true` suit la réparation ; suppression d'écriture toujours détectée |
| BUG-862 | VÉRIFIÉ (lecture de code + tsc, pas de navigateur) | `Blockchain.tsx` l.130 : `borderLeft: 4px solid hsl(var(--${tone}))`, aucune référence à `allIntact` dans la bordure ; `tone` = warning (neutre) / success / danger, même variable que le badge ; `tsc --noEmit` 0 erreur |

## 2. Nouveau ticket (1)
- **BUG-863** (Mineur, backend) : à la confirmation (`validate`), un écart recalculé (dépense saisie après une clôture exacte, écart 0 -> 500) est confirmé sans notification ; création et resoumission (BUG-860) notifient. Seul le journal d'activité en garde trace. Test `test_BUG_863_confirmation_with_recalculated_gap_is_notified` (`@expectedFailure`). Proposé en ticket (le cycle 5 l'avait laissé en observation).

## 3. Contrôles verts (aucun ticket)
- Confirmation avec écart recalculé : le journal d'activité mentionne `Écart: 500` ; le versement qui suit est égal au net confirmé (9 500 FC), la clôture est mise à jour, la chaîne reste valide.
- `generate` : idempotent (2 appels, 1 rapport, total 3 000 FC) ; sur un rapport validé sans changement de factures : drapeau et totaux conservés ; livraison supplémentaire sur la vacation validée : refusée, rapport inchangé. La réécriture d'un rapport validé n'est atteignable que par la livraison rétroactive (BUG-083), déjà notée au cycle 5 : à confirmer avec le client, pas de ticket.
- Bons de décaissement : un bon réduit le solde (100 000 - 30 000 = 70 000), chaîne valide ; bon supérieur au solde : 400, ni bon ni écriture. Observation de conception : l'écriture du livre porte le net confirmé (pas le comptage physique), donc le solde disponible d'une clôture en écart est le net.
- Épargne : n'écrit rien dans le livre de caisse (soldes et hash inchangés) ; montant = recette x taux ; même jour deux fois : pas de doublon, pas de 500.
- Concurrence : `_get_last_balance` lit sous `select_for_update` ; une seule fonction de hash (ni `hashlib` ni sha256 dans `treasury/views.py` ni `blockchain/views.py`). Les collisions concurrentes (nouvelle tentative) sont couvertes au cycle 5.

## Bilan
BUG-860, BUG-861, BUG-862 : VÉRIFIÉS (registre mis à jour). 1 nouveau ticket : BUG-863 (Mineur). Ce cycle n'est donc pas « 0 nouveau ticket ».

Remarque d'environnement : `$TEMP/x.log` est partagé avec d'autres exécutions concurrentes (il contenait une sortie `core.tests`) ; les résultats ci-dessus viennent d'un journal dédié.
