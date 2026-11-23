# Rapport testeur-tresorerie c10 (2026-11-23)

Fichier : `backend/treasury/tests/test_verif_tresorerie_c10_v9.py` (37 tests : 30 verts, 7 `@expectedFailure`). Log : $TEMP/c10.log.

## Verification
- BUG-910 a 914 : VERIFIE (rejets cibles montants/equipe/dates/billets/bordereau nul, bordereau > solde sans bon orphelin, atomicite bon + ecriture, rejeu idempotent, lot mixte, solde exact, chaine de hash intacte, journee mixte push + REST).
- Regression BUG-911 (d27) : deux facturiers distincts acceptes et stockes, meme facturier rejete, equipes A/B distinctes OK, sans facturier une seule fois ; somme des rapports multi-facturiers = total_entries de la cloture.

## Nouveaux tickets (4)
- BUG-929 (Majeur) : `facturier` pousse non controle (autre noeud, autre role, autre equipe) ; sert de cle d'unicite donc N utilisateurs forges = N rapports de la meme vacation, ventes comptees N fois a la cloture.
- BUG-930 (Mineur) : facturier UUID inexistant converti en NULL sans rejet.
- BUG-931 (Majeur) : rapport accepte au push sur un jour de cloture confirmee (REST refuse).
- BUG-932 (Mineur) : billetage en chaines numeriques passe le controle strict puis echoue au handler (motif generique).

Verifies sans defaut : lecture des rapports cloisonnee par noeud, suppression du facturier (SET_NULL) sans effet sur la cloture.
Conflit de numerotation : 919-928 pris par d'autres testeurs, numerotation 929+.
