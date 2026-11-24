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

---

## Questions sur la paie des commissions (Q-022 à Q-024)

*Préparées le 21/11/2026. Les montants ci-dessous sont des exemples inventés, calculés avec les vraies formules de l'application (commission = commande × 25 %, cotisation sociale 3 000 FC, pain à 500 FC). Une réponse courte suffit (par exemple « Q-022 : A »).*

### Q-022 (BUG-266) — Quand la commission d'un client ne couvre pas ses retenues, que fait-on du manque ?

**Exemple.** Un client commande 20 000 FC en février. Sa commission est de 5 000 FC. Il doit encore 6 000 FC à la boulangerie et sa cotisation sociale est de 3 000 FC.
5 000 − 6 000 − 3 000 = **−4 000 FC** : la commission ne suffit pas, il manque 4 000 FC.

**Aujourd'hui, l'application** ne paie rien à ce client (le bouton « Régler » est bloqué), affiche −4 000 FC et **reporte ces 4 000 FC sur sa paie de mars**.
En mars, le client commande 60 000 FC (commission 15 000 FC) et a entre-temps payé toute sa dette de 6 000 FC. Son net de mars est : 15 000 − 0 − 3 000 − 4 000 (report) = **8 000 FC**.

- **A.** Garder ce fonctionnement : on reporte le manque sur le mois suivant. Mars : **8 000 FC**.
- **B.** Oublier le manque : en février le net est ramené à 0 et rien n'est reporté. Mars : 15 000 − 0 − 3 000 = **12 000 FC**.
- **C.** Le client doit payer les 4 000 FC en espèces en février. Mars : **12 000 FC** (et la boulangerie encaisse 4 000 FC en février).

*Cela complète Q-002 (report de la dette), qui n'a pas dit ce qui arrive quand le client a payé sa dette entre-temps.*

### Q-023 (BUG-267) — L'épargne d'un client doit-elle s'ajouter à sa commission ?

**Exemple.** Un client a 7 000 FC d'épargne chez nous (son solde est de −7 000 FC) et il achète quand même 4 000 FC de pain. Commission : 1 000 FC. Cotisation : 3 000 FC.

**Aujourd'hui, l'application** fait comme vos classeurs (NET = commission − solde) : l'épargne s'ajoute et il reçoit 1 000 + 7 000 − 3 000 = **5 000 FC**. Un client qui n'a que de l'épargne et n'achète rien n'a, lui, aucune ligne de paie.

- **A.** Garder ainsi : l'épargne s'ajoute à la commission. Il reçoit **5 000 FC**.
- **B.** L'épargne n'entre jamais dans la paie (elle reste son argent déposé, rendu autrement). Net : 1 000 − 0 − 3 000 = **−2 000 FC** (manque reporté, voir Q-022).

### Q-024 (BUG-268) — Une dette peut-elle être comptée deux fois ?

**Exemple.** En février : commande 20 000 FC, commission 5 000 FC, dette 10 000 FC, cotisation 3 000 FC. Net : 5 000 − 10 000 − 3 000 = **−8 000 FC**, reporté en mars. En mars le client commande la même chose et sa dette est toujours de 10 000 FC.

