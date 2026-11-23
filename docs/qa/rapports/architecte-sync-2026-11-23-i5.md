# Rapport architecte-sync, lot I-5 (2026-11-23) : intrants sur les postes locaux

Tickets : BUG-1111 (intrants, CORRIGÉ), BUG-1112 (`facturier` d'une facture poussée, CORRIGÉ).
Fichiers modifiés : `backend/sync/services.py`, `backend/sync/views.py`, `backend/sync/desktop_client.py`,
`backend/sync/management/commands/sync_now.py`. Nouveau : `backend/sync/tests/test_dev_i5_intrants_postes.py` (17 tests).
Aucune migration (`makemigrations --check` : « No changes detected »). Rien commité.

## 1. Inventaire des données et statut de synchronisation

| Donnée | Poste -> cloud | Cloud -> poste | Verdict |
|---|---|---|---|
| `ConsumableMovement` ENTRY/EXIT (quantité, prix, fournisseur, session) | oui, UUID, rejeu idempotent, portée = son nœud | **non avant ce lot** ; oui maintenant pour les mouvements DU nœud créés au cloud (envois direction) | corrigé |
| Date d'un mouvement (`created_at`) | **non portée** : le cloud datait à l'arrivée | n/a | corrigé |
| `ConsumableStock` | jamais poussé (reconstruit au cloud par les mouvements) | jamais tiré (reconstruit au poste par les mouvements) | conforme : quantités poste = cloud vérifiées |
| `ConsumableInventory` + `ConsumableCount` (physique, écart) | oui, un par nœud et par jour, doublon journalisé | non (inutile) | conforme, sauf stock système négatif (corrigé) |
| `ProductionSession.flour_sacks_used` et `date` | oui, ouverte ou clôturée ; farine suit le poste tant que ouverte | non | conforme |
| « Consommation déclarée » (`consumables_used`) | n'est pas un champ de la fournée : c'est la création de sorties EXIT liées à la fournée (`session`) ; poussées après la fournée | non | conforme |
| Stock direction (nœud SIEGE) et ses sorties | cloud seulement | **jamais descendu** | conforme au périmètre : la ligne D1 ne peut être calculée qu'au cloud |
| Envoi direction (`consumables/dispatch/`) | sortie SIEGE + entrée boulangerie créées ensemble au cloud (appariées, vérifié) | l'entrée descend maintenant au poste concerné seulement | corrigé |
| `ConsumableType` (unités sacs/litres/g/paquets) | non | **non** | limite connue (voir §4) |

## 2. Trous trouvés (par lecture du code, confirmés par test)

1. Date des mouvements : `created_at` est la date de saisie ; non transmise au push, donc le cloud datait un mouvement poussé en retard du jour d'arrivée. Les statistiques par jour auraient été fausses au cloud seulement. Correctif : `created_at` exporté, restitué par `_stamp_movement_date` (lisible, >= 2020, non futur, sinon date d'arrivée).
2. Envois de la direction : le pull ne portait aucun consommable. Le poste ne voyait jamais l'entrée « reçu de la direction » : stock, entrée et solde comptable faux hors ligne et après synchro (écart de 20 sacs dans le scénario ; stock « système » négatif aux inventaires). Correctif : bloc additif `consumable_movements` + curseur `since_consumables` (nœud du jeton seul, émis seulement s'il y a des lignes, recouvrement de 10 min, idempotent par UUID) ; application dans `apply_pull_response`.
3. Inventaire rejeté : `system_quantity < 0` refusé au push alors que le stock peut être négatif (BUG-143) et que le REST l'enregistre. Résultat : inventaire du jour bloqué en attente, écart jamais remonté. Correctif : seule la quantité physique négative reste refusée.

## 3. Cohérence du solde et des dates (points 3 et 4)

