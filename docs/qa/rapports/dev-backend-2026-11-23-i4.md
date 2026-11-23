# Rapport dev-backend (Dev B) — lot I-4 : export Excel des intrants (BUG-1113), 2026-11-23

## Contrat de l'endpoint
`GET /api/production/intrants-export/?date=AAAA-MM-JJ[&month=AAAA-MM][&node=<id|code>]`
- Droits : ceux de `intrants-stats` (`CanReadIntrantsStats` : ADMIN, DIRECTION, COMPTABLE, GERANT ; FACTURIER/LIVREUR 403, anonyme 401, compte sans boulangerie 403). Gérant : sa boulangerie seulement (`node` d'une autre : 404). Partie mensuelle : mêmes droits que `flour-month-stats` (le gérant n'a ni entrée, PU, PT ni solde direction).
- Paramètres invalides : 400 `{"detail": ...}` en français (`parse_day`, `parse_month`, `resolve_node_param`). `date` absent = aujourd'hui.
- Réponse : `.xlsx`, `Content-Disposition: attachment; filename="statistiques-intrants-AAAA-MM-JJ.xlsx"`.
- Feuilles : FARINE, Levure, HUILE, SEL (titre fusionné, en-têtes sur deux lignes, une ligne par boulangerie active, ligne D1 seulement si le nœud SIEGE existe et sans filtre `node`, ligne TOTAUX), « ENTREE FARINE » si `month`, « Hypothèses » (liste `hypotheses` de dev-a).
- Colonnes : A DATE, B BLGR, C initial, D entrée, E sortie, F total avant production (`=C+D-E`), G consommation, H solde (`=F-G`), I référence production, J indice (`=G/I`, vide si pas de référence), K reste déclaré, L écart (`=K-H`, vide si non déclaré) ; SEL : M « RESTE/SAC », N « RESTE/BOITE » vides avec commentaire « Conversion à venir ». TOTAUX : SUM des colonnes de quantité, F/H/J en formules, K/L = totaux des seules lignes déclarées (valeurs).
- Format : `0.000` (quantités), `0.0000` (indice), `0.00` (mensuel). Decimal converti en float uniquement à l'écriture de la cellule.
- Feuille mensuelle : une ligne par jour (consommation par boulangerie, TOTAL, ENTREE, PU, PT, SOLDE), puis TOTAL DU MOIS et MOYENNE / JOUR (achats et solde final sur la ligne du total). Valeurs seulement (les totaux JSON sont arrondis à 2 décimales, des formules pourraient s'en écarter de 0,01). Colonne « vente » et écart du mois non repris (comme I-3).
- Anti-injection : toute chaîne issue de la base débutant par `= + - @`, tab ou retour est préfixée d'une apostrophe.

## Fichiers
- Nouveau : `backend/production/intrants_export.py`, `backend/production/tests/test_dev_i4_intrants_export.py`.
- Modifiés : `backend/production/urls.py` (route + import), `backend/production/flour_month_stats.py` (extraction de la fonction `build_month_stats(user, year, month, raw_node)` ; le corps de la vue est déplacé tel quel, contrat inchangé, laissé sous un `if True:` pour garder le diff minimal), `docs/qa/REGISTRE_BUGS.md` (BUG-1113).
- `intrants_stats.py` non modifié. Aucune migration. `sync/`, `clients/`, `commissions/` non touchés.

## Résultats RÉELS (log `$TEMP/i4.log`)
`manage.py test production.tests.test_dev_i4_intrants_export production.tests.test_intrants_stats_a production.tests.test_dev_i3_flour_month_stats --noinput` : Ran 41 tests, OK. `makemigrations --check --dry-run` : No changes detected. Suite complète NON relancée (hors consigne).
Les 14 tests : cellules = JSON pour les 4 intrants (formules évaluées par un mini-évaluateur du test), D1 présent au cloud et absent sans nœud SIEGE, filtre `node`, droits par rôle, gérant limité, compte sans boulangerie, paramètres invalides, injection dans un nom de boulangerie, feuille mensuelle = JSON, mois vide (février 2024) et gérant sans colonnes direction, absence de feuille mensuelle sans `month`, en-têtes/hypothèses/en-têtes HTTP, sel vide + commentaire, aucun `#DIV`.

## Risques et points ouverts
- Cellules à formule : openpyxl n'écrit pas de valeur en cache ; Excel/LibreOffice recalculent à l'ouverture (`fullCalcOnLoad`), un aperçu sans moteur de calcul (certains lecteurs mobiles) les affichera vides.
- Sel : conversion sacs/boîtes à brancher quand dev-a aura poussé `bag_weight_g/units_per_bag` et son contrat (colonnes M/N prêtes).
- La sélection des boulangeries est répétée (≈15 lignes) depuis `IntrantsStatsView.get` car elle est inline dans la vue, que je ne devais pas modifier ; proposition : dev-a l'extrait en fonction publique.
- Frontend à faire : boutons de téléchargement (blob) via `src/api/services.ts`.
