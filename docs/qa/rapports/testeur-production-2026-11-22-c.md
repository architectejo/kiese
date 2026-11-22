# Rapport testeur-production (Dev C) — vérification indépendante, 2026-11-22c

Branche dev-c, état 2fcfa0e. Aucun code applicatif modifié. Tests : `backend/production/tests/test_verif_direct_consommables_c.py` (46 tests, dont 4 `@expectedFailure` pour BUG-540 et BUG-541). Données fictives.

## Verdicts

| Ticket | Verdict | Détail |
|---|---|---|
| BUG-380 (envoi direct de pains, backend) | VÉRIFIÉ | Rôles (facturier/livreur 403, siège sans boulangerie 400/403), `from_node` forcé, quantités 0/négatif/décimal/texte/booléen/10^40 -> 400 sans écriture, lignes mal formées, multi-lignes atomique (une ligne en rupture -> rien d'écrit), séquence 30+30 sur 50 refusée, stock déjà négatif refusé avec « 0 disponible(s) », K1 et K3 ne peuvent pas valider, K2 valide : -N/+N, somme du groupe inchangée, double validation -> 400 sans second mouvement, écart 38/40 -> litige + blocage de clôture de K2 seulement, sur-réception -> litige et résolu par `resolve_dispute`. Anomalie annexe : BUG-540. |
| BUG-382 (frontend envoi direct) | Déjà VÉRIFIÉ par relecteur-code | Relu : `DirectSendModal.tsx` (entiers >= 1, refus du stock insuffisant côté client, double clic bloqué par `sending`, erreur serveur via `getErrorDetail`), bouton masqué facturier/livreur, SIEGE exclu du sélecteur par `NodeViewSet`. `npx tsc --noEmit` : 0 erreur. Pas d'essai navigateur (Playwright non lancé). Statut du registre laissé tel quel. |
| BUG-386 (consommables direction) | VÉRIFIÉ | Lecture globale ADMIN/DIRECTION/COMPTABLE seulement (gérant/facturier/livreur 403, anonyme 401), SIEGE et inactifs absents des lignes, Decimal en chaînes ; envoi réservé ADMIN/DIRECTION (COMPTABLE 403), total supérieur au stock direction -> 400 sans écriture partielle, séquence 70/40/30 bornée au stock, quantités illisibles (NaN, Infinity, 0, négatif, 4 décimales, énorme, booléen) -> 400, destinations invalides (SIEGE, inconnue, inactive, doublon, 10^40) -> 400, virgule décimale 0,25 acceptée, CUMP pondéré à la réception (5 à 800 + 10 à 1000 = 933,33) et CUMP direction inchangé, somme du groupe invariante ; inventaire : gérant seul (siège/facturier/livreur 403), écart = physique - théorique, stock non modifié, une saisie par jour et par boulangerie, `node` du corps ignoré, entrées invalides -> 400, PATCH commentaire seul, isolation K1/K2 (get, patch, node/<id|code>, liste, `?node=`) 404/vide, dates invalides -> 400, comptage manuel d'un inventaire non modifiable. Anomalie annexe : BUG-541. |
| BUG-416 (tests CUMP instables) | VÉRIFIÉ | 6 exécutions complètes vertes, 6 exécutions des fichiers CUMP vertes (mesures ci-dessous). Reste la remarque de B : l'ordre de rejeu de `recompute_cump` sur données réelles à horodatage égal est traité par BUG-364 (sans séquence persistée). |
| BUG-526 (production 500 -> 400) | VÉRIFIÉ | `sessions/?date_from|date_to` illisibles ou impossibles (abc, 2026-13-45, 2026-02-30, %00), `flour_history` mois/année (abc, 13, 0, 1e2, année 1, 40 chiffres) -> 400 pour gérant et siège ; valeurs valides -> 200. |
| BUG-527 (ventes `daily_summary`) | VÉRIFIÉ | Dates illisibles -> 400 (gérant et siège), date valide -> 200. |
| BUG-528 (finance `?node=ZZZ`) | VÉRIFIÉ | `summary`, `doc1_report`, `doc1_export` : `ZZZ`, `-1`, `abc%00` -> 400 ; `P1` -> 200. |
| BUG-529 (blockchain `?node=ZZZ`) | VÉRIFIÉ | `alerts`, `snapshots`, `run_check` (corps inconnu ou liste) -> 400. |
| BUG-402 (CUMP borné) | Déjà VÉRIFIÉ (2026-11-21c) | Non à revérifier ; ses tests passent dans les exécutions complètes. |

## BUG-416 : mesures
- Suite complète `python manage.py test production --noinput` (sans `--parallel`) : exécution 1 : 1048 tests, OK (1 ignoré, 5 échecs attendus), 1257 s sous charge machine.
- Cinq autres exécutions complètes lancées en parallèle (processus distincts, donc plus exposées aux écarts d'horloge) : 1053 tests chacune, 5/5 OK (1 ignoré, 6 échecs attendus), environ 1400 s chacune. Total 6/6 exécutions complètes vertes.
- Les 9 fichiers CUMP (357, 357/147, 402 x4, 123, 364, 364/365 : 133 tests) exécutés 6 fois consécutivement : 6/6 OK (17 s chacune, 1 échec attendu).

## Nouveaux tickets
- BUG-540 (Mineur) : `transfers/send` accepte SIEGE ou une boulangerie inactive comme destinataire (201, pains déduits sans validateur possible). Passe uniquement par l'API (le sélecteur exclut SIEGE).
- BUG-541 (Mineur) : `consumables/dispatch/` avec `"node": true` et `transfers/send` avec `to_node` flottant (ex. 2.5) sont tronqués par `int()` en un pk valide -> envoi vers une boulangerie non voulue.

## Observations (sans ticket)
- Catégorie de pain inactive acceptée à l'envoi direct : admis (écouler un reliquat).
- Sur-réception (reçu > envoyé) : le stock du récepteur est crédité du reçu jusqu'à la résolution du litige (comportement de BUG-223, clôture bloquée entre-temps).
- Concurrence : testée par séquence seulement (SQLite de test non concurrent) ; le code utilise `select_for_update` sous `transaction.atomic`.
