# Dev backend d31 - 2026-11-23

Tickets CORRIGE : BUG-938, BUG-939, BUG-940 (backend/sync/services.py).

- 938/940 : `_resolve_invoice_line` reecrit. Id valide mais ligne cloud d'une autre facture OU d'une autre categorie de la meme facture = collision -> recherche par (facture, categorie[, prix net]) sinon creation avec PK auto (l'id n'est repris que s'il est libre). Id absent/non numerique -> cle naturelle (rejeu idempotent). Collision en chaine couverte.
- 939 : push d'une fournee ouverte existante (meme noeud) propage flour_sacks_used, sac_value_fc_used, notes (bornes deja controlees par _check_production_session), puis totaux recalcules depuis les lignes. Fournee close : jamais modifiee.
- ProductionSessionLine et BreadTransferLine : deja par cle naturelle (d28), motif absent.
- Tests : @expectedFailure retires dans test_verif_production_a10_v10 (assertions inchangees). a10+a9+a8+sync v5+charge v4 : 147 tests OK ; makemigrations --check : aucun changement. Log : $TEMP/d31.log.

Risques : `sync.tests.test_verif_charge_v4.RetenueTroisBoulangeriesVerif.test_imbrication_a_trois_une_seule_retenue` (commissions, hors perimetre) est instable : 1 echec sur ~9 executions avec ou sans... (4 OK de suite apres, 3/3 OK sans mon changement) - a signaler au testeur commissions. Un `git stash` (stash@{0}) a ete laisse : il contient des modifications d'un autre agent sur clients/tests (test_clients_v8, test_tmp_dbg).
