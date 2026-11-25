# Rapport de tests — dev-a (2026-11-25)

Ordre du responsable : série de tests de dev-a ; répartition dans `docs/COMMUNICATION_A_B.md` (#51-A). Rapport en cours de rédaction : complété au fil des résultats.

## 1. Version testée
Branche `dev-a`, base `5e12db5` (fusion de `dev-b` `50623ad` + BUG-1300 + BUG-1302).

## 2. Tests automatisés (backend, base SQLite isolée, `KIESE_TEST_CLOCK_SHIFT=1`)

| Groupe | Résultat |
|---|---|
| `core clients commissions sync chat` | Ran 2 298 — FAILED (failures=3, errors=28) : 30 dus à BUG-1302 (outil de test, corrigé), 1 concurrence SQLite à rejouer seul |
| `production` | Ran 1 731 — **OK** (expected failures=5) |
| `sales treasury finance blockchain` | en cours |

Frontend : `npx tsc --noEmit` propre ; `npx vitest run` 10/10 OK ; `npm run build` OK (4 min 21 s).

## 3. Tickets
- BUG-1300 (fausse alerte Q-021 quand l'appelant est un agent de la boulangerie) : CORRIGÉ (`11f6d94`), à vérifier par dev-b.
- BUG-1301 (verrou de vente sans clôture la veille) : À CLARIFIER (client) — **reproduit en réel** sur installation neuve : interrupteur coché -> K1 bloqué car le 24 n'a aucune clôture.
- BUG-1302 (runner de test / throttle DRF, 28 erreurs) : CORRIGÉ (`5e12db5`), à vérifier par dev-b.
- BUG-1303 (message de blocage « direction » au lieu de « direction ou le comptable ») : CORRIGÉ (`bb887aa`), à vérifier par dev-b.
- BUG-1304 (page Clôture Journalière positionnée sur la journée en cours au lieu de la journée terminée que le verrou exige) : OUVERT, correction en cours (dev-frontend).

## 4. Contrôles API et Chrome (instance jetable 8001 / 5174, base neuve `seed_kiese`, comptes fictifs)

| Contrôle (ticket de B vérifié) | Rôle / taille | Résultat |
|---|---|---|
| Rotation active par défaut sur les 8 boulangeries, SIEGE exclu, clôture 12:00 (BUG-1122) | API | OK |
| Facturation refusée sans équipe désignée (`TEAM_NOT_ASSIGNED`), acceptée après désignation | facturier K1, API | OK |
| Date de travail venant du serveur (`work_date`, `current_work_date`) (BUG-1131/1134) | API | OK |
| Alerte « Clôture sans personne connectée » : 1 seule notification après 2 appels direction ; visible du comptable ; invisible du gérant K1 ; pas d'alerte quand le facturier K1 appelle (BUG-1125 + BUG-1300) | API + Chrome (cloche, bureau) | OK — orange, 3 lignes lisibles |
| Blocage immédiat des ventes (interrupteur coché, clôture de la veille non validée) puis déblocage (BUG-1123) | facturier K1, API | OK (403 puis 201) ; texte corrigé par BUG-1303 |
| Comptable : section « Versement » en lecture seule, menu Caisse / Clôture (BUG-1126) | comptable, Chrome bureau | OK |
| Clôture Journalière côté gérant après midi | gérant K1, Chrome bureau | **KO -> BUG-1304** |
| Modale « Stock de départ du jour » (libellé, « clôture à 12:00 ») | gérant K1, Chrome bureau + POS 360 px | OK |
| « Stock Pains du Jour » (stock de départ, vendu, envoyés, reçu, TOTAL) | gérant K1, Chrome bureau | OK |

Reste à voir à l'écran : boutons confirmer / infirmer du comptable sur une clôture réelle (après BUG-1304), bannière de blocage au POS.
