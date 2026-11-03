[c] Pour la production des pains, le propriètaire des boulangeries veut que le calcul se fasse avec des unités monetaires.
- Ex: 1 sac vaut 200 000 Fc
- Donc pour 1 sac on aura 200 pains de 1000 Fc ou 100 pains de 1000 Fc et 200 pains de 500 Fc
Fait de calcule pour les autres types de pains,
la valeur 1 sac à 200 000 Fc peut varié on peut aussi ajouter ou supprimer les types des pains comme par exemple le pain de 200 Fc.
Il faudrait afficher clairement le manquant et l'excedent — vérifié partiellement conforme par testeur-production le 2026-10-22 : le calcul en valeur (sacs × `Node.sac_value_fc` ou valeur par défaut de `Config`) et le signe manquant/excédent sont corrects, voir `backend/production/tests/test_fournees.py::FourneeValeurTests::test_theoretical_yield_uses_node_sac_value` et `::test_excedent_is_positive`. En revanche, la variation de la valeur du sac peut fausser rétroactivement l'historique d'une fournée déjà déclarée (BUG-038), et l'ajout d'une nouvelle catégorie de pain (ex. 200 FC) au-delà des 4 catégories figées `BreadPrice.category` est impossible (BUG-039) — non conforme sur ces deux points, tickets ouverts.

* Pour les équipes on a seulement l'équipe A et l'équipe B pas de Jour ni de Nuit.

[c] Lors de la facturation, les facturiers peut voir les clients des autres boulangerie pour si il se presente dans sa boulangerie qu'il n'aiet pas du mal à le facturé lors de leurs achats. — vérifié conforme par testeur-ventes le 2026-10-22 : `clients/views.py::ClientViewSet.get_queryset` exempte explicitement les rôles FACTURIER/LIVREUR du filtre par nœud, et `sales/views.py::InvoiceViewSet.create` n'impose aucune contrainte de nœud entre le facturier et le client choisi. Voir tests `backend/sales/tests/test_invoices.py::CrossNodeFacturationTests::test_facturier_can_search_a_client_from_another_node` et `::test_facturier_can_invoice_a_client_from_another_node`.

[c] Le facturier doit pouvoir Confirmer la livraison et Imprimer le reçu parce que d'après le propriètaire c'est lui qui donne le reçu au livreur pour la livraison. — vérifié conforme par testeur-ventes le 2026-10-22 : `sales/views.py::InvoiceViewSet.deliver` utilise `IsFacturierOrLivreur`, le facturier peut donc confirmer lui-même. Voir test `backend/sales/tests/test_invoices.py::CrossNodeFacturationTests::test_facturier_can_confirm_delivery_of_invoice_he_created`. Nuance distincte (BUG-031) : le FACTURIER ne peut en revanche pas annuler (`cancel`) ni déclencher le nettoyage auto des factures expirées (`cleanup_expired`) malgré l'intention explicite du code et de remarque.md l.200 — voir ticket dédié.

* Pour "Historique des Fournées" on doit avoir un bouton "Voir plus" comme ça on affiche que 4 derniers fournées

* Lors du transfert les pains transférés doivent s'ajouter aux pains de la boulangerié qui reçoit et diminuer de la boulangerie qui envoi mais on doit savoir que ces sont des pains réçus

* Au niveau "Stock Pains Actuel" si on clique sur une fournée une boite nodal doit s'ouvrir avec les detaille

* Au niveau de "Stocks Consommables", ajouste la boite nodal, qu'elles soit plus haute, parce que actuellement elle ne s'ouvre pas à la page, il faut scroller pour la voir et regarde que dit le cahier des charges pour l'approvisionnement.

