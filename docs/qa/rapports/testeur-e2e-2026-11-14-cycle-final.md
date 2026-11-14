# Testeur E2E - cycle final (2026-11-14)

Base : `db.sqlite3` (backend 8000, Vite 5173 non redémarrés). Comptes `zz_*` autorisés par l'utilisateur (aucun mot de passe consigné). Plafond de crédit lu en base : 50 000 FC. Playwright avec `--output` personnel (dossiers temporaires supprimés après usage, car les traces du test BUG-284 contiennent un mot de passe temporaire), sans `PLAYWRIGHT_BROWSERS_PATH`.

## Matrice parcours x taille d'écran

| Parcours | pos 360 | tablette 768 | bureau 1440 | tv 1920 |
|---|---|---|---|---|
| 1a. FACTURIER K4 : menu sans Trésorerie/Commissions, `/treasury` et `/commissions` refusés, facture, BP avant, livraison, reçu complet | vert | vert | vert | vert |
| 1b. LIVREUR K4 : mêmes contrôles + livraison de la file + reçu | vert | vert | vert | vert |
| 2. GÉRANT K4 : rapports A/B/sans équipe, dépense 2 000 FC, billetage, écart +500 FC affiché, création de la clôture | lecture seule vert | lecture seule vert | vert (création) | lecture seule vert |
| 3a. Commissions direction : « Net négatif » sans « Régler », fiche sans bouton, API `mark_paid` 400 | vert | vert | vert | vert |
| 3b. Commissions comptable : aucun bouton « Régler » | vert | vert | vert | vert |
| 4. BUG-277 : transfert en litige bloque la confirmation de clôture, résolution K3, confirmation, inscription au livre | non rejoué | non rejoué | vert | non rejoué |
| 5. BUG-281 : libellé « Équipe de service de la période : B (relève de 12:00) » (gérant K3) | vert | vert | vert | vert |
| 6. BUG-284 : écran bloquant, ancien mot de passe faux, succès, `/sales` facturier sans 403 | vert | vert | vert | vert |
| 7. Plafond 50 000 FC : BP = 50 000 pile bloque (message écran + API 403 + notification), BP 49 500 non bloqué | vert | vert | vert | vert |
| 8. Livre de caisse : écriture 13 000 FC, solde, « Chaîne intègre — Aucune altération détectée » | non rejoué | non rejoué | vert | non rejoué |
| 9. BUG-253 volet UI : aucun appel Trésorerie/Commissions pour FACTURIER/LIVREUR | vert | non rejoué | vert | non rejoué |
| 10. BUG-253 volet UI : aucun 403 sur Clients/accueil/Facturation | rouge (BUG-300) | - | rouge (BUG-300) | - |

