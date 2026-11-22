# Rapport testeur-ventes (Dev C) - 2026-11-22-c

Verification independante des tickets CORRIGE du module Ventes. Aucun code applicatif modifie, ni commit ni push.
Tests : `backend/sales/tests/test_verif_ventes_c.py` (nouveau, 20 tests, donnees fictives).

## Resultats par ticket

| Ticket | Verdict | Controles |
|---|---|---|
| BUG-508 (prix plein fige, migrations sales/0011 et 0012) | VERIFIE (ticket deja VERIFIE cote production ; volet migration confirme) | Aller-retour 0011 -> 0010 -> feuille sur lignes normales et soldees aux prix 50/150/300/500 : normal = prix fige, soldee = prix catalogue exact (tarif inchange), `unit_price` et `line_total` jamais modifies, plus aucune ligne NULL. Idempotence (2 executions). Lignes deja remplies (321) preservees. 1203 lignes soldees (plus de 2 lots de 500) toutes remplies. Tarif change apres coup : 300 exact, 150 reconstitue a +/-1 FC (limite deja documentee, pas un nouveau defaut). |
| BUG-197 (numeros de recu retroactifs) | VERIFIE (deja VERIFIE, recontrole) | Retroactif puis vente du jour puis remboursement retroactif : prefixes = `invoice_date`, compteurs independants par jour ; numero herite decale non reutilise (3 numeros distincts) ; fin d'annee. |
| BUG-519 (sync garde les prix) | VERIFIE | Vente soldee 113/150 poussee apres passage du tarif cloud a 400 : prix du noeud conserves, perte 370 ; ancien payload sans prix (ou `null` explicite) : tarif courant, inchange ; 0 accepte ; 100 000 001, 10^30, chaines de 40 chiffres, vide, dict, hex, Infinity, NaN : REJECTED sans creation ; rejeu du meme id avec d'autres prix : prix inchanges ; export `sync_now` transporte les deux prix. |
| BUG-527 (daily_summary 500 -> 400) | VERIFIE | 8 formes invalides (abc, 2026-13-45, 2026-02-30, 0000-00-00, injection, ISO avec heure, 5000 caracteres, annee 99999) en 400 + `detail`, gerant et siege ; formats ISO alternatifs (`20261122`, `2026-W47-7`, vide) jamais 500 ; `bread_summary` voisin avec `node=ZZZ` jamais 500. |
| BUG-526 / 528 / 529 | Hors Ventes (Production, Finance, Blockchain) : non verifies ici ; seule la partie Ventes (BUG-527) l'est. |
| BUG-385 (Sales.tsx) | VERIFIE (partie Sales.tsx) | 102 Ko -> 39 Ko + 11 fichiers `components/sales/`. Comparaison ancien/nouveau (`git show 977aeb0^`) : memes appels `*Api.*` (11 motifs, comptes identiques), aucun libelle francais perdu (seuls deux imports differents), aucun `any` ajoute, aucun axios direct. `npx tsc --noEmit` et `npm run build` : sans erreur. Rendu navigateur non controle (e2e). |

## Non-regression (inchangee)
BP cumulative (3000 commande, 1000 paye : BP 2000), prix pris dans `BreadPrice` (un `unit_price` envoye est ignore), blocage credit (BP = plafond et paiement < commande : 403 ; paiement = commande : 201 ; BP juste sous plafond : 201), remboursement sans ligne (commande 0, BP reduite), mentions du recu en API.

## Anomalies
Aucune nouvelle. Reserve connue (non ticketee) : reconstitution approximative a +/-1 FC du prix plein de vieilles lignes soldees dont le tarif avait change et dont le prix n'est pas multiple de 4.
