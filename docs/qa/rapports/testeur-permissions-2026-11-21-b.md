# Rapport testeur-permissions — 2026-11-21 (dev-b)

## 1. BUG-228 (double encodage des noms) — VÉRIFIÉ

Commande : `backend/core/management/commands/fix_mojibake_names.py`.
Tests indépendants : `backend/core/tests/test_verif_bug228_testeur_permissions.py` (13 tests, verts).

Couvert :
- textes corrects intacts : Gérant, Élodie, Noël, Ça va, Zoé, cyrillique, emoji, chaîne vide, None, « Ã » seul, « Œuvre », CJK ;
- vrais cas cp1252 (« GÃ©rant », « Ã‰lodie ») et latin-1 pur (É = C3 89, caractère de contrôle 0x89) ;
- emoji double encodé : pas d'exception ;
- idempotence (fonction et commande, 2 exécutions, instantané complet des tables identique) ;
- dry-run par défaut : aucune requête UPDATE/INSERT/DELETE, `--dry-run` prime sur `--apply` ;
- `--apply` écrit (User, Node, ActivityLog) ;
- `save()` interdit (mock) et aucun signal pre/post_save ; updated_at/is_synced non touchés (`update()`) ;
- hors périmètre intact (email, username, mot de passe) ;
- atomicité : panne simulée sur un UPDATE ultérieur -> rollback complet.

Dry-run en lecture sur une copie de `db.sqlite3` (dossier temporaire, `DB_NAME`) : 8 enregistrements concernés
(adresse du Node K3 « AthÃ©nÃ©e », 7 ActivityLog « GÃ©rant Athenee »). Aucun `--apply` sur l'original.
Aucun écart : pas de ticket BUG-410+.

Remarques non bloquantes : (a) l'heuristique ne peut pas distinguer un vrai texte « Ã© » volontaire (cas
pratiquement inexistant pour des prénoms) ; (b) les 8 lignes réelles restent à corriger par `--apply`,
à lancer par la direction après sauvegarde de la base.

## 2. Tickets BUG-247, 248, 249, 250, 251, 252, 255

Déjà VÉRIFIÉS le 2026-11-12 sur la base réelle ; re-contrôlés le 2026-11-21 par les tests isolés
(`core/tests/test_verif_bug247_248_252_255_testeur_permissions.py`,
`clients/tests/test_verif_bug249_250_testeur_permissions.py`,
`production/tests/test_verif_bug251_testeur_permissions.py`, 40 tests).

Relecture critique : aucun test vide détecté. Les assertions portent sur l'état en base après tentative
(`refresh_from_db`, comptage d'objets, rôle/node/is_superuser inchangés), pas seulement sur le code HTTP ; les
cas négatifs ont leur contre-test positif (ADMIN/direction/gérant légitimes en 200/201/204), ce qui empêche
un faux vert par « tout refusé ». Réserves mineures : `test_patch_foreign_client_and_forged_node` (249) et
`test_gerant_quantity_readonly_and_node_forced` (251) ne vérifient pas le code HTTP de certains PATCH/PUT,
mais l'état final en base est bien contrôlé, donc la correction absente ferait échouer le test. Pas de
complément nécessaire.

## 3. Suite `manage.py test core`

288 tests, OK (1 skipped : schéma OpenAPI libre en DEBUG), 422 s, base de test uniquement.
