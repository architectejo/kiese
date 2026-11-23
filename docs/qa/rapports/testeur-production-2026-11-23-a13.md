# Testeur production - ronde a13 (2026-11-23)

Fichier : `backend/production/tests/test_verif_production_a13_v13.py` (29 tests, 9 `@expectedFailure`, 0 échec ; `OK (expected failures=9)`).
Banc : un cloud + postes K1/K2/K3 simulés dans une base de test ; l'état (transferts, lignes, stocks de pains, notifications) de chaque site est sauvegardé/rechargé à chaque changement de site. Cycle = `build_outbound_payload` -> push -> pull -> `apply_push_response` + `apply_pull_response`. Actions REST jouées sur le poste concerné ou sur le cloud (siège).

## Vérifiés (VÉRIFIÉ)
- BUG-964 : pull de K1 et K2 contient transfert + lignes, K3 rien ; la réceptrice recrée le transfert sans mouvement de stock. BUG-965 : K2 exporte sa validation, pas de réexport après succès, K3 n'exporte rien.
- BUG-966 : matrice DISPUTED -> CONFIRMED (réceptrice, émettrice, tiers, lignes alignées/non alignées/sans reçu) ; BUG-967 / 968 : normalisation entière ou rejet motivé (`'1e1'` rejeté avec motif, jamais « erreur serveur »).
- Flux : envoi 100 / validation 100 (K1 -100, K2 +100, somme groupe inchangée, 3 cycles de rejeu sans double mouvement, K3 intact) ; demande -> réponse -> écart 98 -> litige -> blocage clôture K2 (K1, K3 non bloqués) ; multi-lignes avec écart sur une ligne ; double validation ; émettrice/tiers ne valident pas ; recomptage K2.
- Transferts de plus de 30 jours : exclus si CONFIRMED/CANCELLED, présents si PENDING/RESPONDED/DISPUTED.

## Limites annoncées par d35 : verdict
- Ordre transfert/lignes : première confirmation de recomptage refusée, acceptée au cycle suivant. **Acceptable** (converge en 2 cycles, l'état local n'est pas écrasé pendant l'intervalle).
- Résolution émettrice (poste) : **défaut réel** (BUG-974) : cloud DISPUTED à vie, clôture de K2 bloquée.
- Résolution / confirmation du siège : **défaut réel** (BUG-975 : lignes non alignées, blocage persistant en ALIGN_ON_RECEIVED ; BUG-976 : aucun stock miroir, somme groupe 98 au lieu de 100 ; confirmation siège : K2 reçoit CONFIRMED sans les 100 pains).
- Copie locale en retard : même cause que BUG-976 (défaut réel).

## Nouveaux tickets (7) : BUG-974 à BUG-980
974 émettrice (Majeur), 975 lignes non alignées au pull (Majeur), 976 stock miroir (Majeur), 977 `flow` perdu (Mineur), 978 alertes non synchronisées (Majeur), 979 lignes jamais complétées à statut égal (Mineur), 980 fenêtre 30 jours (Mineur).
