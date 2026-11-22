# Rapport dev-backend — 2026-11-22 (a6) : envoi direct de pains + « Versement » direction

Tickets : BUG-380 (CORRIGÉ), BUG-381 (CORRIGÉ), BUG-382 (OUVERT, frontend). Aucun ticket passé à `VÉRIFIÉ`.

## 1. Envoi direct de pains (BUG-380)

Second flux `DIRECT` à côté du flux historique `REQUEST` (demande -> réponse -> confirmation, inchangé).

### Contrat d'API

`POST /api/production/transfers/send/` — permission : GERANT et au-dessus (comme les autres écritures de transferts). Facturier/livreur : 403. Compte sans boulangerie non siège : 403 ; siège sans boulangerie : 400 (même règle que la demande).

Corps :
```json
{ "to_node": 2,                       // pk OU code de la boulangerie destinataire ("K2")
  "lines": [ {"bread_price": 3, "quantity_sent": 40} ],   // entier >= 1, catégories distinctes (doublons fusionnés)
  "notes": "texte libre (optionnel)" }
```
`from_node` n'est jamais lu : c'est la boulangerie de l'appelant (un `from_node` forgé est ignoré).

Réponse 201 : le transfert sérialisé comme les autres (`BreadTransferSerializer`) avec `flow: "DIRECT"`, `flow_display: "Envoi direct"`, `transfer_status: "RESPONDED"`, `from_node`, `to_node`, `lines[]` (`quantity_sent`, `quantity_received: null`).
Erreurs 400 `{"detail": "..."}` en français : destinataire absent/inconnu/identique à l'émetteur, lignes absentes/mal formées, catégorie inconnue, quantité non entière/<1/trop grande, « Stock insuffisant pour <catégorie> : N disponible(s) à K1, M demandé(s). » (aucune écriture partielle).

Nouveaux champs en lecture seule sur tous les transferts (liste/détail) : `flow` (`REQUEST` | `DIRECT`), `flow_display`. Les lignes existantes valent `REQUEST`.

Cycle (frontend) :
- Émettrice : l'envoi déstocke immédiatement ; le transfert est ensuite figé (PATCH/DELETE -> 400) ; `respond_to_request` -> 400.
- Réceptrice : voit le transfert dans `GET /api/production/transfers/` (filtre `?to_node=`, `?transfer_status=RESPONDED`) et le valide avec l'action existante `POST /api/production/transfers/<id>/confirm_reception/` `{"lines":[{"bread_price":3,"quantity_received":40}]}` -> `CONFIRMED` (égal) ou `DISPUTED` (écart : notification DANGER, clôture de la réceptrice bloquée, résolution par `resolve_dispute`). Seule la réceptrice peut valider (émettrice 403, tierce invisible/404).
- Un notification INFO « Pains Envoyés » est créée pour la destinataire ; `log_activity` « Envoi Direct de Pains ».
- Distinguer les deux flux à l'écran : `flow === 'DIRECT'` -> « Envoi direct de K1 » (la réceptrice n'a rien demandé), `REQUEST` -> libellé actuel.

Clôture journalière / rapports : inchangés et corrects, car l'envoi direct passe par les mêmes statuts : `appro_effectue` (émettrice) et `appro_recu` (réceptrice) comptent le transfert une fois `CONFIRMED` (jour de la confirmation), comme pour le flux existant ; un envoi non encore validé n'est pas compté (testé).

