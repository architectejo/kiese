# Rapport testeur charge et résilience, ronde b3, 2026-11-22

Cycle 2, Dev B. Aucun code applicatif modifié, aucun commit, données fictives, SQLite.
Fichier ajouté : `backend/sync/tests/test_verif_charge_v3.py` : 35 tests, 28 verts, 7 `expectedFailure` (un ticket chacun). Une seule passe ciblée (environ 20 s).

## 1. Vérification indépendante des corrections

| Ticket | Résultat | Preuve |
|---|---|---|
| BUG-720 lot mal formé | VÉRIFIÉ | 8 formes de valeurs de modèle : aucun 500 |
| BUG-721 bornes | VÉRIFIÉ | 40 chiffres, ±10^12 rejetés ; cumul à 999 999 999 999 puis +999 999 999 999 rejeté ; liste clients reste 200 |
| BUG-722 portée | VÉRIFIÉ | clôture K2 par jeton K1 rejetée, 0 écriture au livre de caisse ; `node_origin` forgé et `node` non texte rejetés |
| BUG-723 occurrences | VÉRIFIÉ | 5 rejeux = 1 ligne, `occurrences=5` |
| BUG-724, 725, 727 | VÉRIFIÉ | mouvement rejoué avec un autre montant rejeté, dette intacte |
| BUG-726 idempotence | VÉRIFIÉ | rejeu identique `replayed`, 1 `SyncBatchLog`, 0 doublon ; ordre des clés sans effet sur l'empreinte ; contenu différent = 409 sans rien appliquer ; `batch_id` d'un autre nœud = lot appliqué, aucune fuite ; lot vide puis non vide = 409 |
| BUG-728 dette d'ouverture | VÉRIFIÉ | 20 000 + 1 000 = 21 000 |
| BUG-730 | VÉRIFIÉ | second jeu de valeurs rejeté, 1 seule ligne |
| BUG-733 | VÉRIFIÉ (côté push) | voir BUG-781 pour la descente |
| BUG-735 | VÉRIFIÉ | espion : `select_for_update` émis sur `ClientCommission` ; double `mark_paid` = 400 ; `set_manuel` après paiement = 400 (SQLite sans verrou réel : à rejouer sous PostgreSQL) |
| BUG-736 | VÉRIFIÉ | 8 jeux de paramètres hostiles (mois 13, bool, flottant, liste, entier géant, `'1e1'`) : tous 400 |
| BUG-737 (retenue unique) | TIENT en séquence | 3 régénérations dans les deux ordres : total 10 000 / 1 500 ; mais voir BUG-782 et 783 |
| BUG-743 KIESE_FOLD | TIENT | NULL, entier, NFD, `ß`, 100 000 caractères, connexion de thread ; recherche sur 5 000 clients : 107 à 156 ms, au plus 5 requêtes (objectif 300 ms respecté) |
| BUG-731 | ROUVERT | voir ci-dessous |
| BUG-729, 732c, 734 | restent OUVERTS | décisions métier ou pagination en attente, non retestés |

## 2. Nouveaux défauts

| Ticket | Gravité | Constat |
|---|---|---|
| BUG-731 (rouvert) | Majeur | La clé `inventory` n'est posée que par le handler. Un rejet au contrôle commun (ex. `notes` de plus de 10 000 caractères, réponse `{"id":"None","status":"REJECTED"}`) laisse l'inventaire marqué synchronisé : ligne perdue. Reproduit par un cycle réel `build_outbound_payload`, push, `apply_push_response`. |
| BUG-780 | Majeur | Le pull écrase la dette locale par la valeur Cloud, même avec un mouvement local non poussé (1 500 redescend à 1 000). BP et contrôle de plafond faux pendant au moins un cycle. |
| BUG-782 | Majeur | Course de `generate` entre deux boulangeries : double retenue (20 000 et 3 000 FC au lieu de 10 000 et 1 500). Interleaving simulé, à rejouer sous PostgreSQL. |
| BUG-784 | Majeur (perf) | Le desktop n'envoie jamais le curseur de pull : tous les clients à chaque cycle de 30 s. 5 000 clients : 884 Ko, 209 à 387 ms, 15 requêtes ; environ 125 Ko par cycle pour 700 clients. |
| BUG-781 | Mineur | `apply_pull_response` lève `KeyError` sur réponse tronquée ; `since_client_debt=9999-99-99T00:00:00` donne 500. |
| BUG-783 | Mineur | Si la ligne qui retenait la BP est supprimée puis la période régénérée, plus aucune retenue (0 au lieu de 10 000). |

Total : 5 nouveaux tickets (BUG-780 à 784) et 1 réouverture (BUG-731).

## 3. Autres mesures et constats

- Pas de N+1 sur le pull : 15 requêtes pour 5 000 clients, constant.
- Lots partiels : une dépendance manquante rejetée reste figée dans le lot archivé (rejeu du même `batch_id` renvoie le rejet) ; seul un nouveau `batch_id` la rattrape, ce que `sync_now` fait. Comportement cohérent, test vert.
- Le 409 est traité en définitif par `desktop_client` (lot abandonné, reconstruit au cycle suivant) : pas de boucle infinie.
- Non fait : pic du matin sur serveur, `database is locked` avec et sans WAL, Playwright 3G. Recommandation moteur inchangée : PostgreSQL pour le cloud, SQLite WAL pour le poste.

## Commande

```
cd backend
export PYTHONIOENCODING=utf-8 DJANGO_DEBUG=False DJANGO_SECURE_SSL_REDIRECT=False DJANGO_SECRET_KEY=test-only-not-a-real-key-0123456789-abcdefghij
./.venv/Scripts/python.exe manage.py test sync.tests.test_verif_charge_v3 --noinput
```
