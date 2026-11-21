# Rapport dev-backend (B) - 2026-11-20

## BUG-228 : CORRIGÉ (non vérifié)
- Commande `backend/core/management/commands/fix_mojibake_names.py` : simulation par défaut, `--apply` pour écrire, idempotente, transaction atomique, `update()` (pas de signaux). Champs : User.first_name/last_name, Node.name/address, ExpenseCategory.label, BreadPrice.label, ColisDistribution.beneficiary_label, ActivityLog.user_display. Un texte correct n'est jamais modifié (le ré-encodage cp1252/latin-1 doit être de l'UTF-8 valide et différent).
- Test `backend/core/tests/test_bug228_mojibake.py` (données fictives) : fonction pure, dry-run sans écriture, apply + idempotence, texte correct intact.
- Source : seeds et code sans défaut (littéraux UTF-8 corrects, pas de décodage latin-1). Cause probable : saisie console cp1252 (y compris arguments de `ensure_local_admin`). Pas de correctif code supplémentaire.
- Pas de migration. `--apply` jamais lancé sur `db.sqlite3`.

## Risques / en attente
- Impossible d'exécuter `python manage.py test core` ni `makemigrations --check` : aucun interpréteur Python avec dépendances sur ce poste (py launcher cassé, pas de .venv). Logique vérifiée à la main. À lancer avant fusion.
- ActivityLog.user_display : les anciens journaux sont réparés aussi (update direct).
