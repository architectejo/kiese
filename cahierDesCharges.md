# 1. Contexte, Objectifs et Acteurs du Projet

## 1.1. Identification et Identité Administrative de l'Entreprise

Le présent projet de numérisation et d'automatisation est mené pour le compte de l'**ÉTABLISSEMENT KIESE** (sous la marque **ETS. KIESE**). L'entreprise est une entité commerciale légalement enregistrée et régie par les autorités de la République Démocratique du Congo, dont les identifiants officiels opposables sont les suivants :

* 
**Numéro de Registre du Commerce et du Crédit Mobilier (RCCM) :** 021 – A-650.


* 
**Identification Nationale (Id. Nat) :** 10 – F4300 -N85947U.


* 
**Numéro d'Impôt (Numéro d'Identification Fiscale) :** A1902266K.


* 
**Siège Social et Administratif :** Situé au numéro 49 de l'Avenue Tabora, dans la commune et ville de Mbanza–Ngungu, Province du Kongo-Central.


* 
**Contact Téléphonique Officiel :** +243851992947.



L’ETS. KIESE est représenté au plus haut niveau par son **Administrateur Directeur Général, Monsieur NDUNGA NSAYI PIERRE** , qui agit en qualité de maître d'ouvrage et donneur d'ordres principal pour l'ensemble des décisions stratégiques, financières et fonctionnelles liées au présent logiciel.

## 1.2. Contexte Métier, Problématique et Vision Stratégique

L'ETS. KIESE s'est imposé comme un acteur clé de la transformation alimentaire et de la panification traditionnelle dans sa région. À la date du présent cahier des charges, l'entreprise pilote et exploite de manière active un réseau décentralisé de **huit (8) boulangeries traditionnelles** interconnectées.

Chaque unité de production possède une identité et un code d'identification strict au sein du système:

1. 
**Code K1 :** Boulangerie **TABORA** 


2. 
**Code K2 :** Boulangerie **COQ** 


3. 
**Code K3 :** Boulangerie **ATHENEE** 


4. 
**Code K4 :** Boulangerie **LOMA** 


5. 
**Code K5 :** Boulangerie **MPIANGU** 


6. 
**Code K6 :** Boulangerie **ZADIM** 


7. 
**Code B1 :** Boulangerie **KUMBI** 


8. 
**Code B2 :** Boulangerie **MPETE** 



### La problématique actuelle :

Sur le plan opérationnel, la gestion de ce réseau repose historiquement sur des flux d'informations artisanaux, caractérisés par l'usage intensif de cahiers physiques de pointage et de fichiers Excel fragmentés, gérés localement et de manière indépendante. Cette architecture d'information non centralisée génère plusieurs points de friction critiques :

* 
**Asymétrie de l'information :** Difficulté d'obtenir une visibilité consolidée, instantanée et en temps réel sur les stocks globaux et les flux financiers depuis le siège.


* 
**Lenteur administrative :** Le processus actuel ralentit la libération des clients lors des transactions quotidiennes, alors que la rapidité de service est le vecteur principal de confiance et de fidélisation.


* 
**Complexité des calculs :** La gestion manuelle des commissions des clients, le suivi des dettes et les retenues diverses augmentent le risque d'erreurs comptables humaines.


* 
**Risques de démarques et d'écarts :** L'absence d'outils de réconciliation automatisés entre la farine engagée à la production et les pains réellement distribués complexifie le contrôle de gestion.



### La vision cible :

Le projet vise à concevoir et déployer une solution logicielle sur-mesure capable d'unifier les huit sites. L'objectif est de substituer l'ancienne infrastructure manuelle par un écosystème applicatif automatisé, fluide, rapide et hautement sécurisé.

## 1.3. Objectifs Macro-Fonctionnels du Logiciel

Le programme applicatif à concevoir doit répondre à cinq (5) objectifs stratégiques fondamentaux :

1. 
**Centralisation absolue de la gestion multisite :** Permettre un pilotage global et unifié du réseau des 8 boulangeries depuis le siège de l'Avenue Tabora.


2. 
**Optimisation de la relation client et des flux financiers :** Automatiser le fichier client, fluidifier la facturation en chaîne à haute vitesse (libération rapide du client) , et assurer le calcul instantané des commissions de vente, des remises annuelles et des grilles de retenues (dettes, caisse sociale).


