# Testeur production (Dev A) - cycle 9 / a8 - 2026-11-23

Fichier de tests : `backend/production/tests/test_verif_production_a8_v8.py` (27 tests : 9 passants de garde-fous + flux complet, 18 `@expectedFailure`). Aucun code applicatif modifié.

## Angle
Push de synchronisation (`/api/sync/push/`) des modèles production et ventes face aux règles REST, puis flux légitime complet.

## Garde-fous qui tiennent (tests verts)
- Portée nœud, équipe A/B, propriété d'une session existante, clôture jamais rouverte, rejeu idempotent.
- Date non ASCII et `closed_at` illisible : REJECTED sans 500.
- Disposition : type invalide, prix négatif, quantité négative hors REMAINING, autre nœud refusés ; total_value = quantité x prix.
- Facture : statut invalide, montants négatifs, transition par un autre nœud refusés ; factures LIVRÉE/ANNULÉE non modifiées par rejeu.

## Nouveaux tickets (9) : BUG-901 à BUG-909
| Ticket | Sév. | Constat |
|---|---|---|
| 901 | Mineur | Fournée datée du futur acceptée au push (REST refuse) |
| 902 | Majeur | `flour_sacks_used` négatif / non ASCII / > 100 000 accepté |
| 903 | Mineur | Ligne de production : quantité 10^12 et chiffres non ASCII acceptés |
| 904 | Majeur | Ligne `quantity: null` : ACCEPTED sans ligne créée (perte silencieuse) |
| 905 | Majeur | Ligne ajoutée à une fournée clôturée |
| 906 | Mineur | Disposition : quantité 3e9 et type vide acceptés |
| 907 | Majeur | Mouvement consommable : négatif, non ASCII, prix négatif, > 3 décimales arrondies |
| 908 | Majeur | Facture : `commission_rate` hors [0 ; 1], `delivered_at` futur, reçu non ASCII |
| 909 | Majeur | Nouvelle ligne ajoutée à une facture livrée / annulée |

Cause commune : `_validate_fields` utilise `field.clean(value, None)` (pas de plage entière), sans ASCII ni date future ; les handlers n'ont pas les contrôles REST.

## Flux complet (vert)
Fournée 2 sacs (400 000 théorique) 700 x 300 + 400 x 500 = 410 000 : excédent +10 000, stock K1 800/500. Facture 170 000 FC : stock 400/400. Appro 100 pains vers K2 : K1 300, K2 100, groupe inchangé ; clôture : appro_effectue +30 000 FC (K1), appro_recu retranché -30 000 FC (K2), somme nulle (signe BUG-675 confirmé).

## Observation
Le stock de pains est décrémenté à la création de la facture (`sales/views.py` ~l.757), pas à la livraison comme l'écrit CLAUDE.md 5.2. À trancher par le coordinateur.

## Statuts
Aucun ticket production à vérifier/rejeter ce cycle. BUG-684 non touché (À CLARIFIER).
