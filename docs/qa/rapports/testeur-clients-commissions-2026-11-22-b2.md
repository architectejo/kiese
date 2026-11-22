# Rapport testeur Clients et Commissions, ronde v2 (2026-11-22-b2)

Agent : testeur-clients-commissions (pour le Dev B). Périmètre : `backend/clients/`, `backend/commissions/`.
Aucun code applicatif modifié. Données fictives uniquement (classeurs Excel générés en mémoire avec openpyxl, jamais `data_kiese/`).

## Fichiers livrés

- `backend/clients/tests/test_clients_v2.py` (69 tests) : recherche prédictive inter-boulangeries, création/codes/plafond/photo, catégories (bornes), actions de masse, import Excel malformé, caisse sociale, paramètres invalides, isolation par nœud.
- `backend/commissions/tests/test_commissions_v2.py` (42 tests) : formules à la main, BUG-417 (cotisation et carte par boulangerie, `summary`, `periods/history`, commissions déjà générées inchangées), paramètres invalides, net négatif et report, client facturé dans deux boulangeries.
- Registre : BUG-737 à BUG-746 ajoutés dans `docs/qa/REGISTRE_BUGS.md` (numérotation décalée : BUG-701 à 736 étaient déjà pris par d'autres agents).

## Scénarios couverts

Clients : recherche par nom partiel, code (minuscule), téléphone, caractères spéciaux et LIKE ; un facturier/livreur de K1 trouve un client de K3 mais ne peut ni le modifier ni le supprimer ; un gérant de K1 ne voit pas K3 (liste, `?node=`, détail, history) ; pertinence exact/préfixe/sous-chaîne ; `page_size` et `page` invalides ; filtres `node`/`category` invalides = 400 ; codes `K1-0001` uniques par préfixe, séquence périmée, non-réutilisation après suppression, code et nœud forcés côté serveur ; plafond 50 000 FC par défaut, modifiable gérant/direction, refusé facturier/livreur, bornes (négatif, NaN, Infinity, 3 décimales) ; taux max 0,30 ; photo (PNG valide, texte déguisé, > 5 Mo, SVG) ; catégories : seuil `best_client_threshold` inclusif, dette = plafond -> à risque, risque prioritaire, BP négative (épargne) jamais à risque, reclassement immédiat après PATCH du plafond, notification unique ; `bulk_move` (codes régénérés sans collision), `bulk_delete` (clients protégés) ; import Excel : nominal, doublons dans le fichier et en base (casse, espaces), dry-run, fichiers vides/corrompus/CSV/BOM = 400, feuille sans en-tête, nœud inconnu, accents, cellule numérique, ligne vide, 600 clients (codes uniques), accès réservé au siège ; caisse sociale : `bulk_create_month` (valeur de la boulangerie, exemption, idempotence, nœud étranger), contributions (mois, montant, doublon, client d'une autre boulangerie), `toggle_paid`, distribution (indice, remise = indice x tarif, total = social + remise + mérite calculés à la main, unicité nœud/année, clôture figée, tarif réservé à la direction), lignes ; `effective_cotisation_sociale` Decimal.

Commissions (valeurs à la main) : CM 0,30 sur 160 000 FC = 48 000, retenues 5 000 + 2 000 + 1 000 + 500 = 8 500, net 39 500, remise 0,25 % = 400 non déduite, carte 1 % toujours 0 ; CM 0,25 ; Decimal exact (333 FC x 7 x 0,25 = 582,75) ; agrégation et bornes de mois ; exclusion des factures soldées/exonérées/RG/taux 0/non livrées ; client épargne, remboursement, vente sans client = aucune ligne ; cotisation et carte propres à chaque boulangerie, client exempté ; changer `card_fee_fc`/`monthly_social_contribution` après génération ne modifie pas les lignes existantes (un nouveau client prend la nouvelle valeur) ; `summary` : totaux verticaux (170 000 / 47 500 / 4 000 / 6 000 / 3 000 / 13 000 / 34 500) égaux à la somme des lignes, zéros sur liste vide, isolation, permissions, filtres invalides ; `periods/history` : totaux cotisation/carte/encaissements (versement « Non servi » inclus, autre boulangerie exclue) ; net négatif non payable puis report (12 500 - 2 000 - 1 000 - 2 500 = 7 000) ; BP créditrice ; `mark_paid`/`set_manuel` réservés à la direction ; période clôturée figée ; idempotence de `generate` (pas de double retenue) ; retenues saisies conservées à la régénération.

## Résultats réels

Exécution isolée des deux fichiers v2 (SQLite en mémoire, machine chargée par d'autres agents, 500 à 1 350 s par fichier) :
- `test_clients_v2` : 69 tests, 10 échecs bruts à la première passe, tous dus au code applicatif ou à une erreur de mon attente (voir plus bas).
- `test_commissions_v2` : 40 tests, 12 échecs bruts dont 5 à cause de mes attentes (arithmétique, chaînes `'170000'` au lieu de `'170000.00'` : `Sum` SQLite non quantifié, comparaison corrigée en `Decimal`).
- BUG-736 (paramètres de `generate`) : corrigé entre-temps dans l'arbre de travail par un autre agent ; mon test (`test_generate_corps_invalide_400_pas_500`) passe désormais et sert de non-régression.
- Tests révélant un défaut non corrigé : marqués `@expectedFailure` avec le numéro du ticket. Résultat final de `python manage.py test clients commissions` : voir la section « Exécution finale » ci-dessous.

## Tickets ouverts

| Ticket | Gravité | Résumé |
|---|---|---|
| BUG-737 | Majeur | Client facturé dans deux boulangeries : sa BP et sa cotisation sont retenues en double (20 000 au lieu de 10 000 ; 3 000 au lieu de 1 500). |
| BUG-738 | Majeur | CM calculée au taux courant du client, pas au taux de chaque facture (30 000 au lieu de 27 500). À valider avec le client. |
| BUG-739 | Majeur | `bulk_create_month` sans validation : mois 13, année 99999999999, montants négatifs écrits (200) ; valeurs non numériques = 500. |
| BUG-745 | Majeur | `set_manuel` avec NaN/Infinity/hors plage : 500 et ligne illisible persistée (les lectures suivantes plantent). |
| BUG-740 | Mineur | Ligne de distribution : indice 100 000 et mérite négatif acceptés. |
| BUG-741 | Mineur | `bulk_move`/`bulk_delete` : `ids`/`node` invalides = 500 (et `bulk_move` non atomique). |
| BUG-742 | Mineur (À CLARIFIER) | Plafond 0 + dette 0 = « à risque ». |
| BUG-743 | Mineur | Recherche : « élodie » ne trouve pas « Élodie » sous SQLite (casse non ASCII). |
| BUG-744 | Mineur | `payroll_listing?period=<non UUID>` = 500. |
| BUG-746 | Mineur | Import Excel : noms > 100 caractères et doublons NFC/NFD non traités. |

Déjà ouverts par d'autres et recoupés : BUG-705 (gérant 403 sur `history`/`payroll_listing`, test `@expectedFailure` ajouté), BUG-736 (corrigé dans l'arbre), BUG-735 (verrous `mark_paid`/`set_manuel`, corrigé dans l'arbre).

## Observations sans ticket (à trancher)

- `generate` fige `deduction_debt` à la première génération : si la BP du client change ensuite (paiement), régénérer ne la met pas à jour (les retenues sont considérées comme saisies à la main). À confirmer avec le client : la paie de fin de mois doit-elle prendre la BP du jour de clôture ?
- `payroll_listing` : le docstring annonce les commissions « non payées » mais la vue renvoie toutes les lignes.
- Sous SQLite, `Sum()` renvoie `'170000'` sans décimales alors que les lignes sont en `'170000.00'` (les montants restent des chaînes, jamais des floats). Sans conséquence si le frontend formate ; sous PostgreSQL le format serait cohérent.
- `clients/views.py::bassins` renvoie les seuils en `float` (`float(config.bassin_grand)`) : pas un montant comptable, mais contraire à la règle « jamais de float pour un montant ».
- Concurrence : les créations simultanées de codes sont couvertes par les tests existants (BUG-017/112) ; je n'ai ajouté que le cas séquence périmée (pas de TransactionTestCase avec threads, SQLite en mémoire).

## Exécution finale

`python manage.py test clients commissions --noinput` (arbre de travail du 2026-11-22, SQLite en mémoire) : **Ran 395 tests in 3973 s, OK (expected failures=16)**, aucun échec, aucune erreur, aucun succès inattendu. Les `@expectedFailure` de cette ronde : BUG-737 (2), BUG-738, BUG-739, BUG-740, BUG-741 (2), BUG-742, BUG-743, BUG-744, BUG-745, BUG-746 (2), BUG-705 (1). Quand un développeur corrige un ticket, le test correspondant passe en « succès inattendu » : retirer alors `@expectedFailure` et passer le ticket à VÉRIFIÉ.
