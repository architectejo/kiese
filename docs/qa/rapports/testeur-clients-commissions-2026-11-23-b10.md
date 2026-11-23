# Rapport testeur clients/commissions, cycle 10 (2026-11-23)

Fichier de tests : `backend/clients/tests/test_clients_v7.py` (31 tests : OK, 3 échecs attendus). Log : `$TEMP/b10.log`. Code applicatif non modifié, rien commité.

## Vérification
| Ticket | Résultat |
|---|---|
| BUG-916 (push Client) | VÉRIFIÉ : bornes exactes (0,30 / 10 000 000) acceptées ; 0,31, 0,305, plafond dépassé, NaN/Infinity, booléen, chiffres arabes/pleine largeur, noms vides/blancs/non texte refusés ; rejeu altéré d'un client connu sans effet |
| BUG-917 (push SocialContribution) | VÉRIFIÉ : cycle légitime (création, is_paid, paid_at, montant), mois 0/13/non ASCII/décimal/booléen, année hors plage, montant négatif/non ASCII/trop grand refusés ; client inconnu ou non UUID refusé |
| BUG-918 (push Line) | VÉRIFIÉ : indice 12 accepté (remise 8 400), 13/-1/non ASCII/décimal, mérite/total négatifs, position/forme invalides refusés ; remise et total_payer recalculés (2 100 / 9 000 puis 2 800 / 9 700) et identiques à REST |
| BUG-915 (REST ASCII) | RÉOUVERT : `bulk_create_month` accepte `amount="٣٠٠٠"` (200, cotisations créées). Cotisation, tarif, ligne, mois, année, `generate` OK |

Non-régression OK : création REST (taux 0,30, cotisation 1 500), import Excel (nom d'un mot, chiffres arabes/pleine largeur dans les noms, codes K1-), multipart et nombres JSON, génération de paie avec mois/année en chaînes ASCII, dette d'ouverture conservée au push, rejeu idempotent, client d'un autre nœud accepté pour un DebtMovement, ancien nœud sans prénom REJECTED avec motif (cohérent REST).

## Nouveaux tickets (2)
- BUG-933 : push `DebtMovement` sans montant (absent/null/'') ACCEPTED (mouvement perdu).
- BUG-934 : push `DebtMovement` sous-centime (0.004) ACCEPTED (même défaut que BUG-900).
Numéros 933/934 (919-932 pris en parallèle).

## Observations sans ticket
- Client non UUID dans un push de cotisation, doublon de distribution (nœud/année) ou de ligne (client) : ValidationError/IntegrityError levées puis interceptées (REJECTED, journal « non traité »), pas de 500.
- `is_paid`/`is_closed` poussés en chaîne `'false'` : refusés correctement (pas de bug).
- Modèles `core.*`, `chat.*`, `clients.ClientCategory` : rejetés proprement (« modèle non supporté en V1 »).
- DebtMovement : kind/note invalides, node_origin usurpé, facture d'un autre nœud, rejeu au contenu différent, NaN/Infinity/non ASCII/hors plage : tous refusés, dette intacte.
