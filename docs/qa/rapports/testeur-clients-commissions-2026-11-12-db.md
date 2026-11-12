# Rapport testeur Clients et Commissions — base réelle, K4 — 2026-11-12

Périmètre : `clients/`, `commissions/`, pages Clients et Commissions. Base `db.sqlite3` (backend :8000, Vite :5173 déjà lancés), boulangerie K4. Comptes créés : `zz_clients_gerant`, `zz_clients_facturier` (K4), `zz_clients_comptable`. Clients fictifs « ZZTEST Clients n » / « ZZTEST Import … ». Aucun des clients réels n'a été modifié ni supprimé (lecture, recherche, et K3-0044 consulté par le facturier K4). Aucun migrate/SQL d'écriture, pas de `reset-data`, aucun git.

## Résultats par scénario

| Scénario | Résultat |
|---|---|
| Code unique auto (`K4-NNNN`), code/nœud forcés dans le payload ignorés | OK |
| Création simultanée (10 threads) : 10 codes uniques | OK |
| Plafond par défaut 50 000 FC ; PATCH par gérant/comptable/admin ; refusé au facturier (403, aussi téléphone et DELETE) | OK |
| Recherche prédictive : nom partiel, code, casse ; facturier K4 trouve un client K3 (code et nom) ; gérant K4 ne voit pas K3 | OK |
| Catégories : 999 pains = Normal, 1 000 = Meilleur client (seuil Config 1000) ; dette = plafond -> À risque ; À risque prioritaire sur Meilleur ; passage À risque à la livraison ; remboursement -> Normal | OK |
| Blocage plafond : BP >= plafond et versement < commande -> 403 ; versement = commande accepté | OK |
| Types : VENTE SOLDE (75 %, CM 0), vente occasionnelle, épargne (BP -5 000 puis -4 000), RG/NS (CM 0, NS jamais livrée) | OK côté ventes ; RG KO côté commissions (BUG-261) |
| Photo : image valide acceptée, `.txt`/`.php` refusés | OK ; taille non limitée (BUG-258) |
| Validation des champs client | KO : plafond négatif, taux 0,99, cotisation négative acceptés (BUG-257) ; BP et total pains modifiables à la main (BUG-259) |
| Import Excel (fichier fictif généré : feuille K4, doublons casse/espaces, ligne vide, nœud inconnu K9, feuille libre) : dry-run, import 4 créés, réimport 0 créé, gérant/facturier 403, fichier non Excel 400, sans fichier | OK |
| Caisse sociale : cotisations (doublon 400, nœud imposé, toggle payé/impayé), distribution (doublon 400, clôture bloque `auto_populate`) | OK ; validations absentes (BUG-260) |
| Caisse sociale : `auto_populate_lines` / `bulk_create_month` / création de ligne | KO au début de la vague (0 client, 500) = BUG-256 / BUG-254 déjà ouverts, corrigés en cours de session et revérifiés (voir ci-dessous) |
| CM brute 25 % et 30 % (valeurs à la main : 5 000 x 0,25 = 1 250 ; 16 000 x 0,30 = 4 800) | OK |
| Retenues : dette + sociale + imprimés + autre (+ CARTE 1 %) : 5 000 + 3 000 + 0 + 0 + 12,50 = 8 012,50 ; net = 1 250 - 8 012,50 = -6 762,50 | OK |
| Remise annuelle 0,025 x pains livrés (10 -> 0,25 ; 26 -> 0,65), incorporée : net +0,25 | OK |
| Totaux verticaux du listing (valeur 24 500, CM 6 925 ; historique `total_payments` 23 750) = somme des lignes | OK |
| VENTE SOLDE, exonérée, occasionnelle : exclues de la base de CM | OK |
| Cohérence factures livrées : valeur de période = somme des factures livrées non solde | OK |
| Périodes : génération (gérant/facturier 403), régénération idempotente (6 lignes), clôture, régénération refusée sur période clôturée | OK |
| Report de dette (net négatif repris le mois suivant, BUG-122) | OK techniquement ; double comptage de la BP (BUG-268) |
| Pagination déterministe : 721 clients lus par pages de 25, tri par défaut, `last_name`, `current_debt` (nombreux ex æquo), recherche `a` (469) : lus = count = uniques ; commissions idem | OK |
| Interface 360 px et 1440 px (Playwright, `--output` perso) : Clients (20 lignes puis Voir plus 40, 60, sans doublon de code, recherche ZZTEST), facturier K3-0044, page Commissions | OK, aucun débordement horizontal. Un premier passage 360 px a été redirigé vers /login après `goto('/clients')` (non reproduit au second passage, probablement lenteur/jeton) |
| KPI de la page Clients pendant le chargement progressif | KO : « 25 fiches », « 4 000 FC » présentés comme définitifs (BUG-269) |
| KPI page Commissions | Montants négatifs « payées -8 147,75 FC » (BUG-266) |

