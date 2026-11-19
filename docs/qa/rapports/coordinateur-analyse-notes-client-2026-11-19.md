# Analyse d'écarts : notes du client du 2026-11-19

Source : `notes-application-boulangerie.md`. Analyse en lecture seule, aucun ticket créé dans le registre.
Référence de priorité : remarque.md > adaptes.md > cadre_comptable.md > cahierDesCharges.md. Les notes du 19/11 sont plus récentes que les documents précédents ; en cas de conflit avec une décision antérieure, la question est posée au client et la valeur actuelle est conservée entre-temps.

Légende : FAIT, PARTIEL, ABSENT, CONTRADICTION (C).
Les corrections BUG-303 à BUG-307 du 19/11 ne sont pas encore commitées (git status) ; elles sont comptées « FAIT (non commité) ».

## 1. Tableau des points

| # | Point des notes | Statut | Preuve dans le code / ce qui manque |
|---|---|---|---|
| R1 | Reste d'hier ne dépend pas d'une équipe | FAIT (non commité) | `production/views.py::_build_daily_closure_report` expose `reste_du_hier_jour` et `reste_du_jour_jour` (niveau jour) en plus du détail par équipe. `ClotureJournaliere.tsx` (l.297) affiche le niveau jour. Test : `production/tests/test_bug303_304_306_2026_11_19.py`, BUG-303/304. Reste : `DailyOpeningConfirmation` et `DailyBreadStockSnapshot` gardent `team`, donc la saisie du stock de départ reste par équipe (c'est du stockage interne, voir Q-A). |
| R2 | Non vendu = sortie gratuite (même chose) | CONTRADICTION (C) | `BreadDisposal.DisposalType` garde `UNSOLD` (« Invendu, perte sèche ») et `FREE_DIST` (« Sortie gratuite ») séparés ; le rapport de clôture a `non_vendu_nv` et `sorties_gratuites` ; CLAUDE.md §5.4 les liste séparément ; le libellé frontend `Production.tsx` l.99 dit « Sorties gratuite (NV) ». Les notes demandent une seule notion. Choix à faire : fusionner (migration de données UNSOLD vers FREE_DIST, un seul libellé) ou garder deux types mais les additionner dans l'affichage. |
| R3 | Transfert = vente / revenu du jour chez l'émetteur ; soustrait chez le receveur | PARTIEL + C | Existe : `appro_effectue` et `appro_recu` par catégorie dans le rapport de clôture, entrés dans `mvm_interne_fc` donc dans `total_du_jour_fc` (Q-006). Écart : `appro_recu_fc` est ajouté avec le signe PLUS, comme `appro_effectue_fc` (l.2593). Le receveur devrait le soustraire (notes ; adaptes.md l.34 : « Appro reçu k1 = -463 500 FC »). Avec deux « plus », la somme au niveau du groupe est le double, ce qui contredit CLAUDE.md §5.4 (« somme nulle au niveau du groupe »). Avec « plus » chez l'émetteur et « moins » chez le receveur, la somme est nulle : les notes et le §5.4 sont alors compatibles. À vérifier contre le classeur K6 (Q-006) avant de corriger. Le transfert n'alimente par ailleurs ni la caisse ni les états financiers (c'est un mouvement de stock, pas une facture). |
| R4 | Paiement des épargnes = encaissement spécial, compte épargne distinct du compte d'achat de pain | ABSENT / PARTIEL | Le paiement d'un client épargne est une `Invoice` normale (commande = 0, paiement = dépôt, adaptes.md l.19). Aucun compte épargne client séparé : `Client.current_debt` (BP) est le seul solde, `Client.ClientType` = Détaillant/Grossiste/Revendeur (pas d'épargne). Le retrait d'épargne est un simple motif (`Invoice.Motif.RETRAIT_EPARGNE`, BUG-290) qui modifie la BP. `treasury.DailySavings` est l'épargne journalière des boulangeries (taux × revenu, adaptes.md [11.1]), un autre concept. Les dépôts d'épargne se mélangent donc au CA cash et à la BP : contradiction de fond avec « ne pas associer à l'achat de pain » et avec BUG-290 (le retrait d'épargne réduit la BP au lieu d'un compte propre). |
| R5 | Paiement déclaratif | PARTIEL (flou) | Le paiement est déjà saisi librement par le facturier (`payment_amount`), mais il n'y a pas de notion de « déclaré » vs « vérifié ». Le sens exact n'est pas donné par les notes (Q-C). |
| R6 | L'heure est une variable | PARTIEL | Existe : heures de rotation d'équipe et journée de travail (`core/workday.py`, `work_date_for`, `delivered_on_work_date_filter`, BUG-141/161/193/247/286). Rien dans les notes ne dit quelle heure doit devenir configurable (début de journée, rotation, ou heure de saisie sur la facture). Q-D. |
| C1 | Clôture : liste des clients du jour avec nombre de tours (factures) et montant | ABSENT | `_build_daily_closure_report` agrège par catégorie de pain ; aucune clé « clients » (par client : nombre de factures, total). Facile à ajouter à partir des `Invoice` livrées de la journée. |
| C2 | L'encodeur corrige ses erreurs de saisie | PARTIEL | Correction d'une facture par `InvoiceViewSet.adjust` (BUG-097), réservé au GERANT ; annulation d'une facture en attente (`cancel`, IsFacturier). Stock de départ : confirmation rééditable (BUG-136). Mais le rôle « encodeur » n'existe pas dans `core/permissions.py` (IsAdmin, IsDirection, IsHeadquarters, IsGerant, IsFacturier, IsLivreur) ; le facturier ne peut pas corriger une facture livrée. Question : qui est l'encodeur, et quelles corrections (facture, versement, fournée, dépense) ? |
| C3 | Bordereaux de versement chez le comptable | PARTIEL | `DisbursementVoucher` existe (niveau Direction, sortie de caisse avec billetage, motif, bénéficiaire). Il s'agit d'une sortie de la caisse direction. Les notes parlent d'un bordereau « chez le comptable », donc probablement le versement d'argent de la boulangerie vers le comptable (justificatif de dépôt), avec accusé de réception. Ce flux n'existe pas. Q-E. |
| C4 | Séparer dépenses du gérant et de l'admin | PARTIEL | `LocalExpense` (gérant, `IsGerant`) filtré par nœud ; `ExpenseCategory` géré par l'admin ; pas de champ « émetteur/nature » (dépense de boulangerie vs dépense de l'administration/direction) ; les dépenses de la direction passent par `DisbursementVoucher` et `CashbookEntry`. La séparation n'est pas explicitée comme règle. Q-F. |
| C5 | Ajouter le « paiement actuel » | ABSENT (terme flou) | Aucune occurrence du concept. Probablement la somme des paiements reçus pendant la journée, à côté du paiement cumulé ou de la BP (colonne de l'Excel de clôture ?). Q-G. |
| D1 | Dette de transactions = paiement − facture (+ = trop payé, − = dette) | PARTIEL / signe inversé | La BP calcule `BP_après = BP_avant + commande − paiement` (CLAUDE.md §5.2, BUG-290/293 y sont alignés), donc BP positive = dette. La « dette de transaction » des notes a le signe opposé pour une seule transaction (paiement − commande = −(variation de BP)). Pas de champ ou colonne affichant ce résultat par facture. `ecart_facture_fc` (clôture) = commande − payé, soit aussi le signe BP. Recommandation : pas de changement de la BP ; ajouter un champ calculé « solde de la transaction » (paiement − commande) avec libellés « plus au compte » / « dette ». |
| D2 | Perte / manque à gagner = paiement + commission − facture | ABSENT | Aucun calcul de ce nom. Seule `perte_fc` des ventes soldées existe. Formule à clarifier : la note de « passages à confirmer » dit que « commission (?) » est ambigu ; la commission devrait s'ajouter car elle est une remise accordée au client (facture × 25 % est déduite du montant dû). Résultat attendu : positif = trop payé, négatif = déficitaire. Q-H. |
| G1 | Régularisation : traiter d'abord le non servi ; le gérant déclare « non servi » une facture depuis Facturation et « Dernières Factures Livrées » (Tableau de Bord) | ABSENT (déclaration a posteriori) | `special_code = NS` ne se pose qu'à la création de la facture (`sales/views.py` l.510 ; NS jamais livrable, jamais déstockée). Aucun endpoint ni bouton pour marquer NS une facture existante (déjà livrée) : il faudrait restituer le stock, recalculer la BP et le CM, tracer l'opération (ajustement lié, comme BUG-097). |
| G2 | Régularisation = retrait des pains pour une facture NS, éventuellement plusieurs jours après | PARTIEL | Code `RG` et facture RG (BUG-177), mais sans lien explicite entre la facture RG et la facture NS d'origine (pas de clé `adjusts`/`regularizes`) ni suivi des NS restant à régulariser. |
| S1 | Stock : signalement de problème (farine, huile, sel, sucre, levure) | PARTIEL | `ConsumableType` configurable (codes, libellés), `ConsumableCount` (comptage physique et écart), alerte de stock négatif (`ConsumableMovement`, notification « Stock négatif »). Pas de « signalement de problème » manuel par le gérant (type de problème, commentaire, photo) ; sucre : pas de type par défaut (ajoutable par la configuration). |
| S2 | Déclaration de fournée : renseigner les informations d'un sac pour le contrôle | PARTIEL | Fournée avec sacs, `sac_value_fc_used`, écart théorique / réel. Aucune information propre à un sac (lot, fournisseur MIDEMA / GMK, poids, numéro). L'annotation de la note est illisible (déjà signalée dans les notes). |
| S3 | Enregistrer le poids du produit | ABSENT | Aucun champ poids dans `production/models.py` ni `BreadPrice`. À préciser : poids par pain (catégorie) ou par fournée ? Q-I. |
| S4 | Fournée automatique : ventes et restes déclarés par catégorie | FAIT (non commité) / PARTIEL | BUG-306 (API) : `ProductionSession.auto_track`, `objective_fc`, `progress_value_fc`, `progress_pct`, `services.py` (suivi des ventes sur la fournée en cours), migration `0024`. Reste côté frontend : barre de progression rouge/orange/jaune/vert ; « restes déclarés par catégorie » dans la fournée auto : à confirmer. |
| P1 | Auto-évaluation du gérant | ABSENT | Aucune occurrence. Contenu à définir (formulaire, notes, périodicité). Q-J. |
| P2 | Vue synthèse de tous les rapports | PARTIEL | Existent : rapport de clôture consolidé (BUG-120), tableau de bord, états financiers, rapports facturier. Pas de page de synthèse unique par boulangerie et par jour (clôture + caisse + stock + écarts + alertes). Lié à l'étape 3 des notes (statistiques direction). |
| T1 | Transfert : envoi sans demande préalable, par catégorie | ABSENT | Le flux actuel part toujours d'une DEMANDE du receveur : `BreadTransferViewSet.perform_create` impose `to_node = user.node` (le demandeur reçoit) ; l'émetteur doit répondre (`respond_to_request`). L'envoi spontané par l'émetteur n'existe pas. Le modèle `BreadTransfer` (PENDING, RESPONDED, CONFIRMED, DISPUTED, CANCELLED) et les lignes par catégorie conviennent déjà. |
| T2 | Transfert : le receveur confirme la réception | FAIT | `confirm_reception` (IsGerant, boulangerie réceptrice), tests `production/tests/test_transfers.py`. |
| T3 | Transfert : alerte si quantités différentes, les deux régularisent | FAIT | `confirm_reception` passe en `DISPUTED` et notifie ; `resolve_dispute` ; clôture bloquée par `_unresolved_incoming_transfer_gap` (BUG-277). Éventuel complément : notification aux deux boulangeries (à vérifier) et lien direct vers la régularisation. |
| E | Étapes de développement 1 à 3 (production, caisse, statistiques) | Information | Séquençage : étape 1 et 2 largement couvertes ; étape 3 = P1/P2. |

## 2. Contradictions avec les documents ou décisions antérieurs

1. **R2** (non vendu = sortie gratuite) contre CLAUDE.md §5.4 et le rapport de clôture actuel (types séparés, formule MVM interne : `non_vendu` ajouté, `sorties_gratuites` non ajoutée dans `mvm_interne_fc`). Fusionner change donc aussi la formule : décision du client nécessaire.
2. **R3** : signe de `appro_recu` ; les notes et adaptes.md l.34 demandent un signe moins chez le receveur. Cela ramène la somme du groupe à zéro (CLAUDE.md §5.4), donc on corrige le code, mais l'impact sur le total du jour est à valider avec le client.
3. **R4** contre BUG-290 : « Retrait d'épargne » existe comme motif de paiement négatif sur la BP ; avec un compte épargne séparé, le motif devrait devenir un retrait du compte épargne et ne plus toucher la BP. À traiter avec le même ticket que R4, avec migration des données existantes.
4. **D1** : inversion de signe par rapport à la BP (pas une contradiction si on garde deux libellés ; à ne pas confondre dans l'interface).
5. **R1** : le stock de départ reste saisi par équipe (BUG-161, 133, 136) ; les notes (et remarque.md du 19/11) veulent le jour entier. Pas de conflit d'affichage, mais la modale « Stock de départ du jour » demande encore équipe par équipe.

## 3. Tickets proposés (à créer par le coordinateur si accord)

| Id prov. | Titre | Gravité | Module | Couche | Taille |
|---|---|---|---|---|---|
| N-01 | Signe de `appro_recu` : le receveur soustrait ; somme du groupe nulle (test sur K1/B2) | Majeur | Production / Clôture | backend + frontend (libellé) | S |
| N-02 | Fusionner « Non vendu » et « Sortie gratuite » (un seul type, migration de données, formule MVM interne, libellés, exports) | Majeur | Production | backend + frontend | M |
| N-03 | Clôture journalière : liste des clients du jour (nombre de factures, montant total) dans l'API, l'écran, l'export et l'impression | Majeur | Production / Ventes | backend + frontend | M |
| N-04 | Déclarer « non servi » une facture existante (gérant) : endpoint + boutons dans Facturation et « Dernières Factures Livrées » ; restitue le stock, recalcule BP et CM, trace par ajustement lié | Majeur | Ventes | backend + frontend | L |
| N-05 | Régularisation liée à la facture NS d'origine (clé de lien, suivi des NS restantes, régularisation plusieurs jours après) | Majeur | Ventes | backend + frontend | M |
| N-06 | Compte épargne client séparé du compte d'achat de pain (modèle, dépôt = encaissement spécial hors CA pain, retrait, migration des motifs `RETRAIT_EPARGNE`) | Bloquant (comptable) / Majeur | Clients / Ventes / Trésorerie | backend + frontend | L |
| N-07 | Transfert envoyé spontanément par l'émetteur (sans demande préalable), par catégorie, confirmé par le receveur | Majeur | Production | backend + frontend | M |
| N-08 | Transfert : notification aux deux boulangeries en cas d'écart et écran de régularisation partagée (si manque constaté) | Mineur | Production | backend + frontend | S |
| N-09 | Champ calculé « solde de la transaction » = paiement − commande sur la facture, le reçu et le rapport | Mineur | Ventes | backend + frontend | S |
| N-10 | Indicateur « perte / manque à gagner » = paiement + commission − facture (par facture, par jour, par client) | Majeur | Ventes / Commissions | backend + frontend | M |
| N-11 | Bordereaux de versement boulangerie vers comptable (émission, accusé de réception, rapprochement avec la clôture) | Majeur | Trésorerie | backend + frontend | L |
| N-12 | Séparer dépenses du gérant et dépenses de l'admin/direction (champ « émetteur », filtres, totaux) | Majeur | Trésorerie | backend + frontend | M |
| N-13 | Rôle ou droit « encodeur » : correction de ses erreurs de saisie (facture non livrée, versement, fournée) avec trace | Majeur | Permissions / Ventes | backend + frontend | M |
| N-14 | « Paiement actuel » dans la clôture (définition à obtenir) | Majeur | Trésorerie / Clôture | backend + frontend | S |
| N-15 | Signalement de problème de stock (consommable, type de problème, commentaire) avec notification au gérant et à la direction ; sucre en consommable par défaut | Majeur | Production | backend + frontend | M |
| N-16 | Informations d'un sac à la déclaration de fournée (lot, fournisseur, poids) | Mineur | Production | backend + frontend | M |
| N-17 | Poids du produit (par catégorie ou par fournée) et contrôle | Mineur | Production | backend + frontend | M |
| N-18 | Fournée automatique : barre de progression rouge, orange, jaune, verte et restes déclarés par catégorie (suite de BUG-306) | Majeur | Production | frontend (+ backend si restes) | M |
| N-19 | Auto-évaluation du gérant (formulaire périodique, historique, vue direction) | Mineur | Pilotage | backend + frontend | M |
| N-20 | Vue de synthèse de tous les rapports (par boulangerie et par jour) | Majeur | Pilotage | backend + frontend | L |
| N-21 | Paiement déclaratif (selon réponse) et heure configurable (selon réponse) | Mineur | Ventes / Core | backend + frontend | S à M |

Ordre conseillé : N-01, N-09, N-03, N-18, N-08 (rapides, sans décision client lourde) ; puis N-07, N-04, N-05 ; N-06, N-11, N-12 après réponse du client (impact comptable, dossier à valider avant développement car changement de schéma et de flux de caisse) ; N-19 et N-20 en dernier (étape 3).
N-06 et N-02 sont des décisions irréversibles (migration de données) : préparer le dossier et attendre la validation humaine.

## 4. Questions pour le client (M. NDUNGA NSAYI PIERRE) et recommandation par défaut

Questions qui EXIGENT une réponse :

- **Q-A (reste d'hier)** : saisit-on encore le stock de départ équipe par équipe (A puis B), ou une seule fois pour la journée ? Défaut : une seule saisie du jour, reprise automatique du « reste du jour » de la veille.
- **Q-B (non vendu = sortie gratuite)** : voulez-vous une seule ligne « Non vendu / Sortie gratuite » ? Aujourd'hui l'application compte les invendus comme une perte et les sorties gratuites comme des dons. Défaut : une seule ligne, avec un champ « motif » facultatif (don, personnel, invendu) pour garder l'information.
- **Q-C (transfert dans le revenu)** : pour K1 qui envoie à B2, le total du jour de K1 augmente et celui de B2 diminue du même montant ; est-ce bien le but, et à quel prix compte-t-on (prix de vente du catalogue ou prix de cession) ? Défaut : prix du catalogue, plus chez l'émetteur, moins chez le receveur, total du groupe inchangé.
- **Q-D (épargne)** : un client épargne a-t-il un compte épargne distinct de sa balance de paiement, avec dépôts et retraits ? Le retrait d'épargne sort-il de la caisse de la boulangerie ? Défaut : compte épargne séparé, dépôt exclu du chiffre d'affaires pain, retrait = sortie de caisse tracée, BP intacte.
- **Q-E (bordereau de versement)** : le bordereau est-il le document remis par la boulangerie quand elle verse l'argent au comptable, avec signature du comptable ? Qui le saisit, qui le confirme ? Défaut : le gérant émet, le comptable confirme la réception, l'écart de montant est signalé.
- **Q-F (dépenses gérant et admin)** : quelles dépenses appartiennent à l'administration (siège) et lesquelles à la boulangerie ? Défaut : séparer par émetteur ; l'admin ne voit pas dans le total du gérant et inversement.
- **Q-G (paiement actuel)** : que veut dire « paiement actuel » ? Défaut proposé : total des paiements encaissés dans la journée, affiché à côté du cumul.
- **Q-H (perte / manque à gagner)** : dans « paiement + commission − facture », la commission est-elle bien celle de 25 % du client ? Un résultat positif est-il un « plus » pour la boulangerie ou pour le client ? Défaut : commission = CM du client ; résultat positif = client a trop payé, négatif = déficit.
- **Q-I (poids du produit)** : le poids est-il noté par pain (catégorie) ou pour la fournée entière ? Défaut : poids moyen par catégorie, saisi à la fournée.
- **Q-J (auto-évaluation)** : que doit contenir l'auto-évaluation du gérant (notes sur quoi, chaque jour ou chaque mois) ? Défaut : formulaire hebdomadaire court, lu par la direction.
- **Q-K (encodeur)** : qui est l'encodeur (le facturier, le gérant, un employé de bureau) et quelles erreurs doit-il corriger sans passer par le gérant ? Défaut : le facturier corrige ses propres factures non livrées ; le gérant corrige le reste, avec trace.
- **Q-L (paiement déclaratif / heure)** : que veut dire « paiement déclaratif » (le montant est déclaré par le facturier puis vérifié à la clôture ?) et quelle heure doit être modifiable (début de journée, rotation des équipes, heure de la facture) ? Défaut : heure de rotation par boulangerie modifiable dans la configuration ; paiement toujours saisi par le facturier et rapproché à la clôture.
- **Q-M (sacs et stock)** : « sucre, levure » : confirmez-vous ces deux consommables, et que doit contenir l'information d'un sac (fournisseur, lot, poids) ? Défaut : ajouter le sucre, enregistrer fournisseur et poids du sac.

Questions où la recommandation par défaut peut être appliquée sans attendre (à confirmer au passage) :

- Transfert spontané (N-07) : même flux que la demande, mais l'émetteur crée le transfert et le receveur confirme ; aucune réponse requise.
- Solde de la transaction (N-09) : affiché en plus de la BP, sans la remplacer.
- Non servi (N-04) : déclaration par le gérant, avec motif, qui n'efface rien (ajustement lié).

## 5. Points non lisibles dans les notes (rien à inventer)

La note « paiement + commission (?) = facture », la liste « farine, huile, su…, livre… », l'annotation « prod… à la bouillie ? » et la dernière puce vide : voir Q-H et Q-M ; l'annotation illisible est laissée sans suite.

## 6. Prochaines actions

1. Le coordinateur envoie les questions Q-A à Q-M au client (à ajouter dans `docs/qa/QUESTIONS_CLIENT.md` par la session principale).
2. En attendant : lancer N-01, N-09, N-03 (dev-backend puis dev-frontend), vérifications par `testeur-production` et `testeur-ventes`.
3. N-06 (épargne) et N-02 (fusion non vendu / sortie gratuite) : dossier de migration à valider par un humain avant tout développement.
