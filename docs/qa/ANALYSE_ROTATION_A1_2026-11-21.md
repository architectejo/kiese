# Analyse A1 - Rotation d'équipes 24 h et boîte « Stock de départ » (2026-11-21)

Auteur : coordinateur (analyse seule, aucun code applicatif modifié). Branche dev-a.
Sources lues : remarque.md l.437, 460, 464, 468 ; docs/PLAN_DEUX_DEVELOPPEURS.md (A1) ; BUG-161 et BUG-278 (registre) ; `backend/core/workday.py` ; `backend/production/views.py` (`DailyOpeningConfirmationView`, `shift_end_status`, `_handover_shift_end_response`, `TeamAssignmentView`) ; `OpeningStockConfirmationModal.tsx` ; montage dans `DashboardLayout.tsx` (l.1134).

## 1. Ce qui existe déjà

BUG-161 est la rotation (reste OUVERT comme chantier parent) ; BUG-278 est VÉRIFIÉ (redésignation de la même équipe).

Boîte « Stock de départ » (livrée : BUG-133 à 141, 161 B4/F2, 188, 247, 272, 281, 317, 330) :
- Qui la voit : GERANT ou FACTURIER rattaché à une boulangerie (pas les rôles siège / `can_access_all_nodes`). Montée une seule fois dans `DashboardLayout`.
- Quand elle s'ouvre : au montage, à chaque changement de page (`routeKey`) et, en rotation, à chaque tick du sondage de 10 s (`pollKey`), sans rechargement. « Plus tard » ne ferme que jusqu'à la page suivante : elle revient donc à chaque page tant que non confirmée.
- Déclencheur par heure de relève (nœud avec `Node.team_rotation_enabled = True`) : `needs_confirmation = équipe désignée existe ET aucune confirmation du nœud depuis le début de la période de service` (`shift_period_start` = dernière relève). Au passage de l'heure : (1) reste du jour de l'équipe sortante (boîte forcée BUG-156, ou clôture forcée après 30 min de grâce, `SHIFT_END_GRACE_MINUTES`), (2) désignation de l'équipe entrante, (3) boîte « Stock de départ de la relève », proposition = dernier reste déclaré, jamais négatif. L'ordre est garanti par `suspended` (saisies conservées).
- Par équipe : en rotation, une seule équipe de service (la désignée), plus de choix A/B, une confirmation par période. Hors rotation : choix A/B, une confirmation par jour pour l'équipe du créneau d'ouverture (`Node.opening_team()`).
- Par nœud : tout est filtré sur le nœud de l'utilisateur ; heure = `Node.handover_time` (défaut 12:00, libellé « Heure de relève des équipes » dans Nodes.tsx).
- La date de travail reste le jour calendaire (décision 2026-11-12) ; la période de service court de relève à relève.

## 1 bis. Ce qui manque par rapport à la remarque