[c] La liste de consomables n'apparait pas lorsque je veux enregistrer l'approvisionnement — vérifié conforme par testeur-production le 2026-10-22 : `ConsumableStockViewSet._ensure_stock_accounts()` crée automatiquement les comptes de stock manquants pour chaque `ConsumableType` actif dès le premier `GET /api/production/stocks/` (utilisé par le formulaire d'approvisionnement), y compris pour un type ajouté après coup. Voir `backend/production/tests/test_consumables.py::ApprovisionnementConsumableListTests::test_consumable_list_appears_for_supply_form_without_prior_setup` et `::test_new_type_added_later_appears_without_manual_setup`.

[c] Lors de l'enregistrement des fournées, on doit aussi en registré la quantité des autres consomables utilisé et les quantités enregistrés doivent être diminuer dans le "Stocks Consommables" — vérifié conforme par testeur-production le 2026-10-22 : `ProductionSessionViewSet.perform_create` appelle `_record_consumable_exits(session, user, extra_consumables=request.data['consumables_used'])`, qui crée un `ConsumableMovement` EXIT par consommable utilisé et décrémente `ConsumableStock.quantity`. Voir `backend/production/tests/test_fournees.py::FourneeConsumablesTests::test_salt_yeast_oil_decimal_quantities_are_decremented`.

[c] Lors de l'enregidtrement de la "Déclaration de Fournée" je ne vois pas la possibilité d'enregistrer les autres Consommables (huile, sel, levure) utiliser qui devront diminuer dans le "Stocks Consommables" — même vérification que ci-dessus (champ `consumables_used` du payload de création de session).

[c] Le sel doit être en gramme (g), la Levure doit accepter des nombres flottants generagement ils utilise 1/4 d'un pacquet par sac ça peut varier, Huile aussi doit accepter des nombres flottants — vérifié conforme par testeur-production le 2026-10-22 : `ConsumableType` seedé avec SALT en grammes, YEAST en paquets, OIL en litres (migration `production/0010_consumabletype.py`) ; `ConsumableMovement.quantity`/`ConsumableStock.quantity` sont des `DecimalField(max_digits=10, decimal_places=3)`, acceptant 0,25 paquet de levure ou 0,33 litre d'huile sans arrondi. Voir `test_salt_yeast_oil_decimal_quantities_are_decremented` (ci-dessus) qui vérifie explicitement 0,25 et 0,33.

[c] Au niveau de "Stocks Consommables" met le sel en gramme (g) — même vérification (SALT seedé avec `unit='g'`).

[c] Au niveau de "Déclaration de Fournée" Levure et Huile ne prennent pas de va floatante, ex: on peut utiliser 1/4 d'un pacquet de levure et 1/3 litre d'huile. — vérifié conforme côté backend (voir ci-dessus, `DecimalField` à 3 décimales accepte 0,25/0,33) ; le champ de saisie frontend (`Production.tsx`, formulaire Approvisionnement) utilise déjà `type="number" step="any"` pour les quantités décimales — non re-testé en détail côté UI (hors périmètre des tests backend de cette itération), à confirmer en E2E si besoin.

* Dans la "Gestion Clientèle" le gerant peut "Enregistrer un Achat / Vente" lors de cette enregistrement il doit pouvoir enregistrer les quantité des differents type de pains, ces vents comme des vente occasionnls doivent être enregistrer

* Les Dettes(BP) des clients doivent être prise en compte dans le calcule et le PB ou Dette d'un client doit s'afficher sur le formulaire "Enregistrer un Achat / Vente"

* PLAFOND CRÉDIT par defaut doit être de 50 000 FC [c] — vérifié conforme par testeur-clients-commissions le 2026-10-22 : Client.credit_limit défaut 50000.00 FC, voir backend/clients/tests/test_models.py::ClientCreditLimitTests::test_default_credit_limit_is_50000.

* Si BALANCE ANTÉRIEURE (BP) devient superieur ou égale au PLAFOND CRÉDIT, bloqué l'enregistrement de la vente seulement si le "Versement du Jour" est inferieur à la "Valeur Commande"

* Dans le tableau de client dans "Gestion Clientèle" la colone "Action" a le bouton avec l'icone de oeil pour voir les details sur un client, dans les details le gerant et ses superieurs doivent pouvoir modifier "Limite Crédit"

* Dans le tableau de client dans "Gestion Clientèle" c'est mieux d'écrire "BP" à la place de "Dette"

* Dans "Gestion Clientèle" le sections "Plafonds Dépassés","Encours Global" et "Solvabilité" lorsqu'on clique dessus, une boite nodal doit s'ouvrir avec les details de la section

* Pour le "Direction Générale" la partie "Commissions CM" n'affiche pas les données comme si elle n'était pas branché au cerveau backend. [c] — vérifié conforme par testeur-clients-commissions le 2026-10-22 : Commissions.tsx est bien branché sur l'API (commissionsApi.commissions.list/generate), voir backend/commissions/tests/test_generate.py.

* La partie "Commissions CM" doit avoir un champ de recherche et des filtre pour filtrer le tableau des clients [c] — vérifié conforme par testeur-clients-commissions le 2026-10-22 : champ de recherche (searchTerm) et filtres (statusFilter, nodeFilter) présents dans Commissions.tsx.

* Lors de la création d'une succursale j'ai une erreur:
Nodes.tsx:83  POST http://localhost:8000/api/core/nodes/ 400 (Bad Request)
dispatchXhrRequest @ axios.js?v=2ed14f2e:2165
xhr @ axios.js?v=2ed14f2e:2071
dispatchRequest @ axios.js?v=2ed14f2e:2661
Promise.then
_request @ axios.js?v=2ed14f2e:2872
request @ axios.js?v=2ed14f2e:2788
httpMethod @ axios.js?v=2ed14f2e:2924
wrap @ axios.js?v=2ed14f2e:12
(anonymous) @ Nodes.tsx:83
executeDispatch @ react-dom_client.js?v=2ed14f2e:9141
runWithFiberInDEV @ react-dom_client.js?v=2ed14f2e:851
processDispatchQueue @ react-dom_client.js?v=2ed14f2e:9167
(anonymous) @ react-dom_client.js?v=2ed14f2e:9454
batchedUpdates$1 @ react-dom_client.js?v=2ed14f2e:2044
dispatchEventForPluginEventSystem @ react-dom_client.js?v=2ed14f2e:9240
dispatchEvent @ react-dom_client.js?v=2ed14f2e:11319
dispatchDiscreteEvent @ react-dom_client.js?v=2ed14f2e:11301
Nodes.tsx:88 Error saving node AxiosError: Request failed with status code 400
    at settle (axios.js?v=2ed14f2e:1738:14)
    at XMLHttpRequest.onloadend (axios.js?v=2ed14f2e:2091:4)
(anonymous) @ Nodes.tsx:88
await in (anonymous)
executeDispatch @ react-dom_client.js?v=2ed14f2e:9141
runWithFiberInDEV @ react-dom_client.js?v=2ed14f2e:851
processDispatchQueue @ react-dom_client.js?v=2ed14f2e:9167
(anonymous) @ react-dom_client.js?v=2ed14f2e:9454
batchedUpdates$1 @ react-dom_client.js?v=2ed14f2e:2044
dispatchEventForPluginEventSystem @ react-dom_client.js?v=2ed14f2e:9240
dispatchEvent @ react-dom_client.js?v=2ed14f2e:11319
dispatchDiscreteEvent @ react-dom_client.js?v=2ed14f2e:11301

* Lorsqu'on clique sur un succursale on doit avoir un boite nodal avec la liste des agents(utilisateurs) et leurs rôles

* La partie "États Financiers N/N-1" n'est pas connecté au cerveau backend [c] — vérifié conforme par auditeur-comptable le 2026-10-23 : `backend/finance/views.py` (compte de résultat, bilan, cash-flow, comparatif) interroge réellement `sales.Invoice`, `commissions.ClientCommission`, `treasury.LocalExpense`/`CashbookEntry`, `production.ConsumableMovement` (aucune donnée statique/mock) ; `frontend/src/pages/dashboard/Finance.tsx` appelle réellement `financeApi.*`. Déjà corrigé avant cette session, ce point est donc clos — voir BUG-016 (partie Finance) et `docs/qa/rapports/auditeur-comptable-2026-10-22.md`. L'écart restant avec `cadre_comptable.md` (structure Balance/Bilan en partie double, cascade TFR) est documenté séparément dans `docs/qa/ECART_CADRE_COMPTABLE.md` pour décision du client, ce n'est pas un défaut de connexion au backend.


* Pour la direction generale la partie "Production & Stocks" les "Stocks Consommables", "Stock Pains Actuel" et "Historique des Fournées" doivent être separer par succursale

* Dans "Facturation en Chaîne & Livraison" les dates sur les "File des Livraisons — Confirmation & Impression Reçu" affiche "Invalid Date"

* Dans "Commissions des Revendeurs (CM)" les "Com. Brute", "Déductions" et "Net Payable" reste à "0" malgré les enregistrement des ventes pour les clients. [c] — vérifié conforme par testeur-clients-commissions le 2026-10-22 : les montants ne restent plus à 0 une fois la période générée via /api/commissions/periods/generate/, voir backend/commissions/tests/test_generate.py::GenerateCommissionPeriodTests::test_generate_computes_cm_brute_from_delivered_invoices.

* Dans "Commissions des Revendeurs (CM)" la "Déductions" se calcule comment pour chaque client. [c] — vérifié conforme par testeur-clients-commissions le 2026-10-22 : formule documentée et testée dans backend/commissions/models.py::ClientCommission.compute() et backend/commissions/tests/test_formulas.py (Total retenues = dette + sociale + imprimés + autre + CARTE 1% + REMISE 0.1%, cf. adaptes.md §3.2).

* Analyse le design de l'application pour ameliorer l'affichage qu'il y aie pas d'éléments que debordent sur l'ecran, que les tableaux affichent bien avec la bonne taille de caractère et que celà soit responsive.

* Au niveau du site web "Boulangerie" dans "Sélectionnez une Boulangerie" les succursales doivent s'afficher

* Lorsqu'on clique sur l'icone des notifications la boite nodal qui s'affiche a un certain degré d'opacité, fait en sorte que boite nodal soit entierement opacque 0% de transparence 

* Au niveau du "Tableau de Bord" les sections "Chiffre d'Affaires", "Volume de Pains Distribuer", "Alertes Risques" et "Clients Actifs" si on clique dessus on doit ouvrir un boite nodal avec les details, si c'est la direction generale les details doivent être par boulangeries

* Au niveau du "Tableau de Bord" dans le tableau de "Dernières Factures Livrées" on doit afficher que les 5 derniers et avoir un bouton "Voir Plus" qui va afficher une boite nodal avec les derniers factures livrées classés par mois, si on clique sur un element du tableau on pourra afficher l'element, la même chose pour le tableau "Alertes Risques Clients"

* Dans le tableau de "Gestion Clientèle" les colones "Type", "Contact" et "Plafond Crédit" doivent être enlever, elle ne doit s'afficher que dans les details,

* [c] "Registre Blockchain" est vraiment connecté au cerveau backend ? — Vérifié par testeur-permissions le 2026-10-22 : `frontend/src/pages/dashboard/Blockchain.tsx` appelle bien `blockchainApi.snapshots.globalStatus()`, `alerts.list()` et `runCheck()` (endpoints réels `/api/blockchain/...`), pas de données statiques/mockées. Conforme.

* Au niveau de "Facturation (Facturier)" dans la section "File des Livraisons — Confirmation & Impression Reçu" on afficher les 3 Premiers et avoir un bouton "Voir plus" 

* Au niveau de "Facturation" les sections "LIVRÉES AUJOURD'HUI" et "TOTAL FACTURÉ" lorsqu'on les cliques elles doivent ouvrir une boite nodal avec les details.

* Au niveau de "Facturation (Facturier)" dans la section "File des Livraisons — Confirmation & Impression Reçu" les elements de la boite nodal du bouton "Voir plus" n'affiche pas toute les données a cause de la hauteur des sections certaines données sont en dessous et pas visible

* Au niveau de "Production & Stocks" c'est le Directeur General qui approvisionne les differentes boulangerie en "Stocks Consommables", le formulaire "Approvisionnement Consommable" doit avoir un champ pour renseigner le prix d'achat des consommables et que cela soit pris en compte dans "États Financiers Consolidés" au niveau des "Coût Matières Premières (Farine, Sel, Levure, Huile)"

[c] Pour chaque boulangerie trouve le moyen de faire renseigne "Charges Locales & Exploitation" — vérifié conforme par testeur-tresorerie le 2026-10-22 : `treasury/models.py::LocalExpense.node` (FK obligatoire) et `LocalExpenseViewSet.get_queryset`/`perform_create` filtrent et rattachent systématiquement la dépense à la boulangerie du gérant (ou au nœud choisi pour un utilisateur HQ). Voir test `backend/treasury/tests/test_reports_closures.py::CashClosureNetCashTests::test_net_cash_is_cash_sales_minus_local_expenses`.

* Au niveau de "Production & Stocks" dans le "Stocks Consommables" tu dois separer les consommables par boulangerie

* Non dans la section "Production, Stocks & Transferts" on peut selectionné un boulangerie, les données des "Production & Stocks" doivent aussi s'affichier selon la boulangerie sectionnée

* Malheureusement par defaut ça continue d'affichier tout les consommables au lieux d'affichier ceux de la boulangerie par defaut

* Je veux qu'on fasse des tests sur cPanel, prepare l'applicaton a être hebeurgé sur "etskiese.com"

* Au niveau de "Commissions CM" la "Déductions" doit se calculer en tenant compte la dette(BP) [c] — vérifié conforme par testeur-clients-commissions le 2026-10-22 : CommissionPeriodViewSet.generate() affecte bien deduction_debt = client.current_debt, voir backend/commissions/tests/test_generate.py::GenerateCommissionPeriodTests. Reste BUG-020 (ventes soldées non exclues de la base CM) et BUG-019 (crash sur vente occasionnelle).

* Au niveau de la "Configuration Système" les valeurs par défaut doivent être accepter

[c] A vérifié, le facturier peut aussi enregistrer des ventes occasionelles (Nouvelle Facture POS sans séléctionnez un client) — vérifié conforme par testeur-ventes le 2026-10-22 : `sales/views.py::InvoiceViewSet.create` accepte `client` absent/null, aucune contrainte ne l'impose. Voir test `backend/sales/tests/test_invoices.py::SpecialCodesTests::test_occasional_sale_without_client_is_allowed`. Nuance (BUG-028) : la commission par défaut (25%) reste appliquée sur ces ventes sans client au lieu de 0%, voir ticket dédié.

[c] Enleve l'option "Livraison (Livreur)" dans la sidebar — vérifié conforme par testeur-ventes le 2026-10-22 : aucune entrée « Livraison »/LIVREUR trouvée dans `frontend/src/components/layout/DashboardLayout.tsx` (vérification par lecture de code, pas de test Django applicable à une sidebar React).

* Au niveau de "Personnel (Utilisateurs)" dans le tableau "Annuaire des Utilisateurs" juste le username doit apparaitre dans la colone "Identifiant" enleve le symbole "@"

* Au niveau "Tableau de Bord" sur la section du graphique "Transactions Récentes (FC)" on doit avoir deux courbe, une sur le chiffre d'affaire journalier et une autre sur sur le resultat attendu selon la production journaliere

* Au niveau de "Caisse & Trésorerie" le "§5.1.1 — Niveau 1 · Rapports Journaliers des Facturiers" doit avoir, le nombre de sacs consomés, le nombre de pains produit par catégorie de pains(200Fc, 300Fc, 400Fc, 500Fc et 1000Fc), le nombre de pains vendu par catégorie de pains(200Fc, 300Fc, 400Fc, 500Fc et 1000Fc), les écarts par rapport au montant attendus sur le nombres de sacs consomé et le montant obtenu après vente — NON CONFORME, vérifié par testeur-tresorerie le 2026-10-22 : `FacturierReport` n'expose que des totaux agrégés (cash/crédit/théorique), aucun champ de détail par catégorie de pain ni de sacs consommés ni d'écart sacs/ventes. Voir ticket BUG-033 et test `backend/treasury/tests/test_reports_closures.py::FacturierReportDetailFieldsTests::test_facturier_report_model_has_no_category_breakdown_fields` (`@expectedFailure`).


[c] Le nombre des pains vendu doit être reduit dans le nombre des pains produits par categorie de pains(200Fc, 300Fc, 400Fc, 500Fc et 1000Fc) le nombre passe au negatif si le nombre devient inferieur à "0" — vérifié conforme par testeur-ventes le 2026-10-22 : `production/models.py::BreadStock`/`_adjust_bread_stock` n'impose aucun plancher (champs `IntegerField`, mise à jour par `F()`), une vente peut donc faire passer `qty_available` au négatif. Voir test `backend/sales/tests/test_invoices.py::DeliveryAndCancelTests::test_oversold_bread_stock_can_go_negative`.


* Au niveau de "Configuration Système" même si les valeurs par defaut sont là, le système doit accepter n'importe quelle valeur ("§3.1 — Valeur Théorique par Sac de Farine (pas seulement une valeur entre 199001 et 200000)", §2.2 — Seuils de Segmentation Clients et §2.3 — Algorithme des Commissions (CM)) doivent accepter n'importe quelle valeurs

[c] Au niveau de "Caisse & Trésorerie", les "§5.1.1 — Niveau 1 · Rapports Journaliers des Facturiers" doivent être filtrer par boulangerie (Succursales) et doit prendre en compte "Caisse & Trésorerie" — vérifié conforme par testeur-tresorerie le 2026-10-22 : `FacturierReportViewSet.get_queryset` filtre par `node` (query param ou nœud de l'utilisateur non-HQ) ; `Treasury.tsx` propose un sélecteur de succursale sur la section §5.1.1. Voir test `backend/treasury/tests/test_reports_closures.py::FacturierReportGenerationTests::test_report_filtered_by_node`.

[c] Au niveau de "Caisse & Trésorerie", les "Clôtures du Jour" doivent automatique baser sur les "§5.1.1 — Niveau 1 · Rapports Journaliers des Facturiers" être filtrer par boulangerie — vérifié conforme par testeur-tresorerie le 2026-10-22 : `CashClosureViewSet.perform_create` agrège `FacturierReport.total_cash_sales` par `node`+`date` pour calculer `total_entries`, et `CashClosureViewSet.get_queryset` filtre par nœud. Voir test `backend/treasury/tests/test_reports_closures.py::CashClosureNetCashTests::test_net_cash_is_cash_sales_minus_local_expenses`.

[c] Au niveau de "Caisse & Trésorerie", "Clôtures du Jour" la boite nodal qui s'affiche lorsqu'on clique sur une cloture doit avoir comme écrit "Rapport de caisse" à la place de "Détail Clôture" et "Versement du jour" à la place de "Ventilation des Billets" — vérifié conforme par testeur-tresorerie le 2026-10-22 : `frontend/src/pages/dashboard/Treasury.tsx` affiche bien les titres « Rapport de caisse — ... » et « Versement du jour » (vérification par lecture de code, pas de test Django applicable à une boîte modale React).

[c] Au niveau de "Caisse & Trésorerie", le gerant peut ajouter une cloture mais seule le comptable direction generale peut confirmer ou infirmer un cloture, il la cloture est infirmer alors le gerant peut la modifier et la soumettre à nouveau au au comptable (direction generale) pour confirmer ou infirmer — vérifié conforme pour le cycle principal par testeur-tresorerie le 2026-10-22 : `CashClosureViewSet.validate`/`reject` réservés à `IsHeadquarters`, la création reste `IsGerant`, et une clôture infirmée (`is_rejected=True`) redevient modifiable par le gérant puis confirmable par le comptable. Voir test `backend/treasury/tests/test_reports_closures.py::CashClosureWorkflowTests::test_comptable_can_reject_then_gerant_resubmits_then_confirms`. Nuance (BUG-034) : une clôture déjà CONFIRMÉE (pas seulement infirmée) reste elle aussi modifiable par le gérant, ce qui ne devrait pas être possible — voir ticket dédié.

* Au niveau de "Tableau de Bord" la section "Volume de Pains Distribués" doit affichier le volume de Pains distribués par jour

* [c] Au niveau de "Tableau de Bord" la section "Clients Actifs du Groupe" un client est actif si et seulement si au cours du mois passé il a effectuer au moins un achat (commande) — Vérifié par testeur-permissions le 2026-10-22 : `clients/views.py::ClientViewSet.active_last_month` filtre bien sur `invoices__invoice_date__gte=date.today()-30 jours` avec au moins une facture (`Count(...) > 0`). Conforme.


[c] Au niveau de "Caisse & Trésorerie", le gerant doit aussi voir le "§5.1.1 — Niveau 1 · Rapports Journaliers des Facturiers" dans boulangerie — vérifié conforme par testeur-tresorerie le 2026-10-22 : un GERANT (`can_access_all_nodes=False`) voit la section §5.1.1 restreinte à son propre nœud (`FacturierReportViewSet.get_queryset`), même mécanisme que l.150. Voir test `backend/treasury/tests/test_reports_closures.py::FacturierReportGenerationTests::test_report_filtered_by_node`.

* Au niveau du "Tableau de Bord", la section du graphique "Transactions Récentes (FC)" le terme "Transactions Récentes (FC)" doit être "Chiffre d'Affaires du Mois", sur les courbes le terme "Chiffre d'affaires" doit être remplacer par le terme "Payement" et "Résultat Attendu (Production)" par "Commande", les courbes doivent avoir des couleurs différentes.

* Au niveau de "Facturation (Facturier)" les "File des Livraisons — Confirmation & Impression Reçu" ayant depassé un delai de 12heures après leurs création doivent s'auto-supprimer (Ne pas le prendre en compte dans le calcule) et sur les "File des Livraisons — Confirmation & Impression Reçu" au niveau du bouton "Confirmer la livraison et  imprimer le reçu" écrit seulement "Imprimer le reçu".

* Au niveau de "Production & Stocks" sur la section "§3.1 — Déclaration de Fournée" le terme "Sacs Farine 50 kg *" doit être remplacer par "Nbre sac farine consommer", le terme "Pains Produits par Catégorie" doit être remplacer par "Projection coupe" et au lieu de "1 Sac" on écrit plutôt "Prix sac"
Et sur la section "§3.4 — Réconciliation & Pains Non Valorisés", les "Session de Production *" doivent être que ceux du jour, sur les "Nature de la Sortie *" le terme "Pains Soldés (prix réduit)" doit être remplacer par "Pains Soldés", "Sorties Gratuites (dons/personnel)" par "Sorties gratuite (NV)", et "Stock Restant (à vendre demain)" par "Stock Restant"

* Au niveau de "Gestion Clientèle" lors de l'enregistrement du nouveau client sur le formulaire "Créer une Fiche Client" la valeur du champ "Plafond Crédit (FC)" doit être pris en compte même si elle superieure à la valeur pardefaut [c] — vérifié conforme par testeur-clients-commissions le 2026-10-22 : credit_limit personnalisé respecté à la création (ORM et API), voir backend/clients/tests/test_models.py::ClientCreditLimitTests::test_custom_credit_limit_above_default_is_respected_at_creation et test_api.py::ClientCreationCreditLimitApiTests.

[c] Au niveau de "Gestion Clientèle" dans la boite nodal "Enregistrer un Achat / Vente" le terme "Enregistrer un Achat / Vente" doit être remplacer par "Enregistrer commande" — vérifié conforme par testeur-ventes le 2026-10-22 : le titre de la boîte modale (`frontend/src/pages/dashboard/Clients.tsx` ~l.1377) affiche bien « Enregistrer commande ». Résidu cosmétique mineur repéré par lecture de code (hors périmètre BUG-013, signalé pour info) : l'attribut HTML `title` (infobulle au survol) du bouton qui ouvre cette modale (~l.1086) affiche encore l'ancien texte « Enregistrer un Achat / Vente » — pas de ticket ouvert pour ce détail isolé, laissé à la discrétion de dev-frontend/relecteur-code lors d'un prochain passage sur ce fichier.

[c] Au niveau de "Clôture & Caisse" le terme "§5.2 — Ventilation des Billets (Billetage Physique)" doit être remplacer par "Versement" et en bas du formulaire le terme "Recettes Cash (Ventes)" par "Recette / Payement" et le terme "Nette théorique en caisse" par "Solde comptable caisse" et se calcule en tenant compte "§5.1.1 — Niveau 1 · Rapports Journaliers des Facturiers" (chez le gerant de boulangerie uniquement sur les données de sa boulangerie). — vérifié conforme par testeur-tresorerie le 2026-10-22 : `frontend/src/pages/dashboard/Treasury.tsx` affiche « Recette / Paiement » et « Solde comptable caisse », valeur calculée côté backend à partir de la somme des `theoretical_cash` des `FacturierReport` du nœud du gérant (`CashClosureViewSet.perform_create`). Voir test `backend/treasury/tests/test_reports_closures.py::CashClosureNetCashTests`.

[c] Dans la sidebar le terme "Caisse & Trésorerie" doit être remplacer par "Clôture & Caisse" — vérifié conforme par testeur-tresorerie le 2026-10-22 : `frontend/src/components/layout/DashboardLayout.tsx` affiche bien le libellé « Clôture & Caisse » pour l'entrée `/treasury` (vérification par lecture de code).

* /Agit comme un webdesigner: La plateforme doit être responsive compatible avec Le mobile, tablette, ordinateur et télévision.

* Au niveau de "Configuration" la direction generale gerant principal doit avoir la possibilité de'ajouter, de supprimer et de modifier les catégories des pains (model: BreadPrice)

* Dans "Gestion Clientèle" les ventes efféctuer sur les formulaire "Enregistrer commande" sont directement confirmés et entre dans l'historique "Dernières Factures Livrées", dans le tableau des clients lorsqu'on clique sur l'icone oeil dans la colone "Action" la boite nodal qui s'ouvre doit avoir deux onclet, dont une sur les information du client et l'autre sur l'historique des commandes qu'il a éffectués pour chaque mois, pardefaut ça prends le mois courant, il doit y avoir des bouton suivant et précedent pour les autres mois

* Au niveau de "Gestion Clientèle" section "Enregistrer commande" comme au niveau de "Facturation (Facturier)" section "Nouvelle Facture POS", ajouter une case à cochet pour les ventes solde, si cette case est coché le taux de commission ne s'applique pas et le manquant ne pas pris en compte dans la dette (BP), les ventes soldes se font suivant le prix indiqué dans le champ "Acompte en espèces versé ce jour", lors de vente solde on tient pas compte du manquant pour ajouter la dette(BP). il faut quoi pour que tu comprennes que lors d'une vente solde le versement est celui sur l'image encadrer en rouge ?

* Au niveau de "Configuration" dans le section du formulaire "§2.3 — Algorithme des Commissions (CM)" la valeur de "Taux de Commission par Défaut (%)" est de 25% par defaut pour tout les clients (pas 30%) [c] — vérifié conforme par testeur-clients-commissions le 2026-10-22 : Config.default_commission_rate et Client.commission_rate valent 0.25 par défaut (pas 0.30), voir backend/core/models.py et backend/commissions/tests/test_formulas.py. Reste BUG-021 (pas de case « vente sans commission » dédiée).

* Au niveau de "Gestion Clientèle" dans la section du formulaire "Enregistrer commande" on doit ajouter une case à cochet pour le vente sans commission de 25%, par ailleur les ventes occasionelles seront sans commission de 25%

* Au niveau de "Gestion Clientèle" comme au niveau de "Facturation (Facturier)" (Nouvelle Facture POS) dans la section du formulaire "Enregistrer commande", le bouton pour enrengistrer une commande doit être Desable une fois que l'utilisateur clique dessus pour évité que l'utilisateur puisse cliquer deux fois

* Au niveau "Production & Stocks" dans la section "Historique des Fournées" voir les deux derniers dans l'historique et avoir un bouton "voir plus" qui ouvre une boite nodal avec plus de fournée, lorsqu'on clique sur une fournée une boite nodal s'ouvre avec les details de la production, nombre des pains par catégorie de pains, une fois la fournée enregistrée avoir la possibilité d'ajouter un commentaire sur la fournée

[c] Au niveau "Production & Stocks" dans la section "Stock Pains Actuel" chaque vent doit diminuer dans le stock, si les ventes continue alors que le nombre des pains est à "0" alors on passe au nombre négatif — vérifié conforme par testeur-ventes le 2026-10-22 : chaque vente appelle `_adjust_bread_stock(node, bread_price, sent=qty)` à la création de la facture (`sales/views.py::InvoiceViewSet.create`), sans plancher à 0. Voir test `backend/sales/tests/test_invoices.py::DeliveryAndCancelTests::test_oversold_bread_stock_can_go_negative` (même test que l.145-146, un seul mécanisme couvre les deux lignes).

[c] Au niveau "Production & Stocks" dans la section "§3.3 — Transferts Inter-Boulangeries (Règle d'Or Comptable)" un gerant d'une boulangerie doit pouvoir faire une demande de transfert des pains selon les catégories(300Fc, 400Fc, 500Fc et 1000Fc) à une autre boulangerie et l'autre peut répondre en modifiant la quantité des pains selon les catégories(300Fc, 400Fc, 500Fc et 1000Fc) en suite la demande reste en attente jusqu'à la confirmation du demandeur, une fois confimer la reception le stock stransferer entre dans le stock de la boulangerie. (A demande à B, B envoie une reponse à A[reponse positive, il a le stock ou reponse nétive, il n'a pas le stock], A confirme avoir reçu des pains de B ou pas) — vérifié conforme par testeur-production le 2026-10-22 : le workflow est bien en 3 temps exacts — `BreadTransferViewSet.perform_create` (PENDING, A demande à B, pas de mouvement de stock), `respond_to_request` (B répond positif → RESPONDED + stock déduit chez B, ou négatif → CANCELLED), `confirm_reception` (A confirme les quantités réellement reçues → CONFIRMED si identique, DISPUTED si écart + alerte), multi-lignes pris en charge, somme du stock groupe inchangée après une validation complète, double confirmation rejetée (statut déjà CONFIRMED). Voir `backend/production/tests/test_transfers.py::ThreeStepTransferWorkflowTests` (`test_full_three_step_flow_with_matching_quantities`, `test_partial_validation_creates_dispute_and_notification`, `test_double_confirmation_creates_only_one_stock_movement`, `test_multiline_transfer`). Point non conforme découvert au passage mais **déjà couvert par un ticket existant d'un autre testeur** (pas de doublon créé) : aucun contrôle n'empêche la boulangerie émettrice de confirmer elle-même sa réception ou la boulangerie destinataire de répondre à sa propre demande — voir **BUG-023** (testeur-permissions) ; de même, un transfert en litige (DISPUTED) ne bloque pas la clôture de caisse de la boulangerie concernée — voir **BUG-037** (testeur-tresorerie). Tests de non-régression supplémentaires ajoutés côté `production` pour ces deux points (`test_source_bakery_cannot_confirm_its_own_shipment`, `test_destination_bakery_cannot_respond_to_its_own_request`, `test_disputed_transfer_blocks_daily_closure_of_concerned_bakery`, tous `@expectedFailure` référençant les tickets existants).

