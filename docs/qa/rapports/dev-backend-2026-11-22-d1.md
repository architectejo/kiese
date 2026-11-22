# Rapport dev-backend 2026-11-22 (d1, Dev B)

## BUG-564 : CORRIGÉ
- Cause : la garde de suppression de BUG-517 repose sur `node.code == 'SIEGE'`, or le code était modifiable par PATCH/PUT.
- Correction : `NodeViewSet.perform_update` (backend/core/views.py) refuse en 400 (français) tout changement du code du nœud SIEGE et tout renommage d'un autre nœud vers « SIEGE ». Les autres champs de SIEGE restent modifiables. Pas de migration.
- Test : backend/core/tests/test_bug564_siege_code_protege.py (6 cas : PATCH, PUT, renommage vers SIEGE, autre champ OK, renommage ordinaire OK, suppression toujours refusée).
- Registre : le ticket BUG-564 n'existait pas dans docs/qa/REGISTRE_BUGS.md ; une ligne a été ajoutée (statut CORRIGÉ) après BUG-517.
- `makemigrations --check` : aucun changement ; `manage.py check` : 0 problème.

## Risques
- La création d'un nœud avec le code SIEGE n'est pas traitée (hors ticket).
