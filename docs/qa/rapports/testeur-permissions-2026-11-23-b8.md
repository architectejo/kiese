# testeur-permissions, cycle 21 (ronde b8), 2026-11-23 : LIVREUR vs FACTURIER vs GERANT (BUG-1106, BUG-1203)

Tests : `backend/core/tests/test_verif_permissions_b8_v8.py` (33 tests : OK, 4 expectedFailure). Log `$TEMP/p21.log`.
Matrice brute (JSON) : `$TEMP/p21_matrix.json` (variable `P21_OUT`). Code applicatif non modifié.

## 1. Matrice dynamique (267 routes x méthodes de /api/, hors jetons de noeud sync et login)
Énumération automatique (EndpointEnumerator), appels réels GERANT / FACTURIER / LIVREUR (même boulangerie K1).

| Groupe | Routes | Lecture |
|---|---|---|
| Les trois passent | 54 | écrans communs (clients list/detail/create, factures lecture/deliver/not_served, production lecture, config, prix, nodes, me, chat) |
| GERANT seul passe | 121 | commissions, caisse sociale, trésorerie, inventaires, mouvements, modification/suppression de clients, etc. : FACTURIER et LIVREUR identiques (403) |
| Aucun des trois | 86 | admin, finance, blockchain, users, reset |
| **FACTURIER passe, LIVREUR 403** | **6** | voir ci-dessous |
| LIVREUR passe, FACTURIER refusé | **0** | « rien de plus » respecté |
| GERANT refusé et LIVREUR/FACTURIER passe | 0 | hiérarchie respectée |
| 5xx | 0 | |

Routes FACTURIER oui / LIVREUR 403 (le rapport frontend en citait 5 ; la 5e, `clients create`, est corrigée par B-3 et vérifiée) :

| Route | Code | Ticket | Propriétaire |
|---|---|---|---|
| POST `/api/sales/invoices/` | sales/views.py ~l.304 | BUG-1023 | dev-a (sales) |
| POST `/api/sales/invoices/{pk}/cancel/` | sales/views.py ~l.1007 | BUG-1024 | dev-a (sales) |
| GET et POST `/api/production/opening-confirmation/` | production/views.py ~l.3626 | BUG-1025 | dev-a (production) |
| GET et POST `/api/production/team-assignment/` | production/views.py ~l.4023 | BUG-1026 | dev-a (production) |

