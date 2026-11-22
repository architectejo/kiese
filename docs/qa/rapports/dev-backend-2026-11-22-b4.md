# Rapport dev-backend (Dev B) - 2026-11-22 - lot b4

## BUG-519 : CORRIGÉ
- Cause : `_push_invoice_line` créait la ligne sans prix ; `InvoiceLine.save()` figeait le tarif courant du cloud.
- Correctif : `sync/services.py` (nouveau `_parse_line_price`, entiers FC >= 0 validés en Decimal ; booléen, flottant, négatif, non numérique, fractionnaire, hors borne -> REJECTED). `full_unit_price` est passé à `create()` (donc `save()` n'est pas affaibli : il ne relit le catalogue que si la valeur est None). `unit_price` exact du nœud est réappliqué par `update()` si différent du calcul de `save()`, avec `line_total` cohérent. Ancien payload sans ces champs : comportement inchangé.
- Export : `sync/management/commands/sync_now.py` ajoute `unit_price` et `full_unit_price` aux lignes de facture.
- Test : `sync/tests/test_bug519_invoice_line_prices.py` (4 tests).
- Contrat : champs optionnels ajoutés au payload `sales.InvoiceLine`; pas de ticket frontend.
- Risque : la mise à jour d'une ligne existante (BUG-321) n'est pas modifiée ; `desktop/` non touché.
