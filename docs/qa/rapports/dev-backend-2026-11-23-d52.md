# dev-backend d52 (2026-11-23) : BUG-1010 et BUG-1011

## BUG-1010 -> CORRIGE
`sync/views.py` : avec `client_after_id`, `_parse_cursor` accepte un curseur jusqu'au plus grand `updated_at` reel des clients (plafond), en plus de now+1 h. Sans after_id, ou au-dela de toute ligne : traite comme absent (BUG-785, tests 1h/2h inchanges). Borner le curseur a min(updated_at, now) ecarte : doublons de la page 1.
Test : `test_marche_avec_lignes_datees_futur_3h_ne_boucle_pas` (@expectedFailure retire, a confirmer par le testeur).

## BUG-1011 -> CORRIGE
`commissions/views.py::generate` : si aucune ligne du mois ne porte la retenue ET qu'une boulangerie facturee a une periode du mois sans ligne pour le client (porteuse supprimee), la plus ancienne ligne non payee (created_at, pk) reporte dette+cotisation puis recalcul. Jamais doublee, ligne payee jamais touchee. Un zero manuel (toutes lignes presentes) est conserve (test v5).
Test : `test_regeneration_seules_lignes_restantes_sans_recreer_la_supprimee` (@expectedFailure retire).
Limite : si on regenere une ligne qui n'est pas la plus ancienne, la retenue reste a 0 jusqu'a la regeneration de la plus ancienne.

## Tests
- Passe 1 (213 tests : clients v13-15, commissions v4-v6, d49, sync v5, charge v3/v4) : 1 echec (v5 ex_aequo), cause : premiere version trop large ; corrige (condition sur periode existante sans ligne).
- `commissions` complet (259) avant ajustement final : 1 echec (le meme v5).
- Apres ajustement : commissions v5+v6+d49 (33 tests) OK ; commissions v3+v4, clients v15, sync v5 (89 tests) : 0 echec, 1 succes inattendu.
- Non relances apres l'ajustement final : clients v13/v14, sync charge v3/v4 (code sync inchange depuis la passe 1, verte).
- Succes inattendu : `test_commissions_v3...test_suppression_de_la_ligne_qui_retient_puis_regeneration` (@expectedFailure BUG-783) passe desormais ; a traiter par le testeur (retirer le decorateur).
