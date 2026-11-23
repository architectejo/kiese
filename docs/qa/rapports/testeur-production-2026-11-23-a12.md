# Rapport testeur-production a12 (2026-11-23)

Fichier de tests : `backend/production/tests/test_verif_production_a12_v12.py` (34 tests : 29 verts, 5 `@expectedFailure` = BUG-964 à 968). Aucun code applicatif modifié.

## Vérifiés (VÉRIFIÉ)
- BUG-955 : `invoice` malformé (`'pas-un-uuid'`, 12345, `''`, liste, None, objet, booléen, float, non-ASCII) avec l'id d'une ligne existante : REJECTED « dépendance manquante : invoice », quantité intacte ; ancien payload sans clé `invoice` : repli par l'id conservé ; id inconnu + invoice malformé : rien créé.
- BUG-956 : `'150000.0'`, 150000.0, `'110000.00'`, `' 90000 '`, `'+80000'` acceptés et normalisés en entier (création et mise à jour) ; `'1e3'`, `'9.0E4'`, `'150000.5'`, non-ASCII rejetés avec motif.
- BUG-957 : sac à 0 conservé à la création comme à la mise à jour (valeur théorique 0) ; absent/vide/null : 200000.
- BUG-958 (point critique, relu par moi : `production/transfer_direct.py::send_direct`, `sync_now.build_outbound_payload`, `_push_bread_transfer*`) : envoi direct REST (K1 -> K2, 2 lignes) -> export -> oubli local -> push : transfert RESPONDED et lignes ACCEPTED, `quantity_sent` correctes, aucune quantité reçue, stocks inchangés par le push (jamais de rejeu), rejeu x3 idempotent, 3 catégories. Création refusée : par la réceptrice ou un tiers en RESPONDED, par l'émettrice en CONFIRMED/DISPUTED/CANCELLED/statut inconnu ou avec `quantity_received` ; réceptrice en PENDING acceptée ; soi-même/nœud inconnu refusés ; lignes d'un transfert refusé : aucun orphelin.
- Machine d'états par rôle (BUG-874/888/891/921/922/928) : matrice complète 5 statuts x 3 rôles (émettrice, réceptrice, tiers) x 5 statuts = 75 combinaisons : seules PENDING->RESPONDED/CANCELLED (émettrice) et RESPONDED->CONFIRMED/DISPUTED (réceptrice) changent l'état, le tiers est toujours REJECTED ; quantité reçue réservée à la réceptrice ; CONFIRMED/CANCELLED immuables (lignes) ; double validation = un seul effet ; aucune régression de statut.
- Flux complet : demande K2 (REST) -> push -> réponse K1 (push) -> confirmation 98/100 K2 (push) : DISPUTED, clôture de K2 bloquée (pas K1/K3) -> `resolve_dispute` REST direction : CONFIRMED, lignes (98, 98), clôture débloquée, rejeu périmé sans réouverture. Flux direct 100/100 : K1 refusée, K2 acceptée, somme du stock groupe inchangée (REST).

## Nouveaux tickets (5)
- BUG-964 (Majeur, À CLARIFIER) : `PullView` ne descend aucun transfert (contraire à SYNC.md §5.3) : le poste réceptrice n'est ni alerté ni en mesure de valider.
- BUG-965 (Majeur) : l'export filtre sur `node_origin` : la validation/écart de K2 sur un transfert de K1 n'est jamais exportée ; K1 exporte un statut qu'il ne peut pas pousser (REJECTED indéfiniment).
- BUG-966 (Majeur) : `DISPUTED -> CONFIRMED` (recomptage ou résolution) absent de la machine d'états : push ACCEPTED sans effet, cloud DISPUTED, clôture bloquée à vie.
- BUG-967 (Mineur) : transfert créé avec `quantity_sent`/`quantity_received` = `'5.0'` : « erreur serveur ».
- BUG-968 (Mineur) : disposition avec `quantity='3.0'`/`unit_price_sold='100.0'` : « erreur serveur » (TypeError).

Autres champs décimaux contrôlés sans défaut : ligne de fournée (`'5.0'`, 7.0, `' 3 '`), ligne de transfert (`quantity_sent`/`quantity_received` normalisés par `_sync_int`), mouvement de consommable (0,25 / 12,5 / 1e2), valeurs hostiles de transfert (motif clair). Note : `'1e1'` est refusé sur une ligne de fournée mais `'1e2'` accepté pour la farine (incohérence mineure de format, non ticketée).

## Remarques
- Hors périmètre : `flow` (DIRECT/REQUEST) n'est pas exporté ; le transfert cloud est toujours REQUEST (sans effet constaté : un transfert RESPONDED n'est ni modifiable ni supprimable).
- Commande : `cd backend; ./.venv/Scripts/python.exe manage.py test production.tests.test_verif_production_a12_v12 --noinput` (journal `$TEMP/a12.log`).
