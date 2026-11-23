# Analyse du fichier « STATISQUES NOVEMBRE 2026 LOGICIEL.xlsx » (intrants) et répartition A / B (2026-11-23)

Auteur : dev-b. Source : `docs/Intras/STATISQUES NOVEMBRE 2026 LOGICIEL.xlsx` (donné par le client, 5 feuilles, ~30 Ko, aucune donnée personnelle : des quantités de stock). Le mot « LOGICIEL » dans le titre indique que le client veut que le logiciel produise ces tableaux. Priorité en cas de contradiction : `remarque.md` > `adaptes.md` > `cadre_comptable.md` > `cahierDesCharges.md`.

## 1. Ce que contient le fichier

Cinq feuilles, une par intrant. Pour les quatre premières, un bloc **par jour** (une ligne par boulangerie K1 à K6, B1, plus une ligne **D1 = stock de la direction**, puis une ligne **TOTAUX**) :

| Feuille | Colonnes (dans l'ordre) |
|---|---|
| **FARINE** | Date · Boulangerie · Stock initial · Entrée · Sortie · **Total avant production** (= initial + entrée − sortie) · **Stock produit** (consommation du jour) · **Solde comptable** (= total − produit) · **Inventaire physique : reste déclaré** · **Écart** (= déclaré − comptable) |
| **Levure** | idem + **Référence production** (sacs de farine utilisés par la boulangerie ce jour-là) + **Indice de consommation** (= consommation ÷ référence production) |
| **HUILE** | idem Levure ; la formule du total avant production est `initial + entrée × sortie` (voir §4, probable erreur du tableur) |
| **SEL** | idem Levure, avec une colonne **Bte/U** (204, 205…) qui convertit des sacs en boîtes/unités, et deux restes : **reste/sac** et **reste/boîte** ; une marque « ok » apparaît dans une colonne sans titre selon l'écart |
| **ENTREE FARINE** | **Statistiques du mois** : une ligne par jour avec la **consommation de farine de chaque boulangerie** (K1 à K6, B1), une colonne **vente**, le **total** ; puis **entrée** (achat), **PU** (prix unitaire), **PT** (prix total = entrée × PU), **solde courant** du stock ; en bas : **total du mois**, **écart du mois** par boulangerie, **moyenne par jour**, **accroissement** |

Les jours suivants (24/11 et au-delà) sont des gabarits vides (`#DIV/0!`, écarts négatifs) : le client a préparé le calendrier du mois.

## 2. Ce que l'application fait déjà (vérifié dans le code)

- Modèles `production/models.py` : `ConsumableType`, `ConsumableStock` (stock par boulangerie et par type), `ConsumableMovement` (entrées/sorties, CUMP), `ConsumableCount` (comptage), `ConsumableInventory` (inventaire physique journalier avec écart signé), `ProductionSession.consumables_used` (consommation déclarée par fournée), `flour_sacks_used` (sacs de farine utilisés).
- Vues : `consumables/global/` (vue globale direction : stock par boulangerie et par type, dernier inventaire), `consumables/dispatch/` (envoi du stock direction vers les boulangeries), historique des achats de farine (§3.2b, `flour_history`, direction seulement ; **BUG-1101 : à clarifier avec le client, il est conservé pour l'instant**).
- Frontend : onglet **Intrants** de « Production & Stocks » (`IntrantsTab.tsx`, `GlobalConsumablesSection.tsx`, inventaire physique, approvisionnement direction).

## 3. Ce qui manque (écart application / fichier)

1. **Tableau statistique journalier par intrant** (feuilles FARINE, Levure, HUILE, SEL) : colonnes stock initial → solde comptable → reste déclaré → écart, pour toutes les boulangeries d'un jour, avec la ligne **D1 (direction)** et la ligne **TOTAUX**. L'application a les données (mouvements, consommation déclarée, inventaire) mais pas cette vue consolidée par jour.
2. **Indice de consommation** : consommation de l'intrant ÷ sacs de farine utilisés le même jour (« référence production »), par boulangerie, avec la moyenne du groupe. Il n'existe nulle part dans le code (aucun champ ni calcul).
3. **Statistiques mensuelles de la farine** (feuille ENTREE FARINE) : consommation par boulangerie et par jour, achats avec prix unitaire et prix total, solde courant, total, écart du mois, moyenne par jour. L'historique des achats de farine existant n'en couvre que la partie « achats ».
4. **Export Excel** de ces tableaux au format du client (le client travaille ses statistiques sous Excel).

## 4. Points douteux ou ambigus à poser au client (aucun code tant que non tranché)

1. **D1** : confirmer que la ligne « D1 » est le **stock de la direction** (nœud SIEGE) avec ses sorties = envois aux boulangeries.
2. **Indice de consommation** : confirmer la définition (consommation du jour ÷ sacs de farine du jour) et s'il y a un **seuil d'alerte** (une boulangerie qui dépasse la moyenne du groupe ?). Le client a une colonne « ok » dans SEL : que signifie-t-elle (écart toléré ? seuil ?).
3. **SEL** : l'application compte le sel en **grammes** ; le fichier compte des **sacs** avec une conversion `Bte/U` (≈ 204 boîtes ou unités par sac ?) et un reste en sacs ET en boîtes. Quelle est l'unité de saisie voulue ?
4. **HUILE** : la formule `initial + entrée × sortie` (au lieu de `+ entrée − sortie`) semble une **erreur du tableur** : confirmer que le logiciel doit faire `initial + entrée − sortie`.
5. **ENTREE FARINE** : la colonne **vente** (farine revendue ?), le solde de départ **codé en dur** (`273,18 − total + 1`) et la ligne « accroissement » : que représentent-ils exactement ?
6. **Écart** : confirmer le signe (reste déclaré **moins** solde comptable) et la règle quand le reste n'est pas déclaré (le tableur affiche l'opposé du solde comptable : −26,8 ; le logiciel doit-il laisser l'écart vide ?).
7. **Qui voit ces statistiques** : la direction seule, ou aussi le gérant de chaque boulangerie pour la sienne ?

## 5. Décision de répartition (dev-b, à valider par dev-a)

Principe : dev-a est propriétaire de `production/` et de l'onglet Intrants ; dev-b prend la partie qui s'y greffe sans toucher aux mêmes fichiers (nouveaux fichiers, URLs distinctes), car dev-b dispose du moteur de synchronisation et de l'export.

| Lot | Contenu | Propriétaire | Fichiers principaux |
|---|---|---|---|
| **I-1** | Endpoint de statistiques **journalières** par intrant (FARINE, Levure, HUILE, SEL) : toutes les boulangeries d'un jour, ligne D1 (direction), ligne TOTAUX, solde comptable, reste déclaré, écart, **indice de consommation** ; rôles : direction/admin/comptable, gérant pour sa boulangerie | **dev-a** | `production/` (nouveau module `production/intrants_stats.py`), `production/urls.py` |
| **I-2** | Onglet **« Statistiques »** dans « Production & Stocks › Intrants » (tableaux par intrant, sélecteur de date, 360 px) | **dev-a** | `frontend/src/components/production/` (nouveau composant), `IntrantsTab.tsx` (ajout minimal) |
| **I-3** | Statistiques **mensuelles de la farine** (feuille ENTREE FARINE) : consommation par boulangerie et par jour, total, achats avec PU/PT, solde courant, total et écart du mois, moyenne par jour ; réutilise `flour_history` sans le modifier | **dev-b** | nouveau module `production/flour_month_stats.py` (+ URL distincte), composant `FlourMonthStats.tsx` |
| **I-4** | **Export Excel** au format du client (openpyxl côté serveur, une feuille par intrant + la feuille mensuelle de la farine) ; bouton dans l'onglet | **dev-b** | `production/intrants_export.py`, appel via `src/api/services.ts` |
| **I-5** | **Disponibilité sur les postes locaux** : vérifier que les données nécessaires (consommation déclarée, inventaires, mouvements, stock direction) sont bien synchronisées pour que les statistiques d'un poste soient justes hors ligne ; ticket si une donnée manque ; recoupement des calculs avec le fichier du client sur des **valeurs fictives** (jamais copier le fichier dans les tests) | **dev-b** | `sync/`, tests |

Ordre : I-1 d'abord (dev-a) car I-3 et I-4 réutilisent son calcul de solde, d'indice et d'écart : dev-b démarre I-3 et I-5 en parallèle sur ses propres fichiers et I-4 quand I-1 est poussé. Les lots attendent la réponse du client aux points 3, 4 et 6 du §4 pour tout ce qui concerne le sel, l'huile et le signe de l'écart : coder la farine et la levure d'abord.

## 6. Règles (rappel)

Numéros de tickets : dev-a `BUG-1000+`, dev-b `BUG-1100+` (un ticket par lot : dev-a ouvre ceux de I-1 et I-2 dans sa plage ; dev-b ouvre `BUG-1110` à `BUG-1112` pour I-3 à I-5). Éditions ciblées du registre. Un développeur ne vérifie pas son propre correctif. Données réelles du client : ne jamais les copier dans des fixtures. Hors périmètre : desktop et documentation de livraison.
