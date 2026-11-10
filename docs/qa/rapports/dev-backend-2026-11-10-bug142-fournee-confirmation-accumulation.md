# Rapport dev-backend — 2026-11-10 — BUG-142 (fournée / confirmation du stock de départ)

## Contexte

Nouvelle exigence client ajoutée dans `remarque.md` juste après la ligne 394 :

> Lors de la confirmation de reste des pains, une fournée doit être créée pour l'équipe en
> question dans "Production & Stocks" pour l'équipe choisie et lors de la déclaration de fournée
> dans "Production & Stocks" les nombres des pains déclarés doit s'ajouter à la fournée selon
> l'équipe, en cas de plusieurs déclarations dans la journée on ne crée pas plusieurs fournées
> mais on ajoute à la fournée existante de la journée selon l'équipe.

Ticket ouvert : **BUG-142** (`docs/qa/REGISTRE_BUGS.md`, tableau de suivi + fiche détaillée en fin
de fichier). Un seul ticket pour les deux volets (A : accumulation des déclarations ; B : la
confirmation alimente la fournée) car ils partagent le même modèle de données
(`ProductionSessionLine`) et la même garde-fou (session clôturée).

## Résumé de la correction

1. **`ProductionSessionLine`** (`backend/production/models.py`) gagne un champ `source`
   (`DECLARED` par défaut / `CARRYOVER`), et `unique_together` passe de
   `[session, bread_price]` à `[session, bread_price, source]` — une catégorie de pain peut avoir
   une ligne « vraie déclaration » et une ligne « reste d'hier confirmé » sur la même session.