- Solde comptable = initial + entrées − sorties : chaque ligne du jour, recalculée de façon indépendante depuis les mouvements, est identique au poste et au cloud pour K1 et K2 sur 3 jours et 4 intrants (initial, entrée, sortie, déclaré, solde, sacs de farine, inventaire physique, écart, stock courant).
- Mise à jour du stock : `ConsumableMovement.save()` dans `transaction.atomic()` avec `select_for_update()` ; sorties par `F()`, entrées par valeur calculée sous verrou. Correct ; sur SQLite un écrivain concurrent obtient « database is locked », jamais une perte silencieuse.
- Doublons : push rejoué 3 fois, pull rejoué 4 fois : aucun mouvement, inventaire, comptage ni fournée en double ; quantité de stock inchangée.
- Dates : jour d'un mouvement = date locale (Africa/Kinshasa) de `created_at`, jour d'une fournée = sa `date`. Fournées ouvertes et clôturées comptent de la même façon (somme de `flour_sacks_used`). Les mouvements poussés AVANT ce correctif gardent leur date d'arrivée au cloud (pas de rattrapage).
- Écart d'inventaire : `gap` est un instantané figé à la saisie. Dans le scénario K1 compte 22 sacs hors ligne avant d'avoir reçu l'envoi de 20 : `gap` = 28,5 (identique poste et cloud) alors que physique − solde complet = 8,5. **Les lots I-1/I-3/I-4 doivent recalculer l'écart (reste déclaré − solde comptable du jour) et non lire `gap`.**
- Point 2 : un poste ne reçoit pas le stock ni les mouvements de la direction. Il n'a donc pas à afficher la ligne D1 ; c'est une vue cloud. Le poste voit seulement ses propres entrées, dont l'envoi de la direction.

## 4. Limites et décisions pour le coordinateur

- `ConsumableType` ne descend pas. Les 4 types sont semés par la migration `production/0010` sur chaque poste ; un type ajouté ou une unité changée au cloud n'arrive pas. Le faire descendre ajoute une clé au pull, ce qui casse `TOP_KEYS` de `clients/tests/test_clients_v13.py` (dossier interdit pour ce lot). Je n'ai donc rien fait : décision à prendre.
- Les modifications ou suppressions de mouvements faites au cloud ne descendent pas (seules les créations).
- Pagination du bloc : 1000 lignes par pull ; au-delà, reprise au cycle suivant.

## 5. BUG-1112 : `facturier` des factures poussées

`_resolve_invoice_staff` : UUID strict, utilisateur existant, rôle FACTURIER/LIVREUR/GERANT/COMPTABLE/DIRECTION/ADMIN, même boulangerie (rôles sans rattachement acceptés), sinon NULL sans rejeter la facture. Même règle pour `livreur`. Facture déjà connue : champ vide renseigné, jamais écrasé. `build_outbound_payload` exporte `facturier` et `livreur`. Poste ancien sans la clé : accepté, NULL (comportement d'avant).

## 6. Résultats RÉELS des tests

Log : `%TEMP%/i5.log` (et `i5b.log`).

| Suite | Résultat |
|---|---|
| `sync.tests.test_dev_i5_intrants_postes` + `test_verif_sync_v5` + `test_verif_sync_v6` + `production.tests.test_verif_production_a15_v15` + `a16_v16` + `test_sync_transfers_d43` (une seule passe) | **76 tests, OK** (205 s) |
| `makemigrations --check --dry-run` | « No changes detected », code 0 |
| Régression sync : `test_consumable_inventory_sync`, `test_consumables_prices_resilience_v2`, `test_hostile_payloads_v2`, `test_sync`, `test_bug146_exit_before_entry`, `test_dev_b1030_node_settings` | 104 tests, OK (2 échecs attendus déjà présents) |

Tests du nouveau fichier : banc K1/K2/cloud + direction sur 3 jours (toutes les lignes poste = cloud), D1 cloud seul et envois appariés, **témoin sans le pull des envois : le poste diverge de 20 sacs** (preuve que le test échoue sans le correctif), dates d'origine (poste ancien, date future, année 1999, texte : date d'arrivée), push rejoué 3 fois, pull rejoué 4 fois, coupure avant le pull puis reprise, envoi direction après une première synchro, aucune donnée d'une autre boulangerie ni du stock SIEGE, application défensive (lignes invalides), inventaire à stock système négatif accepté et physique négatif refusé, 6 tests BUG-1112. Données fictives uniquement.

Les suites complètes `python manage.py test` et `npm run build` n'ont pas été relancées (périmètre : sync et les suites demandées).
