# Testeur Clients / Commissions - ronde b9 (2026-11-23)

Fichier : `backend/clients/tests/test_clients_v6.py` (24 tests : 13 verts, 11 `@expectedFailure`).
Resultat : `OK (expected failures=11)` apres retrait d'un `@expectedFailure` devenu inutile (chiffres arabes en push : deja refuses).

## Regressions (flux legitimes, valeurs realistes)
Creation client REST, import Excel fictif, paie (CM 25 %/30 %, retenues dette/sociale/carte, net, totaux verticaux), mark_paid, regeneration, cloture de periode, BUG-737 (deux boulangeries), net negatif non payable, caisse sociale complete (indice 3, remise 3 x 700 = 2 100, total 8 100 puis 9 000 avec merite 900), cloture de distribution. Aucune regression due a AsciiDigitsMixin, au gel des periodes ou a la caisse sociale close.

## Push sync vs REST
Verts : flux legitimes, ligne figee apres cloture (BUG-887), modeles commissions non supportes (aucun effet sur une commission payee / periode close), scope noeud, doublon cotisation, paid_at invalide, ASCII.
Tickets : BUG-915 (ASCII REST caisse sociale/paies), BUG-916 (push Client sans bornes), BUG-917 (push cotisation sans bornes ni controle client/noeud), BUG-918 (push ligne de distribution : bornes et remise/total_payer non recalcules).

## Observation sans ticket
La modification d'une cotisation (REST ou push) d'une annee dont la distribution est close reste possible ; la distribution figee n'est pas touchee (a clarifier avec le client si necessaire).
