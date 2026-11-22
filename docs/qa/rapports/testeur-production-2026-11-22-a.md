# Testeur Production - vérification BUG-501/502/508/509/510 (Dev A, 2026-11-22-a)

Tests : `backend/production/tests/test_verif_bug501_510_a.py` (31 tests, 5 `@expectedFailure`). DB isolée via `DB_NAME` (scratchpad), sans `--parallel`. Code applicatif non modifié.

## Contrôle d'affaiblissement (git diff)
Les 6 `@expectedFailure` retirés (BUG-501 x2, 502, 508, 509, 510) : seuls les marqueurs disparaissent ; aucune assertion, aucun corps de test modifié. Un test ajouté (`test_bug501_force_applies_replay_on_untraced_stock`).

## Résultats
| Ticket | Verdict | Contre-attaque |
|---|---|---|
| BUG-501 | VÉRIFIÉ | sans `--force` : CUMP, sorties, quantité, journal d'activité intacts + message IGNORÉ ; `--force` applique et journalise ; run mixte (K1 non tracé ignoré, K2 tracé corrigé, compteur « 1 corrigé ») ; `--dry-run --force` n'écrit rien ; `--node` respecté ; non tracé sans rien à corriger : pas de message |
| BUG-502 | VÉRIFIÉ | 3 déclarations 2 + 1,5 + 0,25 : 3,75 sacs sortis exactement ; déclaration sans farine : aucune sortie ; sel/levure/huile = quantité de la requête ; équipes A/B indépendantes ; grand livre des mouvements = stock |
| BUG-508 | **ROUVERT** | 300/500 FC corrects (5 changements de tarif successifs). Défaut : prix pleins non multiples de 4 (50, 150, 250...) : RG soldée 10 x 150 = 1 500 FC avant, 1 510 FC après passage du tarif à 400 (prix figé 113 / 0,75 = 150,67 -> 151) ; 50 FC : 500 -> 510. Test `@expectedFailure` x2 |
| BUG-509 | VÉRIFIÉ | 3 confirmations successives (B 8, A 9, B 6 -> -6) ; retour de désignation sans reconfirmation (-8) ; 2 catégories indépendantes ; confirmation = snapshot ; rapport rejoué (idempotent) ; sans rotation inchangé |
| BUG-510 | VÉRIFIÉ | 23 identifiants invalides (texte, vide, flottant, négatif, 0, 2^63, 2^70, chaîne de 5 000 chiffres, booléens, liste, objet, `1e3`, NaN, null, arabe, hex, injection) : tous 400 `{detail}`, session reste ouverte ; id introuvable 400 ; int et chaîne numérique valides clôturent ; lot mixte refusé atomiquement |

## Nouveaux tickets
- **BUG-363** (Mineur) : `InvoiceLine.loss` relit le catalogue : `perte_fc` d'une journée passée bouge avec le tarif (750 -> 1 750 FC pour 10 x 300 après tarif 400). Vrai défaut, même famille que BUG-508.
- **BUG-512** (Mineur) : `_check_overconsumption` sur 2e déclaration : quantité ajoutée / sacs cumulés (sous-estimation, alerte manquée : 120 g/sac calculé 60 g/sac pour une moyenne de 50, seuil 2x). Séquelle de BUG-502.
- Remarque sans ticket : la simulation de `recompute_cump` compte « à corriger » un stock non tracé que `--apply` ignorera (test de caractérisation). Cosmétique.

## Exécution
Fichier dédié : 31 tests, OK (expected failures = 5) après correction d'un défaut de mise en place de mon test (ouverture hors rotation exige `team`). Suite complète `production` : voir résumé de l'appelant.