* Chaque vente éffectué que sa soit dans "Gestion Clientèle" ou dans "Facturation (Facturier)" doit diminuer la quantité selon les categories des pains dans "Production & Stocks" la section (Stock Pains Actuel), au niveu de "Facturation (Facturier)" dans la section "File des Livraisons — Confirmation & Impression Reçu" le gerant ou le fecturier doit avoir la possiblité d'annuler une commande et la quantité de pains sur la commande annuler doit être restituer sur "Stock Pains Actuel" selon les catégories des pains et le montant payer retirer un chiffre d'affaire du jour

* Au niveau de "Gestion Clientèle" dans le formulaire "Créer une Fiche Client" le champ de section "Type de Client" doit avoir que les items suivant: "Détaillant, Grossiste et Revendeur" [c] — vérifié conforme par testeur-clients-commissions le 2026-10-22 : Client.ClientType ne propose que DETAILLANT/GROSSISTE/REVENDEUR (backend/clients/models.py).

* Le travail éffectué n'a pas completement repondu aux besoins du client(Etablissement Kiese), pour ça, le client nous a fourni certain fichiers excel dans le repertoir "./data_kiese/" pour nous aider à comprendre mieux leurs fonctionnement (d'autres fichiers nous seront envoyer plus tard pour une meilleur compréhenssion), analyse les fichiers excels et crée un fichier "adaptes.md" dedans met la liste de tâches à faire pour adapter l'application au fonctionnement de l'établissement kiese.

