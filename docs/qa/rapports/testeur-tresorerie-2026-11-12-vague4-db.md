# Rapport testeur-trésorerie — vague 4 (K3, db.sqlite3) — 2026-11-12

Rapport transmis par l'agent et enregistré par le coordinateur.

## Verdict
Le jour calendaire fonctionne côté trésorerie : clôture, billetage, écarts, versement au livre de caisse et chaîne de hash conformes. Deux tickets mineurs : BUG-276 (frontend) et BUG-277 (à clarifier). BUG-231 passé à VÉRIFIÉ (avec réserve 276).

## Base réelle K3 (rotation active, relève 12:00)
- 20 factures livrées le 2026-11-12 (équipes A et B, 10 200 FC cash + 6 000 FC crédit chacune) ; 2 rapports facturier (A et B) ; UNE clôture du jour additionnant les deux équipes (entrées 20 400, dépense 1 200, net 19 200, billetage 18 000, écart −1 200).
- Recalcul après vente tardive de l'équipe B conforme.
- Refus : double clôture 400, date future 400, billets hors borne/négatif/texte/décimal 400, gérant validant ou versant 403, clôture confirmée PATCH 400 / DELETE 403.
- Transfert K4→K3 en litige : versement bloqué avec message français ; débloqué après résolution.
- Livre de caisse : `VC-K3-20261112` +19 200 (solde 30 300 → 49 500), second versement refusé, POST/PUT/PATCH/DELETE 405.
- Intégrité : `integrity_check` valide (7 écritures), `run_check`/`global_status` intacts, ancre `CashbookHead` = 7 écritures, hash de tête cohérent.
- Fenêtre 00:00–12:00 non jouable en réel (il était 18:10) : couverte par tests à horloge simulée.

## Tests
- Nouveau `backend/treasury/tests/test_vague4_db_testeur_tresorerie.py` : 6 tests verts (jour réparti sur minuit/relève, frontière de minuit, verrou (équipe, date), recalcul, billetage 8 coupures, ancre de chaîne).
- Tests réécrits par le dev (`test_verification_b3_tresorerie_2026_11_12.py`, `test_bug189_*`) : 24/24 verts, pas d'affaiblissement réel. Réserves : `test_journal_entry_default_date_is_calendar_date_in_rotation` accepte 201 ou 400 (peut ne rien contrôler) ; le scénario principal b3 n'utilise plus que l'équipe A.

## UI (360 et 1366 px)
- BUG-231 : VÉRIFIÉ (blocage sans requête POST ; message = bulle native du navigateur, cf. BUG-276).
- La modale « Stock de départ » (Production) bloque l'écran Trésorerie des gérants K1/K4 : retirée du DOM par le testeur, sans rien confirmer.

## Tickets
- BUG-276 (Mineur, frontend) : message de billetage hors borne = validation native, le message français de `validateBillCounts` n'apparaît jamais ; `-3` effacé et `2.5` → `2` sans message.
- BUG-277 (Mineur, À CLARIFIER) : confirmation d'une clôture par le comptable possible pendant un transfert en litige (seules la création et le versement sont bloqués ; CLAUDE.md §5.4 : « blocage de la clôture »).
- BUG-273 (ventes) non exercé ici.

## Données créées (K3, comptes zz_treso_*)
20 factures, dépense `ZZTEST V4 eau`, clôture `0b6ae005-1cd8-4fd8-a0ce-e495635cf803` (confirmée et versée), écriture `VC-K3-20261112`, transfert K4→K3 résolu. Rotation K3 laissée à son état d'origine (active, relève 12:00).
