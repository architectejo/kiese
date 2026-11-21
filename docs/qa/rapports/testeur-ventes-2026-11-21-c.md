# Rapport testeur-ventes, ronde C, 2026-11-21

Vérification indépendante des tickets Ventes au statut CORRIGÉ (branche dev-c). Aucun code applicatif modifié.

## Verdicts
| Ticket | Verdict | Base |
|---|---|---|
| BUG-173 | VÉRIFIÉ | Lecture de `Sales.tsx` : `queueComplete` remis à false à chaque `loadData` (l.207), passé à true seulement si `serverIds.size === count` (BUG-172, l.269-274). Sous-titres des modals « Liste Complète » (l.1651) et « Total facturé » (l.1666) = « Chargement en cours (X/Y) — liste partielle. » tant que non complet ; compteur et « Cumul… » ensuite. `npx tsc --noEmit` : 0 erreur. |
| BUG-197 | VÉRIFIÉ | Nouveau `backend/sales/tests/test_verif_bug197_c.py` (5 tests) + `test_bug197_receipt_unique.py` (4) : 9 OK. |
| BUG-076 (volet Ventes) | VÉRIFIÉ (code) | Diff 4299fc5 : `printerWidthMm = prop ?? window.kiese?.printerWidthMm ?? 80`, `@media print` en `${printerWidthMm}mm`, échelle des polices 0,82 et aperçu 240 px à 58 mm, `buildPrintableHtml` et `printReceipt` reçoivent la même largeur. `Sales.tsx` (l.899) passe `window.kiese?.printerWidthMm ?? 80`. Contrat `preload.ts`/`kiese.d.ts` cohérent. tsc OK. Reste : rendu physique sur rouleau 58 mm réel (testeur-materiel), non vérifiable ici. |

## Tests écrits (test_verif_bug197_c.py)
- Frontière de mois : vente rétroactive au 30/11 puis vente du 01/12 : `V8-20261130-0001/0002`, `V8-20261201-0001`.
- Remboursement rétroactif : préfixe et compteur sur `invoice_date`.
- Ajustement (`/adjust/`) rétroactif : numéro unique, compteur partagé avec les ventes du même jour.
- Deux nœuds, même date : compteurs indépendants.
- Six créations mixtes sur 3 dates : tous uniques, préfixe = `invoice_date`.

## Résultats
- `manage.py test sales.tests.test_verif_bug197_c sales.tests.test_bug197_receipt_unique` : 9 tests OK.
- Suite `sales` complète : 384 tests OK (expected failures = 2, préexistants), 648 s.

## Observations non bloquantes (pas de ticket)
- BUG-173 : en cas d'erreur de chargement des pages suivantes (`queueError`), `queueComplete` reste faux et le sous-titre reste « Chargement en cours… liste partielle ». Honnête (jamais présenté comme final) mais un peu trompeur ; l'erreur est affichée par ailleurs.
- BUG-173 : « N facture(s) du jour » compte aussi les PENDING d'anciens jours (`pending_deliveries`), comportement antérieur au ticket.
- BUG-197 : l'unicité repose sur un test d'existence en boucle, sans contrainte en base ; la concurrence reste couverte par la transaction + verrou nœud (non rejouée ici sous SQLite).
