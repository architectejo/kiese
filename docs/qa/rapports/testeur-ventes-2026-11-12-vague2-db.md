# Rapport testeur-ventes — vague 2 sur la base réelle (K1) — 2026-11-12

Périmètre : API `http://localhost:8000` + interface `http://localhost:5173` (Playwright), boulangerie K1 uniquement, base `backend/db.sqlite3` restaurée. Aucun code applicatif modifié ; aucun client réel touché ; ni reset, ni migrate, ni SQL, ni git.

## Exécuté
- (A) Rejeu exact des reproductions de BUG-208, 209, 210, 211, 212, 213, 214, 215, 229, 230, 233.
- (B) Non-régression : clients régulier/solde/cash/épargne, plafond 50 000 FC (49 500 + 500 accepté ; BP = plafond refusé 403 + notification ; versement < commande 403 ; versement = commande accepté), remboursement (commande 0, BP réduite, stock inchangé), BP, flux facturier -> livraison (livreur ET facturier) -> reçu, NV/RG/NS (NS non livrable), annulation (BP et stock restitués, livreur 403, livrée 400), prix client ignoré, nœud forcé ignoré (K1), rotation (403 `TEAM_NOT_ASSIGNED` pour vente, remboursement, vente occasionnelle ; équipe désignée portée par la facture ; correction de désignation ; livreur 403), rétroactif (veille, futur refusé), recherche client (le facturier K2 trouve les clients K1, y compris un client RISK).
- (C) Nouveau : série de 12 factures alternées (facturier A/B), 6 factures simultanées sur le même client (BP finale exacte, 6 numéros de reçu distincts), 30 livraisons en lot par le livreur (4 threads), triple requête de livraison simultanée (200/400/400, pas de double effet), cohérence `current_debt` = somme des mouvements recalculée depuis les factures pour 6 clients après chaque série (OK), épargne (BP -5 000 puis commande 3 000 -> -2 000), VENTE SOLDE (375 FC/pain, CM 0, BP inchangée), VENTE SOLDE au comptant, `bread_summary` / `daily_summary` en rotation avec livraison rétroactive, expiration 12 h (`cleanup_expired` : 0 sur base réelle ; scénario complet en base de test), UI Sales à 360 px et 1440 px.
- Tests : `backend/sales/tests/test_vague2_db_ventes_2026_11_12.py` (9 tests, OK) ; `test_vague1_corrections_ventes` (14 tests dev, OK) ; `e2e/tests/13-ventes-vague2-db.spec.ts`.

## Tickets VÉRIFIÉS
BUG-208, 209, 210, 211, 212, 213, 214, 215, 233 (rejeu sur base réelle : défaut disparu). BUG-229 et 230 (UI) VÉRIFIÉS aussi. BUG-211 : le décalage minuit-relève ne se rejoue pas sur la base réelle (horloge) ; vérifié par relecture du code (`delivered_on_work_date_filter`), tests dev et cohérence `bread_summary`/`daily_summary` en rotation.

## UI (BUG-229 / 230)
- Client à risque K1-0081 (BP 50 000 = plafond) proposé dans la recherche avec badge, bandeau « Client à risque », refus 403 affiché (« Plafond de crédit atteint … »), règlement intégral accepté, livraison, reçu complet (RCCM, Id.Nat, N° Impôt, code K1, équipe, BP avant/après, « Solde arrêté ce jour »), sans débordement horizontal : bureau OK et 360 px OK (BUG-229 et 230 passés à VÉRIFIÉ).
- Vente occasionnelle : versement forcé = commande et grisé, facture créée : bureau OK et 360 px OK.

## Données de test créées (K1, base réelle)
- Comptes : `zz_ventes_facturier` (A), `zz_ventes_facturierb` (B), `zz_ventes_livreur`, `zz_ventes_facturier_k2` (K2, mot de passe = identifiant).
- Clients `ZZTEST Ventes 1` à `8` (K1-0078 à K1-0085) ; ~50 factures K1 (livrées/annulées/en attente), stock K1 négatif (autorisé, BUG-155), une désignation d'équipe K1 du jour (A).
- Effet de bord sur K2 : 1 facture `K2-20261112-0001` créée par `zz_ventes_facturier_k2` sur un client K1 (comportement voulu par remarque.md), annulée aussitôt (stock restitué) ; elle consomme un numéro de reçu K2. Une requête `POST /production/team-assignment/` avec `node=K1` envoyée par ce compte a été appliquée à K2 (le `node` est ignoré pour un non-HQ, conforme à la docstring), pas à K1.

## Rotation
- Constat : à l'arrivée, `team_rotation_enabled` valait `True` sur K1 (et K3), contrairement à « désactivée partout ». Je l'ai mise à `False` pour la première partie, activée pour le scénario rotation, et remise à `False` (état de fin K1 = False).

## Observations (sans ticket)
- Hors rotation, une facture créée par un gérant sans équipe porte `team = ''` (reçu : « — », BUG-184 déjà traité côté affichage).
- `daily_summary` : le bucket CREDIT inclut le manquant d'une vente soldée (3 750 FC non payés alors que la BP est inchangée) ; à trancher par le coordinateur / auditeur comptable (pas de ticket ouvert).
- Environnement : serveur Vite/Django très lents sous charge parallèle (navigation > 90 s, `Enregistrement…` > 20 s) ; `outputDir` Playwright partagé entre testeurs (ENOENT sur les artefacts) : lancer avec `--output <dossier perso>`.

## Tickets ouverts
Aucun nouveau ticket.

## Verdict
AUCUNE ANOMALIE nouvelle sur le périmètre Ventes (API et UI) lors de cette vague.
