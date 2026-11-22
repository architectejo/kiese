# Rapport dev-backend (Dev B), 2026-11-22, d10

Tickets passés à CORRIGÉ : BUG-785, 787, 788, 789 ; BUG-786 corrigé côté code, test v4 non passé (voir ci-dessous).

- 789 (bloquant) : bordereau de versement refusé pour tout nœud != SIEGE (`_push_disbursement_voucher`).
- 788 : consommable limité au nœud authentifié ; transfert créé/modifié seulement par émetteur ou récepteur ; `quantity_received` seulement par le récepteur ; ligne existante contrôlée avant écriture.
- 787 : `updated_at` ajouté aux `update_fields` de `recompute_client_debt`.
- 785 : curseur validé côté poste (ISO, non futur), oublié après un 400 de paramètre ; côté serveur un curseur futur = absent.
- 786 : curseur lié au nœud (`node_code`), via paramètre ou `KIESE_NODE_CODE`.

Tests : sync complet 230 tests, seule erreur initiale (test_two_nodes_do_not_mix, qui poussait K2 avec un jeton K1) corrigée en poussant avec le jeton K2 ; reste 1 expectedFailure v4 (786). `makemigrations --check` : aucun changement. Aucune migration.

Tests existants modifiés (ils encodaient le défaut) : test_verif_bug146_testeur_charge::test_two_nodes_do_not_mix, test_sync_bug004_extension::test_disbursement_voucher_push_promotes_to_cashbook_once, test_verif_charge_v4::test_bordereau_rejeu_ne_double_pas_la_sortie (jeton SIEGE).

Risques : (1) BUG-786 : le testeur doit passer `node_code` dans son test. (2) Un poste existant dont le fichier curseur n'a pas `node_code` fera un pull complet une fois (voulu). (3) Un poste direction qui pousse un bordereau doit s'authentifier avec un jeton du nœud SIEGE. (4) Verrou réel à rejouer sous PostgreSQL.