Les parcours à état unique (clôture K4 du jour, transfert en litige, livre de caisse) n'ont été joués que sur le bureau ; la clôture ne peut être créée qu'une fois par jour et par boulangerie. Aucun résultat rouge sur les autres cellules, mais deux faux rouges de ma suite (pas de l'application) ont été corrigés : modale « Stock de départ du jour » qui se rouvre après rechargement (le test la reporte maintenant avant chaque recherche) ; délais de navigation de 15 s trop courts pour le serveur de dev (portés à 90 s dans `e2e/playwright.config.ts`).

## Détails vérifiés

- Plafond 50 000 FC : client à BP 50 000 FC pile, 2e facture sans versement : bandeau « Plafond de crédit atteint (50,000 FC >= 50,000 FC) », et l'API répond 403 « Plafond de crédit atteint (50,000 FC ≥ 50,000 FC). Réglez intégralement la commande ou remboursez la dette. » avec notification « Facturation bloquée ». Client à 49 500 FC : deuxième facture acceptée (pas de blocage au-dessous du plafond).
- Reçu : ID.Nat 10-F4300-N85947U, Impôt A1902266K, RCCM 021-A-650, K4 - LOMA, date/heure, caisse, client, lignes, total, commission (25 %), balance antérieure, nouvelle dette, « Solde arrêté ce jour ». Facturier de test sans équipe : « Éq. — » (donnée de compte, pas un défaut).
- Clôture K4 : rapports « sans équipe » (crédit 450 000), équipe A (10 000 cash), équipe B (5 000 cash, 15 000 crédit) ; billetage 10 000 + 3x1 000 + 500 = 13 500 FC contre 13 000 FC (15 000 - 2 000) : « +500 FC (Excédent) », clôture « Espèces physiques 13 500 FC, Écart 500 FC », puis confirmation et inscription au livre (13 000 FC) par la direction.
- BUG-277 : transfert K3 -> K4 envoyé 2, reçu 1 : « LITIGE D'ÉCART » + « Clôture de caisse bloquée » ; confirmation de la clôture par la direction refusée par le serveur (alerte citant le transfert/écart), clôture inchangée ; après résolution par K3 (motif), confirmation puis inscription OK.
- Commissions K4 de novembre : 4 clients à BP 50 000 FC, net à payer « Client: 40 625 FC » (12 500 - 125 carte - 50 000 dette - 3 000 sociale), étiquette « Net négatif » sans bouton « Régler », fiche « paiement impossible », `mark_paid` -> 400 en français.
- BUG-284 : voir registre ; mesuré aussi à 360 px (formulaire 3 champs et bouton atteignables).

## Tickets

Passés à VÉRIFIÉ dans `docs/qa/REGISTRE_BUGS.md` : BUG-277, BUG-281, BUG-284 (frontend + backend, E2E), BUG-253 (volet UI Trésorerie/Commissions seulement ; il reste BUG-300).

Ouverts (tous mineurs, frontend) :
- BUG-298 : Trésorerie, après création de la clôture, « ÉCART DE CAISSE -13 000 FC (Manque) » et bandeau « ÉCART BILLETAGE -13 000 FC » contredisent l'écart enregistré (+500 FC) ; deux « solde comptable caisse » différents (15 000 / 13 000).
- BUG-299 : Commissions, carte « RESTE À VERSER » = -379 200 FC (somme des nets négatifs non payables).
- BUG-300 : Clients, FACTURIER et LIVREUR reçoivent des 403 sur `clients/active_last_month/` (x4) et `clients/contributions/`.

Non ouverts, à connaître : (a) une livraison est refusée tant que le rapport Niveau 1 de la même équipe/date existe (règle voulue, message clair) ; (b) la modale « Stock de départ du jour » propose un stock négatif (-300) issu des ventes sans fournée (BUG-158, voulu) ; (c) pendant l'écran bloquant BUG-284 les pages sous-jacentes continuent d'interroger l'API (403 attendus).

## État laissé en base (pour la restauration)

Comptes : `zz_treso_facturier_a` mis en équipe A et `zz_clients_facturier` en équipe B (via PATCH direction) ; mots de passe de `zz_facturier_k3`, `zz_livreur_k3` réinitialisés/changés ; équipe B de K3 désignée. Données : factures de test K4 (clients K4-0010 à 0013, 0020 à 0023, 0030 à 0033, 0040 à 0043, 0050/0051), une facture annulée, clôture K4 du 2026-11-14 confirmée et inscrite au livre, un transfert K3 -> K4 résolu et une demande K4 -> K3 restée PENDING, commissions K4 de novembre générées.

## Fichiers

`e2e/tests/19-cycle-final-ventes.spec.ts`, `19b-cycle-final-securite-rotation.spec.ts`, `20-cycle-final-commissions.spec.ts`, `21-cycle-final-cloture-transfert.spec.ts`, `22-cycle-final-treso-lecture.spec.ts`, `23-cycle-final-403-ecrans.spec.ts`, `e2e/fixtures/cycle.ts`. Variables de rejeu : `E2E_CLIENT_BASE` (fenêtre de clients K4), `E2E_SKIP_SETUP`, `E2E_SKIP_TRANSFER_SETUP`, `E2E_STRICT_403`. Captures : `docs/qa/captures/cf-*.png`.


## Vérification des corrections frontend (BUG-298, 299, 300) - 2026-11-14

Base `db.sqlite3`, serveurs 8000/5173 existants, comptes `zz_*`. Tests : `e2e/tests/23-cycle-final-403-ecrans.spec.ts` (avec `E2E_STRICT_403=1`) et `e2e/tests/24-verif-bug298-299.spec.ts` (nouveau, lecture seule). Sorties Playwright dans un dossier temporaire personnel (aucune trace conservée, donc aucun mot de passe sur disque).

| Ticket | pos 360 | tablette 768 | bureau 1440 | tv 1920 | Statut |
|---|---|---|---|---|---|
| BUG-298 : après clôture K4, écart +500 FC (Excédent), solde comptable unique 13 000 FC, cohérents avec l'API | vert | vert | vert | vert | VÉRIFIÉ |
| BUG-299 : « RESTE À VERSER » non négatif, nets négatifs « reportés en dette » à part | vert | vert | vert | vert | VÉRIFIÉ |
| BUG-300 : FACTURIER et LIVREUR, aucun 401/403 sur accueil, Clients, Facturation | vert | vert | vert | vert | VÉRIFIÉ |

BUG-253 passé à VÉRIFIÉ en entier. Limites : BUG-298 vérifié sur la clôture K4 déjà enregistrée (la création du jour n'est plus rejouable), ce qui est précisément la situation du défaut ; BUG-299 contrôle le signe et la présence de la ligne « reportés », pas le montant exact au franc. Captures : `docs/qa/captures/vf-*-bug298.png`, `vf-*-bug299.png`.
