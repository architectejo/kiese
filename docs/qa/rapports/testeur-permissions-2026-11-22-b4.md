# Rapport testeur-permissions (Dev B), 2026-11-22, ronde b4

Fichier de tests : `backend/core/tests/test_verif_permissions_b4_v4.py` (56 tests, données fictives, aucun code applicatif modifié).
Résultat : 54 OK + 2 `@expectedFailure` (BUG-761, BUG-762). Dernier passage : `Ran 56 tests ... OK (expected failures=2)`.
Commande : `manage.py test core.tests.test_verif_permissions_b4_v4 --noinput` (environnement imposé, journal `b4perm.log`, car `x.log` est partagé avec les autres testeurs).

## 1. Vérification BUG-760 : VÉRIFIÉ
`DELETE /api/clients/clients/<id>/` sur un client référencé renvoie 400 avec `{"detail": ...}` et le client subsiste : ligne de distribution sociale, facture, et commission (GERANT, COMPTABLE, DIRECTION, ADMIN). Client libre : 204 pour le gérant du nœud ; anonyme 401 ; FACTURIER/LIVREUR 403 ; gérant d'un autre nœud 404 ; identifiants forgés (`NIL`, UUID inconnu, `abc`, `1`, `%27`) sans 5xx. Registre mis à jour.

## 2. Matrice rôles x routes (anonyme, ADMIN, DIRECTION, COMPTABLE, GERANT, FACTURIER, LIVREUR)
Attendu = observé sur toutes les lignes ; aucune ligne en 5xx hors BUG-762.

| Route | Méthode | Autorisés | Autres |
|---|---|---|---|
| commissions/periods, periods/<id> | GET | GERANT et au-dessus (gérant : son nœud seul) | 403 ; anonyme 401 |
| commissions/periods | POST, PATCH, DELETE, `generate`, `history`, `<id>/close_period` | ADMIN, DIRECTION, COMPTABLE | 403 |
| commissions/commissions, `<id>`, `summary` | GET | GERANT et au-dessus | 403 |
| commissions/commissions | POST, PATCH, DELETE, `payroll_listing` | ADMIN, DIRECTION, COMPTABLE | 403 |
| commissions `<id>/mark_paid`, `<id>/set_manuel` | POST, PATCH | ADMIN, DIRECTION | COMPTABLE 403 |
| clients `<id>` | DELETE | GERANT et au-dessus (nœud propre) | FACTURIER/LIVREUR 403 |
| sales `<id>/adjust` | POST | GERANT et au-dessus (gérant : son nœud, 404 sinon) | FACTURIER/LIVREUR 403 |
| treasury closures `<id>` | PATCH, PUT | GERANT et au-dessus (nœud propre) | FACTURIER/LIVREUR 403 |
| treasury closures `validate`, `reject`, `push_to_cashbook` | POST | ADMIN, DIRECTION, COMPTABLE | GERANT et inférieurs 403 |
| treasury `cashbook/integrity_check`, `cashbook` | GET | ADMIN, DIRECTION, COMPTABLE | 403 ; écriture 403/405 pour tous |
| blockchain alerts, `resolve`, snapshots, `run_check`, `global_status` | GET/POST | ADMIN, DIRECTION, COMPTABLE | 403 ; alertes en lecture seule (POST/PUT/PATCH/DELETE : 405 pour le siège) |
| sync `pull`, `push`, `status`, `handshake` | GET/POST | jeton de nœud actif uniquement | JWT humain (même ADMIN) 401/403 ; jeton inconnu, vide ou révoqué 401 |
| sync `conflicts` | GET | ADMIN, DIRECTION, COMPTABLE | 403 ; jeton de nœud refusé |

