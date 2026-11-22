# Rapport auditeur-comptable (Dev C) - cycle 4 - 2026-11-22

Etat : branche dev-b (contient dev-c), SQLite. Lecture seule du code applicatif, donnees fictives.
Tests : `backend/finance/tests/test_audit_c_cycle4_v4.py` (19 tests : 18 verts, 1 `@expectedFailure` BUG-870). Commande : `manage.py test finance.tests.test_audit_c_cycle4_v4` -> OK (expected failures=1).

## 1. Verification de BUG-850 a 854

| Ticket | Angles rejoues (en plus des tests du correcteur) | Resultat |
|---|---|---|
| BUG-850 | Facture CASH en attente puis non servie ; non servie apres une facture livree du meme client (BP 500) ; non servie datee de l'annee suivante (exclue de N-1) ; livraison avec ajustement negatif ; annulation toujours exclue | VERIFIE |
| BUG-851 | Deux ventes CLIENT DIVERS = une seule ligne agregee (qty 3, 1 500 / 1 500, code vide) ; ajustement negatif sur divers ; CSV : meme nombre de colonnes, ligne « CLIENT DIVERS » ; total DOC 1 = total du CA (2 500) | VERIFIE |
| BUG-852 | `abc`, `null`, absent, 2000.5 refuses (400) ; bornes 2000 et 2100 : les 4 etats + comparatif repondent 200 ; doublon refuse proprement (400) ; gerant 403 | VERIFIE |
| BUG-853 | `=`, `+`, `-`, `@`, tabulation, retour chariot, `=cmd|...` en nom ; prenom commencant par `=` ; nom normal inchange | VERIFIE |
| BUG-854 | Facture antidatee + ajustement negatif + remboursement BP : BP fin de mois = `current_debt` ; client d'une autre boulangerie (BP globale) ; facture non servie du mois suivant exclue | VERIFIE |

Les 5 tickets passent a VERIFIE dans le registre.

## 2. Recoupement N / N-1, DOC 1, formules

| Controle | Resultat |
|---|---|
| Bilan N-1 (exercice clos) = `current_debt` apres NS CASH/CREDIT, ajustement, livraison, annulation | Aucun ecart |
| DOC 1 : total COMMANDE = CA du compte de resultat (avec CLIENT DIVERS) | Egal (2 500) |
| DOC 1 : BP fin de mois = BP reelle (antidatage, ajustement, remboursement, multi-boulangerie) | Egale |
| Annees limites 2000 / 2100 : 4 etats + comparatif, N-1 isole | OK, aucune erreur |
| Arrondis Decimal : revenus entiers, couts arrondis a 2 decimales (BUG-806), JSON en chaines (BUG-807) | Inchanges, aucune derive |
| CLAUDE.md 5.2 (BP cumulative, `commande - paiement`) et 5.3 (CM, retenues) | Conformes (5.3 : remise annuelle, contradiction deja signalee) |
| Balance / bilan equilibre (actif = passif) | Toujours impossible (BUG-808, Q-003) : non rouvert |

## 3. Nouveau ticket

| Ticket | Gravite | Resume |
|---|---|---|
| BUG-870 | Mineur | DOC 1 ignore les factures « Non servi » : leur versement conserve (compte dans le cash facturier, `treasury/services.py`, et dans `total_payments` des commissions) manque a la colonne PAIEMENT ; le client n'a aucune ligne si c'est sa seule operation du mois. Exemple : cash 1 000 + versement non servi 400 -> DOC 1 = 1 000 au lieu de 1 400. Test `test_doc1_payment_total_includes_not_served_kept_payment` (`@expectedFailure`). |

Hors perimetre (non retraites, comme demande) : BUG-821, 822 (commissions), 824 ; points 804, 805, 808, 809 non rouverts.

## 4. Limites
SQLite seul. Aucun test visuel du frontend. L'inclusion des non servis dans DOC 1 depend du classeur DOC 1 du client (non verifie ici : `data_kiese/` non utilise) ; le ticket propose aussi de documenter l'exclusion.
