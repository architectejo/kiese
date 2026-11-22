# Rapport dev-frontend — 2026-11-22 (a) : « Caisse » / « Clôture Journalière » et « Versement » direction

Ticket : BUG-383 (CORRIGÉ). BUG-382 : volet 2 (« Versement ») traité ici ; volet 1 (envoi direct de pains, Production) reste OUVERT. Aucun ticket passé à `VÉRIFIÉ`.

## 1. Ce qui a été déplacé où

Ancienne page « Clôture & Caisse » (`frontend/src/pages/dashboard/Treasury.tsx`, 2 895 lignes) scindée.

| Section d'origine | Classée | Nouvel emplacement |
|---|---|---|
| Barre KPI (cash, crédit, solde comptable, écart billetage) | Clôture | `ClotureOperations` |
| §5.1.1 Niveau 1 : rapports facturiers par équipe (génération, date rétroactive, validation, impression, récap production) | Clôture | `ClotureOperations` |
| « Versement » = billetage du gérant, écart, notes, date rétroactive | Clôture | `ClotureOperations` |
| §5.1.2 Dépenses locales + historique mensuel | Clôture (lecture conservatrice, voir §3) | `ClotureOperations` + `ExpenseHistoryModal` |
| Synthèse globale des billetages (siège) | Clôture | `ClotureOperations` |
| Clôtures du jour (confirmer / infirmer / inscrire au livre) + détail | Clôture | `ClotureOperations` + `ClosureDetailModal` |
| §5.1.3 Livre de Caisse Direction, vérification d'intégrité, comptage physique direction | Caisse | reste dans `Treasury.tsx` |
| Bordereaux de Versement — Décaissements Direction | Caisse | reste dans `Treasury.tsx` |
| §5.1.4 Journal de Caisse par boulangerie | Caisse | reste dans `Treasury.tsx` |
| §5.1.5 Épargne journalière | Caisse | reste dans `Treasury.tsx` |

- `Treasury.tsx` (route `/treasury` conservée, aucun lien cassé) : titre « Caisse », menu « Caisse » (`DashboardLayout.tsx`). Un sélecteur de succursale du siège a été ajouté à son en-tête (il était dans l'en-tête du Niveau 1).
- `ClotureJournaliere.tsx` : affiche `<ClotureOperations />` sous le rapport consolidé (titre « Opérations de clôture du jour »).
- Permissions inchangées : routes `/treasury` et `/cloture-journaliere` gardent `ADMIN, DIRECTION, COMPTABLE, GERANT` ; `canConfirm` (siège), `canWriteTreasury`, `can_access_all_nodes` appliqués comme avant ; le serveur reste l'autorité.
- Aucun appel d'API modifié (sauf l'ajout de la lecture `closures.versements`, §2).

## 2. « Versement » visible de la direction centrale (remarque l.456)

- API utilisée : `GET /api/treasury/closures/versements/?date=&node=` (BUG-381, `dev-backend-2026-11-22-a6.md`). Ajouté `treasuryApi.closures.versements` et les types `VersementStatus`, `VersementRow`, `VersementsResponse` dans `src/api/services.ts`.
- Nouveau composant `ClosureVersementReadOnly` : une ligne par boulangerie (statut NON VERSÉ / EN ATTENTE / CONFIRMÉ / INFIRMÉ, entrées cash, dépenses, caisse nette, espèces physiques, écart), totaux et cumul des billets, filtre de date (jamais future) et filtre de succursale (sélecteur du Niveau 1). États chargement / erreur (`detail` affiché) / vide. Tableau défilant horizontalement à 360 px.
- Visible pour `ADMIN` et `DIRECTION` seulement, lecture seule ; la saisie du billetage reste celle du gérant.

## 3. Décisions à confirmer (je n'ai pas tranché)

