# adaptes.md — Adaptation de l'application au workflow réel des ETS. KIESE

Basé sur l'analyse des fichiers Excel fournis par le client (août 2026) :
`B1 KUMBI`, `B2 MPETE`, `K1 TABORA`, `K2 COQ`, `K3 ATHENÉE`, `K4 LOMA`, `K5 MPIANGU`, `K6`, ainsi que le `DOC 1 - RAPPORT CLÔTURE PAR GÉRANT`.

---

## MODULE 1 — Facturation quotidienne

### [1.1] Types de vente dans la facturation

Le fichier Excel distingue 4 types de lignes dans chaque session :

| Type | TAUX | CM | Prix des pains |
|------|------|----|----------------|
| Client régulier (Revendeur) | 25% | FACTURE × 25% | 200 / 300 / 500 / 1000 FC |
| VENTE SOLDE | 0% | 0 | 150 / 225 / 375 / 750 FC (75%) |
| VENTE CASH | 0% | 0 | 150 / 225 / 375 / 750 FC (75%) |
| Client épargne (ex: SAMSON/epargne) | 0% | 0 | COMMANDE = 0 ; PAIEMENT = dépôt |

**Tâche :** Vérifier que le module Facturation de l'application gère correctement ces 4 cas. VENTE SOLDE et VENTE CASH doivent utiliser les prix 150/225/375/750 FC et générer CM=0. Les clients épargne ne commandent pas de pain (COMMANDE=0) mais enregistrent un paiement.

### [1.2] Codes clients spéciaux dans la facturation

Dans les sheets FACTURATION, certaines lignes ont des codes non numériques :

| Code | Signification |
|------|---------------|
| `NV` | Nouveau client (inscription en cours de mois) |
| `RG` | Régularisation d'une transaction précédente |
| `NS` | Non Servi (boulangerie fermée ce jour-là) |
| `B2` (ou `B1`, `K1`, etc.) | Transfert de pain inter-boulangeries |

**Exemple B2 :** `B2 | Appro reçu k1 | qté négative = -463500 FC` — signifie que B2 a reçu du pain depuis K1.

**Tâche :** Documenter ces codes dans l'interface et les prendre en compte dans le rapport mensuel. Les lignes B2/K1/etc. représentent des mouvements inter-sites : les intégrer dans le module Stock/Approvisionnement.

### [1.3] REMBOURSEMENT mois précédent

Dans B2, une ligne `B2 | REMB JUILLET | PAIEMENT = 176500` indique un remboursement global de la dette du mois précédent, sans COMMANDE.

**Tâche :** Prévoir dans la facturation une ligne de type "Remboursement" : COMMANDE=0, PAIEMENT=montant remboursé, qui réduit le BP sans comptabiliser de vente.

---

## MODULE 2 — Balance Précédente (BP) et suivi de créance

### [2.1] Calcul journalier du BP

Formule quotidienne (confirmée par la sheet "clients cite") :
```
BP_j = BP_{j-1} + COMMANDE_j - PAIEMENT_j
```

Le BP initial du premier jour du mois = BP final du dernier jour du mois précédent (la dette se reporte).

**Tâche :** Vérifier que l'application calcule le BP de façon cumulative et persistante d'un mois à l'autre (pas de remise à zéro automatique).

### [2.2] BP négatif = crédit client

