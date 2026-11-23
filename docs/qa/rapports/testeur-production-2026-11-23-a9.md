# Testeur production a9 (cycle 10 partie A) - 2026-11-23

Fichier : `backend/production/tests/test_verif_production_a9_v9.py` (39 tests : 24 verts, 15 `@expectedFailure` = 10 tickets). Log : `$TEMP/a9.log`.

## Verifies (VERIFIE)
BUG-901 a 909. Flux legitimes OK : fournee terminee hors ligne avec lignes dans le meme lot, fournee ouverte puis cloturee + lignes, facture livree + lignes (ids explicites, rejeu idempotent), facture PENDING livree hors ligne, rejeu x3 sans doublon, lot mixte, bornes (2e9, 0,30 / 0,300, 0,25, 3 decimales, flour 100000, 9999999,999), juste au-dessus refuse, dates (aujourd'hui, demain refuse, delivered_at 23:59 locale accepte, chiffres arabes / datetime naif refuses).
Contournements de `_batch_terminal_parents` : AUCUN trouve (autre noeud, lot precedent rejoue avec is_closed, thread-local entre deux lots HTTP et deux appels directs `process_push_batch`, cloture rejetee, autre facture deja livree dans le meme lot, UUID en majuscules).
Non couverts par ticket : BreadStock / DailyBreadStockSnapshot / ConsumableStock / CashbookEntry non poussables (rejetes), ConsumableCount (ecart, negatifs, 4 decimales, ASCII) solide, doublon de vacation de fournee refuse.

## Nouveaux tickets : 10 (BUG-919 a 928)
- 919 Majeur : `sync_now` envoie l'id entier local des lignes ; collision entre postes (InvoiceLine rejetee, ProductionSessionLine acceptee sans creation).
- 920 Mineur : ligne en double (autre id, autre quantite) acceptee, valeur perdue (fournee et transfert).
- 921 Majeur : ligne ajoutee / quantite recue reecrite sur un transfert CONFIRME.
- 922 Mineur : transfert K1 -> K1.
- 923 Mineur : `closed_at` futur (2099).
- 924 Majeur : totaux de fournee copies tels quels (2e9 FC sans ligne).
- 925 Majeur : `BreadDisposal` 2e9 x 2e9 : total_value 4e18 stocke et illisible par l'ORM.
- 926 Mineur : `consumable_type` non controle (stock parasite).
- 927 Mineur : `Invoice.team` non controle.
- 928 Mineur : `quantity_sent` transfert / ligne > 2e9.

Observations sans ticket : rejeu hors lot d'une ligne de facture (sans id) sur facture livree est refuse (conforme a la decision d25) ; `_is_future_date` (inventaire/comptage) tolere +1 jour alors que les autres controles sont stricts (BUG-729, intentionnel).
Le code applicatif n'a pas ete modifie.
