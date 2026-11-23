# Testeur trésorerie, cycle 13 (2026-11-23)

Fichier : `backend/treasury/tests/test_verif_tresorerie_c13_v12.py` (27 tests, OK, 1 échec attendu = BUG-971).

## Vérifiés
BUG-959, 960, 961, 962, 963 : VÉRIFIÉ.
- 959 : `facturier` exporté, deux facturiers de la même équipe acceptés, poste ancien sans clé inchangé (doublon refusé), facturier forgé refusé.
- 960 : création validée avec écart refusée (DISPUTED et écart saisi directement) ; PENDING, CANCELLED, transfert sortant sans effet ; clôture déjà confirmée puis écart : pas de versement (même verdict que REST), versement à la résolution, rejeu sans double versement.
- 961/962 : dépense refusée un jour de clôture confirmée, rejeu idempotent, autres jours/boulangeries acceptés, dépense poussée avant confirmation relue au net ; dates futures/invalides refusées avec motif précis.
- 963 : COMPTABLE/DIRECTION/ADMIN acceptés ; facturier et gérant d'un autre nœud refusés.

## Question ouverte BUG-960 : DÉFAUT (BUG-971, Majeur)
remarque.md l.156 (prioritaire) : le gérant ajoute, seul le comptable direction générale confirme ou infirme. CLAUDE.md §5.5 niveau 2/3 et REST (BUG-200) : confirmation et versement réservés à `IsHeadquarters`. Un jeton de boulangerie qui pousse `is_validated=True` obtient une clôture confirmée puis une écriture au livre direction sans comptable ni revue de l'écart physique. Les montants sont bien relus au versement (non-régression BUG-839), donc le défaut est le statut. Pas de décision client nécessaire. Test `@expectedFailure`.

## Balayage sans nouveau défaut
Rapport après clôture non confirmée (accepté, relu à la confirmation) / confirmée (refusé) ; rejeu d'un rapport ou d'une clôture existante (montants et statut inchangés, y compris rapport validé) ; jeton C2 ne valide pas un rapport de C1 ; dépense existante non modifiable par jeton étranger ; JournalEntry, DailySavings, CashbookEntry non acceptés par le sync (aucune création) ; bordereau : jeton boulangerie refusé, siège accepté, rejeu sans double débit, solde insuffisant sans orphelin ; double clôture même jour avec autre id : REJETÉ, sans 500.
Remarque mineure (non ticketée) : ce dernier cas est rejeté avec le motif générique « non traité (IntegrityError) ».

## Journée complète 2 postes via sync_now
C1 : 2 facturiers équipe A + 1 équipe B, dépense 2000 ; C2 : 1 facturier, dépense 5000 ; clôtures avec billets ; dépense poussée avant confirmation (net 12000, écart +1000 relus) ; transfert DISPUTED bloque confirmation et versement de C2 puis résolu ; dépense et rapport après confirmation refusés ; versements VC-C1-AAAAMMJJ 12000 et 15000, rejeu du lot sans doublon ; bordereau siège 5000, solde 22000 ; chaîne valide ; run_check intact ; altération directe détectée.

Nouveaux tickets : 1 (BUG-971). Numéros 964 à 970 pris par d'autres testeurs.
