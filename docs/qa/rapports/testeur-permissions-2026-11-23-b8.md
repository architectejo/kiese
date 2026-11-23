# Testeur permissions - ronde b8 - 2026-11-23

Fichier de tests : `backend/core/tests/test_verif_permissions_b7_v7.py` (35 tests, OK avec 5 `@expectedFailure`). Log : `$TEMP/b8.log`. SQLite. Code applicatif non modifié.

## Tickets VÉRIFIÉS (7)
- BUG-890 (ventes) : 5 scénarios (ajustement +/- en attente puis annulation mère, versement, plusieurs ajustements, annulation répétée, livraison puis ajustement non régressé) : résumés propres, BP et stock restitués.
- BUG-891 : création par push toujours PENDING pour 3 jetons x 9 statuts (y compris `None`, entier, liste) ; PENDING et défaut restent acceptés.
- BUG-892 : 6 rôles x 7 corps non objets : jamais 500 (400/403).
- BUG-893 : période close immuable (PATCH et PUT, month/year/node, 3 rôles siège) ; période ouverte vide ou changement identique toujours possibles ; période ouverte avec commissions refuse mois/année/nœud ; gérant/facturier/livreur/autre nœud refusés.
- BUG-894 : `quantity_received` > 2e9, négatif, non ASCII, booléen, exponentiel, flottant, liste : sans effet à la création et à la mise à jour ; 0, 10, "10" acceptés.
- BUG-895 : chaque champ de `ascii_digit_fields` (Config x7, Client x3, Node, BreadPrice) refuse « ٣ » et « １２ ».
- BUG-896 : 20 formes exotiques refusées (non ASCII, 1e3, +3, 0x3, 3.5, vide...) ; "5", "5.0", "5.00", 5, 0, "0" acceptés.

## Relecture du changement de portée de BUG-895
Aucun champ légitime refusé : décimaux avec point, entiers JSON, flottants JSON, valeurs avec espaces ASCII autour, `null`, chaîne vide, multipart, libellés accentués/arabes (champs texte non concernés). Le parseur Excel clients (`clients/imports.py`) et `seed_kiese` n'utilisent pas ces serializers. Réserve sans ticket : une valeur entourée d'espaces insécables (U+00A0) était auparavant nettoyée par DRF et est désormais refusée ; sans impact (le frontend envoie des nombres).

## Nouveaux tickets (3)
- BUG-897 (Mineur) : chiffres non ASCII encore acceptés sur les montants hors mixin : dépense (201), journal, épargne, commissions (order_value, 4 retenues, set_manuel), `Node.monthly_social_contribution`/`card_fee_fc`, `payment_amount` facture (création et ajustement). Recommandation : un champ décimal/entier ASCII partagé plutôt qu'une liste par serializer.
- BUG-898 (Majeur) : push `LocalExpense` accepte un montant -500, 0 ou absent (REST exige > 0).
- BUG-899 (Mineur) : push `LocalExpense` accepte une catégorie `scope=DIRECTION` depuis une boulangerie.

## Constats sans ticket
- Push `LocalExpense` avec catégorie désactivée : accepté (cohérent avec une dépense saisie hors ligne avant la désactivation) ; à confirmer côté métier.
- `DISPUTED -> CONFIRMED` : impossible par push pour les 3 jetons (conforme) ; seule la voie REST `resolve_dispute` conclut (émettrice/siège, motif obligatoire, 2e résolution refusée).
- Isolation push : dépense et rapport facturier destinés à une autre boulangerie refusés (régression gardée).

Nombre de nouveaux tickets : 3 (BUG-897, 898, 899).