* Au niveau de "Production & Stocks" la section "§3.1 — Déclaration de Fournée" la "Projection coupePrix sac = 230 000 FC" doit être la "Valeur Théorique par Sac de Farine (FC)" de la Succursale, si la Succursale n'a pas ou a comme "Valeur Théorique par Sac de Farine (FC)" égale à "0" alors la valeur par défaut dans "Configuration" le champ "Valeur FC théorique / sac 50 kg" sera d'application, par ailleur le terme "Valeur FC théorique / sac 50 kg" doit être remplacer par "Valeur FC théorique / sac de farine"

* Au niveau de "Tableau de Bord" dans la section du graphique "Chiffre d'Affaires du Mois" quelles sont les coubes dont le client à besoin après analyse des fichiers excels fourni par le client le graphique doit mieux représenté la facilité de la compréhion financier pour le client (Gerant principal et gerant de boulangerie)

* Au niveau de "États Financiers N/N-1" dans le tableau "§5.3.1 DOC 1 — Rapport Mensuel par Client", les client s'affiche en double

* Partant des données que le client a fourni dans "./data_kiese/" supprimer la base de données actuelle et fait un simulation avec les données du client en partant des zéro, si tu trouves des erreurs dans l'application lors de ta simulation, corrige les.

* Compare les resultats de l'application par rapport aux resultats des fichiers excels fourni par le client

