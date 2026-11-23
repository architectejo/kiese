# testeur-tresorerie c15 (2026-11-23) : vérification BUG-981 à 984 et tests indépendants BUG-973

Fichier de tests : `backend/treasury/tests/test_verif_tresorerie_c15_v14.py` (52 tests, 49 verts + 3 `@expectedFailure`). Code applicatif non modifié.

## Vérifiés
- **BUG-981** (horloge en avance : appliqué + conflit `HORLOGE_POSTE_EN_AVANCE` avec valeurs écrasées, tolérance 5 min, pas de bruit sans changement, une ligne en rafale, version ramenée à l'heure serveur) : VÉRIFIÉ.
- **BUG-982** (une notification par client et par conflit ouvert ; renotifie après résolution) : VÉRIFIÉ.
- **BUG-983** : resoumission avec billetage/totaux changés lève le rejet, jamais confirmée, pas de versement, journalisée, autre nœud refusé, billetage invalide refusé, flux resoumission -> validation -> versement -> chaîne OK ; pull limité au nœud du jeton, 60 jours, champs attendus, `is_paid` ; `apply_pull_response` sans toucher aux montants, entrées invalides ignorées, motif tronqué, id alternatif, resoumission locale non ré-infirmée : VÉRIFIÉ (avec la limite ci-dessous ouverte en BUG-985).
- **BUG-984** (UUID en majuscules, sans tirets, accolades, espaces : un seul client, le premier gagne) : VÉRIFIÉ.

## Limite annoncée : resoumission identique -> défaut (BUG-985, Majeur)
Oui, c'est un défaut. REST lève le rejet à toute resoumission (PUT identique vérifié) ; le gérant doit pouvoir recompter et renvoyer (remarque.md, règle BUG-860). En sync une resoumission identique est indiscernable d'un rejeu et est ignorée ; le pull ré-infirme ensuite la clôture sur le poste : impasse pour le gérant. Piste : marqueur explicite de resoumission postérieur au rejet.

## BUG-973 : écarts et défauts
Vert : heure exacte (11:59:59.999999 / 12:00:00), secondes, minuit et changement de jour (la validation de la veille ne débloque pas le jour suivant), fuseau Kinshasa (23:30 UTC = 00:30 locale), instant naïf, interrupteur off, autre boulangerie, SIEGE, direction qui vend pour un nœud bloqué (403), validation REST par la direction qui débloque, clôture infirmée ou créée mais non validée qui ne débloque pas, gérant qui ne peut pas se valider seul, NS/RG bloqués, remboursement/livraison/annulation non bloqués, série de ventes (3x403 puis 3x201 après validation), `closure-status` (401, `?node=` réservé HQ y compris pour son propre nœud, 404 code/uuid/injection, 405 en écriture, contrat à 6 clés). Concurrence : pas de test threadé sur SQLite ; la vérification est faite avant la transaction de création, donc une vente concurrente à la validation peut tomber dans le jour validé (question Q-017 ouverte, non ticketée). Les factures poussées par sync (ventes hors ligne) ne passent pas par le verrou : comportement attendu.

Comparaison à remarque.md l.464/488 :
- BUG-986 (À CLARIFIER, Mineur) : le client écrit « valide le Versement » ; le code débloque à la confirmation, avant le versement au livre.
- BUG-987 (Mineur) : une notification WARNING par tentative refusée (10 tentatives = 10 notifications).
- BUG-988 (Mineur) : `invoice_date` passée (avec `allow_backdated_sales`) contourne le verrou, même quand la clôture d'hier est confirmée. Voisin non ticketé : l'ajustement (+) du gérant n'est pas bloqué.
- Non couvert côté backend (déjà noté d38) : modale de clôture avec NV/déclassés/sorties gratuites, choix d'équipe, restes du jour -> stock de départ ; frontend (bannière, réglages) à faire.

## Tickets
Nouveaux : BUG-985, 986, 987, 988 (4). VÉRIFIÉ : 981, 982, 983, 984. BUG-973 reste CORRIGÉ (frontend à faire).
