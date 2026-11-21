# Rapport testeur-production — Dev C — ronde 3 (2026-11-21)

Vérification indépendante des tickets Production au statut `CORRIGÉ`. Aucun code applicatif modifié. Tests : `backend/production/tests/test_verif_rotation_prod_c.py` (48 tests ; 3 `@expectedFailure` portant BUG-508, 509, 510). Les 54 tests existants des tickets 185 à 196 et 177 passaient avant. `npx tsc --noEmit` : exit 0. Les tickets frontend sont vérifiés par relecture de code et `tsc` (pas de contrôle navigateur).

## Verdicts
| Ticket | Verdict | Remarque |
|---|---|---|
| BUG-185 | VÉRIFIÉ | RG soldée comptée une fois, à prix plein ; jour calendaire local à 00:30 correct |
| BUG-186 | VÉRIFIÉ | répartition à 100 %, deux équipes le même jour, pas de division par zéro (écart d'arrondi de 0,02 sur 3 catégories égales) |
| BUG-188 | VÉRIFIÉ (code + tsc) | `suspended` masque sans démonter ; `OpeningStockConfirmationModal` reste montée |
| BUG-190 | VÉRIFIÉ | correction A↔B, idempotence, passage de minuit, concurrence simulée |
| BUG-191 | VÉRIFIÉ | reste d'hier compté une fois ; défaut annexe API seule : BUG-509 |
| BUG-192 | VÉRIFIÉ | `team` invalide ou non objet : 400 ; rétroactif explicite accepté |
| BUG-193 | VÉRIFIÉ | transfert confirmé à 00:30 local rattaché au jour local |
| BUG-194 | VÉRIFIÉ (portée) | 11 endpoints POST × 5 types de corps, aucun 500 ; défaut annexe : BUG-510 |
| BUG-195 | VÉRIFIÉ (code + tsc) | `BatchInProgressPanel.tsx` : en rotation ni `team` ni `date` envoyés |
| BUG-196 | VÉRIFIÉ | seul le nœud concerné est bloqué, pas de désignation fantôme, course simulée |
| BUG-170, 171, 174 | VÉRIFIÉ (code + tsc) | frontend seulement |
| BUG-177 (volet Clôture Journalière) | VÉRIFIÉ | NS PENDING comptée, NS annulée exclue ; `cleanup_expired` ne touche plus les NS |
| BUG-159 | laissé CORRIGÉ | objet caduc : voir contradiction ci-dessous |

## Nouveaux tickets (OUVERT)
- **BUG-508** (Mineur) : une RG soldée est valorisée au tarif courant du catalogue (rapport d'une journée passée : 6 000 → 7 000 FC après passage du tarif de 300 à 400), alors qu'une RG simple lit le prix figé de la ligne.
- **BUG-509** (Mineur, API seule) : confirmation de B (8, déclaré 10), désignation → A, confirmation de A (9) : reste d'hier -7 au lieu de -9.
- **BUG-510** (Mineur) : `POST sessions/<id>/close/` avec `remaining[].bread_price` non numérique ou 10^30 : HTTP 500 au lieu de 400.

## À signaler au coordinateur
- **Contradiction BUG-159 / BUG-303** : BUG-159 voulait une modale acceptant un reste négatif ; `remarque.md` (postérieur, prioritaire) a donné BUG-303 (négatifs refusés, `allowNegative={false}` et 400 serveur). Ticket à clore ou reformuler. La clôture forcée automatique enregistre toujours le stock physique, y compris négatif (testé).
- Non ticketé : en rotation, un `POST sessions` à corps vide crée une fournée vide (0 sac), alors que hors rotation `team` et `date` sont exigés (400) ; `approved: "false"` (chaîne) est traité comme vrai dans `respond_to_request`.