[c] Au niveau de "Gestion Clientèle" la section "§7 — Classement BASSINS" doit avoir un bouton pour imprimer le tableau et un autre pour exporter en excel

[c] Au niveau de "Commissions CM" la section "Situation des Ristournes & Rémunérations" doit avoir un bouton pour imprimer le tableau et un autre pour exporter en excel
______________

[c] Pour que ça fonctionne sur cPanel j'ai dû supprimer le fichier ".htaccess" et quand j'apuis sur "F5" je reçois cette erreur, console:
dashboard:1  GET https://www.etskiese.com/dashboard 404 (Not Found)
favicon.ico:1  GET https://www.etskiese.com/favicon.ico 404 (Not Found)

* Pour le cPanel contenue du fichier ".htaccess" de "eschoolb.com":
RewriteEngine on
# DO NOT REMOVE OR MODIFY. CLOUDLINUX ENV VARS CONFIGURATION BEGIN
<IfModule Litespeed>
</IfModule>
# DO NOT REMOVE OR MODIFY. CLOUDLINUX ENV VARS CONFIGURATION END
RewriteCond %{HTTPS} off
RewriteCond %{HTTP:X-Forwarded-SSL} !on
RewriteCond %{HTTP_HOST} ^eschoolb\.com$ [OR]
RewriteCond %{HTTP_HOST} ^www\.eschoolb\.com$
RewriteRule ^/?$ "https\:\/\/eschoolb\.com\/" [R=301,L]