Un BP négatif signifie que le client a payé plus qu'il n'a commandé (crédit en sa faveur). Observé notamment pour :
- Clients épargne (SAMSON/epargne : BP = -3500, -7000, etc. — crédit croissant)
- VENTE CASH (léger écart de -25 FC d'arrondi récurrent)

**Tâche :** S'assurer que l'interface affiche le BP négatif correctement (crédit), sans bloquer la saisie.

### [2.3] Rapport déficitaires

Le fichier K5 contient une sheet "deoficit" listant les clients dont le DEFICIT ACTUEL = BP - CM est négatif (ils doivent de l'argent net après déduction de la commission).

**Tâche :** Implémenter un rapport "Clients déficitaires" par boulangerie : `COMMANDE | PAIEMENT | BP | CM | DEFICIT = CM - BP`.

### [2.4] Fiche des Remboursements (FICHE DES REMB)

Découvert dans DOC 01 RAPPORT BOULANGERIES, sheet "FICHE DES REMB" :
```
DATE | BOULANGERIE | NOM DU CLIENT BP | BP INITIAL | REMBOURSEMENT | SOLDE BP
```
Ce document suit formellement les remboursements de dettes antérieures (d'un mois précédent) : un client peut rembourser en plusieurs fois un BP accumulé. Le titre du fichier inclut le mois de référence ("MARS 2026") pour indiquer de quelle période la dette provient.

**Tâche :** Créer une vue "Remboursements BP" permettant d'enregistrer un remboursement partiel : sélectionner le client, saisir le montant remboursé, afficher le solde restant. Distinguer ces remboursements des paiements normaux (COMMANDE=0, PAIEMENT=montant, BP réduit).

---

## MODULE 3 — Commissions des Revendeurs (CM)

### [3.1] Calcul de la commission mensuelle

Formule mensuelle :
```
CM_mensuel = Σ(FACTURE_journalière) × 25%
```
Seuls les clients à TAUX=25% sont inclus. VENTE SOLDE, VENTE CASH, et épargne sont exclus (CM=0).

**Bug actuel :** Dans l'application, "Com. Brute", "Déductions" et "Net Payable" affichent '0'. Corriger le calcul pour agréger les CM de toutes les transactions du mois par client.

### [3.2] Structure de la fiche de paie mensuelle des CM

Confirmé par les fichiers DOC 1-2-* (août 2026) — trois variantes selon la boulangerie :

**K1 (TABORA) :** `CODE | NOMS | NET/ORDI | MONT/CARTE | SOCIAL | NET/PAYER | P/RECEPT`
- NET/ORDI = CM_brut - BP (formule confirmée : ex PITSHOUNA : 325500 - 105000 = 220500)
- MONT/CARTE = 0 pour K1 (pas de déduction carte à TABORA pour août 2026)
- SOCIAL = 0 pour K1 (cotisation variable par boulangerie)
- P/RECEPT = montant que le CLIENT doit payer à la boulangerie quand NET/ORDI < 0 (client encore en dette après CM)

**B1 (KUMBI) :** `CODE | NOMS | ORDI | CARTE | SOCIAL | NET APPROUVE | P/RECEPTION`
- ORDI = CM_brut - BP (même formule)
- CARTE = 0 pour août 2026
- NET APPROUVE = NET validé par la direction (peut différer de l'ordinateur)

**B2 (MPETE) :** `CODE | NOMS | ORDI | MANUEL | SOCIAL | NET APPROUVE | OBSERV`
- ORDI = CM_brut - BP (calculé automatiquement)
- MANUEL = montant ajusté manuellement par le gérant (override)
- SOCIAL = cotisation fixe mensuelle (ex: 2000 FC/mois pour B2 août 2026)
- NET APPROUVE = MANUEL si renseigné, sinon ORDI
- OBSERV = justification de l'écart MANUEL - ORDI

**Fiche de répartition CM (sheet "clients cite" / "REPARTITION CM") :**
Colonnes de synthèse mensuelle par client :
```
N° | CLIENTS | COMMANDE | PAIEMENT | BP ACTUEL | TX | CM | SOCIAL | CARTE | REMISE | RETENUE | NET/ORDI | NET/CARTE
```
- **CARTE = 1% du CM brut** (ex : CM=325500 → CARTE=3255)
- **REMISE ≈ 0,1% du CM** (petite déduction supplémentaire variable)
- **NET/ORDI = CM - BP** (sans carte ni social)
- **NET/CARTE = CM - BP - CARTE** (après déduction carte)
- RETENUE = colonne supplémentaire rarement renseignée

**Tâche :** 
1. Afficher la fiche de paie avec les 5 colonnes : ORDI | CARTE (1%) | SOCIAL | REMISE | NET A PAYER
2. Prévoir champ MANUEL optionnel (override gérant) avec zone OBSERV/justification
3. Colonne P/RECEPT : si NET < 0, afficher le solde restant dû par le client

### [3.3] Déduction SOCIALE mensuelle des CM

Cotisation sociale = montant fixe par client par mois (ex: 2000 FC à B2, 0 FC à K1).  
Varie par boulangerie. Peut être 0.

**Tâche :** Paramétrer la cotisation sociale par boulangerie (champ sur le modèle Node ou Config par node).

---

## MODULE 4 — Caisse Sociale des clients

### [4.1] Cotisation mensuelle client

Chaque client revendeur paie une PART SOCIALE mensuelle (sheet "SOCIAL") :
```
CODE | NOMS | PAYE SOCIALE | REMISE KIESE | PAYE TOTAL
```

**Tâche :** Créer ou compléter le module Caisse Sociale pour enregistrer la cotisation mensuelle de chaque client par boulangerie.

### [4.2] Distribution annuelle (REMISE)

En fin d'année (sheet "REMISE" de K2) :
```
NOMS | POSITION | TOTAL SOCIAL | INDICE | TARIF | MERITE | REMISE | TOTAL A PAYER
```
- **INDICE** = nombre de mois où le client a participé à la caisse sociale
- **TARIF** = montant FC par indice (700 FC/indice constaté pour K2)
- **REMISE** = INDICE × TARIF
- **MERITE** = bonus pour clients élus/méritants (variable)
- **TOTAL A PAYER** = TOTAL SOCIAL + REMISE + MERITE

**Tâche :** Implémenter le calcul de distribution annuelle. La REMISE est proportionnelle aux mois de participation (INDICE), pas au montant versé. Le TARIF est fixé par la direction et peut varier d'une année à l'autre.

### [4.3] Clients absents à la distribution

Sheet K5 "les absents" : certains clients ont cotisé mais ne sont pas présents à la distribution (POSITION = absent). Leur montant est mis de côté.

Sheet K5 "REGUL SOC" : distribution en nature (colis : tomates, huile, poulet, riz) pour certains clients selon leur montant accumulé.

**Tâche :** Dans le module Caisse Sociale, gérer le statut de présence à la distribution (présent/absent/dérogation) et la forme de remise (espèces ou colis).

---

## MODULE 5 — Système BASSINS (Classification des clients par volume)

### [5.1] Catégories de clients

Sheet "BASSINS" de K2 (utilisée pour le classement mensuel) :

| Catégorie | Description |
|-----------|-------------|
| GRAND FORMAT | Clients avec COMMANDE mensuel le plus élevé |
| INTER G&M | Intermédiaire Grand & Moyen |
| INTER M&PT | Intermédiaire Moyen & Petit |
| MOYEN | Volume moyen |
| PETIT | Petit volume |

**Formule BASSINS :**
```
NET A PAYER = CM - CARTE (% de REMISE sociale) - BP
```
Note : NET négatif = client encore en déficit après commission.

### [5.2] Classement et affichage

Le classement est effectué une fois par mois, sur la base du COMMANDE total du mois. La COTE (rang dans la catégorie) est attribuée par ordre décroissant de COMMANDE.

**Tâche :** Implémenter la vue BASSINS : tableau mensuel par boulangerie classant les clients par catégorie et rang, avec COMMANDE, PAIEMENT, BP, CM, NET A PAYER. Prévoir un paramètre pour les seuils de catégorie (modifiables par DIRECTION).

---

## MODULE 6 — Rapport de Clôture mensuel par Gérant (DOC 1)

### [6.1] Structure du rapport

Le "DOC 1 - RAPPORT CLÔTURE PAR GÉRANT" agrège, dans un même fichier, les données mensuelles de toutes les boulangeries. Chaque sheet = une boulangerie (TABORA=K1, COQ=K2, ATHENÉE=K3, LOMA=K4, MPIANGU=K5, K6, KUMBI=B1, MPETE=B2).

Structure par sheet :
```
DATE | CODE | CLIENT | NBRE | [200, 300, 500, 1000] | FACTURE | TAUX | CM | PAIEMENT | SITE
```

Le champ SITE indique la boulangerie dans le rapport consolidé.

### [6.2] Tâche : Génération du rapport de clôture

**Tâche :** Connecter la page "États Financiers" au backend. Le rapport de clôture doit être généré depuis les données de l'application et permettre :
- Vue consolidée par boulangerie pour un mois donné
- Totaux : FACTURE, CM, PAIEMENT, BP final par client
- Export (PDF ou Excel) reproduisant la structure du DOC 1

---

## MODULE 7 — Boulangeries B1 (KUMBI) et B2 (MPETE)

### [7.1] Vérification des nodes B1 et B2

Les fichiers Excel montrent 8 boulangeries actives : K1 à K6 + B1 (KUMBI) + B2 (MPETE). Vérifier que B1 et B2 existent comme nodes dans l'application avec les codes corrects.

**Tâche :** Vérifier dans l'admin ou la page Nodes que `B1` (KUMBI) et `B2` (MPETE) sont créés. Les créer si absents.

### [7.2] Transferts de pain inter-boulangeries

B2 enregistre des approvisionnements reçus depuis K1, K2, K6, B1 dans sa feuille FACTURATION (lignes à code `B2`). Ces mouvements affectent le stock global.

**Tâche :** Dans le module Stock/Approvisionnement, formaliser les transferts inter-sites : boulangerie source, boulangerie destination, quantité par type de pain, date. Ces mouvements doivent être distingués des productions et des ventes.

---

## MODULE 9 — Livre de Caisse (Dépenses Journalières par Boulangerie)

Découvert dans **D1-3 LIVRE CAISSE BOULANGERIES** et **D1-4 LIVRE CAISSE DIRECTION** (août 2026).

### [9.1] Structure du Livre de Caisse par boulangerie

Chaque boulangerie (K1–K6, B1, B2) dispose d'un cahier de caisse journalier distinct :
```
DATE | BLG | IMPUT | LIBELLES | ENTREE | SORTIE | SOLDE
```
- **IMPUT** = code catégorie de dépense (numéro ou sigle : CA, numéro 1-20+)
- **ENTREE** = recette (CA du jour, autres encaissements)
- **SORTIE** = dépense (paye boulangers, ration, livraison, eau, frais divers)
- **SOLDE** = solde courant recalculé après chaque ligne
- La première ligne du jour = "CA" + "Recettes du jour K1" avec le montant total recette

Catégories typiques observées :
| IMPUT | Libellé |
|-------|---------|
| CA | Recettes du jour (chiffre d'affaires) |
| - | Paye boulangers |
| - | Ration boulangers |
| - | Livraison [autre boulangerie] |
| - | Eau |
| - | Frais d'appro |
| - | Dépôt rapport (versement à la direction) |

D1-3 contient aussi une sheet **synthèse** regroupant toutes les boulangeries et une sheet **DIR** (dépenses direction au niveau boulangerie).

### [9.2] Livre de Caisse Direction (D1-4)

Structure identique mais pour la direction centrale :
```
DATE | BLG=DIR | IMPUT (numéro) | LIBELLES | ENTREE | SORTIE | SOLDE
```
- Commence par "Repport du [date]" = report du solde du mois précédent
- Dépenses numérotées (1, 2, 3, …) : essence, mazout, crédits personnels, primes, MO ouvriers ferme, achats matériel
- "appro Caisse direction" = transfert entrant depuis les boulangeries

### [9.3] Tâches

**Tâche :** Implémenter un module "Livre de Caisse" (ou étendre le module Caisse actuel) :
1. Saisie de lignes de dépenses/recettes journalières par boulangerie : libellé, catégorie IMPUT, entrée ou sortie, solde automatique
2. Vue direction : consolidation de toutes les boulangeries + cahier direction séparé
3. "Report du mois précédent" : solde final du mois N → solde initial du mois N+1
4. Synthèse mensuelle par boulangerie : total entrées, total sorties, solde final

Ce module est **distinct** de la "Clôture de Caisse" (billetage) — le Livre de Caisse enregistre les opérations ligne par ligne, la Clôture vérifie le solde physique en fin de journée.

---

## MODULE 10 — Statistiques Consommables par Fournisseur (Farine MIDEMA/GMK)

Découvert dans **D1-5 STATISTIQUES AOUT NOVO 2026** (sheets FARINE, Levure, HUILE, SEL).

### [10.1] Farine : deux fournisseurs distincts

La farine est approvisionnée auprès de **deux fournisseurs** : **MIDEMA** et **GMK** (+ parfois DVS/MOITIÉ).  
Chaque boulangerie a un stock séparé par fournisseur :
```
Jour | BLGR | Rst ANTE/MIDEMA | Rst ANTE/GMK | PROD | MIDEM | GMK | DVS | MOITIE | PRO/MDMA | RESTE/MIDEMA | PRO/MINO | RESTE/GMK | RESTE TOTAL
```
- **Rst ANTE/MIDEMA** = stock restant avant, fournisseur MIDEMA
- **PROD** = production du jour (sacs utilisés)
- Les sorties sont imputées en priorité à l'un ou l'autre fournisseur
- **RESTE TOTAL** = somme des restes MIDEMA + GMK

Consommation journalière par boulangerie (août 2026) :
| BLG | Sacs/jour typique |
|-----|------------------|
| K1 | 6–8 |
| K2 | 5–7.5 |
| K3 | 3.5–5 |
| K4 | 7–10 |
| K5 | 4–9.5 |
| K6 | 4–7 |
| B1 | 4–7 |

**D1** = entrée direction (réserve centrale, sacs distribués aux boulangeries).

### [10.2] Levure, Huile, Sel : écart comptable vs physique

Structure commune :
```
Jour | BLGR | S/INITIAL | ENTREE/SORTIE | TOTAL | CONSOMMATION | SOLDE COMPTABLE | PRODUCTION | CONSOMMATION THÉORIQUE | SOLDE PHYSIQUE | ECART
```
- **SOLDE COMPTABLE** = stock déclaré (S/INITIAL + entrées - consommations déclarées)
- **SOLDE PHYSIQUE** = inventaire physique réel
- **ECART** = SOLDE PHYSIQUE - SOLDE COMPTABLE (souvent négatif = écart non justifié)
- La **consommation théorique** = sacs farine × ratio moyen

### [10.3] Tâches

**Tâche :**
1. Ajouter le concept de **fournisseur** sur les `ConsumableStock` de farine (MIDEMA / GMK / DVS) avec stocks séparés
2. Ajouter un champ **inventaire physique** permettant l'écart : lors de la vérification hebdomadaire, le gérant saisit le stock réel constaté → l'écart est calculé et signalé
3. Afficher dans "Production & Stocks" le détail par fournisseur pour la farine

---

## MODULE 11 — Cash Flow & Épargne Journalière

Découvert dans **DOC 06 CASH FLOW 2ème SEMESTRE 2026** (sheets : compte princ, stat, clotures des mois, EPARGNE, COLIS, etude cred).

### [11.1] Épargne journalière par boulangerie (sheet EPARGNE)

Chaque boulangerie dépose une épargne journalière calculée sur la production/revenu :
```
DATE | K1 (PROD | REVENU | EPRG) | K2 | K3 | K4 | K5 | K6 | TOTAL (PAYE | EPRG)
```
- **PROD** = sacs de farine utilisés ce jour
- **REVENU** = chiffre d'affaires du jour (= CA facturé)
- **EPRG** = montant épargné ce jour (= portion du revenu mise de côté)
- Le ratio EPRG/REVENU semble varier (ex: K4 : 10500/66500 ≈ 15.8%, K5 : 9000/57000 ≈ 15.8%)
- **TOTAL EPRG** = cumul mensuel de l'épargne inter-boulangeries

**Lien avec Caisse Sociale** : cette épargne alimente le fonds social distribué annuellement (Remise). Elle est distincte de la cotisation sociale des clients CM.

**Tâche :** Créer une saisie d'épargne journalière par boulangerie. Paramétrer le taux d'épargne (% du revenu). Afficher le cumul mensuel et annuel.

### [11.2] Bilan mensuel consolidé (sheet clotures des mois)

Historique mensuel par boulangerie sur 12+ mois :
```
DATE | BOULANGERIE | COMMANDE | PAIEMENT | BP ACTUEL | TX | CM | SOCIAL | CARTE | REMISE | RETENUE | NET/ORDI | NET/CARTE
```
Ce sheet consolidé permet de suivre l'évolution mois par mois : CA, BP total boulangerie, CM total, montants sociaux, nette CM.

**Tâche :** Ajouter dans "États Financiers" une vue historique mensuelle par boulangerie agrégée sur N mois.

### [11.3] Bilan comptable (sheet compte princ)

Bilan ACTIF/PASSIF mensuel :
- **ACTIF** : stock farine valorisé par boulangerie (qté × prix unitaire fournisseur)
- **PASSIF** : obligations sociales mensuelles (social+remise+carte par mois cumulé), emprunts en cours (ex: CAMEC 84 975 000 FC sur 90 mois)

**Tâche :** Exposer dans "États Financiers" un bilan simplifié : valeur stock farine, total BP clients (créances), total CM dues, total emprunts.

### [11.4] Distribution COLIS au personnel (sheet COLIS)

Distribution annuelle en nature aux boulangers et équipe technique :
```
BENEFICIAIRE | SAC RIZ (qté + valeur) | VIANDE DE PORC (kg + valeur) | ESPECES | TOTAL
```
- Par boulangerie : K1–K6 + EQ/TECH (équipe technique = mécanos, transport, etc.)
- Par bénéficiaire : Boulanger 1, 2, 3, 4, 5…
- Totaux par boulangerie affichés en en-tête

**Tâche :** Prévoir dans "Configuration / Gestion du Personnel" un module de distribution COLIS : saisir les quantités par employé, calculer la valeur totale, imprimer la liste de distribution.

---

## MODULE 12 — Statistiques Farine (Suivi historique par boulangerie)

Découvert dans DOC 06 sheet **stat** : suivi journalier de la consommation de farine sur toute une année.

### [12.1] Structure

```
DATE | K1 | K2 | K3 | K4 | K5 | K6 | B1 | TOTAL | ENTREE | PU | PT | SOLDE
```
- Par date : sacs consommés par boulangerie (ex : K1=7.5, K2=7, K3=5, …)
- **ENTREE** = réapprovisionnement (nombre de sacs reçus ce jour)
- **PU** = prix unitaire du sac de farine lors de l'achat (ex: 90870 FC)
- **PT** = prix total de l'achat (ENTREE × PU)
- **SOLDE** = stock farine résiduel en direction (cumul entrées - sorties)
- Annotations : "ACHAT", "RETRAIT", "achat local X sacs × Y FC"

### [12.2] Tâches

**Tâche :**
1. Enregistrer les achats de farine (ENTREE, fournisseur, PU, PT, date)
2. Vue "Statistiques Farine" : consommation journalière par boulangerie, stock direction, graphique d'évolution
3. Alertes lorsque le stock direction tombe sous un seuil paramétrable

---

## MODULE 8 — Bugs connus (issus de remarque.md)

### [8.1] Commission module : valeurs à zéro
- **Problème :** "Com. Brute", "Déductions" et "Net Payable" restent à '0' dans la page "Commissions des Revendeurs (CM)".
- **Cause probable :** Agrégation mensuelle non connectée au backend.
- **Tâche :** Connecter le calcul CM au backend : agréger les transactions du mois par client, appliquer TAUX=25%, soustraire CARTE + SOCIAL.

### [8.2] Dates "Invalid Date" dans Facturation en Chaîne & Livraison
- **Problème :** Les dates affichent "Invalid Date".
- **Tâche :** Vérifier le parsing des dates retournées par l'API (format ISO vs local) et normaliser l'affichage.

### [8.3] États Financiers N/N-1 non connectés
- **Tâche :** Identifier les endpoints manquants et câbler la page États Financiers au backend pour afficher les données réelles de l'exercice courant vs exercice précédent.

### [8.4] Erreur 400 sur création de Node (Nodes.tsx:83)
- **Tâche :** Investiguer le `POST /api/core/nodes/ 400` lors de la création d'une nouvelle boulangerie. Vérifier les champs obligatoires (code unique, région, etc.) et afficher le message d'erreur dans le formulaire.

### [8.5] Liste des agents par succursale (modal)
- **Tâche :** En cliquant sur une succursale dans la page Nodes, afficher une boîte modale avec la liste des agents (utilisateurs) assignés à ce node et leurs rôles.

### [8.6] Refresh F5 → 404 en production (cPanel)
- **Tâche :** Configurer `.htaccess` pour rediriger toutes les routes non-fichier vers `index.html` (React Router SPA). Exemple : `RewriteRule ^ index.html [L]`.

### [8.7] Registre Blockchain — connexion backend
- **Tâche :** Clarifier avec le client la nature du module "Registre Blockchain" et s'il doit être connecté à une logique métier existante (journal immuable des transactions ?) ou est purement informatif.

---

## RÉSUMÉ DES PRIORITÉS

> Légende : items avec ✅ = réalisés dans les Sprints 1–9 | items sans ✅ = restants

| Priorité | Tâche | État |
|----------|-------|------|
| 🔴 Critique | [3.1] Bug commissions à zéro | ✅ Sprint 5 |
| 🔴 Critique | [8.2] Dates Invalid Date | ✅ Sprint 1 |
| 🟠 Haute | [2.1] BP cumulatif mensuel | à faire |
| 🟠 Haute | [1.1] Types de vente (SOLDE, CASH, épargne) | à faire |
| 🟠 Haute | [3.2] Fiche de paie CM — CARTE 1% + REMISE + MANUEL | à faire (précision [3.2] mise à jour) |
| 🟠 Haute | [9.1-9.3] Livre de Caisse journalier par boulangerie | **NOUVEAU** |
| 🟠 Haute | [8.3] États Financiers connectés | à faire |
| 🟠 Haute | [8.4] Erreur 400 création Node | ✅ Sprint 8 |
| 🟡 Moyenne | [6.2] Rapport de clôture exportable | à faire |
| 🟡 Moyenne | [2.4] Fiche des Remboursements BP | **NOUVEAU** |
| 🟡 Moyenne | [5.2] Vue BASSINS | à faire |
| 🟡 Moyenne | [7.2] Transferts inter-boulangeries | à faire |
| 🟡 Moyenne | [10.1-10.3] Farine par fournisseur + inventaire physique | **NOUVEAU** |
| 🟡 Moyenne | [11.1] Épargne journalière par boulangerie | **NOUVEAU** |
| 🟡 Moyenne | [12.1-12.2] Statistiques farine / achats | **NOUVEAU** |
| 🟡 Moyenne | [8.5] Modal agents par succursale | ✅ Sprint 8 |
| 🟢 Basse | [4.1-4.3] Caisse Sociale complète | à faire |
| 🟢 Basse | [2.3] Rapport déficitaires | à faire |
| 🟢 Basse | [11.2] Bilan mensuel historique | **NOUVEAU** |
| 🟢 Basse | [11.3] Bilan comptable ACTIF/PASSIF | **NOUVEAU** |
| 🟢 Basse | [11.4] Distribution COLIS personnel | **NOUVEAU** |
| 🟢 Basse | [8.6] .htaccess SPA | ✅ Sprint 9 |
| 🟢 Basse | [8.7] Registre Blockchain | à clarifier |