Le mécanisme de la boîte aux heures de relève existe de bout en bout. Les écarts réels :
1. Activation : `team_rotation_enabled` est faux par défaut et n'est activé nulle part (seed et base). Tant que le drapeau est faux, la boîte ne s'ouvre qu'une fois par jour (équipe du premier créneau, 06:00), jamais à 12:00 ni à 14:30 pour l'équipe suivante (la section manuelle de Production & Stocks existe mais n'est pas une ouverture automatique). C'est l'explication la plus probable de la remarque.
2. Aucun test d'horloge ni E2E du scénario « boulangerie en rotation, passage de l'heure de relève, boîte visible » ; seule la variante « (changer) » a été jouée (réserve du testeur-production, vague 4).
3. Libellé : le client écrit « Stock de départ du jour » et dit que « Heure de relève » est en réalité « heure de clôture » ; l'application dit « Stock de départ de la relève » et « Heure de relève des équipes ».
4. Personne connecté à l'heure dite : la boîte apparaît à la connexion suivante (pas de notification serveur). À confirmer (Q-021).
5. Redésignation après confirmation dans la même période : la confirmation de l'équipe précédente couvre toute la période (`any(confirmed)`), l'équipe corrigée n'est pas re-sollicitée. Mineur.
6. Hors périmètre de cette boîte (autres remarques, conception A1) : calcul automatique des restes à l'heure, boîte de confirmation de clôture complétée (nature de sortie §3.4), blocage de la facturation après l'heure jusqu'au « Versement » validé par la direction, « Versement » visible de la direction. Rien de cela n'existe : la clôture forcée utilise le stock physique après 30 min de grâce et le blocage des ventes ne repose que sur l'absence de désignation d'équipe.

## 2. Plus petit lot pour que la boîte apparaisse aux heures de rotation

Sans toucher à la clôture automatique ni au blocage des ventes :
- Backend (aucune migration) : aucun changement de logique pour les nœuds en rotation. Ajouter l'activation de `team_rotation_enabled` et le réglage de `handover_time` par boulangerie (seed ou Configuration). Pour un nœud NON en rotation, si le client veut la boîte au début du créneau B, étendre `needs_confirmation` à « équipe du créneau actif sans confirmation du jour » ; probablement inutile si la rotation est activée partout (Q-017).
- Frontend : libellé seulement (« Stock de départ du jour » ou conserver « de la relève », au choix du client). Aucun nouveau composant, `DashboardLayout` inchangé.
- Tests : un test backend d'horloge simulée (juste avant puis juste après la relève, rotation active : `needs_confirmation` faux puis vrai après désignation) et un parcours E2E Playwright (`page.clock`) bureau et 360 px.
- Attention : `frontend/src/components/production/BatchInProgressPanel.tsx` et `sacksIncrement.ts` sont en cours de modification dans l'arbre de travail ; ne pas les toucher en parallèle.

## 3. Contradictions et questions

adaptes.md, cadre_comptable.md et cahierDesCharges.md ne disent rien de la rotation, des heures de relève ni du stock de départ : pas de contradiction à ce niveau, remarque.md prime. Contradictions internes à remarque.md et au code :
- C1 (remarque l.391-393 vs l.468) : créneaux fixes A 06:00-11:30 / B 14:30-20:00 (base remise à zéro le 2026-11-10 avec ces horaires) contre rotation de 24 h à relève unique. Le code gère les deux (drapeau).
- C2 (l.464 vs l.429 et décision 2026-11-12) : « restes du jour = stock de départ demain » avec clôture à l'heure de relève (ex. 12:00), contre « reste d'hier et reste du jour ne dépendent pas des équipes, pris pour le jour » avec un seul rapport et une seule clôture de caisse par jour calendaire. Une clôture à 12:00 fait aller le « jour » commercial de midi à midi, ce qui contredit minuit-minuit.
- C3 (l.464) : blocage des ventes jusqu'à validation du « Versement » par la direction ; aujourd'hui la direction valide des clôtures par date calendaire. Avec deux relèves, quel versement débloque quoi ?
- C4 (l.464) : « Heure de relève = heure de clôture » fusionne deux notions que le code sépare (période de service vs jour calendaire).
- C5 : cadre_comptable.md ne connaît pas de clôture intra-journalière.

Questions client (langage simple), ajoutées à `docs/qa/QUESTIONS_CLIENT.md` (Q-017 à Q-021) :
1. Q-017 : toutes les boulangeries passent-elles en rotation de 24 h maintenant, et à quelle heure l'équipe change-t-elle (12h00 partout ?). Sans cela la boîte ne s'ouvre qu'une fois le matin.
2. Q-018 : quand l'équipe change à midi, la « journée » (clôture, rapport, versement) va-t-elle de minuit à minuit ou de midi à midi ?
3. Q-019 : à l'heure de clôture, bloquer la facturation tout de suite ou après un délai (30 minutes aujourd'hui) ?
4. Q-020 : qui peut débloquer les ventes en validant le « Versement » (direction seule, ou aussi le comptable) et quel versement débloque (celui de la relève ou du jour entier) ?
5. Q-021 : si personne n'est connecté à l'heure de relève, la boîte s'affiche à la connexion suivante (actuel) ; faut-il aussi avertir la direction ?

## 4. Découpage de A1 en 5 lots

| Lot | Contenu | Ticket | Effort | Dépend de |
|---|---|---|---|---|
| L1 | Boîte « Stock de départ » à l'heure de relève : activation rotation par boulangerie (seed/Configuration), libellé, test d'horloge + E2E 360 px/bureau | BUG-350 | 0,5 j + 0,5 j E2E | Q-017 ; vérification par testeur-production |
| L2 | Conception de la clôture à la relève (heure de relève = heure de clôture, jour calendaire vs période, versement par période) : document d'architecture, validation humaine avant code | BUG-351 (à ouvrir) | 1 j | Q-018, Q-020 ; arrêt pour validation |
| L3 | Clôture automatique à la relève + boîte de confirmation (nature de sortie §3.4), reste du jour = stock de départ suivant | BUG-352 (à ouvrir) | 2 à 3 j (backend 1,5 ; frontend 1) | L2, Q-019 |
| L4 | Blocage de la facturation après l'heure jusqu'à validation du Versement par la direction ; « Versement » visible de la direction (remarque l.456) | BUG-353 (à ouvrir) | 2 j | L2, L3, Q-020 |
| L5 | Vérification et fermeture : testeur-production (BUG-161 -> VÉRIFIÉ), E2E global rotation, retrait des champs legacy `team_*_time` (B6) seulement après validation | BUG-354 (à ouvrir) | 1,5 j | L1 à L4 |

L1 est indépendant et livrable tout de suite ; L2 à L4 attendent les réponses client.

## Recommandation

Livrer L1 maintenant (la boîte existe et fonctionne en rotation : il faut l'activer, la tester à l'heure réelle et fixer le libellé), poser Q-017 à Q-021, et ne démarrer L3/L4 qu'après validation de la conception L2 (conflit entre jour calendaire et clôture à la relève, C2/C3).
