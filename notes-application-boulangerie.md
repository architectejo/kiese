# Notes mises au propre : application de gestion de boulangerie

## Règles de gestion

- **Reste d'hier** : ne dépend pas d'une équipe.
- **Non vendu** et **sortie gratuite** : c'est la même chose.
- **Transfert** : Approvisionaire, les pains transférés sont considérés comme vendus ajoute la valeur en montant au revenu du jours. Lors des ventes chez le receveur, on soustrait le montant de pains transferer dans la clôture.

- **Paiement des épargnes** : c'est un encaissement spécial. Il ne faut pas l'associer à l'achat de pain. Prévoir un **compte épargne** et un **compte d'achat de pain**.
- **Paiement déclaratif**.
- **L'heure est une variable**.

## Étapes de développement

1. **Étape 1** : production, justification des pains.
2. **Étape 2** : gestion des recettes et dépenses (caisse).
3. **Étape 3** : statistiques au niveau de la direction.

## Clôture journalière

- Ajouter la liste des clients du jour avec le détail : nombre de tours (facture) et montant total.
- Permettre à l'encodeur de corriger ses erreurs de saisie.
- Ajouter la fonctionnalité des **bordereaux de versement** chez le comptable.
- Voir comment séparer les dépenses du gérant de celles de l'admin.
- Ajouter le **paiement actuel**.

## Calcul des dettes et pertes

- **Dette de transactions** = paiement − facture
  - Résultat positif : le client a trop payé, il a un plus dans son compte courant.
  - Résultat négatif : le client est en dette.
- **Perte ou manque à gagner** = paiement + commission - facture (si c'est positif le client à trop payer, si négatifi il est deficitaire)

## Régularisation

- Traiter d'abord le **non servi**: des factures sur "Facturation (Facturier)" et sur "Tableau de Bord" section "Dernières Factures Livrées" donner au gerant de declarer une facture 'non servi'.

La Régularisation c'est lorsqu'on fait un retrait des pains pour une facture "non servi" celà peut se faire plusieurs jours après

## Consommation et stock

- Voir comment gérer le stock et comment signaler un problème de stock : farine, huile, sel/sucre (?), levure (?).
- **Déclaration de fournée** : renseigner les informations d'un sac pour le contrôle.
- On peut enregistrer le poids du produit pour avoir le contrôle.
- **Fournée automatique** : collecte des données sur les ventes par catégorie et les restes déclarés par catégorie.

## Pilotage

- Voir l'auto-évaluation du gérant.
- Avoir une vue synthèse des tout les rapports.

---

## Passages à confirmer

- « paiement + commission (?) = facture » : le mot est ambigu.
- Liste du stock : « farine, huile, su…, livre… » pourrait être sucre/sel et levure.
- Annotation près de « déclaration fournée… d'un sac » (« prod… à la bouillie ? ») : illisible, omise.
- Dernière puce de la page 2 : vide.

## Transfert (Approvisionnement)
- Donnée la possibilité d'envoyer les pains par catégorie à d'autre boulangerie sans au préalable avoir réçu la demande, l'autre boulangerie pourra confirmer la reception, si lors de la réception l'autre boulangerie saisi un nombre different des pains que celui qui a été saisi, l'application doit alerter pour que les deux regularisent la situation