## 3. Isolation entre nœuds et identifiants forgés (aucune fuite)
- Commissions : le gérant K1 ne voit ni la commission, ni la période de K2 (liste et détail en 404, filtres `period__node`, `period`, `client` forcés vers K2 vides) ; `summary` ne totalise que K1 (count 1 contre 2 pour le siège) ; le gérant K2 ne peut ni modifier, ni supprimer, ni clôturer les objets de K1 (403). `mark_paid`/`set_manuel` : 403 pour le gérant, y compris sur son propre nœud.
- Ventes `adjust` : `node`, `facturier`, `status`, `receipt_number`, `node_origin`, `client` forgés dans le corps ignorés (l'ajustement garde le nœud et le client de l'origine) ; gérant K2 sur facture K1 : 404 ; 15 variantes de corps hostiles (signe, montants, lignes) sans 5xx et sans ajustement créé.
- Résoumission de clôture : `is_validated`, `is_rejected`, `node`, `node_origin`, `gerant`, `cash_gap`, `net_cash`, `total_entries`, `physical_cash_total` forgés dans le PATCH ignorés (totaux recalculés, journal d'activité écrit, BUG-860 tenu) ; gérant K2 sur clôture K1 : 404 ; une clôture confirmée est figée pour tous les rôles (PATCH 400, DELETE 403) ; `validate`/`reject`/`push_to_cashbook` refusés au gérant, au facturier, au livreur et au gérant K2.
- Sync pull : le jeton K1 ne reçoit pas les clients de K2 sans facture K1 (et inversement) ; un client facturé par K1 descend (règle remarque.md) ; aucun secret ni donnée tierce dans la charge ; curseurs hostiles (texte, 100 caractères, mois 13, année 10000, injection, `%00`, fuseau +99) : 200 ou 400 jamais 500 ; `node=K2` forcé sans effet ; un curseur futur renvoie un pull complet mais borné au nœud (comportement voulu BUG-785).
- Sync push : `node` ou `node_origin` d'une autre boulangerie, y compris sous forme de liste, REJECTED ; un nœud ne réécrit ni client, ni facture, ni clôture d'un autre nœud ; `is_validated` forgé sur une clôture de K2 sans effet et aucune écriture de livre de caisse ; modèle inconnu (`core.User`) ignoré sans élévation ; `batch_id` identique sur deux nœuds non mutualisé ; même `batch_id` avec contenu différent : 409.
- Blockchain : `is_tampered` et montants non forgeables (livre en lecture seule) ; `integrity_check` marque puis lève le drapeau après restauration (BUG-861), sans notification en double (BUG-842) ; `run_check` accepte les paramètres hostiles (`node` booléen, flottant, liste, objet, énorme) sans 5xx, écrit au journal (BUG-837) ; `resolve` journalisé et refusé une seconde fois.

## 4. Rôle COMPTABLE
- Lecture seule sur les mouvements de stock : GET 200, POST 403, stock inchangé (BUG-706 tenu).
- Écriture commissions (décision : À CLARIFIER) : état constaté inchangé. Le COMPTABLE peut POST/PATCH/DELETE une commission et une période (`IsHeadquarters`), `generate` compris. Il ne peut pas utiliser `set_manuel` ni `mark_paid`. `manuel_adjustment`, `is_paid`, `net_payable` forgés dans son PATCH ou dans un POST siège sont ignorés (testé).
- `bulk_move`, `bulk_delete`, `import_excel` : restent ouverts au COMPTABLE (constat de b3, toujours en attente de décision).

## 5. Nouveaux tickets
| Ticket | Gravité | Résumé | Test |
|---|---|---|---|
| BUG-761 | Mineur | `NodeAuthToken.issue_for_node` lève `IntegrityError` dès qu'un nœud a déjà un jeton (actif ou révoqué) : contrainte `OneToOne` sur `node`. Un jeton de nœud compromis ne peut pas être remplacé par la méthode prévue. | `SyncAuth::test_BUG_761_reissue_token_for_node_rotates` (`@expectedFailure`) |
| BUG-762 | Mineur | Corps JSON non objet (`[]`, `5`, et `"x"` pour `reject`) -> 500 sur `set_manuel`, `mark_paid`, `periods/generate`, `closures/validate`, `closures/reject`, `clients/bulk_delete`, `clients/bulk_move`. Même schéma que BUG-187/194/561. Siège seulement, aucune écriture. | `CommissionsMatrix::test_BUG_762_non_object_json_body_is_400_not_500` (`@expectedFailure`) |

Aucun ticket bloquant : ni fuite inter-nœuds, ni élévation de droits, ni accès non authentifié inattendu.

## 6. Constats sans ticket
- Le gérant K1 qui lance `run_check?node=K2` après une falsification d'une écriture de K1 voit K2 signalé : c'est voulu (`verify_cashbook_chain` n'avance pas le hash après un bloc invalide, donc tous les blocs suivants de la chaîne globale sont signalés). L'écriture de K1 n'est jamais imputée à K2. À garder en tête pour l'interprétation des alertes.
- Un jeton de nœud qui pousse SA clôture avec `is_validated=True` la fait promouvoir au livre de caisse par le Cloud, sans confirmation du comptable (comportement testé dans `test_sync.py`, SYNC.md §0). Cohérent avec BUG-722 (propriété du nœud contrôlée), mais cela contourne la règle « confirmation = siège » de BUG-200 pour quiconque détient le jeton d'un nœud. À confirmer avec le coordinateur et le client (question de confiance dans les postes locaux, non tranchée ici).
- `x.log` dans `$TEMP` est partagé entre testeurs : une exécution parallèle a écrasé mon journal une fois. J'ai utilisé `b4perm.log`. Les échecs de `sync.tests.*` vus dans ce journal provenaient d'un autre agent (fichiers `sync/*` modifiés dans l'arbre de travail), pas de ma suite.

## 7. Numérotation
Plage 760+ : 761 et 762 utilisés ; le registre contient aussi 780 à 789 (autres agents). BUG-760 passé à VÉRIFIÉ.
