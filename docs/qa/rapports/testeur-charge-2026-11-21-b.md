# Testeur charge/résilience, vérification BUG-146 (2026-11-21)

Verdict : **BUG-146 VÉRIFIÉ**. Aucun nouveau ticket.

Tests : `backend/sync/tests/test_verif_bug146_testeur_charge.py` (20 tests). `manage.py test sync` : 81 tests OK.

## Couverture
- Ordre inversé, plusieurs sorties orphelines puis plusieurs entrées, entrées désordonnées : prix ré-estampillé, marqueurs `CONSUMABLE_EXIT_ORPHAN` résolus, sorties déjà résolues jamais retouchées.
- Rejeu x3 (direct et via API, même batch_id) : stock, CUMP, nombre de mouvements et de marqueurs inchangés.
- Atomicité (le lot est traité enregistrement par enregistrement, chacun dans sa transaction) : une panne dans le ré-estampillage ou l'écriture du marqueur annule l'entrée entière (mouvement, quantité, prix, marqueur), les autres enregistrements du lot passent, et le rejeu après reprise aboutit.
- Entrée à prix 0 : sortie reste en attente, puis résolue à la moyenne pondérée (20 000 sur 0 et 40 000 à quantités égales).
- Deux nœuds et deux consommables : aucun mélange.
- Decimal exact : sel 250 g, levure 0,250, huile 0,125 L, 40 sorties de 0,25 = 10,000 exact. Le ré-estampillage ne change ni la quantité ni le CUMP du stock.
- Charge : 200 mouvements mélangés (graine fixe, 3 ordres d'arrivée) : quantité finale = entrées - sorties dans chaque ordre, aucune sortie à 0 ni en attente. 2549 requêtes SQL pour 200 mouvements (12,7 par mouvement), et le nombre de requêtes par ENTRY ne croît pas avec l'historique (150 entrées ajoutées).

## Limite quantifiée (CUMP chronologique)
- Les prix des sorties sont dépendants de l'ordre d'arrivée. Même jeu (sortie, E1 10 sacs à 100 000, E2 10 sacs à 130 000) : ordre E1,E2 donne 100 000 ; ordre E2,E1 donne 130 000.
- Précision : le prix est la moyenne des entrées reçues AU MOMENT de la première entrée valorisée. Les marqueurs étant ensuite résolus, une entrée plus tardive ne ré-estampille pas. La doc de la fiche (« TOUTES les entrées reçues ») est donc un peu optimiste.
- Pire cas réaliste (farine, +30 % entre deux achats, toutes les sorties arrivées avant toutes les entrées) : COGS exact 875 000 FC contre 800 000 obtenu, soit -8,6 %.
- Ce cas extrême n'arrive qu'au premier lot d'un stock. Un nœud pousse en ordre chronologique, donc seules les sorties du tout premier lot sont concernées. Acceptable pour la valorisation (la valeur du stock reste exacte par quantités). Recommandation : faire porter `created_at` d'origine dans la charge de push pour un CUMP exact, plus tard.

## Constats annexes
- Le test BUG-143 du testeur-production échoue comme attendu (BUG-402, dev A).
- Le tableau du registre indiquait encore OUVERT pour BUG-146 : corrigé en VÉRIFIÉ.
