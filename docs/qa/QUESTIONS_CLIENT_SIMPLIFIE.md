# Questions pour M. NDUNGA NSAYI PIERRE — ETS. KIESE

Ces questions viennent de la comparaison entre vos fichiers Excel d'août 2026 et l'application. Nous avons relu **tous** vos documents (remarque, adaptes, cahier des charges, cadre comptable, et chaque feuille de chacun de vos classeurs, y compris les feuilles « anciennes », les formules et les notes). **Seules les questions dont la réponse ne s'y trouve vraiment pas sont posées ici.** Une réponse courte suffit (par exemple « 1-A »).

*Mise à jour du 14/11/2026 : sur les 5 questions précédentes, 3 ont trouvé leur réponse dans vos fichiers (voir le tableau en bas). Il reste 3 petites questions, plus précises qu'avant.*

---

## 1. Une seule ligne de paiement négatif reste à expliquer

**Ce que nous avons trouvé** : les 19 lignes à paiement négatif de la facturation d'août (−635 850 FC) ne sont pas des erreurs. 18 d'entre elles s'expliquent par leur libellé (retrait d'épargne, emprunt d'un boulanger, manquant d'équipe — voir le tableau en bas). Il en reste une.

**La ligne** : client n° 54 de K3 (ATHENEE), le 13/08. Sa commande est de 2 000 FC et son paiement est écrit `=2000-15000`, soit **−13 000 FC**. Le libellé ne dit pas « épargne ».

**Question** : que représente cette ligne ?
- **A.** Il a payé sa commande de 2 000 FC et retiré 15 000 FC de son épargne.
- **B.** Il a payé 2 000 FC et on lui a rendu 15 000 FC (trop-perçu ou remboursement).
- **C.** Erreur de saisie à corriger.

*Pourquoi c'est important* : 13 000 FC seulement, mais il faut savoir dans quelle catégorie l'application doit ranger ce genre de ligne.

---

## 2. La carte client : 1 % de la commission, ou un montant fixe ?

**Ce que nous avons trouvé** : la carte est bien déduite **dans toutes les boulangeries, chaque mois**, de janvier 2025 à juillet 2026 (votre fichier cash-flow, feuille « clotures des mois », colonne CARTE). En juillet 2026 : K1 72 000, K2 69 000, K3 71 000, K4 90 000, K5 93 000, K6 108 000, B1 136 000, B2 38 000, soit 677 000 FC. Si la colonne est vide en août, c'est parce que la paie d'août n'est pas encore faite dans vos classeurs, pas parce que la carte est supprimée.

**Ce qui ne colle pas** : ces montants ne valent pas toujours 1 % de la commission (de 0,7 % à 1,7 % selon la boulangerie en juillet). Ce sont toujours des milliers ronds, et ils sont proches du nombre de clients payés (par exemple 72 clients à K1 pour 72 000 FC).

**Question** : comment se calcule la carte d'un client ?
- **A.** 1 % de sa commission, comme noté dans le document « adaptes ».
- **B.** Un montant fixe par client et par mois (1 000 FC ?).
- **C.** Autre règle (laquelle ?).

---

## 3. Les derniers jours de juillet dans la paie d'août

**Ce que nous avons trouvé** : vos classeurs de commission de K3 et K4 commencent le 26/07, celui de K5 le 28/07 et celui de B1 le 30/07. Les autres (K1, K2, K6, B2) et tous les rapports de caisse commencent le 01/08. Les jours de juillet pèsent lourd : commission de 872 125 FC (K3), 1 867 750 FC (K4), 739 000 FC (K5), 578 125 FC (B1).

**Question** : ces jours de fin juillet ont-ils déjà été payés dans la paie de juillet ?
- **A.** Non : la paie va d'une clôture à la suivante, donc ils sont payés avec août.
- **B.** Oui : ils ont déjà été payés en juillet. Il faut les ignorer en août (période = du 1er au dernier jour du mois).

*Pourquoi c'est important* : l'application découpe aujourd'hui par mois civil. Si c'est A, la période de paie doit pouvoir démarrer à une date choisie.

---

## Réponses déjà trouvées dans vos documents (rien à répondre)