### Fichiers
- `backend/production/transfer_direct.py` (nouveau : mixin avec l'action `send`)
- `backend/production/models.py` (`BreadTransfer.Flow`, champ `flow`)
- `backend/production/migrations/0027_bug380_transfer_flow.py` (nouvelle, AddField, défaut `REQUEST`, réversible)
- `backend/production/serializers.py` (`flow`, `flow_display`)
- `backend/production/views.py` (2 lignes : import + base du viewset)

### Tests
`backend/production/tests/test_transfert_envoi_direct_a.py` : 23 tests (nominal, code destinataire, `from_node` forgé, miroir -N/+N, somme nulle, écart -> litige -> blocage de clôture -> résolution, double confirmation, isolation (facturier/livreur/anonyme/sans boulangerie/siège/tierce), validations (16 corps invalides, aucun 500, aucune écriture), stock insuffisant atomique, deux envois successifs sans survente, verrou `select_for_update` sur `BreadStock`, lecture par les deux côtés, `appro_*`, non-régression complète du flux demande/réponse).

## 2. « Versement » visible de la direction (BUG-381)

### Constat
Le « Versement » est la clôture de caisse du gérant (`CashClosure` : billetage, écart, statut). Côté API, la liste `/api/treasury/closures/` était déjà lisible par GERANT+ et, pour ADMIN/DIRECTION/COMPTABLE, sur toutes les boulangeries (filtres `node`, `date`). Ce qui manquait : une vue par date incluant les boulangeries qui n'ont PAS encore versé, et les totaux. Côté frontend, le formulaire « Versement » est masqué pour `can_access_all_nodes` (`Treasury.tsx`, ~l.1715) : c'est ce qui rend la section invisible à la direction.

### Contrat d'API
`GET /api/treasury/closures/versements/?date=AAAA-MM-JJ&node=<id|code>` — lecture seule (POST/PUT/PATCH/DELETE : 405). Permission = celle de la liste (GERANT+) ; facturier/livreur 403 ; anonyme 401.
- `date` optionnelle (défaut : date locale du jour) ; `node` optionnel (pk ou code, insensible à la casse). Date/boulangerie invalides -> 400 `{"detail"}`.
- Périmètre : ADMIN/DIRECTION/COMPTABLE = toutes les boulangeries ; GERANT = la sienne (`?node=` autre -> 403) ; compte sans boulangerie = liste vide.

Réponse :
```json
{ "date": "2026-11-18", "count": 8,
  "results": [ { "node": 1, "node_code": "K1", "node_display": "K1 - TABORA", "date": "2026-11-18",
      "status": "NON_VERSE" | "EN_ATTENTE" | "VALIDE" | "INFIRME",
      "closure": { ...CashClosureSerializer (billets, écart, rejection_reason, has_cashbook_entry...) } | null,
      "total_entries": "100000.00", "total_expenses": "20000.00", "net_cash": "80000.00",
      "physical_cash_total": "80000.00", "cash_gap": "0.00" } ],
  "totals": { "total_entries": "...", "total_expenses": "...", "net_cash": "...",
      "physical_cash_total": "...", "cash_gap": "...",
      "bills": { "bills_20000": 5, "bills_10000": 2, "bills_5000": 1, "bills_1000": 0, "bills_500": 0, "bills_200": 0, "bills_100": 0, "bills_50": 0 },
      "counts": { "NON_VERSE": 6, "EN_ATTENTE": 1, "VALIDE": 1, "INFIRME": 0 }, "versed_count": 2 } }
```
Montants en chaînes décimales (`Decimal`, à formater `12 500 FC` côté UI). Boulangeries non versées : montants à `"0.00"`, `closure: null`.

Le détail d'une clôture reste `GET /api/treasury/closures/<id>/`. Les actions `validate`/`reject`/`push_to_cashbook` (siège seul, BUG-200) et la création (gérant) sont INCHANGÉES : Q-020 (« qui valide le Versement ») reste en attente du client.

### Fichiers / tests
- `backend/treasury/versements.py` (nouveau, mixin), `backend/treasury/views.py` (2 lignes : import + base du viewset).
- `backend/treasury/tests/test_versement_visible_direction_a.py` : 14 tests (3 rôles siège, statuts, totaux, filtres pk/code, date par défaut, paramètres invalides incl. entier géant, gérant limité/403, facturier/livreur/anonyme, compte sans boulangerie, lecture seule 405, droits d'écriture inchangés, liste existante inchangée, non-masquage du détail).

## 3. Résultats

- Avant : endpoints inexistants (404/405) ; champ `flow` absent.
- Après : `production.tests.test_transfert_envoi_direct_a` + `treasury.tests.test_versement_visible_direction_a` : 37/37 OK.
- Suites `production` + `treasury` + `core.tests.test_verif_isolation_a_c` : 1328 tests, 1 échec : `production.tests.test_verif_bug522_c::test_every_model_field_untouched_by_patch` (garde-fou du testeur qui exige une attaque PATCH par champ du modèle ; le nouveau champ `flow` n'y figurait pas). Corrigé en AJOUTANT `'flow': 'DIRECT'` à la table d'attaque (couverture renforcée, aucune assertion affaiblie) ; test relancé : vert. À signaler au testeur d'origine.
- `manage.py check` : aucun problème ; `makemigrations --check --dry-run` : « No changes detected ».

## 4. Risques et points à arbitrer

1. Contradiction à trancher (remarque.md) : l.307 « enlève la partie Versement chez le comptable » vs l.456 « visible chez les membres de la direction centrale ». L'API autorise la lecture aux trois rôles siège ; c'est au frontend/coordinateur de décider si le COMPTABLE voit le tableau (l.307 vise le formulaire de saisie).
2. Un envoi direct n'a pas d'annulation : le stock est déduit tout de suite ; si la réceptrice ne valide jamais, le stock de l'émettrice reste déduit (même comportement que le flux demande/réponse après réponse). Pas de rappel automatique : à proposer si le client le souhaite.
3. L'envoi direct refuse un stock insuffisant (comme demandé), alors que `respond_to_request` ne contrôle pas le stock : incohérence de comportement entre les deux flux, volontaire ; à harmoniser seulement sur décision du client (stock négatif toléré ailleurs, BUG-143/158).
4. `treasury/versements.py` réutilise `resolve_node_param` / `parse_date_param` de `kiese/node_guard.py` (en cours de modification par le lot BUG-526 à 529) : si leurs signatures changent, adapter.
5. Concurrence : `select_for_update()` est sans effet sur SQLite (verrou global d'écriture) ; sur PostgreSQL le verrou de ligne s'applique. Test de concurrence réel non simulable en SQLite : couvert par séquence + spy sur le verrou.
