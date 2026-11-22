# testeur-permissions (Dev C) 2026-11-22 c2 : vérification BUG-516

Verdict : **BUG-516 VÉRIFIÉ**. Ticket ouvert : BUG-523 (Mineur, pour B). BUG-517 inchangé.

## 1. Diff et migration
- `blockchain/models.py` : seuls `TamperAlert.node` et `BlockchainSnapshot.node` passent CASCADE -> PROTECT.
- `0002_node_protect.py` : dépend de `blockchain.0001_initial` et `core.0020_bug289`, deux `AlterField` (réversibles, pas de données). `makemigrations --check --dry-run` : « No changes detected ». Une seule migration `0002_node_protect`, aucun conflit.

## 2. Tests : `backend/blockchain/tests/test_verif_bug516_c.py` (16)
- Définition : `on_delete is PROTECT` sur les deux FK.
- API (ADMIN et DIRECTION) : alerte non résolue, alerte « résolue », snapshot seul, alerte + snapshots -> 400 « Impossible de supprimer… », nœud conservé, preuves conservées, aucun log `DELETE` ; refus répété 3 fois idempotent ; alertes d'un autre nœud n'empêchent pas la suppression d'un nœud vide (204, un seul log DELETE) ; double suppression 204 puis 404 ; COMPTABLE/GERANT/FACTURIER/LIVREUR -> 403.
- ORM : `ProtectedError` (instance, queryset), suppression groupée mixte atomique (rien supprimé), nœud vide supprimable, `PRAGMA foreign_key_check` vide.
- Effet `SystemNotification` / `ActivityLog` : aucune notification ni log DELETE sur refus. Constat annexe (hors BUG-516) : le premier appel API crée paresseusement la `Config` et écrit un log « Modification Configuration » + une notification « Configuration mise à jour » ; mes assertions les excluent. Si cela doit être évité (journal pollué par une simple lecture/refus), à signaler à A/B, non ouvert ici.

## 3. Résultats
`manage.py test blockchain core.tests.test_verif_bug414_c` : 45 tests, OK, 1 échec attendu (BUG-517 seul). (Première exécution : 6 échecs de mes tests dus à l'artefact Config ci-dessus, corrigé dans les tests, pas dans le code.)
Le test `test_unresolved_tamper_alert_must_not_be_erased_by_node_delete` (retrait de `@expectedFailure` par le dev) passe pour la bonne raison : il demande 400 et 1 alerte conservée ; le code serveur (`destroy`) n'a pas changé, seul le modèle PROTECT fait lever `ProtectedError`. Mes tests ORM confirment que la cause est le modèle, et le test dev de non-régression échoue si on remet CASCADE (affirmé par le dev, cohérent avec mes tests de définition).

## 4. BUG-517
Non touché, toujours `@expectedFailure` (SIEGE supprimable).

## 5. CASCADE restants
- `sync.NodeAuthToken.node` (OneToOne, hash du jeton) : pas de défaut. Un nœud supprimable n'a aucune donnée métier (tout le reste est PROTECT), donc le jeton n'a plus d'objet à authentifier. Le poste local perd son accès de sync (401), comportement souhaitable pour une boulangerie supprimée ; en cas d'erreur, il faut recréer le nœud et réémettre un jeton (aucune donnée à perdre, le hash seul est stocké, rien de comptable). Pas de risque d'élévation ni de jeton orphelin valide.
- `chat.Conversation.node` : vrai défaut mineur. Le fil de la boulangerie, ses participants et messages sont effacés silencieusement alors que le message d'erreur du serveur promet de « conserver l'historique ». Pas de preuve comptable ni de fuite -> BUG-523 Mineur (pour B).

## Fichiers
- `c:\Users\Mrcomputer\Desktop\Projet\kiese\backend\blockchain\tests\test_verif_bug516_c.py`
- `c:\Users\Mrcomputer\Desktop\Projet\kiese\docs\qa\REGISTRE_BUGS.md` (BUG-516 VÉRIFIÉ, BUG-523 ajouté)
