# Plan de répartition selon les réponses du client (2026-11-23)

Auteur : dev-a. Source : `reponses-clients.md` (réponses de M. NDUNGA NSAYI PIERRE). Complète `docs/PLAN_REPRISE_DEV_A_ET_DEV_B_2026-11-23.md` et `docs/PLAN_TESTS_CORRECTIONS_A_B_C.md` (méthode et règles inchangées). En cas de contradiction avec un autre document : `remarque.md` > `adaptes.md` > `cadre_comptable.md` > `cahierDesCharges.md` ; toute contradiction se signale dans `docs/COMMUNICATION_A_B.md`, on ne tranche pas seul.

## 1. Ce que le client a répondu

| Réf. | Question | Réponse | Statut |
|---|---|---|---|
| Q1 | Ligne de paiement négatif (client n° 54, K3, 13/08) | « en attente » | **à poser de nouveau** |
| Q2 | Carte client : comment se calcule-t-elle ? | **B** : un montant fixe **par client et par mois** (« 1 000 FC ? » : le point d'interrogation est du client) | **ferme**, montant à confirmer |
| Q3 | Derniers jours de juillet (K3, K4, K5, B1) | « en attente » | **à poser de nouveau** |
| Q-022 (BUG-266) | Manque quand la commission ne couvre pas les retenues | aucune ligne « Réponse » : le « A. Reporter le manque » est l'option proposée | **sans réponse** |
| Q-023 (BUG-267) | L'épargne s'ajoute-t-elle à la commission ? | « à confirmer » | **sans réponse ferme** |
| Q-024 (BUG-268) | Une dette peut-elle être comptée deux fois ? | « à confirmer » | **sans réponse ferme** |
| Q-025 (BUG-507) | Le livreur voit-il les clients des autres boulangeries ? | **Oui, comme le facturier, seulement s'il y a connexion, c'est-à-dire s'il est en ligne sur etskiese.com** | **ferme** |
| Q-026 | Valeurs propres à chaque boulangerie | **Cotisation Sociale, Taux de Commission, Valeur Théorique par Sac de Farine, Carte, Heure de clôture** | **ferme** |
| Q-027 (BUG-411, BUG-253) | Écrans du livreur | **Les mêmes que le facturier** | **ferme** |

Toujours sans réponse du client (ne rien coder) : Q-017 à Q-021 (rotation 24 h, BUG-161/278), Q-028 (tarif figé, BUG-513/518/520), Q-043 (valorisation des invendus/déclassés/gratuits dans le total du jour, BUG-1200), BUG-625, 671, 1002, 1101, BUG-083 contre BUG-988 (vente sur une clôture confirmée), BUG-1202 (restes des équipes A et B hors rotation : somme ou dernier instantané ?).

## 2. État du code vérifié le 2026-11-23

- `Node` (`core/models.py` l.113-190) porte déjà : `sac_value_fc` (valeur du sac), `monthly_social_contribution` (cotisation, défaut 2 000 FC), `card_fee_fc` (carte, défaut 1 000 FC), `handover_time` (heure de clôture) et `block_sales_after_closure` (BUG-973).
- **Le taux de commission n'est pas sur `Node`** : il existe `Config.default_commission_rate` (global, défaut 0,25, `core/models.py` l.416), `Client.commission_rate` (par client, défaut 0,25, `clients/models.py` l.112) et `CommissionPeriod.commission_rate` (copie figée par période). Le client veut un taux **par boulangerie**.
- `core/permissions.py` : `IsLivreur` (LIVREUR et au-dessus) et `IsFacturierOrLivreur` existent ; la recherche de clients inter-boulangeries est ouverte au facturier (`clients/views.py`, règle CLAUDE.md §5.1).

## 3. Tâches de dev-b (clients, commissions, core, sync, chat, frontend de ces pages)

Ordre conseillé : B-1, B-2, B-3, B-4, puis les cycles de tests de sa partie.

**B-1. Taux de commission par boulangerie (Q-026, ferme).**
- Ajouter `Node.default_commission_rate` (Decimal 4,2, **nullable** : vide = reprendre `Config.default_commission_rate`), migration dans `core/` avec **migration de données** (copier la valeur actuelle de `Config` dans chaque boulangerie existante), champ dans la fiche boulangerie (`Nodes.tsx`, réservé direction/admin).
- Lire ce taux comme **valeur par défaut d'un nouveau client** de la boulangerie (`clients/`), sans écraser `Client.commission_rate` déjà saisi (le taux client reste une exception explicite : 0,25 ou 0,30). Les types de vente (VENTE SOLDE / CASH = CM 0) ne changent pas.
- Les périodes déjà générées gardent leur taux figé (`CommissionPeriod.commission_rate`).
- Tests : défaut à la création, repli sur `Config`, client existant non modifié, période figée, isolation (un gérant ne modifie pas le taux d'une autre boulangerie).

**B-2. Carte : un montant fixe par client et par mois (Q2, ferme ; montant à confirmer).**
- Relire BUG-417 (`Node.card_fee_fc`) : le client parle d'un montant **par client et par mois**. Vérifier dans `commissions/` que la retenue « Carte » est appliquée **une seule fois par client et par mois** (pas par facture, pas deux fois entre `deduction_carte` et la carte en FC) et que la colonne affichée dans « Situation des Ristournes & Rémunérations » correspond.
- Le montant 1 000 FC reste le défaut, modifiable par boulangerie (Q-026). À confirmer avec le client : « 1 000 FC ? ».

**B-3. Le livreur voit les clients des autres boulangeries seulement en ligne (Q-025 / BUG-507, ferme).**
- Règle : le facturier garde la recherche inter-boulangeries actuelle ; le **livreur** y a accès **seulement quand le poste est connecté au cloud (en ligne sur etskiese.com)** ; hors ligne, il ne voit que les clients de sa boulangerie.
- Côté `clients/` (queryset du livreur) et `sync/` (état de connexion du nœud) et frontend Clients : définir comment l'« en ligne » est établi (dernier échange de synchronisation réussi récent, ou accès direct au cloud), le documenter dans le message de fin, et prévoir le comportement d'erreur (message français, pas de 500).
- Test : livreur en ligne voit K2 ; livreur hors ligne ne le voit pas ; facturier inchangé ; autre rôle inchangé ; isolation des autres écrans.
- Si A doit exposer un indicateur côté ventes, B ouvre un ticket et A le fait.

**B-4. Le livreur a les mêmes écrans que le facturier (Q-027 / BUG-411, BUG-253, ferme) : partie frontend et permissions de B.**
- `DashboardLayout.tsx` et routes (`isAllowed`) : menus et routes du livreur = ceux du facturier ; vérifier que le livreur n'accède à rien de plus (commissions, clôture, caisse restent fermés).
- Fermer BUG-411 (routes sans contrôle d'accès) et BUG-253 selon cette règle.

**B-5. Reste de sa partie.** Cycles test, correction, re-test sur clients, commissions, core, sync, chat jusqu'à deux cycles sans nouveau ticket ; BUG-1006 (clôture × synchronisation) ; vérification visuelle des trois thèmes de « Historique du client » (correctif de dev-a, `ClientHistoryModal.tsx`, remarque.md l.507) ; intégration (fusion des branches, série complète, `docs/PR_dev-c_vers_main.md`).

## 4. Tâches de dev-a (production, ventes, trésorerie, blockchain, finance, e2e, rendu navigateur)

**A-1. Le livreur = le facturier côté ventes et production (Q-027).** Contrôler dans `sales/` et `production/` (permissions et `get_queryset`) que `IsFacturierOrLivreur` couvre **toutes** les routes de facturation et de livraison du facturier (création de facture, remboursement, ajustement, livraison, non servi, annulation), avec l'isolation par boulangerie inchangée ; écrire les tests ; corriger l'écart éventuel. Contrôle visuel du menu et de `Sales.tsx` avec un compte livreur (après B-4).

**A-2. Lecture du taux de commission par boulangerie (Q-026), après B-1.** Vérifier que facturation, reçu thermique et clôture lisent le taux du client (inchangé) et que le défaut de la boulangerie apparaît bien à la création d'un client ; tests de non-régression ventes (BP, plafond 50 000 FC, vente solde/cash CM 0).

**A-3. Valeur du sac et heure de clôture par boulangerie (Q-026).** Déjà portées par `Node` : vérifier de bout en bout (production : écart manquant/excédent avec la valeur du sac de CETTE boulangerie ; clôture : `handover_time` propre à chaque boulangerie, blocage des ventes BUG-973) ; contrôle visuel de la modale de clôture et de la bannière avec des données (jamais vérifié à l'écran).

**A-4. Clôture et contrôle global.**
- Relancer l'e2e (`--repeat-each=5`, bureau et 360 px) sur un poste avec navigateur : le premier essai a été coupé par le réseau ; **ne jamais commiter `docs/qa/captures/*.png`** (c'est ce qui bloquait le push, erreur 408).
- `testeur-charge` (pics du matin, 8 boulangeries) ; rendu à 1440 px ; BUG-655 et 656 à faire passer VÉRIFIÉ par un testeur autre que le développeur.
- Deux tests de production à reclasser : `test_bornes_farine_sur_fournee_existante` (accepte `1e2`) et `test_just_above_boundaries_refused` (accepte `-0.001`) : dire s'ils échouaient avant la fusion de `dev-b` ; si c'est le parseur numérique partagé de B (`core/numeric.py`, BUG-1015 à 1019), aligner le test sur la règle voulue, sans l'affaiblir.
- Question à poser au client : BUG-1202, BUG-1200 (Q-043), BUG-083/988, BUG-625, 671, 1002, 1101.
- Écrire « partie A terminée » dans `docs/COMMUNICATION_A_B.md` quand les critères du plan de reprise (§0) sont remplis.

## 5. Règles communes (rappel)

1. **Propriété** : dev-a = `production/ sales/ treasury/ blockchain/ finance/ e2e/` ; dev-b = `core/ clients/ commissions/ sync/ chat/ kiese/`. Une demande dans le module de l'autre = ticket ou message dans `COMMUNICATION_A_B.md`, pas de modification directe (exception signalée : une ligne dans `ClientHistoryModal.tsx`).
2. **Tickets** : dev-a `BUG-1000+` (déjà pris : 1000 à 1002, 1200 à 1202, 1300+ réservé e2e), dev-b `BUG-1100+`. Relire le registre avant d'écrire un numéro ; **éditions ciblées** du registre, jamais de réécriture.
3. **Un développeur ne vérifie pas son propre correctif** ; chaque correction a un test qui échouait avant. `[]` → `[c]` dans `remarque.md` seulement après vérification indépendante.
4. **Git** : `git fetch origin && git merge origin/dev-<autre>` avant chaque série et chaque push ; on ne pousse que sa branche ; pas de `--force` ; ne jamais ajouter `docs/qa/captures/*.png`, `.env`, `*.sqlite3`, `node_modules`, `dist` (ajouter les fichiers par chemin plutôt que `git add docs`) ; en cas d'erreur 408 au push, regarder `git diff --stat origin/<branche>..HEAD` : un commit trop gros contient presque toujours des captures.
5. **Tests** : sans `--parallel`, `DB_NAME` isolé (jamais `backend/db.sqlite3`), longues séries en arrière-plan, un seul processus lourd à la fois (les tests de concurrence SQLite échouent sous charge).
6. **Hors périmètre** (ordre du responsable) : desktop (Electron, installeur) et documentation de livraison.
