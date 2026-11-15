# Rapport testeur-ventes — 2026-11-15

Vérification indépendante de BUG-286, 287, 288 et du volet backend de BUG-290. Aucun code applicatif modifié. Base isolée : `DB_NAME=%TEMP%/verif290.sqlite3` (`db.sqlite3` non touché), venv `backend/.venv`.

Fichier de tests : `backend/sales/tests/test_verif_bug290_286_287_288_2026_11_15.py` — 18 tests, **OK** (71 s).

## Résultats
| Ticket | Scénarios contradictoires | Verdict |
|---|---|---|
| BUG-290 | Négatif sur versement à BP = plafond exact : 403, notification, BP et nombre de factures inchangés. BP 49 999 : -1 000 accepté (BP 50 999), le suivant bloqué, un versement positif reste possible. Vente avec lignes et paiement négatif : bloquée au plafond, BP exacte (1 000 + 1 000 + 500 = 2 500) sous le plafond. Déficit du mois : 403 « Déficit… ». 0 refusé (400). Motif invalide 400, absent = vide, valide conservé. Valeurs extrêmes (`abc`, `1e400`, -99999999999999999, -0,001, vide) : jamais 500. Sans client : 400. RG, NS, NV avec paiement négatif : ne contournent pas le blocage. Annulation PENDING d'une vente à paiement négatif : BP restaurée. Reçu : numéros distincts, sans ligne, livré immédiatement. Nœud forcé : ignoré ou refusé. `daily_summary` (retrait + vente + RG + solde) : CASH -2 000, CREDIT +4 000, BP -6 000 / 0. Rapport facturier : cash -3 000, crédit 4 000. | VÉRIFIÉ (backend) |
| BUG-286 | Vente facturée à 23:55, livrée à 00:10 : clôture de la veille à 0, clôture du jour à 3 000, cohérente avec `daily_summary` (0 puis 2 000). | VÉRIFIÉ |
| BUG-287 | RG hors CREDIT, CASH et count inchangés, BP de la RG = 0 ; CREDIT du jour = variation de BP. | VÉRIFIÉ |
| BUG-288 | VENTE SOLDE hors crédit du rapport facturier, cash compté, retrait compté +montant. | VÉRIFIÉ |

Registre mis à jour (notes « VÉRIFIÉ » sous chaque ticket). Les lignes de statut des tickets restent « CORRIGÉ » dans leur texte d'origine, la note de vérification fait foi.

## Points à signaler (non bloquants)
1. BUG-290 volet interface : le motif n'est pas encore dans `Sales.tsx` (suivi dans BUG-301, ticket OUVERT). Le volet frontend n'a pas été revérifié ici (hors périmètre de ce passage).
2. Un versement négatif sur un client sous le plafond peut pousser sa BP au-dessus du plafond (49 999 -> 50 999) ; c'est voulu par la documentation de BUG-290, le suivant est bloqué. À confirmer par le client si une sortie de caisse ne doit jamais dépasser le plafond.
3. Le contrôle de non-régression du reste de la suite n'a pas été rejoué (le dev-backend annonce 1 304 tests verts) ; seul le module `sales` ciblé a été exécuté.
4. Ligne K3 n° 54 du 13/08 (-13 000 FC) toujours à confirmer par le client.

## Conclusion
Aucune réouverture. BUG-286, 287, 288 : VÉRIFIÉ. BUG-290 : VÉRIFIÉ pour le backend (le ticket complet dépend de BUG-301 pour le motif en interface).
