# Vérification croisée dev-b de A-1..A-4 (dev-a) — 2026-11-24

Tests indépendants : `backend/production/tests/test_verif_croisee_b_a1_a4.py` (20 tests, valeurs fictives) : 20/20 verts. `frontend/src/utils/fourneeGap.test.ts` (vitest) : 4/4 verts. Aucun code applicatif modifié.

| Ticket | Résultat | Preuves |
|---|---|---|
| BUG-1070 (stock de départ) | VÉRIFIÉ (rendu visuel à confirmer) | `qty_opening` : valeur confirmée, 0 confirmé distinct de None, jour passé (`by-date`), isolation K1/K2 |
| BUG-1071 (Envoyés/Reçu) | VÉRIFIÉ (rendu visuel à confirmer) | `qty_transfer_sent` = transferts seuls (le legacy `qty_sent` mélange : 11 + 12 = 23 contre 12), Reçu = quantité reçue (18 sur 20), rôles facturier/livreur en lecture, tiers à 0, envoi facturier refusé (403), anonyme 401 |
| BUG-1072 (écart) | VÉRIFIÉ (badge à confirmer visuellement) | Signe : backend `yield_gap` = produit − théorique, front = théorique − produit : manquant 190 000/200 000 → +10 000, excédent → −10 000, équilibre → 0 ; fournée par sacs ouverte : non calculable |
| BUG-1073 / 1202 | VÉRIFIÉ (1073) | Reste du jour = dernier déclaré toutes équipes confondues (14 puis 29, pas 45), reste d'hier = veille ou confirmation la plus tôt, `daily-closure` : produit dérivé 30 + 6 − 2 = 34 et MVM interne (6−2)×500 ; isolation K2. BUG-1202 (ticket de l'auditeur) laissé à l'auditeur |
| BUG-1074 (clôture auto) | VÉRIFIÉ | Idempotente (3 rappels : aucun log/notification/snapshot en plus), reste = stock physique, fournée déjà close intacte, reste du gérant conservé par catégorie (13) et déclassés conservés, pas de clôture sans livraison / 0 sac / sans production, inactive sans interrupteur, avant 17:30 (17:00 + 30 min), jour futur, isolation K1/K2, `shift-end-status` déclenché par le gérant et pas par un tiers K2 |

## Remarques
- Le test d'égalité des deux équipes sur `updated_at` : à l'égalité d'horodatage, le tri `(updated_at, pk)` départage par pk ; sans risque réel.
- Contrôle visuel restant : Production > Stock Pains du Jour (colonnes Stock de départ « — », Envoyés, Reçu, ligne TOTAL, jour passé) et badge Excédent/Équilibre/Manquant (liste, modale, détail), à 360/768/1440 px.
- Hors vérification : décision Q-051 (sens « stock de départ compté vendu ») et Q-053 (délai de grâce 30 min) restent ouvertes côté client.
- Aucun défaut trouvé : pas de BUG-1119+.
