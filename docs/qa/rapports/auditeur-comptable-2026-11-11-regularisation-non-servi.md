# Audit comptable — colonnes « Régularisation » et « Non Servi » (Clôture Journalière, BUG-177)

Auditeur : auditeur-comptable — 2026-11-11. Lecture et rapport uniquement : aucun code applicatif modifié, statut de BUG-177 inchangé (OUVERT).

Sources : classeurs d'août 2026 (`DOC 1-2-x … FACTURATION` K2 et K5, `DOC 01`, `DOC 1 RAPPORT CLOTURE PAR GERANT`), `EXTRAIT RAPPORT DE CLOTUREOCTOBRE 2026.xlsx` (feuille `K6`), `adaptes.md` [1.2], code `production/views.py::_build_daily_closure_report` (l.1546-1785), `sales/views.py` (`create` l.295-500, `cleanup_expired` l.785), `sales/models.py`. Aucune donnée nominative reprise : références de cellules, libellés de rubriques, agrégats.

## 1. Ce que contiennent réellement les rubriques dans les classeurs

Il existe DEUX endroits distincts, qu'il ne faut pas confondre.

### 1.a Rubriques `NON SERVI/S` et `REGULARISATION` du bloc de clôture (`K6!C12`, `K6!C13`)
- Structure identique aux lignes 8-19 : quantités par catégorie (D=200, F=300, H=500, J=1000), valeur `L = D*E + F*G + H*I + J*K` (`K6!L12`, `K6!L13`), prix pleins du barème 200/300/500/1000, `M`=25 (colonne CM recopiée, sans effet sur le total). Unité : pains saisis par catégorie, valeur en FC. Pas de paiement (`O` vide).
- Exemple chiffré : `K6!H13`=40 pains de 500 et `K6!J13`=20 pains de 1000 -> `K6!L13` = 40 000 FC (positif). `K6!L12` = 0 (rien de non servi ce jour-là).
- Entrée dans le total : `K6!L21 = SUM(L8:L20)` (FACTURE MVM INTERNE), puis `TOTAL DU JOUR = S/TOTAL AB CARTE + L21` (`K6!L132 = L128 + L21`). Les deux rubriques sont donc ajoutées avec leur signe. Dans cet extrait, le détail jour par jour qui alimente ces deux lignes n'est pas présent (valeurs saisies à la main).

### 1.b Lignes codées `NS` et `RG` dans les feuilles FACTURATION (source probable de 1.a)
Chaque jour se termine par deux lignes fixes dans la liste clients : code `NS` puis code `RG` (K5 : `D02-01- FACTURATION!B167` / `B168`, puis +204 lignes par jour : `B371`/`B372`, `B575`/`B576`… ; K2 : `B81`/`B82`, `B200`/`B201`…). Elles sont comptées 15 à 36 fois par feuille (une paire par jour).
- Ligne `NS` : libellé `TOUS` (K5) ou `NON SERVI` (K2 `C81`) ; quantités NÉGATIVES, saisies sur la grille « solde » 150/225/375/750 (K5 `J1769`=-5 -> `L1769` = -3 750 ; K5 `H2760`=-9 -> `L2760` = -3 375 ; K2 `H320`=-6 -> `L320` = -2 250 ; K2 `H1037`=-10, `J1037`=-1 -> `L1037` = -4 500). CM = 0 (`M`=0), paiement vide, dette (`P`) vide. Nulle la plupart des jours.
- Ligne `RG` : libellé `REG du <date>` (K5 `C168`) ou `REGUL DU 3/4` (K2 `C82`) ; quantités POSITIVES, même grille, CM = 0. C'est la livraison tardive des pains non servis un jour antérieur : K5 `J1769`=-5 (NS) est compensé par `J1967`=+5 (RG, `L1967` = +3 750) ; K5 `H2760`=-9 compensé par `H2960`=+9 ; K2 `H320`=-6 compensé par `H559`=+6.
- Agrégats : K5 sur le mois, somme NS = -7 125 FC, somme RG = +7 125 FC (net 0). K2 : somme NS = -9 750 FC, somme RG = +2 250 FC au moins (certaines régularisations tombent après la fin du mois : net temporaire négatif).
- Ces lignes sont dans le même tableau que les clients, donc dans la somme du jour (`FACTURE` du jour) avec leur signe. Elles ne passent pas par une facture client : aucune dette (`P` vide), aucun paiement.

