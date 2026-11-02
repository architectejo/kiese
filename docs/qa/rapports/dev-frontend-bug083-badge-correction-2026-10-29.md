# Rapport dev-frontend — BUG-083, complément badge « Correction » (2026-10-29)

## Mission
Compléter le volet frontend du BUG-083 : rendre visible, dans l'écran Livre de Caisse Direction
(`Treasury.tsx`), toute écriture de correction (`CashbookEntry.is_correction === true`) — point
d'intégrité explicitement demandé par le client (traçabilité, jamais invisible).

## Périmètre traité
- `frontend/src/api/services.ts` : interface `CashbookEntry` complétée avec les 4 champs déjà
  exposés par `CashbookEntrySerializer` (backend) mais absents côté frontend : `is_correction`,
  `correction_reason`, `corrected_by`, `corrected_by_display`, `correction_source_invoice`. Aucun
  nouveau `any`.
- `frontend/src/pages/dashboard/Treasury.tsx` (section Livre de Caisse Direction) :
  - Badge orange `badge-warning` + icône `FiRefreshCw` + texte « Correction » sur chaque ligne du
    tableau où `is_correction === true`, placé avant le libellé, avec infobulle reprenant le motif.
  - Dans la modale de détail d'une écriture (ouverte au clic sur une ligne) : badge répété dans
    l'en-tête + nouveau bloc dédié affichant motif (`correction_reason`), auteur
    (`corrected_by_display`) et référence à la facture d'origine (`correction_source_invoice`, UUID
    tronqué à 8 caractères, UUID complet en infobulle).
  - Aucun changement visuel pour les écritures normales (`is_correction === false`).

## Limite connue (à signaler, non bloquante)
`correction_source_invoice` n'est exposé par le backend que comme UUID brut de la facture (pas de
champ `*_display` donnant le numéro de facture lisible, à la différence de `corrected_by_display`).
La référence affichée dans la modale reste donc un UUID tronqué plutôt qu'un numéro de facture.
Suggestion pour le coordinateur : envisager un ticket `dev-backend` pour ajouter
`correction_source_invoice_display` (numéro de facture) si la Direction a besoin d'une référence
plus lisible au quotidien. Non bloquant : le motif et l'auteur sont pleinement lisibles et
suffisent déjà à satisfaire l'exigence de traçabilité du client.

## Vérifications effectuées
- `npx tsc --noEmit` : aucune erreur.
- `npm run build` : build de production réussi (seul avertissement préexistant sur la taille du
  chunk legacy, sans rapport avec cette session).
- Aucun test E2E existant pour ce parcours au moment de cette session : étapes de vérification
  manuelle détaillées consignées dans `docs/qa/REGISTRE_BUGS.md` (fiche BUG-083, sous-section
  « Complément — badge "Correction" dans le Livre de Caisse Direction »), à l'attention du testeur
  (testeur-tresorerie).

## Registre
Ticket BUG-083 complété dans `docs/qa/REGISTRE_BUGS.md` (nouvelle sous-section ajoutée après la
correction frontend existante, avant la section « Vérification » déjà en attente — statut global du
ticket inchangé : toujours CORRIGÉ, en attente de VÉRIFIÉ par testeur-tresorerie / testeur-ventes /
testeur-clients-commissions, jamais par moi-même conformément à CLAUDE.md §7.2/§7.3).

## Fichiers modifiés
- `D:\Projects\kiesse\frontend\src\api\services.ts`
- `D:\Projects\kiesse\frontend\src\pages\dashboard\Treasury.tsx`
- `D:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md`
- `D:\Projects\kiesse\docs\qa\rapports\dev-frontend-bug083-badge-correction-2026-10-29.md` (ce rapport)