2. **`ProductionSession.compute_totals()`** : `total_fc_produced`/`theoretical_yield`/`yield_gap`
   (et donc l'alerte « Manquant de Rendement ») ne somment plus que les lignes `DECLARED`.
   `total_breads` et les champs legacy `breads_300/400/500/1000` restent sommés sur TOUTES les
   lignes (total réel de pains disponibles ce jour pour l'équipe).
3. **Cas A — accumulation** : `ProductionSessionViewSet.perform_create()` ne rejette plus une 2e
   déclaration le même jour/équipe (ancien 400 via `unique_together`) — elle incrémente les lignes
   `DECLARED` existantes (ou en crée si la catégorie est nouvelle) et additionne
   `flour_sacks_used`, sous verrou (`select_for_update()`). `sac_value_fc_used` (BUG-038) n'est
   jamais réécrit sur un ajout. Refus explicite (même message qu'avant) si la session est déjà
   clôturée.
4. **Cas B — confirmation alimente la fournée** : nouvelle fonction
   `_sync_carryover_session_lines()` appelée depuis `DailyOpeningConfirmationView.post()` (dans la
   même transaction atomique que l'ajustement BUG-136) — crée/complète la `ProductionSession` du
   jour avec des lignes `CARRYOVER` miroir de CETTE confirmation (remplacement complet à chaque
   soumission, comme la confirmation elle-même). N'appelle jamais `_adjust_bread_stock` (évite le
   double comptage avec l'ajustement `qty_adjusted` déjà fait une fois par BUG-136). Refuse si la
   session du jour est déjà clôturée, sans rien écrire (transaction annulée dans son ensemble).
5. Garde-fous croisés : `perform_update()` (édition d'une fournée) et
   `ProductionSessionSerializer.update()` ne touchent plus que les lignes `DECLARED` — jamais les
   lignes `CARRYOVER`, pour ne pas les effacer silencieusement à l'édition d'une fournée le même
   jour qu'une confirmation.
6. Correctif de cohérence découvert en cours de route (voir « Ambiguïté signalée » ci-dessous) :
   `_build_daily_closure_report()` filtre désormais `produced_by_bp` sur `source=DECLARED`, pour
   que le reste d'hier ne soit jamais compté deux fois dans ce rapport déjà vérifié (BUG-120).

## Fichiers modifiés

- `backend/production/models.py` — `ProductionSessionLine.source` (+ choix), `unique_together`
  élargi, `ProductionSession.compute_totals()` revu (exclusion CARRYOVER du rendement, somme
  legacy non écrasante).
- `backend/production/migrations/0021_bug142_production_line_source.py` — nouvelle migration
  (`default='DECLARED'`, rétro-compatible, aucune migration appliquée modifiée).
- `backend/production/serializers.py` :
  - `ProductionSessionLineSerializer` : nouveau champ `source` (lecture seule, additif).
  - `ProductionSessionSerializer.validate()` : ne bloque plus la soumission sur session existante
    (délégué à `perform_create()`).
  - `create()`/`update()` : tagguent/limitent aux lignes `DECLARED`.
- `backend/production/views.py` :
  - `ProductionSessionViewSet.perform_create()` réécrite (cas A, verrou + accumulation).
  - `ProductionSessionViewSet.perform_update()` : snapshot/réajustement `BreadStock` restreints aux
    lignes `DECLARED`.
  - Nouvelle fonction `_sync_carryover_session_lines()` (cas B).
  - `DailyOpeningConfirmationView.post()` : appelle la fonction ci-dessus, log_activity dédié.
  - `_build_daily_closure_report()` : `produced_by_bp` filtré sur `source=DECLARED`.
- `backend/sync/services.py` (`_push_production_session_line`) : propage le nouveau champ `source`
  lors de la synchronisation inter-nœuds (sinon le défaut `DECLARED` s'applique, rétro-compatible
  avec un nœud distant pas encore mis à jour).
- `backend/production/tests/test_bug142_fournee_carryover_accumulation.py` — nouveau fichier, 13
  tests (tous créés verts après correctif, pas de `@expectedFailure` préexistant puisque le
  comportement n'existait pas avant ce ticket) :
  - accumulation de 2 déclarations le même jour/équipe (catégorie existante + nouvelle catégorie) ;
  - `sac_value_fc_used` figé malgré un changement de `Node.sac_value_fc` entre deux déclarations ;
  - `BreadStock` incrémenté sans double comptage sur accumulation ;
  - équipes différentes le même jour = sessions séparées ;
  - refus (400) d'une déclaration supplémentaire sur session clôturée ;
  - confirmation seule crée la session avec ligne CARRYOVER ;
  - session 100 % carryover : aucune fausse alerte de rendement (`yield_gap == 0`) ;
  - resoumission de confirmation remplace (pas additif) la ligne CARRYOVER ;
  - confirmation puis vraie fournée / vraie fournée puis confirmation (les deux ordres) : une
    seule session, `total_breads` = carryover + déclaré, `total_fc_produced`/`yield_gap` =
    déclaré seul ;
  - absence de double comptage sur `BreadStock.qty_available` dans le scénario confirmation +
    déclaration ;
  - refus (400) d'une confirmation sur session déjà clôturée, sans écriture partielle.
- `docs/qa/REGISTRE_BUGS.md` — ligne BUG-142 ajoutée au tableau de suivi (statut `CORRIGÉ`) + fiche
  détaillée en fin de fichier.

## Tests de non-régression

- `backend/.venv/Scripts/python.exe manage.py test production.tests.test_bug142_fournee_carryover_accumulation`
  → **13/13 OK**.
- `backend/.venv/Scripts/python.exe manage.py test production sales finance` → **225/225 OK**
  (exécuté deux fois, résultat identique).
- `backend/.venv/Scripts/python.exe manage.py test sync production.tests.test_bug142_fournee_carryover_accumulation`
  → **70/70 OK** (vérifie le correctif dans `sync/services.py`).
- `backend/.venv/Scripts/python.exe manage.py test` (suite complète, tous modules) → **567/567 OK**.
- `backend/.venv/Scripts/python.exe manage.py makemigrations --check --dry-run` → **No changes
  detected** (propre après la migration `0021_bug142_production_line_source`).
- Migration appliquée sur la base réelle `backend/db.sqlite3` (démo du matin, comptes
  `@gerant-kX`/`@pierre`) via `manage.py migrate production` — confirmé dans les logs de la suite
  complète ci-dessus (le `migrate` implicite de la suite de tests ne touche pas cette base ; la
  migration a été appliquée séparément sur `db.sqlite3` avec la même commande `migrate production`,
  sans erreur).

## Impact sur le contrat d'API — sous-ticket pour `dev-frontend` (PAS implémenté ici)

- `ProductionSessionLineSerializer` expose désormais un champ `source` (`"DECLARED"` |
  `"CARRYOVER"`) sur chaque ligne de `GET/POST/PATCH /api/production/sessions/...`. **Additif**,
  n'affecte aucun contrat existant (le frontend actuel l'ignorera tel quel).
- **Suggestion pour `dev-frontend`** (à ouvrir comme ticket séparé, non implémenté par moi — « Je
  n'ouvre aucun fichier frontend ») : distinguer visuellement dans « Production & Stocks » les
  lignes « reste d'hier » (`CARRYOVER`) des lignes « produit » (`DECLARED`), par exemple un badge
  ou une colonne séparée, pour que le gérant comprenne pourquoi `total_breads` peut dépasser ce
  que les sacs de farine déclarés justifient (le reste d'hier n'a consommé aucune farine).
- Aucun changement de code HTTP ni de clé d'erreur (`{"detail": "..."}` inchangé) sur les refus de
  session clôturée — simple reformulation du message, pas un changement de contrat.

## Ambiguïté signalée (CLAUDE.md §7 règle 6 — pas tranchée seule)

En relisant `_build_daily_closure_report()` (BUG-120, déjà vérifié formule à formule contre les
Excel réels du client), j'ai trouvé que `produced_by_bp` (rubrique « produit » par catégorie)
agrégeait brutalement **toutes** les lignes `ProductionSessionLine` des sessions du jour, sans
distinction de source. Avec les nouvelles lignes `CARRYOVER`, cela aurait fait apparaître le reste
d'hier confirmé une seconde fois dans la colonne « produit » de ce rapport (qui affiche déjà le
reste d'hier séparément via `reste_du_hier`/`reste_du_jour`, calculés à partir de
`DailyOpeningConfirmation`/`DailyBreadStockSnapshot`, pas de `ProductionSessionLine`).

Ce point précis **n'était pas explicitement tranché** par le brief (qui portait sur le rendement
de `ProductionSession` et le double comptage de `BreadStock`, pas sur ce rapport de clôture
journalier). J'ai choisi de filtrer `produced_by_bp` sur `source=DECLARED` pour préserver
EXACTEMENT le comportement déjà vérifié de ce rapport (aucune ligne CARRYOVER n'existait avant ce
ticket, donc ce filtre ne change rien pour tout jour/équipe sans confirmation — rétro-compatibilité
totale), plutôt que de laisser une régression silencieuse s'introduire dans un rapport financier
déjà audité par le client. Je signale ce choix pour relecture par `auditeur-comptable`/
`testeur-production` plutôt que de le considérer tranché unilatéralement : si le client souhaite au
contraire voir le reste d'hier apparaître aussi dans « produit » de CE rapport spécifique, c'est un
changement de contrat distinct à discuter avec lui, pas une conséquence automatique de ce ticket.

## Statut

Ticket **BUG-142 passé à CORRIGÉ** (pas `VÉRIFIÉ` — CLAUDE.md §7 règle 3, c'est au testeur
d'origine ou au coordinateur de le vérifier et de le faire passer à `VÉRIFIÉ`).

## Risques résiduels / points d'attention pour la vérification

- Le champ `source` n'est, volontairement, pas exposé en écriture (toujours dérivé côté serveur,
  jamais du payload client) — aucun risque qu'un client forge `CARRYOVER` sur une vraie
  déclaration.
- Je n'ai pas modifié `_compute_reconciliation()`/l'action `reconciliation`/`close` (BUG-043/093) :
  `produced_breads`/`produced_fc` y restent basés sur les champs `ProductionSession.total_breads`/
  `total_fc_produced` (déjà corrects par construction via `compute_totals()`), pas sur un nouvel
  agrégat direct de `ProductionSessionLine` — donc aucun changement de comportement nécessaire là.
  À vérifier côté testeur si un scénario carryover + clôture + anomalie NV donne un résultat
  cohérent avec l'intention du client (le reste d'hier est compté comme « pains disponibles » dans
  le recoupement production vs vendu, ce qui semble correct puisque ce sont de vrais pains
  physiquement disponibles à la vente ce jour).
- Pas touché au frontend — voir sous-ticket suggéré ci-dessus.
