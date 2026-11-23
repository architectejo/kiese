# dev-frontend (Dev B) - 2026-11-24 t2 - BUG-1115

Cause : B-4 (BUG-1203) avait ouvert /clients et /production aux six rôles (FIELD_ROLES), plus large que le menu.
Corrections (code, pas seulement le test) :
- /clients : ADMIN, DIRECTION, GERANT, FACTURIER, LIVREUR (= menu ; COMPTABLE n'a pas ce menu).
- /production : ADMIN, DIRECTION, GERANT (= menu) ; FACTURIER/LIVREUR/COMPTABLE -> « Accès refusé » comme /treasury.
- /dashboard : reste ouvert aux six rôles (atterrissage). /sales/* inchangé (le menu pointe /sales/create, non comparé).
Test adapté (intention conservée) : /dashboard n'est plus comparé en égalité, on exige seulement que la garde contienne tous les rôles du menu.
Vérification de la logique : ProtectedRoute affiche AccessDenied (avec lien vers /dashboard, ouvert) si isAllowed est faux ; pas de boucle d'enfermement. Contrôle par lecture du code, pas de navigateur lancé.
Résultats réels : npx tsc --noEmit OK ; npm run build OK (avertissement de taille de chunk préexistant) ; test Python bug407 : 5 tests OK.
