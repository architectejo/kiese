# testeur-tresorerie c16 (2026-11-23)
Fichier : backend/treasury/tests/test_verif_tresorerie_c16_v15.py (23 tests, 22 verts + 1 @expectedFailure BUG-996). Code applicatif non modifié.
- BUG-985 VÉRIFIÉ : REST incrémente, payload exporte, compteur > cloud lève à contenu identique (jamais confirmée), égal/inférieur/types invalides ignorés, 2e infirmation + rejeu, autre nœud refusé, borne 10**6. Journée complète (rejet, recomptage identique, resoumission, confirmation, versement, chaîne OK, vente antidatée refusée) verte.
- Question `resubmitted: true` : relève l'infirmation à volonté, mais le compteur est forgeable de la même façon et le poste peut déjà changer un billet : pas d'escalade, observation documentée.
- BUG-996 (nouveau, Majeur) : compteur incrémenté par tout PUT, même sans infirmation ; rejeu d'un lot antérieur lève une infirmation ultérieure.
- BUG-987 VÉRIFIÉ (rafale, après lecture, autre jour, par boulangerie). BUG-988 VÉRIFIÉ : vente antidatée refusée sur jour confirmé, permise sur jour non clôturé/infirmé/autre boulangerie ; ajustement (+) refusé (hier et aujourd'hui), (−) et remboursement antidaté permis (test dédié écrit).
- BUG-986 non codé, À CLARIFIER : vente du jour acceptée après confirmation (observation).
