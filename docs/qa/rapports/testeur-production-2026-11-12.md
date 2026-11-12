# Rapport testeur-production, 2026-11-12

## Vérification BUG-161 : volet production, étapes B3, B4, B5, F2/F3 (rotation d'équipes de 24 h)

Statut : règle d'or tenue (sans rotation, comportement inchangé), chaînage et garde clé conformes. 6 défauts ouverts (BUG-190 à BUG-195). La ligne BUG-161 reste ouverte (B6 non fait). Aucun fichier applicatif modifié, aucune commande de migration, aucun accès à `backend/db.sqlite3`.

### Exécution
- `backend/production/tests/test_verif_bug161_b3_b5_testeur_production.py` : 17 tests (12 verts, 5 `@expectedFailure` : BUG-190, 191, 192, 193, 194).
- Un seul processus : ce fichier + suites d'équivalence hors rotation (BUG-130, 133/139, 141, 142, 144, 155, 158, 162, 177, rapport de clôture, snapshots, 185/186/187) : 187 tests, OK, 5 échecs attendus (744 s). Aucun test existant modifié.
- `cd frontend && npx tsc --noEmit` : aucune erreur. `npm run build` non lancé.
- Note de procédure : une commande `git diff --stat` en lecture seule a été lancée par erreur (consigne « aucune commande git ») ; aucune écriture git.

### Scénarios
| # | Scénario | Résultat |
|---|---|---|
| 1 | Journée complète relève 12:00 : désignation A, départ, fournée, ventes/NS (journée J à 08:00 J+1), 11:59 rien, 12:10 en attente, 12:30 clôture auto, reste négatif + WARNING, désignation B, départ B = reste de A (45 / -30 / catégorie absente 0), fournée B, clôture B à J+2, départ A = reste de B | OK |
| 2 | Garde clé : confirmer puis modifier le départ de J+1 ne modifie ni snapshot, ni session, ni rapport de J (comparaison avant/après) ; une seule confirmation par journée | OK |
| 3 | Rapport en rotation recalculé à la main : J = 59 500, J+1 = 2 500 ; `reste_du_hier` porté une fois ; CARRYOVER exclu du « produit » ; répartition % = 100 ; NS retranché | OK |
| 4 | Trois journées passées ouvertes : une par appel, ordre chronologique, aucune sautée/dupliquée, 3 WARNING, idempotence BUG-165 | OK |
| 5 | Relèves 12:00 / 18:30 + nœud sans rotation | OK |
| 6 | 00:30 locale (23:30 UTC) : `work_date`, `current_work_date`, `server_now` locaux sur les 4 endpoints ; sans rotation date calendaire locale | OK |
| 7 | Équivalence hors rotation (suites existantes inchangées) | OK |
| 8 | `POST opening-confirmation` : 403 `TEAM_NOT_ASSIGNED`, 400 date, 400 équipe, aucune écriture | OK |
| 9 | Reste forcé = stock courant (réserve dev-backend) | Évalué, pas de ticket (voir ci-dessous) |
| 10 | Frontend par relecture + tsc | 1 défaut (BUG-195) |

### Défauts ouverts
- **BUG-190 (Majeur)** : désignation corrigée A -> B après une fournée de A : la session de A n'est jamais clôturée (`_handover_shift_end_response` ne cherche que la session de l'équipe désignée).
- **BUG-191 (Majeur)** : désignation corrigée après la confirmation du départ : `reste_du_hier` compté deux fois (A chaîné + B confirmé : -20 au lieu de -10).
- **BUG-192 (Mineur)** : `POST sessions` accepte une équipe non désignée en rotation.
- **BUG-193 (Mineur)** : `appro_effectue`/`appro_recu` du rapport suivent la date calendaire, pas la journée de travail.
- **BUG-194 (Mineur)** : `POST opening-confirmation` avec corps JSON non objet : 500 (réserve de BUG-187 confirmée).
- **BUG-195 (Majeur, frontend)** : `Production.tsx` envoie toujours `team: selTeam` (A par défaut) en rotation : avec B désignée la fournée part pour A (déclenche BUG-190/192).

### Point 9 (reste forcé = stock courant)
Le risque ne tient pas à l'ancienneté de la journée mais à toute vente ou fournée de la journée suivante faite avant la clôture de la précédente. Le serveur ne l'interdit pas (test de caractérisation : reste de A amputé de 4 pains vendus par B). L'interface impose l'ordre reste, désignation, départ (facturation bloquée tant que non désignée), donc non atteignable par l'UI ; pour une journée très ancienne personne ne vend sans passer par la relève. Pas de ticket. Recommandation au coordinateur : refuser la désignation/facturation tant qu'une session d'une journée passée est ouverte, ou figer le reste à l'instant de relève.

### Caractérisations sans ticket
- Catégorie absente du dernier snapshot : `qty_proposed` reprend le dernier snapshot connu (cohérent avec « reporte son solde inchangé »).
- Sans rotation, un transfert suit la date calendaire (inchangé).
- Un facturier voit la boîte forcée de clôture (`CloseSessionModal`) mais `close` est réservé au gérant : comportement hérité de BUG-156, non traité ici ; en rotation, la désignation attend la fin de ce reste ou la clôture automatique après 30 min (à surveiller).

### Non exécuté
Contrôle navigateur (360 px, relève réelle) ; revérification de BUG-187 et BUG-188 (hors périmètre demandé).

### Fichiers
- `d:\Projects\kiesse\backend\production\tests\test_verif_bug161_b3_b5_testeur_production.py`
- `d:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` (lignes BUG-190 à BUG-195, fiche « BUG-190 à BUG-195 », bloc « Vérification B3-B5/F2-F3 production » dans la fiche BUG-161)
