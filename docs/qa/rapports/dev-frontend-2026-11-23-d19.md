# Rapport dev-frontend (Dev B) — 2026-11-23 d19

| Ticket | Statut | Résumé |
|---|---|---|
| BUG-685 | CORRIGÉ | Export clôture : « Appro Reçu » signé négatif comme l'écran (BUG-675) |

Cause : `clotureReportExport.ts` écrivait `appro_recu` en positif (Excel et HTML).
Correction : helpers `approRecuQty/Fc` (Excel, nombres natifs négatifs) et `approRecuQtyText/FcText` (HTML), même règle que `ClotureJournaliere.tsx` (> 0 => négatif). Aucun nouveau `any`, backend intact.
Vérifications : `npx tsc --noEmit` OK, `npm run build` OK. Pas de test E2E pour cet export : vérification manuelle décrite dans le ticket.
