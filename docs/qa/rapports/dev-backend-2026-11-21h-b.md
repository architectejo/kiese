# Rapport dev-backend B - 2026-11-21h

## Traité
- BUG-414 [Mineur, core] : CORRIGÉ (non validé). `NodeViewSet.destroy` refuse (400) la suppression d'une boulangerie avec comptes actifs (nombre cité), traduit ProtectedError en 400, journalise `DELETE`. Comptes désactivés non bloquants (choix documenté). Pas de migration, droits inchangés.
- Tests : `backend/core/tests/test_bug414_node_delete_users.py`.

## Risques
- Les comptes désactivés d'une boulangerie supprimée passent à node=NULL (inoffensifs tant qu'inactifs ; réactivation exige un nœud, BUG-506).
- Le frontend affiche le `detail` s'il utilise getErrorDetail (non vérifié, hors périmètre).