Captures : `docs/qa/captures/clients-vague2-*.png`, `commissions-vague2-*.png`. Spec : `e2e/tests/14-clients-commissions-vague2-db.spec.ts` (3 tests verts à 1440 et 360 px).

## Tickets ouverts (BUG-257 à BUG-269)
Majeur : 257 (validation montants/taux clients), 259 (BP et total pains modifiables), 261 (RG compte dans la CM : 125 FC), 262 (PATCH commission : négatifs, taux 0,90), 263 (commission payée / période clôturée modifiables et supprimables), 264 (régénération écrase les retenues saisies), 265 (comptable peut `mark_paid` et `set_manuel`, `get_permissions` écrase `IsDirection`).
Mineur : 258 (photo 12 Mo acceptée), 260 (caisse sociale : mois 13, montants négatifs, clôture réversible), 269 (KPI Clients partiels).
À CLARIFIER (client) : 266 (net négatif marqué payé), 267 (client épargne : son épargne ressort en net à payer +4 000 FC), 268 (double comptage dette BP + report).
Déjà ouverts par testeur-permissions et recoupés : 250 (facturier fixe le plafond à la création), 253 (facturier lit les commissions : 6 lignes K4 constatées).

## Tickets rejoués
- BUG-172 : VÉRIFIÉ (pagination déterministe, clients et commissions, UI 360/1440).
- BUG-254 : VÉRIFIÉ (POST ligne de distribution 201 ; remise 3 x 700 = 2 100 ; total 11 600 ; PATCH indice 5 -> 3 500 / 13 000).
- BUG-256 : VÉRIFIÉ (`auto_populate_lines` K4 : 127 lignes créées ; `bulk_create_month` non rejoué en réel pour ne pas écrire sur les clients réels, couvert en base de test).
- BUG-164 : volet Commissions vérifié, statut laissé CORRIGÉ (autres modules).
- BUG-163, 082 : hors périmètre ou non rejouables.

## Tests automatisés
- `backend/clients/tests/test_vague2_db_clients_2026_11_12.py` (16 tests, dont 4 `@expectedFailure` pour 257, 258, 259, 260 après retrait de 254/256 devenus verts) et `backend/commissions/tests/test_vague2_db_commissions_2026_11_12.py` (9 `@expectedFailure` pour 253, 261 à 268, plus 7 tests verts de formules, totaux, droits, report).
- `python manage.py test clients commissions` : 128 tests, 13 échecs attendus, 2 succès inattendus (254, 256) qui ont ensuite été retirés des `@expectedFailure` (changement de décorateur seulement, suite non relancée une 3e fois).
- Fabriques : `core/testing.py` réutilisé, rien dupliqué.

## Nettoyage et réserves
- Supprimés : distribution sociale 2098, ses 127 lignes et les cotisations d'essai ; périodes de commissions K4 02/2026 et 03/2026 ; 21 clients ZZTEST sans facture. Restent 7 clients ZZTEST K4 (K4-0103 à 0108, 0116) désactivés : ils portent des factures livrées (non supprimables par l'API). Les factures ZZTEST (février et mars 2026, K4) restent, ainsi que des factures en attente créées pour le test du plafond. Quelques fichiers photo de test dans le dossier media du backend. Les trois comptes `zz_clients_*` sont conservés.
- Config réelle : `debt_ceiling = 500 000` (alors que la règle métier est 50 000 FC par défaut ; le plafond client reste 50 000) à faire confirmer par le coordinateur.
- Le serveur a eu des coupures de connexion ponctuelles (rechargement ou charge partagée) ; les scripts ont réessayé.
