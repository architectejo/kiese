# Testeur ventes - contrôle BUG-508/363 (2026-11-22-a)

Périmètre : migration `sales/0011_bug508_full_unit_price.py`, `InvoiceLine.save/loss`, sync.

## Résultats
- `manage.py test sales sync` (sans --parallel, base isolée du scratchpad) : 477 tests, OK. Nouveau fichier `sales/tests/test_verif_bug508_363_testeur_ventes.py` (5 tests, OK) ajouté après le lancement et exécuté à part.
- Migration (base isolée, jamais db.sqlite3) : 0010 -> 0011 -> 0010 -> 0011 sans erreur ; colonne retirée au retour arrière. Rétro-remplissage : normale 300 -> 300 ; soldée 300/225 -> 300 ; soldée 50/38 -> 50 ; soldée 150/113 avec tarif déjà passé à 400 -> 151 (déduction approchée, limite documentée, pas de ticket).
- Création normale / soldée / RG : `unit_price` et `full_unit_price` figés ; après changement de tarif (150 -> 400) re-save : `unit_price`, `full_unit_price`, `loss` (370 FC) inchangés.
- Ligne ancienne sans champ (NULL) : `loss` retombe sur le catalogue, sans erreur.
- Totaux et reçu : `InvoiceLineSerializer` n'expose pas `full_unit_price`, `line_total` inchangé ; ThermalReceipt n'utilise pas le champ -> aucun changement.
- Sync : `_push_invoice_line` crée via `InvoiceLine.objects.create` (champ rempli par `save()`), met à jour par `update()` (champ non touché) ; rejeu d'un évènement ancien sans le champ OK, évènement avec `full_unit_price` inconnu ignoré. `sync_now` n'envoie que id/invoice/bread_price/quantity ; le pull ne concerne pas les lignes. Aucun défaut.
- Observation (préexistante, pas de ticket) : le cloud recalcule les prix de la ligne à partir de SON catalogue à la création ; `full_unit_price` hérite de ce comportement.

## @expectedFailure
Retirés dans `test_verif_bug323_324_testeur_ventes.py` : `test_bug331_negatifs_et_enormes_rejetes_sans_exception` et `test_bug332_non_entiers_et_booleens_rejetes` (passent réellement). Tickets BUG-331/332 déjà VÉRIFIÉ ; ligne « Test » mise à jour.

## Tickets ouverts
Aucun. BUG-508/363 : migration et modèle conformes ; la clôture de statut reste au testeur-production.
