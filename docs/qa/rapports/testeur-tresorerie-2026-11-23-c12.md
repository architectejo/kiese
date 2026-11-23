# Testeur trésorerie c12 (2026-11-23)

Fichier : `backend/treasury/tests/test_verif_tresorerie_c12_v11.py` : 28 tests, OK (5 expected failures).

## Vérifiés
BUG-935 et BUG-936 : VÉRIFIÉS (rôles FACTURIER/GERANT/COMPTABLE/DIRECTION/ADMIN du nœud acceptés ; livreur, inconnu, forgé, autre nœud refusés ; facturier inactif accepté, déduplication conservée, rejeu idempotent).
Tests adaptés relus : c10 `test_facturier_non_facturier_refuse` (livreur) et c11 `test_929_forge...` testent toujours l'essentiel (forge, autre nœud, livreur, types invalides) ; le test supprimé (autre équipe) est remplacé par `test_equipe_du_facturier_non_controlee_decision_937`.

## Balayage 2 postes (sync_now)
Journée complète C1 + C2 plus journée N-1 : rapports A/B, dépenses, clôtures, push, confirmation, versement `VC-<code>-<date>`, bon de décaissement, solde 59 500 FC, chaîne valide, verdict treasury = blockchain, cashflow et résultat N / N-1 exacts : vert. BUG-675 (transferts sans effet sur la caisse, écart non résolu bloque création et confirmation REST), BUG-677, BUG-871 : sans défaut. Lectures finance, livre, blockchain, clôtures : cloisonnées (403/404).

## Nouveaux tickets (5)
- BUG-959 (Majeur) : le lot sortant n'exporte pas `facturier` : 2e facturier d'une même équipe/jour rejeté, cash perdu.
- BUG-960 (Majeur) : clôture poussée validée malgré écart de transfert entrant non résolu.
- BUG-961 (Majeur) : dépense poussée acceptée sur un jour de clôture confirmée.
- BUG-962 (Mineur) : dépense poussée à date future acceptée ; pas de contrôle strict.
- BUG-963 (Mineur) : facturier COMPTABLE/DIRECTION/ADMIN sans nœud refusé au push.

Note : une suite concurrente (migration clients 0011) a brièvement fait échouer la base de test ; relancé après l'arrivée de la migration.
