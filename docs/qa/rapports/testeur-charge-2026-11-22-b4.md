# Rapport testeur charge et résilience, ronde b4, 2026-11-22

Cycle 3, Dev B. Aucun code applicatif modifié, aucun commit, données fictives, SQLite.
Fichier ajouté : `backend/sync/tests/test_verif_charge_v4.py` : 29 tests, 20 verts, 9 `expectedFailure` (dont 8 confirmés un par un en retirant la marque, 1 test de plage retiré car artefact SQLite). Avec v3 : 64 tests, OK. Une passe ciblée (environ 3 s).

## 1. Vérification indépendante

| Ticket | Résultat | Preuve |
|---|---|---|
| BUG-731 | VÉRIFIÉ | Cycle réel `build_outbound_payload` / push / `apply_push_response` : rejet au contrôle commun (notes de 10 500 caractères) et rejet par le handler (écart incohérent) portent `inventory`, inventaire reste non synchronisé ; ligne acceptée = inventaire synchronisé ; réponses tronquées ou `inventory` hostile (dict, entier) sans exception |
| BUG-780 | VÉRIFIÉ (avec réserve BUG-787) | Seul le client à mouvement non poussé est ignoré, l'autre est mis à jour ; mouvement synchronisé = valeur Cloud appliquée |
| BUG-781 | VÉRIFIÉ | 16 formes de réponse hostiles (None, `Infinity`, `1e999`, bool, listes, catégorie inconnue) : aucune exception, dette inchangée ; 9 curseurs serveur hostiles (dates hors calendrier, 65 caractères, `\x00`, offset +99:00) : jamais 500 |
| BUG-782 | VÉRIFIÉ en simulation | Imbrication à 3 boulangeries (V3 interrompu par V1 interrompu par V2) : 3 lignes, retenue 10 000 / 1 500 une seule fois. Verrou réel non vérifiable sous SQLite : à rejouer sous PostgreSQL |
| BUG-784 | VÉRIFIÉ | Curseur écrit dans `sync_pull_cursor.json`, relu après redémarrage simulé ; changement d'URL Cloud = pull complet ; non avancé sur exception d'application, 400, 403, 503, coupure réseau ; fichier vide, tronqué, binaire, `[]`, `null`, types faux : pull complet sans exception ; répertoire absent : pas d'exception |

Pull : aucune fuite des clients d'une autre boulangerie.

## 2. Nouveaux défauts (5 tickets)

| Ticket | Gravité | Constat |
|---|---|---|
| BUG-789 | Bloquant | Un jeton de boulangerie K1 pousse un `DisbursementVoucher` avec `node_origin='CLOUD'` : accepté, SORTIE écrite au livre de caisse du SIEGE. L'API REST le réserve au siège. Rejeu (1 seule sortie), solde insuffisant et `node_origin` d'un autre nœud : corrects |
| BUG-787 | Majeur | `recompute_client_debt` n'inclut pas `updated_at` dans `update_fields` : la dette Cloud change, le pull incrémental ne la renvoie jamais (mesuré : mouvement 700 FC accepté, pull incrémental = 0 client). Un second poste qui facture le même client garde une BP périmée (plafond, règle 5.2). Masqué avant BUG-784 par le pull complet |
| BUG-788 | Majeur | `ConsumableMovement` d'une autre boulangerie accepté (stock K2 modifié par jeton K1) ; `BreadTransfer` K2 vers K3 créé par jeton K1 ; `BreadTransferLine` existante réécrite par un jeton tiers (`quantity_received` passé à 1) |
| BUG-785 | Majeur | Curseur corrompu dans le fichier : 400 à chaque cycle, poste figé en SYNC_ERROR. Curseur dans le futur (Cloud restauré, horloge Cloud déréglée) : 200 avec 0 client indéfiniment |
| BUG-786 | Mineur | Le curseur est lié à l'URL mais pas au nœud : poste reconfiguré K1 vers K2 sur le même Cloud réutilise le curseur de K1 |

5 nouveaux tickets (BUG-785 à 789). Registre mis à jour (5 passés VÉRIFIÉ, 5 ajoutés).

## 3. Points vérifiés sans défaut
- Rejeu de lot : idempotence, 409 sur contenu différent (v3 toujours vert).
- Bordereau rejoué trois fois = une seule écriture au livre de caisse.
- Transfert connu modifié par un tiers : rejeté.
- Non fait : pic du matin sur serveur, `database is locked`, Playwright 3G, résilience par redémarrage serveur. Recommandation inchangée : PostgreSQL pour le cloud, SQLite WAL pour le poste.

## Commande
```
cd backend
export PYTHONIOENCODING=utf-8 DJANGO_DEBUG=False DJANGO_SECURE_SSL_REDIRECT=False DJANGO_SECRET_KEY=test-only-not-a-real-key-0123456789-abcdefghij
./.venv/Scripts/python.exe manage.py test sync.tests.test_verif_charge_v4 --noinput
```