### Conclusion du point 1
- NON SERVI/S = quantité NÉGATIVE de pains commandés mais non servis (boulangerie fermée / rupture), valorisée en FC, CM 0, sans dette ni paiement : elle RETIRE du total du jour ce qui avait été compté.
- REGULARISATION = quantité POSITIVE de pains livrés plus tard en rattrapage d'un jour NS (`REG du <date>`), CM 0 : elle RÉINTRODUIT dans le total du jour ce qui avait été retiré.
- Le classeur ne contient PAS de notion de « correction de commande » (BUG-097, factures d'AJUSTEMENT) : une correction s'y fait en modifiant la ligne du client.
- Point à faire confirmer (Q-008) : prix de valorisation des lignes NS/RG (grille solde 75 % en FACTURATION, prix plein dans le bloc de clôture `K6!E12:K13`).

## 2. Les factures `RG` tombent-elles dans FACTURE/JR ?

Oui. `normal_invoices` (`production/views.py` l.1554-1556) = `base_invoices.filter(is_adjustment=False, is_soldee=False).exclude(special_code=NS).exclude(special_code__in=node_codes)`. Seuls NS et les codes boulangerie sont exclus : `RG` (et `NV`) restent dans FACTURE/JR ; `normal_by_bp` les compte (quantité, FC, commission). La colonne « Régularisation » ne contient que les ajustements (`is_adjustment`, l.1589). Une facture `RG` est donc comptée dans la mauvaise rubrique ; aucun test ne la couvre (`SpecialCodesTests`, `sales/tests/test_invoices.py` l.450, vérifie seulement l'acceptation du code).

Définition correcte au regard du classeur : la rubrique REGULARISATION = codes `RG` (principal et seul présent dans le classeur). Les ajustements BUG-097 sont une notion propre à l'application, déjà exclus de FACTURE/JR : les laisser dans la colonne (décision client 2026-11-11) est cohérent (original dans FACTURE/JR + delta signé dans Régularisation = valeur corrigée). Recommandation : les DEUX, additionnés, mais en retirant les `RG` de FACTURE/JR pour éviter le double comptage. Les deux sources devraient être détaillables dans l'info-bulle.

## 3. Non Servi : unité, signe, entrée dans FACTURE MVM INTERNE, effets de l'application

Classeur : valeur en pains par catégorie ET en FC (`L = Σ quantité × prix`), signe NÉGATIF, CM 0, sans paiement ni dette ; entre dans `SUM(L8:L20)` donc réduit `FACTURE MVM INTERNE` puis `TOTAL DU JOUR`.

Application actuelle (`sales/views.py::create`) : une facture NS n'a aucun traitement spécial. Elle exige au moins une ligne (l.305-306), calcule `order_total` positif, DÉDUIT le stock (l.472-474), AJOUTE `order_total - payment_amount` à `Client.current_debt` si un client est fourni (l.476-485), est créée PENDING, et peut être bloquée par les contrôles de plafond. NON CONFORME au classeur : un « non servi » ne doit ni sortir de pains du stock ni créer de dette. Aggravant : `cleanup_expired` (l.785-814) supprime toute facture PENDING de plus de 12 h, y compris NS (BUG-177 point 2). Les facture NS PENDING ne sont pas non plus livrables sans effet de bord (`deliver` incrémenterait `total_breads_received`).
Côté rapport : un NS livré compterait positivement dans `non_servi_fc` -> `mvm_interne_fc` : signe inverse du classeur (voir recommandation).

## 4. Recommandation chiffrée pour BUG-177 (dev-backend)

Notation : `Σ_NS` = somme des `order_total` des factures NS du jour/nœud ; `Σ_RG` = idem pour les RG ; `Σ_ADJ` = somme signée des ajustements (inchangée).

### 4.1 Filtres
- NS : `Invoice.objects.filter(node=node, invoice_date=report_date, special_code='NS', is_debt_repayment=False).exclude(status=CANCELLED)` (PENDING et DELIVERED inclus), ligne par ligne pour la quantité par catégorie.
- RG : `base_invoices.filter(special_code='RG', is_adjustment=False)` (DELIVERED, comme les ventes). Les retirer de `normal_invoices` : `.exclude(special_code__in=[NS, RG])`.
- NV reste dans FACTURE/JR (inchangé). Codes boulangerie : inchangé.

### 4.2 Unité et signe
- Colonne « Non Servi » : montant FC en valeur principale = `+Σ_NS` affichée en valeur absolue (décision client « somme des montants » respectée), quantité en information.
- Contribution aux totaux : `-Σ_NS` (convention classeur `K6!L12` négatif). Dans le payload : exposer `non_servi.fc` en positif et utiliser `-non_servi_fc` dans `mvm_interne_fc` (ou exposer `fc_signe`). Documenter l'option « montant négatif affiché » si le client préfère coller au classeur.
- Colonne « Régularisation » : `reg_fc = Σ_RG + Σ_ADJ_signé` (RG positif comme `K6!L13`).
- Formule : `mvm_interne_fc = reste_du_jour + reste_du_hier + appro_effectue + appro_recu - non_servi_fc + reg_fc + soldee + non_vendu + declasses` ; `total_du_jour_fc = total_facture_fc + total_mvm_interne_fc` (aucun changement de structure). Effet net d'une paire NS(J) puis RG(J+1) : -X le jour J, +X le jour J+1, total 0 sur la période (identique à K5 : -7 125 / +7 125).
- `total_breads_billed` : retirer les quantités NS, ajouter RG (la ligne 1778 additionne déjà `reg['qty']`).
- `ecart_facture_fc` (l.1792) : exclure NS (pas une commande) ; il filtre déjà DELIVERED seulement.

### 4.3 Exemption de `cleanup_expired`
Ajouter `.exclude(special_code='NS')` dans le queryset `expired` (l.790-795). Une NS PENDING n'a, après correction, ni dette ni stock à restituer. Autres vues à contrôler : `pending_deliveries` (file du livreur, NS non livrable) et tout compteur « en attente ».

### 4.4 Effet sur dette et stock (à implémenter dans `create`, avant `Invoice.objects.create`)
Pour `special_code='NS'` :
- aucun appel à `_adjust_bread_stock` (les pains n'ont jamais quitté la boulangerie) ;
- aucun `Client.current_debt` ni `DebtMovement` ; `debt_after = debt_before`, `payment_amount` forcé à 0 (rejet 400 s'il est > 0), `commission_rate = 0` ;
- aucun contrôle de plafond (le blocage ne s'applique pas à une non-vente) ;
- pas de statut DELIVERED ni appel à `deliver` : refuser `deliver` sur une NS (400) ou la marquer livrée sans incrémenter `total_breads_received` ; le plus simple est de la garder PENDING/exclue de la file livreur.
Garder au moins une ligne (indispensable pour la quantité par catégorie ; le rejet « au moins une ligne » reste valable).
Pour `RG` : facture normale (stock déduit, flux livraison), CM = 0 (`commission_exempt`), pas de nouvelle dette si elle rattrape une NS déjà couverte ; sinon (règle à confirmer, Q-008) dette normale.

### 4.5 Tests à écrire
(1) RG livrée : absente de `facture_jr`, présente dans `regularisation` ; (2) NS PENDING : présente dans `non_servi` ; (3) NS ne touche ni stock ni dette ; (4) `cleanup_expired` ne supprime pas la NS ; (5) paire NS(-X)/RG(+X) sur deux jours : `total_du_jour_fc` J = base - X, J+1 = base + X ; (6) ajustement + RG le même jour : somme dans `regularisation`.

## Écarts et incertitudes (aucun chiffre inventé)
- Valorisation : classeur = grille solde 75 % dans FACTURATION mais prix pleins dans le bloc de clôture. Recommandation provisoire : prix catalogue de l'app (comme le rapport de clôture), à valider (Q-008).
- Le classeur ne dit pas si la dette des clients, facturés ce jour-là puis « non servis », est annulée : la ligne NS est agrégée (`TOUS`), `P` est vide, donc elle ne touche pas la dette individuelle. D'où la recommandation 4.4 (aucun effet).
- L'extrait d'octobre ne contient pas de ligne client codée NS/RG ; l'analyse repose sur les feuilles d'août K2/K5 (les autres feuilles ont les mêmes lignes aux emplacements listés par le balayage : K1 `B152/B153`, K3 `B160/B161`, K4 `B144`, K6 `B144/B145`, B1 `B167/B168`, B2 `B46/B47`).
- Seules K2 et K5 ont été analysées en détail (valeurs) ; les autres feuilles non vérifiées au-delà de la présence des lignes.

Question client ajoutée : Q-008 (`docs/qa/QUESTIONS_CLIENT.md`).