Chaque écart a un test `@expectedFailure` (contrôle positif : le FACTURIER passe ; assertion : le LIVREUR ne reçoit pas 403). Le test de matrice échoue si un nouvel écart apparaît, ou si un écart répertorié disparaît (invitation à retirer l'expectedFailure).

Contrôles positifs vérifiés pour le LIVREUR : création de client (201) rattachée à SA boulangerie même avec `node` forcé vers K2, plafond 50 000 et taux imposés (identique au FACTURIER) ; modification, PUT, DELETE, bulk_delete, bulk_move, import_excel, recalculate_category, history, deficit_report : 403 ; commissions, utilisateurs, trésorerie, finance, PATCH config, POST bread-prices : refusés.

## 2. BUG-1106 : connectivité (sync/connectivity.py), résultat VÉRIFIÉ
- Cloud (aucun `KIESE_CLOUD_URL`) : toujours en ligne ; poste local : fenêtre 15 min, bornes exactes (900 s oui, 901 s non).
- Cas limites, aucun 500 : état corrompu (`'x'`, None, nan, +/-inf, négatif, 1e30, dict, liste, bool, chaîne date) = hors ligne ; état absent ; fenêtre invalide (`0`, `-5`, `nan`, `abc`, vide, None, `[]`, `{}`, `'  '`) retombe sur 15 ; fenêtre `inf`/`1e999`/10^12 : accepté sans erreur (toujours en ligne après un seul échange : choix de configuration, voir observations) ; `Node.last_sync` absent ou None ; nœud None ; livreur sans boulangerie : liste vide, détail 404.
- Horloge : `last_sync` ou échange dans le futur (retour d'horloge) = hors ligne, sans erreur.
- Bascule en ligne puis hors ligne dans la même session : détail d'un client de K2 200 puis 404.
- Pas d'oracle d'existence : GET/PATCH/PUT/DELETE sur un client de K2 existant ou sur un UUID inexistant donnent exactement le même code et le même corps pour le livreur hors ligne.
- Recherche (nom, code, téléphone, `node=`, tris, filtres), `risk_alerts`, `best_clients`, `active_last_month`, `bassins?node=K2` : aucune fuite hors ligne.
- Création hors ligne avec l'identité exacte d'un client de K2 (même nom et téléphone) : la réponse ne révèle ni code, ni UUID, ni boulangerie du client de K2.
- Balayage de TOUTES les routes GET (plus de 200 appels, avec le nom, le téléphone, le code et l'UUID d'un client de K2, sa facture, sa commission, sa période, sa cotisation, avec et sans paramètres `search/q/client/node/month/year`) : zéro fuite pour le livreur hors ligne. Le contrôle positif (même balayage avec un FACTURIER) détecte bien le client de K2 : le balayage n'est pas aveugle.
- `history`, `commissions`, export, liste d'import : `history` et commissions sont IsGerant (livreur 403 avant tout filtrage) ; `import_excel` IsHeadquarters ; aucune route d'export de clients n'existe côté `clients`.
- Facturier et gérant inchangés hors ligne.

## 3. JWT du livreur : identique aux autres rôles
Access 30 min, refresh 7 jours (mêmes durées que le FACTURIER) ; rotation + blacklist (réutilisation d'un refresh : 401) ; refresh après logout : 401 ; jeton expiré : 401 ; `PATCH /auth/me/` avec `role`, `is_superuser`, `node` : sans effet ; limitation de login par compte : 429 au-delà de 5/min, un autre compte non bloqué.

## 4. BUG-1203 frontend (lecture statique, pas de navigateur)
`App.tsx` : `FIELD_ROLES` = six rôles sur les 4 routes ; `DashboardLayout.tsx` : Gestion Clientèle et Facturation incluent LIVREUR ; boîtes de stock de départ / fin de relève ouvertes au LIVREUR. Cohérent avec la matrice : tant que BUG-1023 à BUG-1026 sont ouverts, le livreur voit les boutons « créer facture », « annuler », « stock de départ », « équipe » et reçoit 403.

## Statuts du registre
- BUG-1106 : VÉRIFIÉ (backend). Reste optionnel : indicateur « hors ligne » côté frontend.
- BUG-1203 : PARTIELLEMENT VÉRIFIÉ (menus, routes, clients create) ; volet backend restant = BUG-1023 à BUG-1026.
- Nouveaux tickets : 4 (BUG-1023, BUG-1024, BUG-1025, BUG-1026), tous Majeur, propriétaire dev-a. Aucun ticket dev-b, aucun bloquant (pas de fuite inter-nœuds, pas d'élévation).

## Observations (sans ticket)
1. L'état « en ligne » est la mémoire du processus (`desktop_client._STATE`) ou `Node.last_sync` : après redémarrage du poste, le livreur est hors ligne jusqu'au premier cycle réussi (limite déjà documentée par B-3). Avec `KIESE_ONLINE_WINDOW_MINUTES` valant `inf`/`1e999`, le poste serait « en ligne » indéfiniment après un seul échange : à éviter dans la configuration (aucune validation de borne supérieure).
2. L'état « en ligne » persiste jusqu'à 15 minutes après une coupure réelle (`connection = OFFLINE` n'est pas consulté) : conforme à la fenêtre voulue, à confirmer avec le client si « SEULEMENT en ligne » doit être immédiat.
3. L'horloge utilisée est `time.time()` (heure murale) : un retour d'horloge de quelques secondes (NTP) rend le poste hors ligne jusqu'au prochain échange.
4. Quand BUG-1023 sera corrigé : vérifier que `Invoice.facturier` = le livreur est accepté par la synchronisation (les contrôles de rôle de `sync/services.py` ne visent aujourd'hui que les rapports de facturier) et que les reçus portent bien le livreur comme émetteur.
5. Le test v2 modifié par B-3 (`CreationTests::test_livreur_cree_client_dans_sa_boulangerie_seulement`) est cohérent avec la décision Q-027 : accepté.
