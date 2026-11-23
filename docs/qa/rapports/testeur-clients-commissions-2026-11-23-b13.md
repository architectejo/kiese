# Testeur clients/commissions - ronde b13 (2026-11-23)

Fichier : `backend/clients/tests/test_clients_v10.py` (20 tests, 2 `@expectedFailure`).

## Verifies
- BUG-951 : mouvements de dette intercales (REST et push K3) ne touchent pas `identity_updated_at` ; edition du poste acceptee apres mouvements ; push plus ancien que la version d'identite ignore ; PATCH vide ne marque pas. VERIFIE.
- BUG-952 : edition locale non poussee survit au pull (identite, plafond), dette Cloud appliquee, categorie recalculee sur le plafond local, `is_synced` reste False, lot sortant porte la valeur locale ; apres push accepte le pull reapplique le Cloud ; client cree localement sans edition recoit le Cloud. VERIFIE.
- BUG-954 : PATCH is_paid (payee/annulee), DELETE journalises une fois, pas de journal si is_paid inchange, isolation K3, facturier refuse. VERIFIE.
- Migration 0011 : base SQLite jetable 0010 -> 0011, 3 clients existants conserves, dette/plafond/telephone intacts, `identity_updated_at` NULL. OK.
- BUG-953 reste A CLARIFIER.

## Cas NULL (risque note par le dev)
Avec identity NULL et un mouvement de dette, tout push du proprietaire est applique, meme date d'avant. Acceptable : tant que la version n'est pas transportee (BUG-970) la garde ne sert de toute facon pas en flux reel, et le proprietaire est la source (SYNC.md 5.1). Reserve : un client dont l'edition locale non poussee date d'avant la migration (is_synced=False, identity NULL) est ecrase par le pull (fenetre unique de deploiement) : pousser les clients en attente avant de migrer.

## Nouveaux tickets (2)
- BUG-969 (Mineur) : push d'identite obsolete ignore sans SyncConflictLog.
- BUG-970 (Majeur) : `build_outbound_payload` ne transporte aucune version ; la garde est morte en flux reel, le dernier push ecrase une edition plus recente du siege.
Pas d'exploration commissions/exports/notifications supplementaire dans cette ronde (aucun nouveau defaut constate hors des deux tickets).
