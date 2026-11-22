# Brouillon de Pull Request — `dev-c` → `main`

> Brouillon préparé par le Dev C le 2026-11-22. **À ne pas ouvrir avant l'ordre du responsable** et avant la vérification indépendante finale (voir « Avant de fusionner »). Sur GitHub, le corps de la PR se termine par la mention « Generated with Claude Code ».

## Résumé

`dev-c` réunit le travail des trois développeurs (A, B, C) depuis `main` (v1.0.0) : 93 commits, environ 400 fichiers. Contenu :

- **Isolation entre boulangeries** : fuites corrigées dans trésorerie, production, clients (BUG-503, 504, 505, 506, 521, 522, 362) ; comptes sans boulangerie refusés ; paramètres invalides → 400 au lieu de 500 (BUG-526 à 529).
- **Production** : envoi direct de pains (BUG-380, 382), CUMP borné sur stock négatif (BUG-402), commande `recompute_cump` (BUG-357, 364, 501, 524), auto-création du stock de consommable (BUG-147), fournées cumulées (BUG-502).
- **Ventes** : prix plein figé sur la ligne (BUG-508), numéros de reçu rétroactifs (BUG-197).
- **Trésorerie / Caisse** : page « Caisse » séparée de la « Clôture Journalière » (BUG-383), « Versement » visible de la direction en lecture (BUG-381), rapports rétroactifs hors totaux du jour (BUG-175).
- **Blockchain** : alertes de falsification et snapshots protégés contre la suppression d'un nœud (BUG-516).
- **Plateforme (B)** : sync, pagination `page_size` (BUG-333), commissions par mois/année (BUG-412, 511), suppression d'un nœud protégée (BUG-414), découpage de `Clients.tsx` et `Settings.tsx` (BUG-011), colonne Actions à 360 px (BUG-415).
- **Python 3.14** : `Pillow>=10.4,<14.0`. **Waitress** est le seul serveur WSGI. **`desktop/` est gelé** (aucune modification de ce dossier dans cette PR hors travaux de B antérieurs au gel).

## Migrations à appliquer, dans l'ordre

| Migration | Contenu | Risque |
|---|---|---|
| `blockchain/0002_node_protect` | `TamperAlert.node` et `BlockchainSnapshot.node` en `PROTECT` | aucun (réversible, aucune donnée modifiée) |
| `production/0027_bug380_transfer_flow` | `BreadTransfer.flow` (`REQUEST` par défaut) | aucun (AddField, réversible) |
| `sales/0011_bug508_full_unit_price` | `InvoiceLine.full_unit_price` nullable | aucun (AddField nullable) |
| `sales/0012_bug508_backfill_full_unit_price` | rétro-remplissage, `atomic = False`, par lots | **à mesurer sur PostgreSQL** (voir ci-dessous) |

**`sales/0012` sur PostgreSQL** : un seul `UPDATE` pour les ventes normales (verrou de lignes, plus de verrou de table), puis les ventes soldées par lots de 500. Non testé sur PostgreSQL. Mesure à faire sur une copie de la base cloud : `EXPLAIN (ANALYZE, BUFFERS)` de l'`UPDATE` dans une transaction annulée ; chronométrer `migrate sales` ; écritures de facture concurrentes pendant l'exécution (relever `pg_locks`) ; comparer `pg_relation_size` avant et après. Au-delà d'environ 10^6 lignes, découper aussi l'`UPDATE` par plages de pk.

## Commandes de gestion livrées (ne rien lancer sans sauvegarde)

- `check_users_sans_noeud` : lecture seule, liste les comptes de boulangerie sans boulangerie (BUG-506). À lancer sur la base réelle.
- `recompute_cump` : simulation par défaut, `--apply`, `--node`, `--force`. **Réécrit des valorisations de sorties passées** : sauvegarde et lecture de la simulation avant tout `--apply`. Jamais lancée sur une base réelle.
- `fix_mojibake_names` : simulation par défaut (prénoms au double encodage, 8 lignes dont l'adresse du nœud K3). `--apply` seulement par la personne qui détient la base réelle, après sauvegarde.

## Changements de comportement d'API

- Paramètres de requête invalides (`?node=ZZZ`, `?month=abc`, dates illisibles) : **400** `{"detail": ...}` au lieu de 500.
- `PATCH`/`PUT` d'un transfert qui change un nœud, l'auteur ou une quantité d'en-tête : 400 (BUG-522).
- Création d'un compte GERANT/FACTURIER/LIVREUR sans boulangerie : 400 (BUG-506) ; suppression d'un nœud ayant des comptes actifs, des alertes ou des preuves : 400 (BUG-414, 516).
- `deficit_report` : réservé au gérant et au-dessus, borné à sa boulangerie (BUG-521). `?page_size=` honoré, plafond 500 (BUG-333).
- Nouveaux endpoints : `POST /api/production/transfers/send/`, `GET /api/treasury/closures/versements/`.

## Avant de fusionner

1. **Vérification indépendante** (testeurs, sur l'ordre du responsable) des tickets encore à `CORRIGÉ` : BUG-380, 381, 382, 383, 526 à 529, ainsi que ceux de B livrés après le 2026-11-22 (BUG-530 à 532, 523, 517, 519, ligne 468 de `remarque.md`) ; rejeu de la matrice rôles × routes.
2. **Suite complète** `manage.py test` verte (dernière référence : 2586 tests, voir le rapport du jour), `makemigrations --check` propre, `tsc --noEmit` et `npm run build` OK.
3. **E2E** : cinq specs lisent la clôture sur `/treasury` (désormais `/cloture-journaliere`) : `06`, `18`, `21`, `22`, `24` à adapter par B ; `05-production` et la spec 32 à rejouer sur un poste avec navigateur (BUG-148 reste `CORRIGÉ`).
4. **Décisions du client en attente** : Q-022 à Q-028 (commissions, livreur, valeurs par boulangerie, tarif figé) ; BUG-513, 518, 520, 161, 278, 356 b, 253, 266 à 268, 507, 411 restent ouverts ou à clarifier. La ligne 468 de `remarque.md` (cotisation et carte en FC, défauts 2 000 et 1 000) est à faire par B.
5. **Sauvegarde de la base réelle** avant toute migration ou commande ci-dessus.

## Points connus, non bloquants

- Les tickets `CORRIGÉ` sans vérification indépendante l'ont été sur décision du responsable (testeurs à la fin).
- `Clients.tsx` (1 117 lignes) et `ClotureOperations.tsx` (environ 1 340 lignes) restent volumineux ; `Treasury.tsx` est passé de 2 895 à environ 1 370 lignes.
- Concurrence réelle (`select_for_update()`) non testable sous SQLite : couverte par séquence et espion de verrou.
- Rendu navigateur (thèmes clair/sombre/café, 360 px) non contrôlé pour les écrans modifiés ce jour ; vérification manuelle décrite dans les rapports `docs/qa/rapports/dev-frontend-2026-11-22-*.md`.
