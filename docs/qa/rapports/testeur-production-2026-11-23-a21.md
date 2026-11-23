# Testeur-production, cycle 22 partie A (a21), 2026-11-23

Fichiers : `backend/production/tests/test_verif_production_a21_v21.py` (22 tests), `backend/sales/tests/test_verif_ventes_a8_v8.py` (12 tests). Résultat réel : 34 tests, OK (log `$TEMP/a21.log`). Aucun code applicatif modifié, aucun commit.

## BUG-1031 à 1035 : tous VÉRIFIÉ
- 1031 : matrice complète sans exclusion (mouvements REST/push, comptages REST/push, inventaire, sacs REST/push) conforme à l'oracle ; `0.3330`, `00.250`, `1.500`, ` 0.3330 ` acceptés et stockés exacts (0.333, 1.50) ; `0.3333`, `0.33301`, `1.505` refusés ; payload de l'appelant non modifié ; multipart OK.
- 1032 : prix négatif refusé 400 (message français, format `detail`) en REST (toutes formes, EXIT/ENTRY, PATCH) et au push ; prix absent ou nul accepté. Décision cohérente avec BUG-216 : une quantité d'entrée négative (correction) reste acceptée et ne bouge pas le CUMP ; un prix négatif combiné à une quantité négative est refusé (pas de contournement) ; le CUMP reste >= 0 après stock négatif puis entrée positive.
- 1033 : prix par parseur canonique, parité REST/push sur toute la matrice (`1_0`, `1e1`, non ASCII, NaN refusés ; 4 décimales).
- 1034 : une alerte « Stock négatif » par mouvement REST ou push qui laisse le stock sous zéro ; aucune à 0 ou positif ; pas de doublon à la re-sauvegarde ; sortie inchangée ; levure décimale OK.
- 1035 : écarts d'en-tête (100/98, 100/None, 100/0, 98/100, None/5) bloquent la réceptrice seule ; égal ou annulé ne bloque pas ; avec lignes une seule mention, la ligne fait foi.

## BUG-1050 / 1051 : VÉRIFIÉ
Diff relu (`sales/views.py` : create + cancel ; `production/views.py` : opening-confirmation + team-assignment ; seuls ces 4 passent à `IsFacturierOrLivreur`). Un parcours automatique de toutes les routes `/api/sales/` et `/api/production/` (GET/POST/PATCH/DELETE) montre : le livreur n'est jamais admis là où le facturier est refusé, et aucune différence facturier/livreur (liste vide). Adjust, cleanup, PATCH/DELETE facture restent fermés aux deux. Isolation par boulangerie tenue (annulation par un livreur de K2 : 403/404 ; `node` ignoré pour un non-HQ ; équipes C, J, N, vide refusées). Livreur sans boulangerie : même verdict que le facturier, pas de 500.

## Synchronisation de Invoice.facturier = livreur
Acceptée (push ACCEPTED). Observation, pas un ticket : `_push_invoice` ne lit pas `facturier`, la facture poussée a donc `facturier` NULL, que ce soit un facturier ou un livreur (comportement identique, non propre à 1050).

## Notes de méthode
Deux écarts de mes propres tests corrigés avant conclusion (inventaire du jour verrouillant les comptages suivants ; crawler d'abord vide à cause des URL sans slash final, refait).

## Nouveaux tickets : 0
Premier balayage propre depuis les derniers correctifs sur le périmètre production/ventes.
