# Rapport testeur-ventes — 2026-10-30 — Vérification BUG-090

## Ticket

BUG-090 — `Sales.tsx` n'offrait aucun moyen d'enregistrer un paiement sans commande de pain
(remboursement de dette / dépôt « client épargne »). Corrigé par dev-frontend, jamais vérifié
indépendamment avant cette session.

## Verdict

**VÉRIFIÉ.** Registre mis à jour (`docs/qa/REGISTRE_BUGS.md`, ligne du tableau + fiche détaillée
BUG-090, section « Vérification »).

## Contrôles effectués

1. **Relecture du diff réel**
   - `frontend/src/api/services.ts:779-787` — `salesApi.createRepayment` poste toujours
     `lines: []` et `is_debt_repayment: true`. Aucune ligne de pain fantôme possible. Signature
     rétrocompatible (3ᵉ paramètre `invoiceDate` optionnel) — `Clients.tsx:667` continue d'appeler
     avec 2 arguments sans erreur de type.
   - `frontend/src/pages/dashboard/Sales.tsx` : bouton « Remboursement / Dépôt sans commande »
     visible uniquement si `!isOccasional && selectedClient` (ligne 831), message explicatif si
     « Vente occasionnelle » est cochée (ligne 667-671), champ de date rétroactive dans la modale
     affiché seulement si `allowBackdatedSales` (ligne 1060, `max` = aujourd'hui ligne 1070),
     `handleRepaymentSubmit` (ligne 228-273) construit un reçu à 0 ligne et recharge la file sans
     passer par le mécanisme « en attente de livraison ».

2. **Reproduction end-to-end** — aucun outil de pilotage navigateur n'étant disponible dans cet
   environnement d'agent, la reproduction a été faite au niveau API avec `rest_framework.test.APIClient`,
   en reconstituant exactement le payload envoyé par `Sales.tsx` (même client factice `BUG090-TMP`,
   dans une transaction Django annulée volontairement, aucune donnée persistée) :
   - Remboursement partiel (BP 20 000 → versement 5 000) : `debt_after = 15 000`, `order_total = 0`,
     `commission_rate = 0`, `status = DELIVERED` immédiatement (jamais `PENDING`).
   - Versement supérieur à la dette (15 000 → versement 30 000) : `debt_after = -15 000`, accepté
     sans blocage 403 (dépôt épargne autorisé, conforme CLAUDE.md §5.1/§5.2).
   - `BreadStock` inchangé, 0 `InvoiceLine` créée, 0 facture `PENDING` / 2 `DELIVERED` pour ce client
     — confirme l'absence de double traitement « livraison en attente » pour un paiement pur.
   - Sans client (`client: None`), le backend refuse explicitement (400) — cohérent avec la garde
     frontend (bouton absent si vente occasionnelle).

3. **Date rétroactive** : champ conditionné à `Config.allow_backdated_sales`, `max` = date du jour,
   même garde que BUG-083/086 déjà vérifiés. Aucune divergence.

4. **Non-régression**
   - `npx tsc --noEmit` → aucune erreur.
   - `npm run build` → succès (exit code 0), seul avertissement préexistant (chunk `index-legacy`
     > 500 kB), sans rapport avec ce ticket.
   - `python manage.py test sales` → 58 tests, tous passent.
   - Flux de facturation normale (`handleSubmit`, lignes de pain) non modifié, relu pour confirmer
     l'absence d'impact du nouveau code.
   - `Clients.tsx` : appel `createRepayment(repaymentClient._apiId, amount)` à 2 arguments toujours
     valide avec la nouvelle signature à 3 paramètres optionnels.

5. **Base réelle** : toute vérification manuelle a été faite dans une transaction annulée
   (`transaction.atomic()` + exception de contrôle). Aucune donnée fictive persistée
   (`BUG090-TMP` absent de `clients_client` après coup). `PRAGMA integrity_check` → `ok`.

## Limite signalée

Pas d'outil de pilotage navigateur dans cet environnement d'agent pour cette session : la
vérification visuelle stricte (rendu réel du bouton/modale à 360 px, absence de défilement) s'appuie
sur une relecture de code cohérente plutôt que sur une capture d'écran réelle. Le code relu ne laisse
pas d'ambiguïté sur ces points, mais un recontrôle visuel est recommandé si un outil navigateur
devient disponible pour l'équipe QA.

## Fichiers concernés

- `D:\Projects\kiesse\frontend\src\pages\dashboard\Sales.tsx`
- `D:\Projects\kiesse\frontend\src\api\services.ts`
- `D:\Projects\kiesse\frontend\src\pages\dashboard\Clients.tsx` (lu pour non-régression, non modifié)
- `D:\Projects\kiesse\backend\sales\views.py` (lu pour confirmer le contrat serveur)
- `D:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` (mis à jour : statut VÉRIFIÉ + fiche de vérification)