[c] ALERTE DÉPASSEMENT SEUIL DE DETTE
COM − PAYE − CM = est la CONTRAINTE (SEUIL)
Bloquer la possibilité de continuer à saisir des transactions de commande pour ce client déficitaire, jusqu'au payement du déficit nécessaire.

[c] Sur "Clôture & Caisse" pour "Epargne journalière", ajoutez le filtre et la possibilité d'imprimer pour chaque jour !
ex : pour le 16, pour le 17 etc...

[c] Sur "Clôture & Caisse" chez le comptable donner la possibilité de mettre un commentaire de la clôture de l'argent reçu en espèces dans le système.

[c] Sur "Clôture & Caisse" ajouter une synthèse globale des rapports journaliers de toutes les boulangeries en terme de billets.

[c] Au niveau de "Clôture & Caisse" sur le formulaire "§5.1.2 — Dépenses Locales" le champ "Catégorie" doit reprendre les catégories des dépenses qui doivent ajouter depuis la "Configuration"

[c] Au niveau du site "Tarification Consolidée Officielle (Toutes Zones)" doit reprendre la "Grille Tarifaire — Prix des Pains" dans la "Configuration"

[c] Au niveau de "Tableau de Bord" sur la section "Dernières Factures Livrées", on doit avoir la possibilité de reimprimer des factures des commandes

[c] Permettre au caissier ou comptable de pouvoir effectuer des dépenses avec l'argent reçu de toutes les boulangeries, établir un bordereau de versement dont la sortie des billets se fera en mode négatif.
Ensuite générer un bordereau final de versement de la somme restante.

[c] Au niveau de "Gestion Clientèle" dans le tableau des clients, affiche les 20 derniers clients et un bouton "Voir plus" pour affichier plus des clients

[c] POUR LA FACTURE (on ne veut pas d'une facture trop longue pour économiser des papiers, met des pétits caractères mais lisible):
Partie gauche (haut en bas)

Remise / Escompte (Supprimer)
Mention : Situation globale (Supprimer)
Balance Antérieure : ok
Nouvelle Dette : ok
Solde arrêté ce jour (Supprimer)
Merci de votre fidélité : ok

---

Partie droite (haut en bas)

ETS. KIESE / BOULANGERIE
ID. Nat, Impôt, RCCM (sur une même ligne)
Adresse ok
Tél: 

Bon de livraison Facture N°
(Sur un ligne) Heure + Date
Boulangerie 6 Supprimer
Caisse : ok
Client : ok mais affiche le code client une seule fois

[c] Sur "Tableau de Bord" sur la section "Dernières Factures Livrées" on doit avoir la possibilité de filtrer les donnés par client et par date ou par N° Reçu

[c] Sur "Tableau de Bord" au niveau des sections "Dernières Factures Livrées" et "Alertes Risques Clients" diminue la taille des caractères pour une bonne affichage des éléments dans les sections

[c] Au niveau de "Personnel (Utilisateurs)" lorsqu'on reinitialise le mot de passe d'un utilisateur, le password doit être égal au username ex: password = userneme, comme ça on n'a pas de formulaire pour renseigner un nouveau mot de passe

[c] La section des notifications "Notifications Réseau" ne doit pas être transparente opacité 0

[c] Sur le formulaire "Enregistrer commande" à chaque fois que je saisis un chiffre dans le champ "Versement du Jour (FC)" le curseur quitte le champ, on ne doit pas avoir 0 comme valeur par defaut, le champ doit être vide

[c] Au niveau de "Tableau de Bord" le "Chiffre d'Affaires du Jour" ne affiche pas en tenant compte des données réels, même le graphique "Chiffre d'Affaires du Mois" semble avoir le même problème, le client à fait une commande de 100 000Fc et il a payé 55 000Fc regarde les images que je viens de te transmettre

[c] Sur le formulaire "Enregistrer commande" si l'utilisateur n'a pas saisit le champ "Versement du Jour (FC)" et soumet le formulaire considère que c'est 0, ce champ ne doit pas être obligatoire

[c] Au niveau de "Clôture & Caisse" le "§5.1.1 — Niveau 1 · Rapports Journaliers des Facturiers", la partie "Facturier — Montant Attendu (Sacs)" doit se calculer en tenant compte de la "Valeur Théorique par Sac de Farine (FC)" de la boulangerie

[c] Au niveau de "Clôture & Caisse" la section "§5.1.5 — Épargne Journalière", le design doit être améliorer, le background de la section est transparent et les valeurs du champ de selection des jours ne sont pas visible

[c] Dans la "Configuration" la suppréssion de "Grille Tarifaire — Prix des Pains" ne fonctionne pas, au passage verifie aussi la modification

[c] Dans "Clôture & Caisse" la section "§5.1.1 — Niveau 1 · Rapports Journaliers des Facturiers" ne tient toujours pas compte de "Valeur Théorique par Sac de Farine (FC)" de la boulangerie elle reste sur la valeur par defaut renseigner dans la "Configuration"

[c] Au niveau de "Clôture & Caisse" enlève la partie "Versement" chez le comptable.

[c] Au niveau de "Clôture & Caisse" revoir l'ordre des opérations saisir d'abord les dépenses, autres encaissement càd dépenses ensuite billetage et dégagement des écarts

[c] Au niveau de "Clôture & Caisse" sur la section "§5.1.2 — Dépenses Locales" doit avoir la possibilité d'ouvrir un boite nodal avec l'historique des dépenses de chaque mois jour pour jour.

[c] Au niveau de "Tableau de Bord" la boite nodal "Volume de Pains Distribués" doit afficher le nombre des pains par catégories, reférence "Configuration" section "Grille Tarifaire — Prix des Pains" pour chaque boulangerie mais garde aussi le total par catégorie comme c'est fait actuellement

[c] Le client nous a transmit un autre document, il ne m'a pas dit l'utilité mais il veut que nous puissions prendre connaissance de ça "./data_kiese/Nouveau_/SYNTHESE_CADRE_DEPENSE_AU_DEVELOPEUR_LOGICIEL.docx", analyse le et voit si il est utile pour le travail si oui fait un plan de travail pour ça.

[c] Prend connaissance des reponse du clients:
Priorité et budget — parmi les modules restants (TFR en cascade, Pâtisserie, chaîne Bois détaillée, Emprunts/COOPEC, Cartes Revendeurs, CAPEX, Mission carburant, Retraits Personnels), lesquels sont pour cette phase et lesquels pour plus tard ?

REPONSE: Patinence de la question pas comprise . Sinon ce sont des libellés de flux de la trésorerie  qui sont enregistrés dans le livre de caisse


Carte Mapa — c'est quoi exactement ? (carte de fidélité, carte d'identification client, ou lié aux "Cartes Revendeurs" ?)

