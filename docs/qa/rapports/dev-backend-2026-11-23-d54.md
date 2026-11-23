# Rapport dev-backend (Dev B) - d54 - 2026-11-23

## Tickets
- BUG-1013 (mineur) : CORRIGE.
- BUG-1014 (mineur) : CORRIGE.

## Cause
L'heuristique d52 de `commissions/views.py::generate` (« boulangerie facturee sans ligne = porteuse supprimee », basee sur les factures LIVREES) etait fragile : retenue perdue si la facture de la porteuse est annulee ou si seule la ligne la plus recente est regeneree (1013) ; zero manuel ecrase si une autre ligne est supprimee ou si la periode d'une autre boulangerie existe sans ligne (1014).

## Correction (regle explicite)
- Pour (client, mois) la retenue (dette BP + cotisation) est portee par exactement UNE ligne non payee, la plus ancienne (created_at, pk), d'une periode non close.
- Une ligne creee par `generate` demarre a 0. Report automatique seulement si aucune ligne du mois (payee ou non) ne porte la retenue ET aucune ligne n'a `deduction_manual=True`. La ligne choisie est mise a jour meme si ce n'est pas celle qu'on regenere (cas 1013 b).
- Aucune dependance au statut des factures ni a l'ordre de regeneration ; une ligne payee n'est jamais modifiee ; pas de doublon.
- Nouveau champ additif `ClientCommission.deduction_manual` (BooleanField, defaut False, migration 0006 additive), lecture seule dans l'API, pose a True par PATCH/PUT quand `deduction_debt` ou `deduction_social` change reellement (`perform_update`).

Fichiers : backend/commissions/views.py, models.py, serializers.py, migrations/0006_bug1014_deduction_manual.py, tests/test_commissions_v7.py (decorateurs @expectedFailure retires ; le zero est pose via un helper PATCH `zero()` au lieu d'un update ORM), tests/test_commissions_v5.py (test ex aequo : zero pose par PATCH), tests/test_commissions_v6.py (assertion inversee, voir risques).

## Resultats REELS
- Run 1 : commissions v7, v6, v5, v4, v3, d49 + sync.test_verif_charge_v3 + v4 : 179 tests, 1 echec (v6 test_manuel_zero_sur_la_porteuse_..., qui encodait le contraire de BUG-1014). 854 s.
- Apres adaptation de ce test : v6 + v7 relances : 23 tests, 0 echec.
- `makemigrations --check --dry-run` : No changes detected.
- Soit 179 tests au total, 0 echec apres adaptation (le run complet n'a pas ete relance apres la seule modification du test v6, verifiee separement).

## Risques / points a valider par le testeur
- Le test v6 adapte (assertion inversee : zero PATCH => la ligne regeneree ne reprend pas la retenue) et le test v5 ex aequo (zero via PATCH) : un update ORM de zero est desormais indiscernable d'une porteuse supprimee et est re-reporte.
- Un PATCH qui change la dette/cotisation d'une ligne (meme non nulle) pose `deduction_manual` : plus de report automatique ce mois pour ce client.
- Les lignes existantes en base ont `deduction_manual=False` (zeros manuels anterieurs a d54 pourront etre re-reportes une fois).
- Contrat API : champ `deduction_manual` ajoute en lecture seule ; aucun ticket frontend necessaire.