1. **COMPTABLE et « Versement »** : remarque l.307 (« enlève la partie Versement chez le comptable ») vs l.456 (« visible chez les membres de la direction centrale »). Lecture conservatrice : la section n'est PAS montrée au COMPTABLE (l.307 respectée). L'API l'autoriserait ; pour l'ajouter, élargir `canViewVersementReadOnly` dans `ClotureOperations.tsx` à `COMPTABLE`. À confirmer : « direction centrale » inclut-elle le comptable ?
2. **Dépenses locales = clôture ou caisse ?** Classées « clôture » car elles alimentent la caisse nette et l'écart du billetage et la remarque l.309 impose l'ordre dépenses -> billetage -> écarts sur le même écran. Si le client les veut dans « Caisse », il faudra les extraire de `ClotureOperations` (composant et modale déjà isolés).
3. **Rapport facturier §5.1.1** : classé « clôture » (c'est le Niveau 1 de la clôture, et la validation des rapports précède le billetage).
4. **« Bordereaux de Versement — Décaissements Direction » et « Comptage physique direction »** : restent dans « Caisse » (sorties de caisse / contrôle du livre de caisse, pas des options de clôture). Attention au vocabulaire : « Versement » (billetage du gérant = clôture) et « Bordereaux de Versement » (décaissements direction = caisse) sont deux choses distinctes à l'écran.
5. **Deux sélecteurs de succursale côté siège** dans « Clôture Journalière » : celui du rapport consolidé (par code, obligatoire) et celui des opérations (« Toutes les succursales » par défaut, comme l'ancienne page). Les opérations sont toujours celles du jour courant (comportement d'origine, plus la date rétroactive si activée) ; elles ne suivent pas la date choisie dans le calendrier du rapport. À confirmer si le client veut un sélecteur unique.
6. **Aucune contradiction entre documents de référence** n'a été tranchée par moi ; seule l.307/l.456 de remarque.md est signalée (même document).

## 4. Fichiers

Modifiés : `frontend/src/pages/dashboard/Treasury.tsx` (2 895 -> ~1 370 lignes), `frontend/src/pages/dashboard/ClotureJournaliere.tsx`, `frontend/src/components/layout/DashboardLayout.tsx` (libellé), `frontend/src/api/services.ts` (types + `versements`), `docs/qa/REGISTRE_BUGS.md` (BUG-383, note sur BUG-382).
Créés (`frontend/src/components/treasury/`) : `ClotureOperations.tsx`, `ClosureVersementReadOnly.tsx`, `ClosureDetailModal.tsx`, `ExpenseHistoryModal.tsx`, `treasuryShared.tsx`.
Aucun nouveau `any`. Restent volumineux : `ClotureOperations.tsx` (~1 340 lignes) et `Treasury.tsx` (~1 370) ; extraire le panneau Niveau 1, les dépenses, le journal et l'épargne en sous-composants est un suivi recommandé (non fait pour limiter le risque de régression sur un déplacement de ce volume).

## 5. Sorties

- `cd frontend && npx tsc --noEmit` : aucune erreur, aucune sortie.
- `npm run build` : `✓ built in ~20 s` ; seul avertissement : taille de chunk > 500 kB (préexistant, hors périmètre).
- Aucun test e2e lancé (consigne : pas de testeur ; scénarios e2e à adapter, voir §6).

## 6. e2e concernés (périmètre B, non modifiés)

Les parcours qui lisent le contenu de clôture sur `/treasury` doivent viser `/cloture-journaliere` (même contenu, sous le rapport consolidé) :
- `e2e/tests/06-tresorerie-caisse.spec.ts` : `fixme` clôture gérant (l.50) et versement (l.65) ; le commentaire l.35 cite l'ancien titre « Clôture & Caisse — 3 Niveaux » ; le test du Livre de Caisse (l.9, l.31) reste valide sur `/treasury`.
- `18-vague5-verification-db.spec.ts` : BUG-242 garde de route (inchangée, valide) ; BUG-276 (l.64-90, « Saisir le nombre de coupures », « Valeur Faciale », POST `closures`) -> à passer sur `/cloture-journaliere`.
- `21-cycle-final-cloture-transfert.spec.ts` (l.42, « Clôture créée », « Clôture de caisse bloquée ») et `22-cycle-final-treso-lecture.spec.ts` (l.11-17 : « Saisir le nombre de coupures », CONFIRMÉE, « Inscrit au grand livre », « Espèces physiques: 13 500 FC »).
- `24-verif-bug298-299.spec.ts` (l.21 : cartes « ÉCART BILLETAGE » / « SOLDE COMPTABLE CAISSE », « Écart: +500 FC »).
- `10-regression-remarque-2026-10-30.spec.ts` l.213 : Journal de Caisse §5.1.4 -> reste sur `/treasury`, inchangé.
- `17`, `19`, `23` : gardes de routes / liens `a[href="/treasury"]` : inchangés (route et garde conservées).
Aucun libellé de menu « Clôture & Caisse » n'est testé par un e2e (seulement le commentaire l.35 du 06).

## 7. Vérification manuelle attendue (testeur)

1. Connexion gérant (ex. K4) : menu « Caisse » (plus « Clôture & Caisse »). `/treasury` : titre « Caisse », Journal de Caisse et Épargne présents ; plus de rapports facturiers, billetage, dépenses ni clôtures.
2. Gérant -> « Clôture Journalière » : rapport consolidé puis « Opérations de clôture du jour » : KPI, §5.1.1, « Versement » (billetage -> écart, validation de la clôture, erreurs serveur affichées), dépenses (ajout, historique), clôtures du jour. Parcours inchangé par rapport à l'ancienne page.
3. DIRECTION / ADMIN -> « Clôture Journalière » : section « Versement » (Lecture seule) avec 8 lignes (versé / non versé), totaux, billets ; changer la date et la succursale ; confirmer / infirmer une clôture dans « Clôtures du jour » met à jour le tableau.
4. COMPTABLE : confirme/infirme les clôtures, ne voit pas la section « Versement » (voir §3.1). Livre de Caisse visible dans « Caisse ».
5. DIRECTION -> « Caisse » : sélecteur de succursale dans l'en-tête, Livre de Caisse, Bordereaux, comptage physique, Journal, Épargne.
6. Largeurs 360 / 768 / 1440 px : pas de débordement de page (tableaux en défilement horizontal interne). `/treasury` et `/cloture-journaliere` refusés au facturier / livreur (inchangé).
