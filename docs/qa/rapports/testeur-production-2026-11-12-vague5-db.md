# Testeur Production, vague 5 (2026-11-12) : vérification BUG-278

## Résultat
- BUG-278 : VÉRIFIÉ côté backend (tests), avec réserve : pas de rejeu sur db.sqlite3.
- `@expectedFailure` retiré de `test_vague4_testeur_production_2026_11_12.py::SameTeamTwoConsecutivePeriodsTests::test_bug278_...` (import inutile retiré) : passe.
- `test_bug278_equipe_redesignee.py` : A poursuit après minuit, clôturée à la relève, redésignée, fournée acceptée (une seule session, rouverte, sans reste fantôme) ; confirmation du stock de départ OK ; ré-clôture : un seul instantané (5) et un seul reste ; BUG-093 intact (clôture volontaire dans la période = 400) ; autre équipe refusée ; deux équipes un même jour : manquant -50 000 / excédent +50 000, rapport consolidé 800 pains.
- Suite `production` complète : 405 tests OK (2685 s).

## Rejeu sur la base réelle : non effectué
Activer la rotation de K2 et régler la relève demande un compte ADMIN/DIRECTION. Le gérant K2 reçoit 403 ; la connexion avec un autre compte a été bloquée par le contrôle de permissions (identifiants non fournis pour cette session). K2 est inchangé : rotation False, relève 12:00, créneaux d'origine. Aucune donnée créée. État constaté : désignation du 12/11 = B, sessions A (close) et B du 12/11 présentes. À relancer si vous fournissez un compte autorisé (ou activez vous-même la rotation).

## Libellé « Équipe de service du jour : B »
Trompeur en rotation : un même jour a deux équipes. Ticket BUG-281 (Mineur, frontend, OUVERT ; BUG-279 et 280 étaient déjà pris). Suggestion : « Équipe de service de la période : B (relève de HH:MM) ».

## Proposition de stock de départ
Code lu (`views.py` ~2931-2947) : en rotation, quantité proposée = dernier reste déclaré (`last_snapshot_upto`), à défaut le stock courant `BreadStock.qty_available`. Ce n'est pas le stock réel quand un instantané existe. Pas de ticket (conception BUG-161 B4), à surveiller.

## Non-régression
Couverte par la suite complète (BUG-157, 190, 196, consommables, stock négatif, transferts, clôture, NS/RG). Non rejouée sur la base réelle.
