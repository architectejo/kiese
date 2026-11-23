# dev-frontend B-4 (2026-11-23) : BUG-1203 (demandé « 1105 », occupé par la plage : plus haut libre = 1203)

Droits avant : menu ADMIN/DIRECTION/COMPTABLE/GERANT = Tableau de bord ; Clientèle + Facturation = ADMIN/DIRECTION/GERANT/FACTURIER ; Production = ADMIN/DIRECTION/GERANT ; routes /dashboard, /clients, /sales/*, /production ouvertes à tout rôle connecté (FACTURIER et LIVREUR arrivent sur /dashboard après login). LIVREUR : aucun menu.

Modifications (frontend seul) :
- DashboardLayout.tsx : LIVREUR ajouté à Gestion Clientèle et Facturation ; boîte stock de départ et fin de relève (canSeeShiftEnd) étendues au LIVREUR comme au FACTURIER.
- FourneesTab.tsx : même extension (bouton rotation).
- App.tsx : `isAllowed={FIELD_ROLES.includes(role)}` sur les 4 routes (les six rôles, donc aucun droit retiré, superuser inclus). Commissions, caisse, clôture, finance, blockchain, admin restent fermés au LIVREUR (inchangés).
- Aucun test de rôle FACTURIER seul ne masque de bouton dans Sales/Clients ; Production/Clients/Dashboard traitent déjà LIVREUR comme FACTURIER.

Vérifs : `npx tsc --noEmit` OK, `npm run build` OK. Non vérifié visuellement (pas de navigateur) : connexion LIVREUR, menu à 360 px.

Routes API refusées au LIVREUR (`IsFacturier` au lieu de `IsFacturierOrLivreur`), à traiter par dev-a/dev-b :
- clients : ClientViewSet `create` (clients/views.py l.59)
- sales : InvoiceViewSet `create` (sales/views.py l.304) et action `cancel` (l.1007)
- production : confirmation du stock de départ (views.py l.3626) et désignation d'équipe (l.4023)
Tant que non corrigées, le livreur voit ces boutons mais reçoit un 403 (detail affiché).
