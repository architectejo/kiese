# Testeur Clients et Commissions, vague 3 sur db.sqlite3 (K4), 2026-11-12

Base réelle (backend :8000, Vite :5173 déjà lancés), boulangerie K4, comptes `zz_clients_*`, clients « ZZTEST Clients n ». Aucun migrate/SQL d'écriture, aucun git, aucun des 678 clients réels modifié. Périodes de commissions K4 02/2026 et 03/2026 régénérées (lignes dérivées des factures ZZTEST uniquement).

## Vérification des tickets
| Ticket | Résultat | Preuve |
|---|---|---|
| 257 | VÉRIFIÉ | plafond -100, taux 0,99 / -0,10, cotisation -3000 : 400 français |
| 258 | VÉRIFIÉ | PNG 12 Mo 400 « La photo ne doit pas dépasser 5 Mo. » ; .txt 400 ; PNG valide 200 |
| 259 | VÉRIFIÉ | PATCH current_debt / total_breads_received ignorés |
| 260 | VÉRIFIÉ | mois 13, montant et tarif négatifs 400 ; clôture irréversible |
| 261 | VÉRIFIÉ | RG 500 FC et facture à taux 0 exclues (K4-0107 sans CM) |
| 262 | VÉRIFIÉ | valeurs négatives, taux 0,9 : 400 |
| 263 | VÉRIFIÉ (partiel) | tests unitaires verts ; DELETE de période non rejoué sur la base (aucun compte DIRECTION/ADMIN utilisable) |
| 264 | VÉRIFIÉ | retenues 1000/200/50 conservées après régénération, net -6 002,50 ; test ajouté pour « ligne payée sautée » |
| 265 | VÉRIFIÉ | comptable 403 sur mark_paid et set_manuel |
| 269 | VÉRIFIÉ | K4 = 107 clients (et non >125) ; pages 2+ ralenties de 6 s : « … fiches / Actifs : … / … alertes / … » puis 107 fiches, Actifs 100, 0 alerte, encours 4 000 FC = somme API |
| 270 | VÉRIFIÉ avec réserve | COMPTABLE sans Régler / Ajustement manuel (ligne et fiche). DIRECTION SIMULÉ côté navigateur (role réécrit dans /auth/login et /auth/me, jeton comptable) : boutons visibles, bannière avec le detail 403 réel ; 400 simulé. Réserve : BUG-280 |

À CLARIFIER, non touchés : 253, 266, 267, 268 (leurs 4 `@expectedFailure` restent).

## Non-régression (valeurs calculées à la main)
- Février K4 : 5000x0,25 = 1250 ; 16000x0,30 = 4800 ; vente solde exclue (2000x0,25 = 500) ; 1000x0,25 = 250. Carte 1 % (12,50 / 48,00 / 5,00 / 2,50), retenues = dette + sociale 3000 + carte, nets -6762,50 / -8248,00 / -4505,00 / +1247,50. Remise annuelle 0,25 / 0,65 (26 pains) / 0,10 / 0,05. Totaux verticaux du listing : valeur 24 000, CM 6 800, net -18 268 = historique.
- Code unique, plafond 50 000 (gérant/comptable oui, facturier 403), recherche inter-boulangeries, catégories BEST/RISK aux bornes, import Excel fictif, caisse sociale : tests unitaires verts.
- `python manage.py test clients commissions` : 128 tests OK (4 échecs attendus : 253, 266, 267, 268) ; puis fichier commissions vague 2 : 17 tests OK avec le nouveau test de régénération (saute les lignes payées, conserve les retenues, rafraîchit valeur et CM).
- Pagination « Voir plus » : couverte par `14-clients-commissions-vague2-db.spec.ts` (non rejouée).

## Interface (Playwright 360 et 1440 px)
`e2e/tests/16-clients-commissions-vague3-db.spec.ts` : 6 scénarios verts (3 par largeur), sans débordement horizontal. Captures `docs/qa/captures/*vague3*`.

## Tickets
Nouveau : BUG-280 (Mineur, frontend) : la fiche reste ouverte au-dessus de la bannière après un échec d'ajustement manuel.
Limites : aucun mot de passe ADMIN/DIRECTION connu, donc rôle DIRECTION simulé et mark_paid / DELETE de période / « ligne payée sautée » non rejoués sur la base réelle (couverts en base de test).
