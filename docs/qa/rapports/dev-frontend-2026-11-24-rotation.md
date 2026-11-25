# Rapport dev-frontend, 2026-11-24 : rotation 24 h, journee midi a midi (BUG-1126)

Voir le ticket BUG-1126 du registre. Resume des modifications :

- Libelles : « Heure de cloture » (Nodes, TeamAssignmentModal, AutoClosedNoticeModal, CloseSessionModal, OpeningStockConfirmationModal) ; « Stock de depart du jour ».
- Roles : section Versement visible pour ADMIN/DIRECTION/COMPTABLE (`ClotureOperations.tsx`). Gardes de routes (App.tsx) et menu autorisaient deja le COMPTABLE sur /treasury ; les boutons de validation utilisent `canConfirmClosures` (ADMIN, DIRECTION, COMPTABLE, superuser).
- Bannieres et textes de blocage : « direction ou le comptable ».
- Notification « Cloture sans personne connectee » (WARNING) : style orange existant ; message du dropdown passe de 1 ligne tronquee a 3 lignes.
- Boulangerie : rotation activee par defaut a la creation et a l'edition si la valeur est absente.

Points a signaler au coordinateur :
- `block_sales_after_closure` reste decoche par defaut a la creation d'une boulangerie (la decision client « blocage immediat » suppose de le cocher ; defaut a decider cote backend/client).
- Les reponses 1130/1134 (date du jour = `work_date` serveur, plus `new Date()`) ne sont pas traitees ici (BUG-1134, a traiter apres livraison backend).
- Les creneaux A/B de la modale Nodes sont toujours affiches (heritage).

Verification : `npx tsc --noEmit` sans erreur ; `npm run build` OK (seul l'avertissement de taille de chunk preexistant). Pas de test E2E lance, pas de commit.
