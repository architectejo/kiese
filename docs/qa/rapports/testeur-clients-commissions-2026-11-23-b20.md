# Testeur clients/commissions, ronde b20 (2026-11-23)

Fichiers : `backend/clients/tests/test_clients_v16.py` (9 tests), `backend/commissions/tests/test_commissions_v7.py` (13 tests). Résultat : 22 tests, OK, 4 `@expectedFailure`.

## BUG-1010 : VÉRIFIÉ
Pagination avec 5, 7 ou 9 clients datés +3 h, +30 min ou dans le passé : aucun perdu, aucun doublon, boucle bornée. Un curseur forgé au-delà du plafond ou sans `client_after_id` est traité comme absent (BUG-785 conservé). Le plafond qui baisse entre deux pages termine sans boucle. Le périmètre inter-boulangeries est inchangé.
Observation (non défaut) : le curseur final est `now`. Les lignes datées dans le futur sont donc relivrées à chaque cycle jusqu'à ce que l'horloge les rattrape. C'est idempotent et borné.

## BUG-1011 : VÉRIFIÉ, avec limites résiduelles
Le report fonctionne dans ces cas : porteuse supprimée, deux lignes supprimées, BP créditrice, porteuse payée jamais touchée ni doublée, trois régénérations sans doublon, première génération du mois, période close non supprimable. Le net est calculé en Decimal exact (300 FC sur la ligne porteuse).
La limite « retenue perdue » existe encore dans des scénarios réalistes, d'où deux tickets.

## Nouveaux tickets : 2
- BUG-1013 (Mineur) : retenue encore perdue. (a) La facture de la porteuse supprimée est annulée : `nodes_inv` ne compte que les factures `DELIVERED`, donc le report ne se déclenche pas. (b) Seule la ligne la plus récente est régénérée : seule la plus ancienne ligne non payée reporte.
- BUG-1014 (Mineur) : un zéro manuel de la comptabilité est écrasé par le report. Cas (a) : une autre ligne non porteuse est supprimée. Cas (b) : la période d'une autre boulangerie existe sans ligne parce que la facture a été livrée après sa génération.
Tests marqués `@expectedFailure` dans `test_commissions_v7.py`.

## BUG-783
Aucun test `charge_v3` démarqué ni référence à BUG-783 trouvé dans le code (grep à vide) : rien à vérifier côté tests de mon périmètre.

## Remarques
- Python n'est pas dans le PATH de Bash : utiliser `./.venv/Scripts/python.exe`.
- Aucun échec de concurrence ; la charge a seulement ralenti la série (≈ 155 s).
- Rien n'est commité.
