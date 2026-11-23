# Testeur Clients/Commissions - ronde b5 (2026-11-23)

## Vérification des tickets CORRIGÉ : 10 / 10 VÉRIFIÉS
BUG-751, 752, 753, 761, 762, 785, 786, 787, 788, 789.

- 751/762 : 3 routes clients x 4 corps non objet = 400 français.
- 752 : création, modification, suppression de ligne refusées sur distribution close ; déplacement vers une distribution close refusé.
- 753 : tests v4 durcis (ils n'exigeaient que `< 500`) : 400 français et aucune écriture partielle, pour `refresh_indices` et `auto_populate_lines`.
- 761 : ancien jeton 401, nouveau 200, autre nœud intact, une seule ligne ; réémission après révocation.
- 785/787 : tests existants verts ; ajout d'un test de pull incrémental après recalcul de dette.
- 786 : test `test_curseur_lie_au_noeud_pas_seulement_a_l_url` adapté (`node_code='K1'`/`'K2'` passé à `_pull_only`, K1 réutilise son curseur, K2 repart en pull complet) ; marque `expectedFailure` retirée, vert.
- 788/789 : tests verts ; jetons K2 et K3 rejetés pour le bordereau.

## Tests préexistants adaptés par l'agent : relus
- `test_two_nodes_do_not_mix` : mêmes assertions, seul le jeton de push change. OK.
- `test_disbursement_voucher_push_promotes_to_cashbook_once` : identique avec jeton SIEGE. OK.
- `test_bordereau_rejeu_ne_double_pas_la_sortie` : identique avec jeton SIEGE. OK.
- Constat annexe : `test_bordereau_superieur_au_solde_rejete` poussait avec un jeton K1. Depuis BUG-789 il passait pour la mauvaise raison (rejet de portée, plus de solde). Repris avec jeton SIEGE, assertion « solde » et absence d'écriture au livre.

## Nouveaux tickets : 3
- BUG-872 (Majeur) : une distribution de caisse sociale CLÔTURÉE est supprimable par un gérant (204), lignes comprises.
- BUG-873 (Mineur) : `PATCH /api/core/auth/me/` renvoie 500 sur corps non objet et sur `new_password` non textuel.
- BUG-874 (Majeur) : l'émetteur d'un transfert peut le confirmer ou y écrire la quantité reçue par push sync (transition RESPONDED vers CONFIRMED, création CONFIRMED, création de ligne avec `quantity_received`) ; contourne BUG-788 et la validation de la réceptrice.

Angles sans défaut : `mark_paid` (`paid_by` non texte ou 500 caractères), `set_manuel` (`manuel_notes` non texte, refus après paiement), isolation des lignes de distribution entre K1 et K3.

## Fichiers
- Nouveaux : `backend/clients/tests/test_clients_v5.py`, `backend/sync/tests/test_verif_sync_v5.py`.
- Modifié : `backend/sync/tests/test_verif_charge_v4.py` (BUG-786 et test du solde).
- Registre : 10 passages à VÉRIFIÉ et 3 lignes ajoutées.

## Résultats
- `clients.tests.test_clients_v5 sync.tests.test_verif_sync_v5 sync.tests.test_verif_charge_v4` : 53 tests, OK (expected failures=6, BUG-872/873/874).
- Run précédent (v4 clients, v4 commissions, charge v4, bug146, bug004, permissions b4) : 172 tests OK ; le seul expected failure était BUG-786, depuis adapté et vert.
- SQLite conservé : verrous seulement simulés.
