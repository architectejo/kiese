# Testeur tresorerie, cycle 18 partie C (2026-11-23) : second balayage final

Fichier : `backend/treasury/tests/test_verif_tresorerie_c18_v17.py` (11 tests, tous verts). Aucun nouveau ticket.

1. Changements sync depuis c17 (BUG-1000 a 1005) : un marqueur de miroir valide ou hors borne ne modifie ni
   total_entries, ni net_cash, ni cash_gap d'une cloture, ni le livre (solde, chaine). Un litige entrant bloque la
   cloture et un marqueur ne le leve pas ; la resolution au cloud la libere. Les transferts n'entrent pas dans la caisse.
2. Journee de 2 jours sur 2 postes + cloud (un poste en REST, l'autre par push) : rapports A/B, depenses, transfert
   sans ecart, billetage (ecart 0 et +500), infirmation puis resoumission (resubmit_count=1), validation, versement,
   pieces VC-<code>-<AAAAMMJJ>, soldes progressifs [67500, 102500, 122500, 147500, 107500], bon de decaissement,
   double versement refuse, chaine valide, blockchain sans alerte, etats financiers N / N-1 en 200,
   closure-status (jour 1 valide ne debloque pas le jour 2 ; debloque apres validation du jour 2).
3. Jamais attaque : closure-status ?node= (gerant/facturier/livreur 403 meme pour son propre code, direction par code
   ou UUID, parametre hostile 404 sans 500, lecture seule, pas de fuite de champs) ; /api/sync/conflicts/ (HQ 200,
   autres 403, anonyme 401, jeton de noeud refuse, 5 types visibles, lecture seule 405) ; volumetrie : 40 rejeux hors
   borne = 1 ligne de conflit (occurrences 40) et 1 TransferMirror ; 700 identifiants forges ou transfert etranger = 0 ligne ;
   exports final_report / period_summary / cashbook reserves a la direction, coherents avec le livre.

Observation (pas un ticket) : `validate` accepte une cloture infirmee non resoumise (la direction peut surcharger
son propre rejet et l'infirmation est levee) ; comportement ancien, non contredit par le CLAUDE.md.

Statuts : aucun ticket tresorerie a verifier. Nouveaux tickets : 0.
