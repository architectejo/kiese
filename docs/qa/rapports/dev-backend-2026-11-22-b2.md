# Rapport dev-backend (Dev B) - 2026-11-22-b2

## Ticket traite : BUG-417 (CORRIGE) - carte et cotisation en FC par boulangerie
Source : remarque.md l.452-454, Q-026, message #17.

### Changements
- `core/models.py` : `Node.card_fee_fc` (Decimal 10,2, defaut 1000) ; `Node.monthly_social_contribution` defaut 2000 (nouvelles boulangeries).
- `core/migrations/0021_node_card_fee_fc.py` : AddField + AlterField (defaut seulement, aucune valeur existante modifiee) + migration de donnees (`card_fee_fc` = `Config.print_fee` si > 0, sinon 1000 ; reverse = noop). Aucune migration existante modifiee.
- `core/serializers.py` : `card_fee_fc` dans `NodeSerializer`, validation >= 0. Ecriture : `NodeViewSet` est deja reservee a `IsDirection` (ADMIN/DIRECTION), comme `monthly_social_contribution`.
- `commissions/views.py` : `generate` fige `deduction_prints = node.card_fee_fc` (plus `Config.print_fee`, conserve dans `Config` en lecture compat uniquement) ; cotisation = `client.effective_cotisation_sociale` (inchange). Nouvelle action `GET /api/commissions/commissions/summary/` ; `periods/history/` enrichi.
- `commissions/serializers.py` : champs `cotisation_sociale_fc`, `carte_fc`.
- `core/testing.py::make_node` : parametres `social` / `card_fee` (defaut 0) pour que les ~centaines de tests existants, calcules a la main avec retenue nulle, restent valides malgre les nouveaux defauts 2000 / 1000. Les tests de defauts creent `Node.objects.create(...)` directement.

### API pour le frontend
- Node (`/api/core/nodes/`) : `monthly_social_contribution`, `card_fee_fc` (chaines Decimal FC), PATCH par ADMIN/DIRECTION, 400 si negatif, 403 sinon.
- Ligne `/api/commissions/commissions/` : `cotisation_sociale_fc`, `carte_fc` (en lecture, alias de `deduction_social` / `deduction_prints`, qui restent modifiables par le siege).
- Totaux verticaux : `GET /api/commissions/commissions/summary/` (memes filtres que la liste : `period`, `period__node`, `period__month`, `period__year`, ...) -> `{total_orders, total_cm, total_debt, total_cotisation, total_carte, total_other, total_deductions, total_net, count}` (isole par noeud, IsGerant). `periods/history/` : `total_cotisation`, `total_carte` par periode.
- Le filtre mois/annee demande a la ligne 454 existe deja cote API (`period__month`, `period__year`) ; a brancher au frontend.
- Frontend a ouvrir (ecran Commissions CM : colonnes Cotisation/Carte + totaux + filtre mois/annee ; Configuration : champ carte par boulangerie).

### Formule (CLAUDE.md 5.3)
Net a payer = CM brute - (dette + sociale + imprimes/carte + autre) - report ; verifiee, non modifiee. `deduction_carte` (ancienne colonne CARTE = 1 % de la CM, BUG-291) reste forcee a 0 : c'est une colonne DISTINCTE de la carte en FC (`deduction_prints`). La retirer ferait une double retenue ; je n'ai donc pas retire ce forcage (jugement, a confirmer par le coordinateur).

### A confirmer (decision client)
Les boulangeries EXISTANTES gardent leur cotisation actuelle (B2 = 2000, les autres = 0 issues des Excel d'aout) : seul le defaut change pour les nouvelles. Si le client veut 2000 partout, il suffit de les saisir (ou une migration de donnees, a decider C/A/B).
Les commissions deja generees conservent leur `deduction_prints` (0 ou ancienne valeur) ; seule une nouvelle generation de periode applique la carte du noeud.

### Tests
- Nouveau : `commissions/tests/test_bug417_carte_cotisation_par_boulangerie.py` (defauts 2000/1000, K1 != B2 deduits par client, `Config.print_fee` n'est plus la source, champs et totaux API, history, isolation par noeud, droits d'ecriture, migration de donnees ne touche pas la cotisation).
- Suite `commissions core clients sync` (858 tests) : seules erreurs = mes tests (collision des codes K1/B2 deja seedes, corrige ; 403 sur summary pour le gerant, corrige). Nouveau module : 8 tests OK ; `makemigrations --check` : aucun changement.

## Risques
- Les nouveaux defauts 2000/1000 touchent tout code qui cree un `Node` sans valeurs (seed, tests d'autres apps non lances ici).
- BUG-521 (deficit_report) non touche.