3. 
**Maîtrise de la production et des approvisionnements inter-boulangeries :** Suivre la consommation des consommables (farine, sel, levure, huile) au gramme près , analyser les rendements par sac produit , et sécuriser de manière comptable les mouvements de transfert de pains entre boulangeries (flux croisés s'annulant au stock général).


4. 
**Garantie de continuité de service (Résilience réseau) :** Permettre l'exécution continue des opérations de facturation et de livraison en local au sein de chaque boulangerie sans dépendance obligatoire à une connexion Internet , avec synchronisation ascendante automatique vers le Cloud dès le rétablissement du réseau.


5. 
**Fiabilisation comptable et analytique :** Générer automatiquement des états financiers comparatifs (Exercice N et Exercice N-1) conformes aux exigences d'audit et calqués sur le cash-flow traditionnel utilisé par la direction.



## 1.4. Équipe Projet et Compétences Techniques (Le Prestataire)

La maîtrise d'œuvre et la réalisation technique du logiciel sont confiées à l'**Équipe de Développement FullStack**, pilotée par **M. JONATHAN**. L'équipe intervient en tant qu'experte dans l'ingénierie des systèmes d'information distribués et des architectures de bases de données sécurisées.

L'équipe apporte au projet une expérience éprouvée dans le développement de plateformes transactionnelles à forte charge, avec des références solides incluant :

* **LaxMarket :** Place de marché (marketplace) d'envergure ayant validé les compétences de l'équipe dans la gestion des bases de données volumineuses, l'optimisation des requêtes asynchrones et la sécurité des données financières.
* **Connete+ :** Écosystème web complexe et transactionnel ayant permis de maîtriser les architectures applicatives hybrides et les mécanismes de synchronisation de données en temps réel.

L'équipe déploiera sur ce projet une architecture logicielle moderne, combinant une interface utilisateur ultra-intuitive bilingue (Français/Anglais)  et un moteur de base de données robuste, évolutif et couplé à un registre de sécurité de type Blockchain.

## 1.5. Clause contractuelle de Flexibilité Complète (Périmètre, Délais et Coûts)

Le présent cahier des charges fait office de cadre de référence initial pour le développement de la solution. Toutefois, les parties s'accordent explicitement sur une clause de flexibilité et de variabilité :

* **Périmètre Fonctionnel :** Les spécifications fonctionnelles et les maquettes d'états financiers fournies par le client le 18 mai 2026 servent de périmètre de base. Toute demande d'ajout de module complémentaire, de modification d'algorithme de calcul ou d'extension du réseau au-delà des 8 boulangeries initiales constituera une modification de périmètre.
* **Variabilité des Délais :** Le calendrier prévisionnel (estimé à 2-3 semaines pour le prototype MVP et 4-5 semaines pour la version complète) est conditionné par la validation rapide des étapes par le client et la fourniture des données initiales. Toute modification du périmètre fonctionnel en cours de route entraînera une réévaluation automatique des délais de livraison.
* **Variabilité Budgétaire :** Le montant forfaitaire initialement proposé pour le développement (4 500 $) correspond strictement au périmètre décrit dans ce document. En raison de la complexité des états financiers comparatifs (N / N-1) et des algorithmes spécifiques de gestion des billets de caisse exigés par le client, le montant total définitif des travaux pourra varier et sera ajusté d'un commun accord par un avenant financier si des ajustements ou fonctionnalités additionnelles sont demandés lors des phases de développement.



# 2. Gestion de la Clientèle et Module des Commissions (Spécifications Métier)

Ce module constitue le cœur algorithmique commercial du logiciel. Il automatise le suivi de la clientèle pour l'ensemble des huit (8) boulangeries de l'ETS. KIESE, calcule les rémunérations sous forme de commissions (CM), gère l'écosystème des dettes et génère les fiches de paie réglementaires.

## 2.1. Registre Centralisé et Fichage Numérique des Clients

Le système doit maintenir une base de données relationnelle unique et partagée, capable de segmenter les clients par boulangerie tout en offrant une consolidation au niveau du groupe.

Chaque fiche client doit obligatoirement comporter les champs de données suivants :

* 
**Code Unique Client :** Identifiant alphanumérique généré automatiquement par le système, facilitant la recherche et évitant toute homonymie.


* **Désignation :** Noms et prénoms complets du client.
* 
**Coordonnées :** Numéro de téléphone actif et adresse physique complète.


* 
**Identification Visuelle :** Capture ou téléversement de la photo d'identité du client pour sécuriser les livraisons en comptoir.


* **Boulangerie de Rattachement :** Code de la boulangerie émettrice principale (K1 à K6, B1, B2).

Le logiciel doit intégrer un moteur de recherche prédictif permettant de localiser instantanément un client à partir de son nom partiel ou de son code d'enregistrement unique afin d'accélérer les processus de comptoir.

## 2.2. Algorithme de Segmentation et d'Alerte de Risque

Pour préserver la santé financière de l'ETS. KIESE, le logiciel analyse en continu le comportement d'achat et l'état des comptes des clients pour effectuer un classement automatique dynamique:

### 2.2.1. Catégorie « Meilleur Client »

Un client est automatiquement classé dans cette catégorie s'il remplit les critères cumulatifs ou alternatifs suivants:

* Un volume d'achat de pains (commandes) supérieur à un seuil paramétrable par l'administrateur.


* Un revenu net de commission élevé démontrant sa régularité et sa fidélité.



### 2.2.2. Catégorie « Client à Risque » (Système d'Alerte)

Le logiciel doit déclencher des alertes visuelles immédiates (couleur rouge, notifications) et bloquer ou restreindre les droits de facturation pour les clients déficitaires répondant aux critères suivants:

* **Dettes excessives :** Encours de dette dépassant le plafond autorisé par la direction.
* 
**Prises de stock irrégulières :** Anomalies dans la fréquence de retrait des marchandises.



## 2.3. Moteur de Calcul des Commissions (CM) et des Retenues

Le logiciel applique de manière stricte la logique financière traditionnelle de l'ETS. KIESE pour déterminer la rémunération des clients abonnés. Le calcul s'exécute de manière automatique selon une chaîne d'opérations mathématiques précises:

### 2.3.1. Calcul de la Commission Brute (CM)

Pour chaque transaction ou période (journalière/mensuelle), la commission brute est calculée sur la base de la valeur de la commande de pains livrée, multipliée par le taux indicatif appliqué au client (généralement 25% ou 30% selon la catégorie de produit ou le profil du client) :

$$\text{CM Brute} = \text{Valeur de la Commande Pains} \times \text{Taux Commission (ex: 0.25 ou 0.30)}$$

### 2.3.2. Gestion des Retenues Diverses

Le logiciel doit déduire automatiquement de la commission brute toutes les charges et obligations contractuelles dues par le client:

1. 
**Déduction de la Dette :** Apurement total ou partiel des dettes antérieures accumulées par le client.


2. 
**Cotisation Sociale :** Prélèvement automatique destiné à la caisse sociale de l'entreprise.


3. 
**Frais d'Imprimés :** Retenue pour la fourniture des documents, carnets ou outils de gestion.


4. 
**Frais Divers / Autres :** Toute autre retenue exceptionnelle validée par la direction.



Le total des retenues est calculé comme suit:


$$\text{Total Retenues} = \text{Retenue Dette} + \text{Retenue Sociale} + \text{Retenue Imprimés} + \text{Retenue Autre}$$

### 2.3.3. Intégration de la Remise Annuelle (Bonus de Fidélité)

Le système calcule une remise de fin d'année basée sur le volume global des commandes de pains livrées au client sur l'exercice. La formule standard est la suivante:

$$\text{Remise Annuelle} = 0.025 \times \text{Volume Total des Pains Livrés au Client}$$

L'interface d'administration centrale doit obligatoirement offrir la flexibilité d'incorporer ou d'ajouter cette remise annuelle directement au net à payer du client lors de la période de liquidation finale.

### 2.3.4. Calcul du Net à Payer

Le montant net final dû au client est déterminé par la formule générale:

$$\text{Net à Payer} = (\text{CM Brute} + \text{Remise Annuelle Incorporée}) - \text{Total Retenues}$$

## 2.4. Modélisation des Pièces Justificatives et Listings de Paye

Le logiciel doit générer des documents officiels clairs, exportables et prêts pour l'impression physique, calqués rigoureusement sur les matrices Excel de l'ETS. KIESE.

### 2.4.1. Structure du Listing de Paye CM du Mois (Par Boulangerie)

Ce document se présente sous forme de table de données et sert de registre de décharge lors du paiement physique des commissions :

| Code Client | Noms Clients | CM (Brute) | Retenue Dette | Retenue Sociale | Retenue Imprimés | Retenue Autre | Net à Payer | Signature Client |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| *[Généré]* | *[Saisi]* | *[Calculé]* | *[Déduit]* | *[Déduit]* | *[Déduit]* | *[Déduit]* | *[Calculé]* | *[Physique]* |

*(Note d'alignement technique : Le logiciel calculera automatiquement les totaux verticaux pour chaque colonne de retenue et de net à payer afin de faciliter la réconciliation avec le livre de caisse de la direction).*

### 2.4.2. Fiche Individuelle des Retenues et Justificatifs

Pour chaque client, le système doit être en mesure d'extraire à tout moment une fiche récapitulative des retenues opérées, détaillant l'historique des dettes apurées par prélèvement sur commission, garantissant ainsi une transparence totale et évitant les contestations qui pourraient entamer la confiance des abonnés.

# 3. Gestion de Production, Approvisionnements et Logique Inter-Boulangeries

Ce module technique gère l'amont de l'activité commerciale de l'ETS. KIESE. Il sécurise la transformation des matières premières en produits finis (pains de différentes catégories de prix), suit précisément l'utilisation des consommables et régule les flux logistiques croisés entre les différentes boulangeries afin d'éviter toute freinte ou évaporation de stock non documentée.

## 3.1. Suivi Journalier de la Production

Le logiciel doit remplacer les fiches de pointage papier par un écran de déclaration de production à l'usage des gérants ou des chefs de brigade (Équipes A et B).

* 
**Saisie de l'Intrant Principal :** Indication manuelle et obligatoire, à chaque début de cycle ou fin de journée, du nombre exact de sacs de farine de 50 kg engagés dans le pétrin.


* 
**Déclaration des Produits Finis :** Saisie du volume de pains sortis des fours, ventilé obligatoirement par les catégories de prix réglementaires de l'entreprise : 300 FC, 400 FC, 500 FC et 1 000 FC.


* **Calcul Automatique du Rendement Théorique :** Le système calcule instantanément le ratio de production standard (ex: nombre de pains obtenus par sac de farine traité) pour mesurer l'efficacité de la brigade et la conformité aux recettes de l'ETS. KIESE.



## 3.2. Analyse Mathématique et Fiches de Stock des Consommables

Le logiciel maintient une fiche de stock analytique par boulangerie (K1 à K6, B1, B2) et une fiche consolidée globale pour le siège de l'Avenue Tabora. L'algorithme applique pour chaque intrant la formule comptable immuable:

$$\text{Stock Restant} = \text{Stock Initial} + \text{Entrées (Approvisionnements)} - \text{Quantité Utilisée (Production)}$$

Le suivi s'applique de manière stricte sur les quatre consommables de base suivants:

1. 
**Farine (Unité : Sac de 50 kg) :** Suivi des mouvements entiers ou fractionnés.


2. 
**Sel (Unité : Kilogramme / Gramme) :** Suivi basé sur le grammage standard par sac de farine.


3. 
**Levure (Unité : Paquet de 450 g) :** Suivi des unités entières entamées ou consommées.


4. 
**Huile (Unité : Litre / Gramme) :** Consommation corrélée aux volumes de production.



### Rapport Mensuel de Consommation Moyenne

Le système doit générer un tableau d'analyse décisionnel comparant la quantité de consommables utilisée par rapport à un étalon de « un (1) sac de farine produit ». Toute déviation par rapport à la moyenne historique définie par l'Administrateur Directeur Général doit déclencher une alerte pour surconsommation ou gaspillage.

## 3.3. Logique Algorithmique des Flux et Transferts Inter-Boulangeries

Il arrive fréquemment que les boulangeries s'approvisionnent entre elles pour équilibrer l'offre par rapport à la demande locale. Pour empêcher toute fraude, le logiciel applique un protocole d'annulation stricte des mouvements croisés :

* 
**La Règle d'Or Comptable :** Tout mouvement d'approvisionnement inter-boulangeries doit impérativement s'annuler au niveau du stock général final de l'entreprise. Le logiciel n'augmente ou ne diminue pas la valeur globale de l'entreprise lors d'un transfert, il réalloue les volumes.


* 
**Exemple Algorithmique Intégré :** Si la boulangerie **K1 (Tabora)** transfère un lot de 100 pains de 500 FC à la boulangerie **K2 (Coq)**:


1. Le gérant de K1 saisit un « Bon de Sortie Inter-Boulangerie » vers K2 de 100 pains. Le stock de K1 passe immédiatement en attente de validation.
2. Le système génère une alerte sur le terminal de K2 indiquant un approvisionnement entrant de 100 pains.


3. Le gérant de K2 doit valider la réception exacte de la quantité. À la validation, le système effectue l'opération miroir : **-100 pains au stock de K1** et **+100 pains au stock de K2**.


4. 
**Alerte d'Écart :** Si K2 valide 98 pains au lieu de 100, le logiciel bloque la clôture journalière et lève une alerte d'écart instantanée à l'attention de l'Administrateur.





## 3.4. Réconciliation, Écarts et Suivi des Pains Déclassés

En fin de journée, le logiciel effectue automatiquement une réconciliation stricte pour identifier la démarque inconnue:

$$\text{Écart Évalué} = \text{Production Déclarée (Sacs de farine } \times \text{Rendement)} - \text{Distribution Réelle (Ventes } + \text{Retours)}$$

Le système génère un rapport financier traduisant cet écart en **nombre de pains manquants** et en **valeur monétaire (Francs Congolais - FC)**.

### Segmentation des Pains non valorisés au prix fort

Le tableau de bord d'administration de la direction doit catégoriser précisément le devenir de chaque pain produit qui n'a pas été vendu au tarif standard:

* 
**Rapport des Ventes à Prix Forfaitaire (Pains soldés) :** Analyse des pains vendus en lot en fin de journée à prix réduit, avec calcul automatisé de l'impact sur la marge bénéficiaire.


* 
**Rapport de Pains Déclassés :** Suivi des pains déformés ou non conformes commercialement.


* 
**Rapport des Pains Non Vendus (Pertes sèches) :** Quantification des invendus restants en rayons en fin d'exercice.


* **Rapport des Sorties Gratuites :** Enregistrement des pains affectés aux dons ou à la consommation interne du personnel de l'ETS. KIESE (quantités non facturées).


* 
**Rapport des Pains restant à vendre :** État du stock physique disponible en boutique pour entamer la journée suivante.



# 4. Processus de Vente, Facturation en Chaîne et Preuves Irréfutables

Ce module est l’organe d'exploitation quotidien des points de vente de l'ETS. KIESE. Conçu pour répondre à un flux intense de clients par site, il doit allier une vitesse d'exécution extrême pour « libérer rapidement le client » et une rigueur comptable totale pour générer des preuves d'achat infalsifiables.

## 4.1. Processus de Facturation/Livraison en Chaîne Synchrone

Afin d'éviter les goulots d'étranglement lors de la distribution matinale ou des pics de vente, le logiciel implémente une architecture de facturation en chaîne scindée en deux rôles distincts mais connectés en temps réel :

### 4.1.1. Le Rôle du Facturier (Équipe A / Équipe B)

* **Saisie Ultra-Rapide :** Le facturier appelle la fiche du client (par scanner de code-barres, saisie du code unique ou recherche textuelle prédictive).
* **Enregistrement de la Commande :** Il saisie les quantités de pains demandées par catégorie de prix.
* **Saisie du Paiement du Jour :** Il inscrit le montant en Francs Congolais (FC) physiquement remis par le client pour cette transaction.
* **Mise en attente :** Dès validation, la facture passe au statut *« En attente de livraison »* et est instantanément poussée sur le terminal du livreur.

### 4.1.2. Le Rôle du Livreur

* **Vérification Visuelle :** Le livreur voit apparaître sur son écran la commande validée ainsi que la photo d'identité du client pour éviter toute usurpation ou erreur de lot.
* **Déstockage et Remise :** Après avoir servi physiquement les pains, le livreur clique sur *« Confirmer la livraison »*. Cette action déduis automatiquement les produits du stock de pains de la boulangerie et déclenche l'impression du reçu.

## 4.2. Grille Tarifaire Automatisée par Catégories de Pains

Le système interdit toute saisie libre des prix unitaires afin de prémunir l'entreprise contre les erreurs de manipulation. Les ventes sont obligatoirement indexées sur la grille tarifaire officielle de l'ETS. KIESE :

* **Catégorie Standard Mini :** Pains de **300 FC**
* **Catégorie Standard Moyen :** Pains de **400 FC**
* **Catégorie Standard Grand :** Pains de **500 FC**
* **Catégorie Premium / Spécial :** Pains de **1 000 FC**

Chaque vente d'un lot de pains est valorisée mathématiquement par le système ($Qte \times Prix\_Categorie$) et alimente en temps réel les statistiques de performance par produit de la boulangerie.

## 4.3. Module d'Extraction Rapide et Facturation Groupée en Série

Pour les périodes de très forte affluence (notamment lors des livraisons des revendeurs ou abonnés réguliers), le logiciel intègre des fonctionnalités d'accélération de saisie :

* **Facturation Groupée en Série :** Permet au facturier d'ouvrir une interface de saisie "en grille" où il peut enchaîner la facturation de 10 à 15 clients présélectionnés à la suite, sans devoir recharger les pages de l'application.
* **Historique des Récents :** Affichage en un clic des 5 derniers clients servis sur le terminal pour permettre des corrections rapides ou des doubles commandes.

## 4.4. Génération de la Preuve Irréfutable (Le Reçu Clinique)

Chaque transaction donne lieu à l'émission immédiate d'un reçu (physique via imprimante thermique de caisse ou numérique stocké dans le système). Qu'il s'agisse d'une vente au comptant (**Cash**) ou d'une vente à crédit (**Crédit**), le reçu doit obligatoirement comporter l'arborescence de données suivantes pour constituer une preuve juridique et comptable incontestable :

### 4.4.1. Bloc d'Entête Légal (Identité ETS. KIESE)

* Logotype de l'entreprise.
* Mentions obligatoires : RCCM 021 – A-650 | Id. Nat 10 – F4300 -N85947U | N° Impôt : A1902266K.
* Adresse du siège : 49, Av. Tabora / Mbanza – Ngungu.
* Code d'Identification de la boulangerie émettrice (ex: **K1** pour Tabora, **K2** pour Coq).

### 4.4.2. Corps de la Transaction

* Horodatage précis (Date, heure, minute, seconde).
* Nom du facturier et équipe en cours (A ou B).
* Code Unique et Nom Complet du Client.
* Tableau détaillé des marchandises : *Désignation de la catégorie de pain | Quantité livrée | Prix Unitaire (FC) | Total (FC)*.

### 4.4.3. Bloc de Clôture Financière et Solde de la Balance de Paiement (BP)

C'est la partie la plus critique exigée par la direction pour éviter les contestations de solde. Le système calcule et affiche la situation financière du client en temps réel sur le ticket :

1. **Dette Antérieure (BP Avant) :** Le solde débiteur du client avant la transaction du jour.
2. **Valeur de la Commande :** Le montant total de la livraison du jour.
3. **Versement / Paiement du Jour :** La somme en espèces versée par le client.
4. **Taux de Commission :** Le pourcentage de commission appliqué (25% ou 30%).
5. **Nouvelle Balance de Paiement (BP Après) :** Calculée instantanément selon la formule comptable de l'ETS. KIESE :

$$\text{Nouvelle Dette (BP Après)} = \text{Dette Antérieure} + \text{Valeur de la Commande du Jour} - \text{Paiement du Jour}$$

Le reçu porte la mention claire **« Solde arrêté ce jour »** et est sauvegardé de manière définitive dans le grand livre numérique du système, verrouillé par le protocole de sécurité.



# 5. Gestion de la Caisse, Trésorerie et États Financiers Comparatifs (N / N-1)

Ce module centralise, valide et consolide l'ensemble des flux financiers générés par les activités de production et de vente des huit (8) boulangeries. Il élimine les risques d'erreurs liés à la transcription manuelle des flux de trésorerie et offre à la direction une visibilité comptable absolue à travers des états financiers réglementaires et comparatifs.

## 5.1. Livre de Caisse et Hiérarchie des Rapports Financiers

Le logiciel implémente un système de validation en cascade (workflow permanent) garantissant qu'aucune somme d'argent ne peut être inscrite au niveau central sans avoir été validée à l'échelle locale.

### 5.1.1. Niveau 1 : Le Rapport Journalier des Facturiers (Par Équipe A / B)

À la fin de chaque shift (vacation), le logiciel verrouille la session du facturier et génère automatiquement un rapport comprenant :

* Le cumul des ventes comptant (**Cash**).
* Le cumul des ventes à crédit (**Crédit**).
* Le montant total théorique en espèces (FC) devant se trouver physiquement dans le tiroir-caisse.

### 5.1.2. Niveau 2 : Le Rapport de Clôture du Gérant de Boulangerie

Le gérant de chaque boulangerie (K1 à K6, B1, B2) accède à une interface de centralisation locale. Il valide le rapport des facturiers et y intègre les dépenses d'exploitation locales autorisées (achat de bois, petite maintenance, frais courants) :

$$\text{Caisse Nette Boulangerie} = \text{Total Entrées (Ventes Cash)} - \text{Total Sorties (Dépenses Locales)}$$

### 5.1.3. Niveau 3 : Le Livre de Caisse Direction (Siège Central)

Dès synchronisation, les données alimentent le **Livre de Caisse Direction**, calqué rigoureusement sur le modèle structurel de l'entreprise. Ce grand livre central est non modifiable (protégé par le registre Blockchain).

**Structure de la Matrice d'Affichage du Livre de Caisse Direction :**

* **Entête :** ETS. KIESE | RCCM 021 – A-650 | Id. Nat 10 – F4300 -N85947U | N° Impôt : A1902266K.
* **Période :** Filtre dynamique (Du [Date] Au [Date]).

| DATE | N° PIÈCE | IMPUTATION | LIBELLÉS (Origine Boulangerie / Nature) | ENTRÉE (FC) | SORTIE (FC) | SOLDE CONSOLIDÉ (FC) |
| --- | --- | --- | --- | --- | --- | --- |
| *[JJ/MM/AAAA]* | *[Auto]* | *[Code Comptable]* | *[ex: Versement Journalier K1 Tabora]* | *[Saisi/Calculé]* | *[Saisi/Calculé]* | *[Calculé en Continu]* |

*(Note technique : Le système calcule dynamiquement le solde progressif ligne par ligne : $Solde = Solde_{Précédent} + Entrée - Sortie$).*

## 5.2. Module Spécifique de Ventilation des Billets de Banque (Espèces)

Compte tenu du volume important de transactions en espèces (Francs Congolais) et pour éliminer les risques d'erreurs de comptage ou de versement, le logiciel intègre une interface obligatoire de ventilation physique des billets pour chaque clôture (Gérant et Direction).

L'utilisateur ne saisit pas un montant global, il saisit la quantité de coupures physiques. Le système calcule instantanément la valeur monétaire totale.

### Grille Algorithmique de Ventilation des Billets :

| Valeur Faciale du Billet | Saisie Quantité (Qte) | Valeur Totale Calculée (FC) |
| --- | --- | --- |
| **20 000 FC** | *[Saisie Utilisateur]* | $= Qte \times 20\,000$ |
| **10 000 FC** | *[Saisie Utilisateur]* | $= Qte \times 10\,000$ |
| **5 000 FC** | *[Saisie Utilisateur]* | $= Qte \times 5\,000$ |
| **1 000 FC** | *[Saisie Utilisateur]* | $= Qte \times 1\,000$ |
| **500 FC** | *[Saisie Utilisateur]* | $= Qte \times 500$ |
| **200 FC** | *[Saisie Utilisateur]* | $= Qte \times 200$ |
| **100 FC** | *[Saisie Utilisateur]* | $= Qte \times 100$ |
| **50 FC** | *[Saisie Utilisateur]* | $= Qte \times 50$ |
| **TOTAL GÉNÉRAL ESPÈCES** | *[Verrouillé]* | **$\sum \text{Valeurs Totales}$** |

Le système compare automatiquement le **Total Général Espèces** issu de cette ventilation avec le **Solde Théorique** des ventes. Tout écart (positif ou négatif) est enregistré dans un journal des écarts non modifiable et transmis à la Direction Générale.

## 5.3. Module des États Financiers Réglementaires Comparatifs (N / N-1)

Pour permettre à Monsieur NDUNGA NSAYI PIERRE de piloter l'entreprise et de mesurer la croissance de l'ETS. KIESE d'une année sur l'autre, le logiciel extrait automatiquement quatre (4) états financiers consolidés mettant en parallèle l'Exercice Courant (N) et l'Exercice Précédent (N-1).

### 5.3.1. Balance des Comptes (Comparatitve)

Permet de vérifier l'équilibre comptable permanent du groupe.

* **Champs requis :** Numéro de compte | Libellé du compte | Mouvements Débit N | Mouvements Crédit N | Solde Débiteur N | Solde Créditeur N | Balance Globale N-1.

### 5.3.2. Compte de Résultat (Comparatif)

Mesure la performance et la rentabilité économique des huit boulangeries.

* **Structure des lignes :** * Chiffre d'Affaires Global (Ventes de pains 300, 400, 500, 1000 FC).
* Moins : Coût des matières premières consommées (Farine, Levure, Sel, Huile).
* Moins : Charges de personnel (Commissions CM liquidées, salaires fixes).
* Moins : Charges d'exploitation (Hébergement, Certificats, Dépenses locales).
* **Résultat Net de l'Exercice :** Affiché sur deux colonnes distinctes : **[Colonne Exercice N (FC)]** et **[Colonne Exercice N-1 (FC)]** avec calcul automatique du taux d'évolution en pourcentage (%).



### 5.3.3. Bilan Consolidé (Comparatif Actif / Passif)

Présente le patrimoine de l'ETS. KIESE à une date arrêtée.

* **Structure de l'Actif :** Immobilisations, Stocks restants (Farine, Huile, Sel, Levure valorisés au prix unitaire d'achat), Créances clients (Dettes clients non apurées), Disponibilités (Comptes Banques, Caisse Espèces).
* **Structure du Passif :** Capitaux propres, Provisions pour remises annuelles des clients, Dettes fournisseurs, Dettes sociales.
* Chaque ligne comporte la valeur de l'exercice N, la valeur de l'exercice N-1, et l'écart brut mathématique.

### 5.3.4. Tableau des Flux de Trésorerie (Cash-Flow Comparatif)

Calqué précisément sur la structure d'analyse financière fournie par le client dans son modèle Excel, ce tableau met en évidence l'évolution de la trésorerie nette globale.

**Modèle Mathématique du Tableau de Cash-Flow :**

* **Flux d'Exploitation :** Encaissements clients (+) | Décaissements fournisseurs (-) | Paiements des Commissions (-) | Dépenses opérationnelles (-).
* **Flux d'Investissement :** Acquisitions d'équipements pour les boulangeries (-).
* **Flux de Financement :** Apports en capitaux (+) | Emprunts ou remboursements.

Le logiciel calcule automatiquement :


$$\text{Trésorerie Nette Fin de Période (N)} \quad \text{vs} \quad \text{Trésorerie Nette Fin de Période (N-1)}$$


L'écart de trésorerie est ventilé pour identifier quelle boulangerie contribue le plus positivement ou négativement au Cash-Flow global du groupe.



# 6. Spécifications Techniques, Sécurité Blockchain et Droits d'Accès

Cette section fixe l'architecture logicielle, la structure des bases de données distribuées, le protocole de synchronisation bidirectionnelle, ainsi que l'interopérabilité avec les terminaux physiques (Android POS).

## 6.1. Stack Technologique et Architecture Applicative

Le logiciel de l'ETS. KIESE est développé sur une architecture moderne découplée (API-centric) :

* **Backend (Moteur Logiciel) :** **Django / Django REST Framework (Python)**. Choisi pour sa robustesse, sa sécurité native, sa rapidité de modélisation et sa capacité à gérer des transactions complexes (système ORM).
* **Frontend (Interfaces Utilisateurs) :** **React (JavaScript/TypeScript)**. Choisi pour offrir une interface utilisateur fluide, ultra-rapide (Single Page Application), facilitant la saisie en série aux comptoirs de facturation.

L'application est structurellement divisée en deux espaces distincts :

1. **La partie Site Web :** Vitrine publique de l'entreprise (présentation, catalogue des pains 300, 400, 500, 1000 FC, contact).
2. **La partie Dashboard :** Espace applicatif privé et sécurisé regroupant les modules fonctionnels (Facturation, Livraison, Caisse, Production, États Financiers Comparatifs).

## 6.2. Logique d'Affichage Conditionnel et Modèle `Config`

Pour offrir une flexibilité totale à la direction générale, le cycle d'affichage de la plateforme est piloté dynamiquement par la base de données via un modèle de configuration global.

### 6.2.1. Structure du Modèle Django

```python
from django.db import models

class Config(models.Model):
    on_line = models.BooleanField(
        default=True, 
        help_text="Si True: le site web est visible. Si False: redirection automatique vers la page de login du Dashboard."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuration Globale"

```

### 6.2.2. Comportement Algorithmique au Point d'Entrée (React Router / Django Middleware)

À chaque chargement de la racine de l'application, le système interroge l'état de `on_line` :

* **Si `on_line == True` :** L'utilisateur accède au **Site Web Public**. Un bouton discret "Connexion" permet aux agents d'accéder à la mire de login.
* **Si `on_line == False` :** Le système court-circuite l'accès public. Le Site Web devient invisible et l'utilisateur est instantanément redirigé vers la **Page de Login du Dashboard**.

## 6.3. Architecture Décentralisée, Gestion des Nœuds et Stratégie d'Identifiants (IDs) pour Synchronisation

L'application fonctionne selon un modèle distribué composé d'un **Nœud Central (Cloud)** et de **Nœuds Locaux (Serveurs physiques en boulangeries K1 à K6, B1, B2)**.

### 6.3.1. Administration des Nœuds depuis le Siège Central

Le nœud physique installé au siège de l'Avenue Tabora fait office de console de contrôle. L'administrateur général (Monsieur NDUNGA NSAYI PIERRE ou son délégué technique) possède les privilèges exclusifs pour :

* **Ajouter / Activer un nœud local** (Déclarer une nouvelle boulangerie dans le réseau).
* **Créer et assigner des utilisateurs à des nœuds spécifiques** (ex: affecter un facturier spécifiquement au nœud K1 Tabora ou K4 Loma), garantissant qu'un agent local ne peut pas impacter les données d'une autre boulangerie.

### 6.3.2. Stratégie d'Identifiants Unis (UUIDv4 + Code Nœud) pour la Synchronisation Bidirectionnelle

Pour éviter les collisions de clés primaires lors de la synchronisation asynchrone (ex: si le nœud K1 et le nœud K2 génèrent tous les deux une facture avec l'ID `1` pendant qu'ils sont hors-ligne), l'utilisation d'IDs incrémentaux classiques (`1, 2, 3...`) est strictement interdite pour les entités synchronisables.

Tous les modèles (Facture, Client, Mouvement de Stock, Livre de Caisse) utiliseront un identifiant unique universel couplé au code du nœud émetteur :

```python
import uuid
from django.db import models

class Facture(models.Model):
    # UUID unique au niveau mondial pour éviter les doublons lors de la synchro
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Référancement du nœud d'origine (ex: 'K1', 'K2', 'CLOUD')
    node_origin = models.CharField(max_length=5)
    # Suivi du statut de synchronisation
    is_synced = models.BooleanField(default=False)
    # ... autres champs (client, commande, paiement) ...

```

### 6.3.2. Logique algorithmique de Synchronisation (Local $\leftrightarrow$ En ligne)

* **Local $\rightarrow$ En ligne :** Le nœud local enregistre les ventes en continu sur sa base SQLite/PostgreSQL locale. Dès que la connexion Internet est détectée, un script d'arrière-plan extrait toutes les lignes où `is_synced == False`, les pousse via l'API Django Cloud, et les marque `is_synced = True` après confirmation de réception `HTTP 200 OK`.
* **En ligne $\rightarrow$ Local :** Les modifications de configurations (ex: mise à jour de la grille des prix des pains par la direction, affectation d'un nouvel utilisateur) faites sur le Cloud sont poussées vers les nœuds locaux concernés lors de la poignée de main (*handshake*) réseau.

## 6.4. Sécurité et Registre Blockchain

Afin de fournir la "Preuve Irréfutable" exigée par le client, les tables critiques contenant des données financières (Livre de Caisse Direction, Mouvements de Crédits, Totaux de Commissions payées) sont doublées par un algorithme d'ancrage cryptographique (Blockchain) :

* **Calcul de Hash en Chaîne :** Chaque ligne comptable enregistrée génère un hash SHA-256 combinant ses propres données + le hash de la ligne précédente.
* **Détection des Altérations :** Si un gérant ou un acteur malveillant tente de modifier manuellement une écriture dans la base de données locale pour masquer un écart de caisse, la chaîne de hash est brisée, et le système bloque instantanément le nœud concerné tout en envoyant une alerte rouge au tableau de bord de l'Administrateur au siège.
* **Certificat SSL :** Toutes les API de synchronisation transitent obligatoirement par un protocole sécurisé HTTPS chiffré par le certificat SSL annuel (14 $/an).

## 6.5. Responsive Design Multi-Supports et Interopérabilité Matérielle

L'interface React intègre un système de grilles fluides adaptatives (Responsive Design) strict, garantissant un affichage et une ergonomie au pixel près sur 5 types de supports physiques aux usages bien distincts :

```
[Écran Télévision] ------ (Affichage des rendements et performances au Siège)
        |
[Ordinateur Bureau] ----- (Administration centrale, Comptabilité, États Financiers N/N-1)
        |
[Tablette Tactile] ------ (Gestion des stocks en atelier de production et inventaires)
        |
[Téléphone Portable] ---- (Consultation rapide des rapports de caisse par le DG)
        |
[Android POS Terminal] -- (Facturation en chaîne, Livraison et Impression Thermique)

```

1. **Ordinateur de Bureau :** Vue large optimisée pour la Direction Générale et le Comptable. Permet l'analyse approfondie du Livre de Caisse, du Cash-Flow, du Bilan et du Compte de Résultat comparatif N/N-1.
2. **Tablette Tactile :** Ergonomie tactile à gros boutons pour les gérants en atelier (Saisie rapide des sacs de farine de 50 kg engagés, mouvements de transfert inter-boulangeries).
3. **Téléphone Portable :** Interface minimaliste et sécurisée permettant à Monsieur NDUNGA NSAYI PIERRE de consulter les indicateurs clés de performance (Chiffre d'affaires du jour, alertes de clients à risques) en situation de mobilité.
4. **Télévision (Écran de Contrôle) :** Mode d'affichage "Dashboard Kiosque" plein écran conçu pour être projeté sur des télévisions connectées au niveau du siège, affichant sous forme de graphiques en temps réel les volumes de production de chaque boulangerie.
5. **Terminal Android POS (Point of Sale) :** Interface de caisse ultra-légère dédiée aux Facturiers et Livreurs pour la saisie des commandes clients en comptoir.

## 6.6. Module d'Impression Thermique pour Terminaux Android POS

Le logiciel React intègre une passerelle d'impression native (via pont de communication Web Bluetooth ou SDK d'impression Android) configurée spécifiquement pour les terminaux de caisse portables Android POS dotés d'une imprimante thermique intégrée.

Dès que le Livreur confirme la remise des pains, le système génère et lance l'impression immédiate du reçu au format de ticket de caisse vertical standard (80mm ou 58mm). Le formatage de sortie respecte l'arborescence transactionnelle demandée :

```
======================================
             ETS. KIESE               
    RCCM 021-A-650 | Id.Nat 10-F4300  
 N° Impôt: A1902266K | Siège: Tabora 49
--------------------------------------
BOULANGERIE : K1 - TABORA             
DATE : 18/05/2026 15:30               
AGENT : FACTURIER A                   
--------------------------------------
CLIENT : [C0245] M. KANZA ALBERT      
--------------------------------------
DESIGNATION      QTE   P.U(FC)   TOT(FC)
Pain 300 FC      50    300       15 000 
Pain 500 FC      20    500       10 000 
--------------------------------------
VALEUR COMMANDE :            25 000 FC
VERSEMENT DU JOUR :          20 000 FC
TAUX DE COMMISSION :               25%
======================================
         SITUATION COMPTABLE          
--------------------------------------
BALANCE ANTÉRIEURE :         12 000 FC
NOUVELLE DETTE :             17 000 FC
--------------------------------------
       SOLDE ARRÊTÉ CE JOUR           
  Merci pour votre fidélité !         
======================================

```