| Sujet | Réponse retenue | Où elle figure |
|---|---|---|
| Plafond de crédit | **50 000 FC** | Votre décision, corrigée dans l'application |
| Cotisation sociale mensuelle | Réglée **par boulangerie** (2 000 FC à B2, 0 FC à K1), pas 3 000 FC pour tous | adaptes.md [3.3] |
| Client qui a trop payé (solde en sa faveur) | Son crédit **s'ajoute** à la commission nette (net = commission − solde, donc un solde négatif augmente le net) | adaptes.md (formule NET A PAYER) et vos Excel |
| Remise mensuelle | Le **calcul de vos Excel** : 0,25 % de la commande. Le « ≈ 0,1 % » du document adaptes n'est qu'une approximation | adaptes.md [3.2] et vos Excel |
| Mots de passe | Changement conseillé, non imposé | Votre décision |
| **Paiements négatifs en facturation** (19 lignes, −635 850 FC) | Ce sont des **sorties d'argent de la caisse** : 11 retraits d'épargne de clients (−360 000 FC), 4 emprunts de boulangers (−199 000 FC), 3 manquants d'équipe (−63 850 FC), plus la ligne n° 54 de K3 (question 1). Elles réduisent la recette du jour dans le livre de caisse | Classeurs DOC 1-2-x, feuilles FACTURATION, colonne O « PAIEMENT ACTUEL » : libellés « …/epargne », « EMPRUNT … /BLGR », « MQ EQUIPE … », « MANQUANT EQUIPE … » ; livre de caisse D1-3 |
| **Blocs de date en double** (K2 le 07/08, B2 le 14/08, et aussi K3 et K4 le 07/08) | Le deuxième bloc est une **copie collée deux fois** : mêmes clients, mêmes montants (par exemple K2 : commande 1 286 125 FC dans chacun des deux blocs). Il n'y a pas de jour caché : toutes les dates du 01/08 au 16/08 (et du 26/07 pour K3, K4) sont présentes une fois. À compter **une seule fois**, comme le fait votre synthèse | Classeurs DOC 1-2-2, 1-2-3, 1-2-4, 1-2-8, feuilles FACTURATION (K2 lignes 718 et 840, B2 lignes 1115 et 1200) |
| **Remise annuelle** | C'est **INDICE × TARIF + MÉRITE**, versée avec l'épargne sociale de fin d'année (TOTAL À PAYER = TOTAL SOCIAL + REMISE). L'INDICE est le nombre de mois de participation (en général épargne ÷ 2 000 FC). Le TARIF est fixé chaque année par boulangerie (en 2023 : 700 FC à K2, 600 FC à K4, 500 FC à K3, K5 et K6). La règle « 0,025 × volume livré » du cahier des charges **n'existe dans aucun de vos Excel**. Le volume n'entre donc pas dans le calcul (ni en pains, ni en FC) | Classeur B2 (dossier daja_analysé), feuille REMISE, formules `=(E4*F4)+G4` et `=D4+H4` ; feuilles « paye social 23 » (K3), « social 2023 » (K4), « SOCIAL 2023 » (K5, K6), avec la note « REMISE : la participation de la boulangerie dans le panier social de sa cliente » ; adaptes.md [4.2] |
| **Livre de caisse boulangerie (D1-3) : écart entre la recette et les paiements** | Recette du jour + « AUTRES ENCAISSEMENTS » = **total des paiements de la facturation** (retraits négatifs compris), jour par jour, pour 118 jours sur 128. Pour 9 autres jours (1er au 3 août à K1, K2, K6 et B2), la différence vient d'une ligne **« REMB JUILLET »** de la facturation (remboursement de dettes de juillet), qui fait l'écart au franc près (5 365 100 FC au total). Il reste un seul jour de 500 FC (K5, 11/08) | Classeur D1-3, feuilles TABORA, COQ… (lignes « Recettes du jour » et « AUTRES ENCAISSEMENTS » de chaque bloc) comparées à la colonne O des FACTURATION |
| **Livre de caisse direction (D1-4) : « rupture » de 6 000 FC** | Il n'y a **pas de rupture** : la ligne 449 « transport équipe sciage » (6 000 FC) est une vraie dépense du 09/08, saisie sans date ni numéro. Le solde est bien calculé (`=G448+E449-F449`). Aucun solde n'est saisi à la main dans ce livre | Classeur D1-4, feuille DIR, lignes 448 à 450 |