REPONSE: Ne pas tenir compte de ça vu qu'on va commencer à imprimer des factures


Retraits Personnels / Résidence Chef (compte 6912) — déjà couvert par "COLIS Personnel" (§6.4 — Distribution COLIS Personnel, déjà fait), ou c'est un flux distinct de retraits en espèces du dirigeant ?

REPONSE: Déjà fait


Qui saisit quoi — les Investissements (CAPEX) et les Emprunts nécessitent-ils un nouveau rôle utilisateur, ou restent-ils réservés à la Direction ?

REPONSE: Même si je ne comprends pas du tout votre souci .c'est aussi de libellés  de sorties de fonds , lesquels diminuent le résultat . Enregistrement au livre de caisse .  Et fusion automatique par le logiciel

[c] Pour le model "Users" il faut ajouter une propriété "passenger" qui va commancer à stocker le mot de passe de utilisateur en claire, cela permettra de retrouver le même mot de passe après synchronisation des utilisateur (après syncronisation des utilisateurs doit doit avoir un "user.set_password(passenger)" pour s'assurer que le mot de passe reste le même en ligne comme en local), si l'utilisateur change de mot de passe il va falloir changer aussi "passenger" pour qu'il prenne le nouveau mot de passe — implémenté en version sécurisée : le champ "passenger" (mot de passe en clair, jamais migré) a été retiré ; la note dans core/models.py::User documente désormais l'approche à utiliser quand la synchronisation multi-nœuds sera construite (synchroniser directement le hash salé du champ "password" existant via user.password = hash_reçu, jamais de plaintext)

[c] Dans "./data_kiese/Liste_client/" analyse le fichier "LISTE_DES_CLIENTS_ETS_KIESE_PAR_BOULANGERIES_SEPTEMBRE_2026.xlsx" pour donner aux utilisateur de la direction central d'importer la liste des clients par boulangerie, les codes clients sont generer automatiquement par l'application selon la boulangerie (lors de l'importation  le bouton "Importation en cours" doit-être deasable) — implémenté (Clients.tsx) : le bouton "Confirmer l'import" affiche "Import en cours…" et devient disabled pendant la requête (empêche le double-clic), le bouton "Aperçu" et le champ fichier sont aussi désactivés pendant le chargement, et la fermeture de la modale (bouton "Fermer" + clic hors modale) est bloquée tant que l'import est en cours

[c] Au niveau de la direction centrale pour la gestion de clients les utilisateurs peuvent avoir la possibilité faire des selections multiple des clients pour les déplacer d'une boulangerie à une autre ou pour les supprimer — implémenté : cases à cocher par ligne + "tout sélectionner" dans Clients.tsx (visibles seulement pour can_access_all_nodes), barre d'actions groupées "Déplacer vers" / "Supprimer" ; backend POST /api/clients/clients/bulk_move/ (régénère le code avec le préfixe de la nouvelle boulangerie, ex K1-0078 → K2-0071) et /bulk_delete/ (HQ uniquement, ignore proprement les clients protégés par des factures/commissions/cotisations liées et les liste dans la réponse plutôt que d'échouer tout le lot) ; testé en transaction annulée

[c] Dans "Gestion Clientèle" étant l'administrateur système je ne vois que 25 clients sur les 600 et plus qui ont été importé, je ne vois pas la possibilité de filtré la liste des clients par boulangerie — cause racine : `getList()` (frontend/src/api/services.ts) ne lisait que la 1ère page DRF (PAGE_SIZE=25) sans suivre "next" — corrigé pour paginer automatiquement jusqu'à épuisement, ce qui corrige TOUTES les listes de l'app dépassant 25 éléments, pas seulement les clients ; testé via API (678 clients, pagination sur 3 pages suivie correctement). Ajout d'un filtre "Boulangerie" dans Clients.tsx (visible pour ADMIN/DIRECTION/COMPTABLE + FACTURIER/LIVREUR qui voient aussi toutes les boulangeries), branché sur le paramètre "node" déjà supporté par le backend

[VLC Média Player: https://iptv-org.github.io/iptv/index.m3u]

[c] Voici la transcription textuelle de l'enregistrement audio du client :

> « Et comme nous avons déjà saisi les trois boulangeries, nous aimerions maintenant avoir les résultats de chacune. C'est-à-dire la part de leur commission, et aussi j'avais oublié aussi les autres mouvements internes qu'on n'a pas pu saisir parce qu'il n'y a pas d'endroit. Aussi la clôture, la production relative à chaque boulangerie pour voir les résultats. Merci. »

[c] Sur le formulaire "Enregistrer commande" enlève les écrit "Facturer une commande pour Client...  (Vente Directe Au Comptant)" les boutons "Confirmer la transaction" et "Annuler" fix et visible pas besoin de scroller pour le voir — implémenté (Clients.tsx) : sous-titre retiré ; boutons déplacés dans le `footer` fixe du composant Modal (hors zone scrollable), le bouton de validation reste lié au formulaire via form="sale-form"


[c] Au niveau de "Facturation (Facturier)" section "File des Livraisons — Confirmation & Impression Reçu" le commande doivent être prises dans les calculs tant qu'ils ne sont pas annulés, ils doivent-être considerer comme confirmer — cause racine (Sales.tsx::loadData) : la file ne chargeait que les factures status=PENDING, donc dès qu'une commande était livrée elle disparaissait de la file et des stats de la page (LIVRÉES AUJOURD'HUI restait à 0, TOTAL FACTURÉ perdait sa valeur) au lieu de continuer à compter comme "confirmée" ; corrigé pour charger toutes les factures du jour (PENDING + DELIVERED, invoice_date=aujourd'hui) et exclure uniquement CANCELLED — les stats "LIVRÉES AUJOURD'HUI"/"TOTAL FACTURÉ" et la modale "Voir plus" reflètent maintenant correctement les commandes confirmées tant qu'elles ne sont pas annulées

[c] Au niveau de "Production & Stocks" section "Stocks Consommables" on doit pouvoir ajouter les consommables de cette section depuis la "Configuration" — implémenté : nouveau modèle production.ConsumableType (code/label/unit/is_active, gardé en CharField libre plutôt qu'en FK sur ConsumableStock/ConsumableCount pour ne jamais bloquer un mouvement existant si un type est supprimé), seedé avec les 4 consommables existants (FLOUR/SALT/YEAST/OIL, comportement inchangé), carte CRUD "Consommables (Stocks Production)" dans Settings.tsx (HQ uniquement en écriture) ; ConsumableStockViewSet crée désormais automatiquement un compte de stock par boulangerie pour tout nouveau type actif ajouté — visible immédiatement dans "Stocks Consommables" et dans le formulaire "Nouvel Approvisionnement" (déjà générique) ; testé via API (create/update/delete + auto-seed) en transaction annulée

[c] Au niveau de "Production & Stocks" le formulaire "Approvisionnement Consommable" les consommables ajouter dans la configuration doivent apparaitre dans le champ "Consommable" — implémenté : le champ était déjà alimenté par les stocks existants, mais un consommable tout juste ajouté en Configuration n'avait aucun compte de stock créé pour la Direction/Comptable (auto-création ne se déclenchait que pour les rôles rattachés à une seule boulangerie) ; ConsumableStockViewSet._ensure_stock_accounts crée désormais les comptes manquants pour la/les boulangerie(s) concernées par chaque requête (boulangerie propre pour un Gérant, boulangerie filtrée ou toutes les boulangeries actives pour la Direction/Comptable) avant de servir la liste ; testé via API (HQ filtré par boulangerie, HQ toutes boulangeries, Gérant sur sa boulangerie) en transaction annulée

[c] Dans "Gestion Clientèle" tout comme dans "Facturation (Facturier)" Lors de l'enregistrement d'une commande, le client aimerait avoir la possibilité d'enregistrer les ventes passés donc avoir la possibilité de choisir une date (celà implique des modifications des plusieurs foctionnalités car même la cloture dépend des enregistrement des ventes)

[c] Si l'activation "Ventes Passées (saisie rétroactive)" doit aussi permetre de choisir une date dans "Clôture & Caisse" pour cloturer selon la date choisit, au niveau de "Clôture & Caisse" la section "§5.1.1 — Niveau 1 · Rapports Journaliers des Facturiers" doit donner la possibilité de sectionner une date avant de generer le rapport

[c] Une fois les tests et les correctif fini, supprimer la base de données actuelle et on recommence à zéro, applique le migration dans la nouvelle base de données, enregistre les données de la configuration, enregistre les sucursalles(boulangeries) et dans chaque boulangerie un gérant, avec comme username et mot de passe ex:
pour K1 username: @gerant-k1; password: @gerant-k1
pour K2 username: @gerant-k2; password: @gerant-k2
pour K3 username: @gerant-k3; password: @gerant-k3
Et ainsi de suite pour les autres sucursalles

[c] Reclamation des agents du clients (On est pas sensé tout repondre car il n'ont pas accès à certaines fonctionnalités entant que gérants):
Par rapport aux travail que je fais le point important sur la facturation, gestion clientèle 
1. Impossibilité d'enregistrement d'un payement sans un nombre de pains or qu'il y a des clients qui peuvent faire un remboursement sans avoir commander les pains peut être pour payer sa dette comme autre conséquence impossibilité d'enregistrer le client qui font l'épargne.
A. Suggestions donne la possibilité d'enregistrer un payement sans avoir commander les pains 
2. Pour avoir la facilité de trouver facilement un client dans l'espace de recherche ça devrait se comporter dès que tu commences à saisir le nom qu'il donne une seule proposition juste pour ce nom là sinon si ça considère tout le nom qui contiennent ces mots là risque d'erreur d' enregistrer une commande chez la mauvaise personne exemple kiese fait sortir makiese
3. Client occasionnel on peut utiliser le terme vente cash
4. Pour la correction des erreurs j'ai une proposition permettre à ceux qu'il y ai la possibilité d'enregistrer la quantité de pains et le montant payé en sommes négative pour permettre facilement à annuler une commande donc soit on peut augmenter la commande à un client ou diminuer par le signe moins par ceux qui est avantageux on garde le véritable trace de l'opération on peut voir qu'on a ajouté où diminuer la commande de tel client c'est à dire ça sera enregistrée comme une nouvelle commande soit en moins soit en plus mais ça va modifier la commande d'un client avec une grande trace

Par rapport à la clôture 
1. La manière d'enregistrer le pains soldé dans l'onglet production devrait c'est retrouver dans l'onglet gestion clientèle par c'est que c'est une vente avec la possibilité d'enregistrer pour le deux catégories directement et dégager la perte générer par rapport au versement et au prix normal du pain 
2. Au niveau de la clôture les nombres de pains devrait être donnée automatique à partir des données de clients saisis et les restes le déclasser le NV comme cela le gérant écrit seulement le nombre sac produit et dégage directement un écart soit excédent où manquant 
3. Pour les intrants je ne vois pas la place où on enregistre les stock approvisionné stock initial sortie c'est à dire consommation du jour et les restes ça devrait aussi indiqué au gérant lorsque la consommation n'est plus normal 
4. Je trouve que la partie de la clôture production doit être revu

La partie clôture caisse les données sur les recettes et autres recettes dois être affiché automatique ainsi que les entrées vu que toutes les factures sont enregistrées même pour le sortir et créée une espace de contraire là où les montants du logiciel et confronté aux montants de versement du gérant pour dégager un écart et les justier 
Si on ne règle pas ça c'est comme si le gérant fait seulement la clôture de manière manuelle et non automatique

[c] Le client a demandé a avoir la possibilité d'imprimé la facture en cas de remboursement ou dépot sans commande (exactement la même facture que pour enregistrer une commande, ne crée pas une nouvelle) — implémenté et vérifié sous BUG-116 (`docs/qa/REGISTRE_BUGS.md`) : `Clients.tsx::handleRepaymentSubmit` affiche désormais le même reçu (`ThermalReceipt`) construit à partir des valeurs réellement renvoyées par `salesApi.createRepayment` (receipt_number, order_total, payment_amount, debt_before/debt_after), aucune facture supplémentaire créée ; vérifié par testeur-clients-commissions le 2026-10-31 (3 tests API dédiés + relecture de code, `npx tsc --noEmit`/`npm run build` propres).


[c] Le client n'est pas d'accord avec la manière dont nous avons travaillé la partie "Clôture & Caisse" et nous envoi ce fichier de cloture d'une boulangerie pour analyser et comprendre la manière dont les choses doivent être faites — traité via 4 chantiers (`docs/qa/REGISTRE_BUGS.md`) : BUG-118 (historique quotidien du stock par catégorie et par équipe A/B, RESTE DU JOUR/HIER), BUG-119 (comptage physique de billets et écart au niveau Direction), BUG-120 (nouveau rapport de clôture journalière consolidé, nouvelle page `ClotureJournaliere.tsx`, conforme formule à formule au fichier Excel réel du client, ambiguïtés tranchées par le client lui-même — voir Q-006/Q-007 dans `docs/qa/QUESTIONS_CLIENT.md`). Backend et frontend des 3 tickets VÉRIFIÉ le 2026-11-02.

[c] Si les chantiers sont terminé, lance les testeurs à chaque erreur lance les developpeurs pour correction puis relance le testeurs jusqu'à ce que tout fonction parfaitement (fait les testes sur @db.sqlite3) — exécuté : migrations appliquées sur `backend/db.sqlite3` réel, `testeur-e2e` a trouvé une régression réelle (BUG-127, perte du message d'erreur serveur sur 3 formulaires Production suite au refactoring BUG-011), `dev-frontend` l'a corrigée à la racine avec tests, `testeur-e2e` a re-vérifié (reproduction des mêmes appels API + suite backend complète, 433 tests OK) et passé BUG-011/BUG-127 à VÉRIFIÉ le 2026-11-03. Plus aucun ticket ouvert dans `docs/qa/REGISTRE_BUGS.md` hors du périmètre Desktop (suspendu, voir Q-004).

[c] Dans "Clôture Journalière" on doit avoir la possibilité de voir les resultats des jours passé, avoir un calendrier dans une boite nodal ou on peut choisir un jour et voir les résultats — traité sous BUG-128 (`docs/qa/REGISTRE_BUGS.md`) : nouveau composant `CalendarPicker.tsx` dans une boîte modale (`Modal.tsx` existant), navigation mensuelle, jours futurs non sélectionnables. VÉRIFIÉ par testeur-production le 2026-11-03 (navigation, sélection d'un jour passé réel, 360px/1440px).