# Auditeur comptable — réponses trouvées dans les Excel (14/11/2026)

Périmètre : les 24 classeurs de `data_kiese/` (dossiers racine, `daja_analysé`, `Liste_client`, `Nouveau_`), toutes feuilles (aucune masquée, aucun commentaire de cellule), formules et textes, plus le document Word de synthèse. Lecture seule, travail sur copies hors dépôt, agrégats uniquement. Aucun code applicatif modifié.

| # | Question | Verdict | Preuve (agrégats) |
|---|---|---|---|
| 1 | Paiements négatifs (19 lignes, -635 850 FC) | **Trouvée** pour 18 lignes sur 19 | FACTURATION colonne O, 1-16/08, libellé de la colonne client : 11 retraits d'épargne « /epargne » (-360 000 : K2 4, K3 1, K4 1, K5 4, K6 1), 4 emprunts de boulangers « EMPRUNT … /BLGR » (-199 000 : K2 1, K4 3), 3 manquants d'équipe « MQ/MANQUANT EQUIPE » (-63 850 : K2 1, K5 2). Total recalculé : 19 lignes, -635 850. Reste K3 n° 54, 13/08, `=2000-15000` (-13 000). Ces lignes réduisent la recette du livre D1-3. |
| 2 | Carte 1 % | **Indice partiel** | Déduite dans les 8 boulangeries chaque mois de 01/2025 à 07/2026 (DOC 06, « clotures des mois », col. I ; juillet 2026 : 72 000 / 69 000 / 71 000 / 90 000 / 93 000 / 108 000 / 136 000 / 38 000 = 677 000 FC, `=SUM(I292:I300)`), reprise dans « compte princ » (social + remise + carte juillet = 2 497 218 FC). Août vide = paie non traitée. Mais ratio carte/CM de 0,7 % à 1,7 %, milliers ronds, proche du nombre de clients payés : aucune formule 1 % nulle part (colonne saisie à la main). |
| 3a | Blocs de date en double | **Trouvée** | Copie collée : blocs identiques (K2 07/08 commande 1 286 125 FC x2 ; B2 14/08 511 875 x2 ; aussi K3 713 750 x2 et K4 1 483 625 x2 le 07/08, non signalés avant). Une seule ligne diffère (dernière ligne). Toutes les dates sont présentes, pas de jour caché. Synthèses K2 et K4 : comptées une fois. |
| 3b | Période « AOUT » | **Indice partiel** | D1-3 et DOC 01 commencent tous au 01/08 ; seuls les classeurs de commission K3, K4 (26/07), K5 (28/07), B1 (30/07) débordent : CM de juillet incluse 872 125 / 1 867 750 / 739 000 / 578 125. Titres « paie » périmés (B2 « JUILLET … traité le 04/08/2026 », K6 « JUIN … 03/07 »). Rien ne dit si ces jours ont déjà été payés en juillet. |
| 4 | Remise annuelle | **Trouvée** | Classeur B2 (daja_analysé), feuille REMISE : `H4 =(E4*F4)+G4` (INDICE x TARIF + MÉRITE), `I4 =D4+H4`. TARIF 2023 : K2 700, K4 600, K3/K5/K6 500. Note « la participation de la boulangerie dans le panier social de sa cliente ». Recherche de `0,025` / `2,5 %` dans toutes les formules et tous les textes : aucune occurrence. Remise mensuelle distincte : commande x 0,25 % (déjà connue, BUG-292). Détail : adaptes.md dit « TOTAL SOCIAL + REMISE + MÉRITE », l'Excel inclut MÉRITE dans REMISE. |
| 5a | Écart recette / paiements (D1-3) | **Trouvée** | « Recettes du jour » + « AUTRES ENCAISSEMENTS » = somme des paiements FACTURATION (négatifs inclus) : 118 jours sur 128. 9 jours (01-03/08 : K1 2, K2 3, K6 2, B2 2) = ligne « REMB JUILLET » exacte (5 365 100 FC, dont K1 1 289 000). 1 jour à 500 FC (K5, 11/08). |
| 5b | -6 000 FC ligne 450 de D1-4 | **Trouvée** | Pas de rupture : ligne 449 « transport équipe sciage » 6 000 FC, sans date ni numéro, solde `=G448+E449-F449`. Aucun solde saisi à la main ; les seuls écarts de chaîne sont les lignes de totaux. |

Autres constats : la feuille « FICHE DES REMB » de DOC 01 est vide (total 0) ; les feuilles « carte » des classeurs K3-K6 sont des historiques 2019-2023 sans lien avec la carte de 1 %.

## Mises à jour des documents
- `docs/qa/QUESTIONS_CLIENT_SIMPLIFIE.md` : 5 questions réduites à 3 (ligne n° 54 de K3 ; règle de calcul de la carte ; jours de fin juillet déjà payés ou non). 6 réponses ajoutées au tableau « Réponses déjà trouvées ».
- `docs/qa/QUESTIONS_CLIENT.md` : Q-009, Q-010, Q-013, Q-014, Q-016 renseignées (date 2026-11-14).
- `docs/qa/REGISTRE_BUGS.md` : BUG-290 passe à OUVERT (nature des lignes connue, règle à implémenter) ; BUG-295 passe à OUVERT (INDICE x TARIF + MÉRITE, adaptes.md > cahier) ; BUG-291 et BUG-294 restent À CLARIFIER avec le détail trouvé ; BUG-296 : complément, statut inchangé.

Scripts d'analyse : scratchpad de session, hors dépôt.
