# dev-backend d42 (2026-11-23)
CORRIGÉ : BUG-985 (compteur `CashClosure.resubmit_count`, migration treasury 0018, sync services/sync_now, treasury/views perform_update), BUG-987 (dédoublonnage notification, sales/views), BUG-988 (vente antidatée et ajustement (+) refusés sur jour confirmé, sales/views).
BUG-986 : À CLARIFIER, non codé.
Tests : c15_v14, d38, c14_v13, c13_v12, sync v5, charge v4, adjust_d7 : 170 OK ; makemigrations : aucun changement. Décorateurs @expectedFailure retirés (assertions inchangées).
Risques : `resubmitted: true` (poste ancien) n'a pas la protection anti-rejeu du compteur ; contrat additif sync (`resubmit_count`) à connaître de l'architecte-sync ; le pull n'exporte pas le compteur (contrat de pull figé par test).