- **A.** (**Aujourd'hui**) La dette de 10 000 FC n'est comptée qu'une fois : le report de 8 000 FC en contient déjà une partie, on ne retire que les 2 000 FC restants. Net de mars : 5 000 − 2 000 − 3 000 − 8 000 = **−8 000 FC**.
- **B.** (Ancien fonctionnement, corrigé) Dette et report comptés ensemble : 5 000 − 10 000 − 3 000 − 8 000 = **−16 000 FC**.

*Question : A est-il bien ce que vous voulez ? Si le client a payé sa dette entre-temps, voir Q-022.*

### Q-025 (BUG-507) — Le livreur doit-il voir les clients des autres boulangeries ?

**Situation.** Un client de K3 se présente à K1. Le **facturier** de K1 peut le chercher et lui faire sa facture (vous l'avez demandé). Aujourd'hui, l'application donne **la même chose au livreur** : s'il tape un nom ou un code, il voit aussi les clients des autres boulangeries (nom, code, solde). Il ne peut rien modifier, c'est de la lecture seule. Vous n'avez parlé que du facturier.

- **A.** (**Aujourd'hui**) Le livreur voit tous les clients, comme le facturier. Avantage : s'il livre un client d'une autre boulangerie, il le retrouve tout de suite.
- **B.** Le livreur ne voit que les clients de sa propre boulangerie. Conséquence : un client d'une autre boulangerie n'apparaît plus dans sa recherche ; il confirme toujours les livraisons des factures de sa boulangerie, mais pour un client venu d'ailleurs il faut que le facturier ou le gérant s'en occupe.

*Question : voulez-vous que le livreur voie aussi les clients des autres boulangeries (A), ou seulement ceux de la sienne (B) ?*

### Q-026 (remarque.md, ligne 452) — Quelles valeurs doivent être propres à chaque boulangerie ?

Voir `docs/qa/MESSAGE_CLIENT_2026-11-21.md`, question Q4 (options A, B, C). Remplace la ligne de `remarque.md` sur les valeurs de §2.3 par boulangerie ; contredit la décision du 14/11 sur le frais de carte (BUG-291).

### Q-027 (BUG-411, BUG-253) — Quels écrans le livreur doit-il avoir ?

Voir `docs/qa/MESSAGE_CLIENT_2026-11-21.md`, question Q6 (liste à cocher). Conditionne les gardes de routes de BUG-411 et le droit du livreur sur `cleanup_expired` (BUG-253).

### Q-044 (intrants, fichier STATISQUES NOVEMBRE 2026) — La ligne « D1 » est-elle bien le stock de la direction ?

**Situation.** Dans votre tableau, chaque jour a une ligne par boulangerie (K1 à K6, B1) puis une ligne « D1 ». Nous la traitons comme le **stock de la direction** : ses sorties sont les envois faits aux boulangeries.

*Question : D1 est-elle bien le stock de la direction (envois aux boulangeries en sortie) ? Aujourd'hui : oui.*

### Q-045 (intrants) — Que signifie l'indice de consommation, y a-t-il un seuil d'alerte ?

**Situation.** Pour la levure, l'huile et le sel, le tableau divise la consommation du jour par les **sacs de farine utilisés le même jour**. Nous faisons pareil (vide si aucun sac).

*Question : cette définition est-elle la bonne ? Faut-il alerter quand une boulangerie dépasse la moyenne du groupe, et à partir de quel écart ?*

### Q-046 (intrants) — Que veut dire la colonne « ok » du sel ?

**Situation.** Dans la feuille du sel, une marque « ok » apparaît dans une colonne sans titre, selon l'écart. Aujourd'hui l'application ne la reprend pas.

*Question : « ok » veut-il dire écart toléré ? Quel écart est toléré (en quelle unité) ?*

### Q-047 (intrants) — Le sel : en grammes, en sacs ou en boîtes ?

**Situation.** L'application compte le sel en **grammes**. Votre fichier compte des **sacs**, avec une conversion « Bte/U » (204, 205…) et deux restes (en sacs et en boîtes).

- **A.** Grammes partout.
- **B.** Sacs, avec conversion en boîtes/unités (préciser le nombre de boîtes par sac).

**Réponse : 1 sac = 20 kg = 204 boîtes (donnée par le client).** Une boîte vaut donc 20 000 g ÷ 204 ≈ 98,04 g. Le stock reste compté en grammes ; les statistiques affichent en plus les équivalents en sacs et en boîtes (poids du sac et boîtes par sac sont réglables dans la configuration des consommables).

### Q-048 (intrants) — Huile : la formule du total avant production

**Situation.** Pour l'huile, votre fichier calcule « stock initial + entrée **×** sortie », alors que farine et levure font « initial + entrée **−** sortie ». Nous pensons à une erreur du tableur.

*Question : faut-il bien faire « initial + entrée − sortie » pour l'huile ? Aujourd'hui : oui.*

### Q-049 (intrants) — Farine du mois : colonnes « vente », solde de départ et « accroissement »

**Situation.** La feuille ENTREE FARINE a une colonne **vente**, un solde de départ écrit à la main (« 273,18 − total + 1 ») et une ligne **accroissement**.

*Question : que représentent exactement la vente (farine revendue ?), ce solde de départ et l'accroissement ?*

### Q-050 (intrants) — Écart : signe et cas « reste non déclaré » ; qui voit ces statistiques ?

**Situation.** L'écart est calculé « reste déclaré − solde comptable ». Quand le reste n'est pas déclaré, votre tableau affiche l'opposé du solde (ex. −26,8) ; l'application laisse l'écart **vide**. Les statistiques sont visibles aujourd'hui par la direction, le comptable et l'administrateur (toutes les boulangeries) et par le gérant (la sienne seulement).

*Questions : (1) le signe et l'écart vide sont-ils corrects ? (2) le gérant doit-il voir les statistiques de sa boulangerie ? (3) la direction seule voit-elle D1 ?*

### Q-052 (remarque.md, ligne 506) — « Taux de commission par défaut » : à garder ou à supprimer ?

**Situation.** Vous avez demandé qu'il n'y ait pas de « Taux de commission par défaut » dans l'écran Commissions CM, avec seulement la cotisation sociale (2 000 FC) et la carte propres à la boulangerie. Cet écran n'a pas ce champ. Mais vous avez aussi répondu (Q-026) que le « Taux de Commission » est **propre à chaque boulangerie** : il se règle dans la fiche de la boulangerie. Il reste un taux **global** dans les Paramètres (§2.3), utilisé seulement quand une boulangerie n'a pas son propre taux.

- **A.** Garder le taux global comme valeur de secours (aucun changement visible pour vous).
- **B.** Supprimer le taux global : chaque boulangerie doit alors avoir son taux renseigné.

*Recommandation : A.*

### Q-051 (stock de départ) — « Compté comme des pains vendus aujourd'hui » : que veut dire exactement ?

**Situation.** Vous avez demandé que le stock de départ s'inscrive dans « Stock Pains du Jour » et soit « compté comme des pains vendus aujourd'hui ». Aujourd'hui l'application l'**affiche** dans une colonne « Stock de départ » et ne change pas le calcul de clôture (produit = vendus + reste du jour − reste d'hier + …).

**Exemple.** Une boulangerie démarre avec **40 pains** de stock de départ, **produit 100** pains, **vend 120** pains et il en **reste 20**.
- Lecture 1 : les ventes du jour restent **120** (le stock de départ est seulement affiché).
- Lecture 2 : le stock de départ compte comme une vente : ventes du jour = **120 + 40 = 160**.

*Question : quelle lecture est la bonne ? Si c'est la lecture 2, quelle valeur de ventes (en FC) doit apparaître dans le rapport du jour ?*

### Q-053 (clôture automatique de la fournée) — Que faire quand l'heure de clôture arrive ?

**Situation.** Vous avez demandé que, à l'heure de clôture de la boulangerie, la fournée se clôture toute seule et que les pains non vendus, déclassés et sorties gratuites figurent dans la Clôture journalière. L'application le fait maintenant, avec des choix **prudents** que nous voulons faire confirmer :
- elle attend **30 minutes** après l'heure de clôture avant de clôturer, pour laisser le gérant compléter sa fenêtre de confirmation ;
- le **reste du jour** de chaque catégorie est pris sur le **stock réel en ce moment** (rien n'est inventé) ; ce que le gérant a déjà saisi n'est **jamais** modifié ;
- une fournée **sans aucune livraison** dans la journée, ou **à zéro sac**, n'est **pas** clôturée : le gérant est alerté et la clôture reste à faire à la main ;
- ce mécanisme n'est actif que pour les boulangeries où l'heure de clôture a été activée (le même réglage que le blocage des ventes), car l'heure de relève par défaut (12 h) clôturerait sinon des boulangeries qui ne l'ont pas voulu.

*Questions : (1) 30 minutes de délai, c'est bien ? (2) Pour une fournée sans livraison ou à zéro sac, faut-il la clôturer quand même (à zéro) ou la laisser ouverte comme aujourd'hui ? (3) Si le gérant n'a pas rempli Non vendu / Déclassés / Sorties gratuites, la clôture automatique est-elle acceptée telle quelle (avec une alerte) ou doit-elle attendre sa saisie ? (4) Faut-il un réglage « clôture automatique » séparé du blocage des ventes ?*

### Q-054 (synchronisation, BUG-1006) — Date d'une réception confirmée hors ligne

**Situation.** Une boulangerie sans connexion confirme la réception d'un transfert un soir. Le poste n'envoie l'information au siège que le lendemain. Les totaux du groupe par jour peuvent alors compter cette réception au lendemain pour une boulangerie et à la veille pour l'autre.

- **A.** La date est celle de la **saisie** sur le poste (la veille).
- **B.** La date est celle de la **synchronisation** (le lendemain).

*Recommandation : A (la journée où le gérant a réellement confirmé).*
