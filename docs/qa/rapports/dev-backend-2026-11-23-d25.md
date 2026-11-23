# Dev backend (Dev B) d25 - 2026-11-23

Tickets BUG-901 a 909 : CORRIGE (a verifier par le testeur-production).

Cause commune : `_validate_fields` (sync/services.py) appelle `field.clean(value, None)` : pas de plage metier, pas d'ASCII, pas de date future.

Correctif (backend/sync/services.py uniquement) :
- Helpers partages `_sync_decimal` / `_sync_int` / `_sync_not_future_date` (ASCII, fini, decimales sans arrondi silencieux, bornes ; date via `work_date_for(node)`).
- Table `_STRICT_CHECKS` appelee par `_preflight` apres `_validate_fields` : ProductionSession (901/902), ProductionSessionLine (903/904), BreadDisposal (906), ConsumableMovement (907), Invoice (908). Rejet = REJECTED + motif francais, le reste du lot passe.
- `_validate_fields` : chiffres non ASCII refuses pour tous les champs numeriques saisis en chaine.
- 904 : `quantity: null` rejete explicitement (cle absente = 0, comportement historique).
- 905/909 : ligne refusee sur fournee cloturee / facture livree ou annulee. Exception : parent pousse deja terminal dans le MEME lot (contexte thread-local `_batch_terminal_parents`, reinitialise par `process_push_batch`), sinon un poste ne pourrait plus synchroniser une fournee/facture terminee hors-ligne avec ses lignes. Rejeu d'une ligne deja presente sur fournee close : accepte (idempotent).

Decisions a signaler :
- 908 : regle REST reelle = taux 0 / 0,25 / 0,30 a la creation, taux client borne a [0 ; 0,30] (ClientBoundsMixin). Le push borne donc a [0 ; 0,30], 2 decimales (pas [0 ; 1]).
- 906 : la borne REST citee (1 000 000) n'existe pas dans `_strict_int` ; j'ai applique la borne 2e9 de BUG-894 (le test utilise 3e9). Negatif autorise seulement pour REMAINING (BUG-158). A trancher si on veut 1 000 000.
- 907 : quantite 3 decimales max, prix 4 decimales max (CUMP BUG-803), >= 0.

Tests : retrait des `@expectedFailure` de `production/tests/test_verif_production_a8_v8.py` (assertions inchangees). Resultats (log $TEMP/d25.log) : a8_v8 + test_verif_sync_v5 + test_verif_charge_v4 = 66 OK ; `manage.py test sync production.tests.test_sync_inventaire_v2_a3` = 243 OK (3 expected failures preexistants) ; makemigrations --check : aucun changement. Suite complete non lancee.

Risques : un rejeu hors lot d'une ligne manquante sur parent deja clos cote cloud est rejete (cas rare de ligne rejetee transitoirement puis parent cloture) ; contrat API inchange cote frontend.
