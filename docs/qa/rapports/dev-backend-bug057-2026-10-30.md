# Rapport dev-backend — BUG-057 (dérive de migrations `production`/`clients`/`treasury`)

Date : 2026-10-30
Mission : résoudre la dérive de migrations préexistante et redécouverte à répétition, décrite
dans `docs/qa/REGISTRE_BUGS.md` (BUG-057).

## Ticket traité

**BUG-057** — Dérive de migrations non résolue sur `production`/`clients`/`treasury` → passé à
**CORRIGÉ** (jamais VÉRIFIÉ, conformément à CLAUDE.md §7 règle 3 — à valider par `relecteur-code`
ou le coordinateur).

## Analyse de cause racine

`python manage.py makemigrations --check --dry-run -v 3` signalait 3 catégories de dérive, dont
l'origine a été confirmée en relisant les migrations de **création** de chaque modèle (pas
seulement l'état actuel des modèles) :

1. **`id` : `AutoField` écrit en dur au lieu de `BigAutoField`.** Les 4 apps concernées
   (`production`, `clients`, `treasury`, `core`) déclarent toutes
   `default_auto_field = 'django.db.models.BigAutoField'` dans leur `AppConfig`, cohérent avec
   `DEFAULT_AUTO_FIELD` dans `backend/kiese/settings.py`. Pourtant, 5 migrations de création
   (`production/migrations/0007_breadtransfer_multiline.py` pour `BreadTransferLine`,
   `0009_consumablecount.py` pour `ConsumableCount`, `clients/migrations/0005_social.py` pour les
   3 modèles de caisse sociale, `treasury/migrations/0003_journalentry.py` et
   `0004_dailysavings.py`) contiennent `models.AutoField(...)` écrit explicitement — ce que
   `makemigrations` n'aurait jamais généré de lui-même avec ce réglage. Cela indique une rédaction
   manuelle ou un copier-coller d'un gabarit de migration plus ancien, sans repasser par
   `makemigrations`. Sans impact réel sur le schéma SQLite déjà en place (`AutoField` et
   `BigAutoField` produisent le même DDL `INTEGER PRIMARY KEY AUTOINCREMENT` sous SQLite) — dérive
   purement déclarative côté Django.
2. **`unique_together` vs `UniqueConstraint` nommée** sur `SocialContribution`,
   `SocialDistribution`, `SocialDistributionLine` (clients) et `DailySavings` (treasury). Les
   migrations de création déclarent l'unicité via `Meta.constraints` nommée
   (`UniqueConstraint(..., name='unique_social_contribution')`), alors que les modèles actuels
   utilisent `Meta.unique_together`. Les deux styles produisent une contrainte strictement
   équivalente en base — confirmé en lisant `sqlite_master` directement : avant et après la
   migration de rattrapage, un index **unique** actif existe sur exactement les mêmes colonnes,
   seul son nom change (`unique_social_contribution` → nom auto-généré
   `..._31eceff6_uniq`). Aucune fenêtre sans contrainte : sous SQLite, Django regroupe
   `RemoveConstraint` + `AlterField` + `AlterUniqueTogether` sur une même table en un seul rebuild
   de table dans une seule transaction.
3. **`transfer_status` sur `BreadTransfer`** : la valeur `RESPONDED` (état intermédiaire
   « Réceptionné — en attente de confirmation », workflow de validation inter-boulangeries décrit
   à CLAUDE.md §5.4) a été ajoutée au `TextChoices` du modèle par un ticket antérieur sans que la
   migration correspondante soit générée. Les `choices` d'un `CharField` ne sont pas imposés par
   une contrainte SQL : aucune donnée bloquée, dérive purement déclarative.

Dans les trois cas : dérive de représentation interne Django/migrations, **pas** un changement de
schéma SQL avec un enjeu métier à préserver. Aucune contrainte réelle n'a jamais été perdue sur la
base déjà peuplée pendant toute la durée de la dérive.

## Fichiers modifiés

- `backend/production/migrations/0014_bug057_schema_drift_fix.py` (nouveau) : `AlterField`
  `BreadTransfer.transfer_status` (ajout `RESPONDED`), `AlterField id` sur `BreadTransferLine` et
  `ConsumableCount` (`AutoField` → `BigAutoField`).
- `backend/clients/migrations/0007_bug057_schema_drift_fix.py` (nouveau) : `RemoveConstraint` +
  `AlterField id` + `AlterUniqueTogether` (équivalent) sur `SocialContribution`,
  `SocialDistribution`, `SocialDistributionLine`.
- `backend/treasury/migrations/0013_bug057_schema_drift_fix.py` (nouveau) : `RemoveConstraint` +
  `AlterField id` + `AlterUniqueTogether` (équivalent) sur `DailySavings` ; `AlterField id` sur
  `JournalEntry`.
- Aucun fichier `models.py` modifié : les modèles étaient déjà corrects, seul l'historique des
  migrations manquait le rattrapage.

## Vérifications effectuées

- `PRAGMA integrity_check` sur `backend/db.sqlite3` → `ok` avant ET après l'application des 3
  migrations.
- Relecture ligne à ligne des 3 fichiers de migration générés avant `python manage.py migrate`,
  en particulier pour écarter tout risque de perte de données ou de contrainte métier réelle.
- Inspection directe de `sqlite_master` (`SELECT name, sql FROM sqlite_master WHERE type='index'`)
  confirmant que les 4 index uniques visés restent actifs après migration, sous un nom différent :
  `socialcontribution(client_id, month, year)`, `socialdistribution(node_id, year)`,
  `socialdistributionline(distribution_id, client_id)`, `dailysavings(node_id, date)`.
- `python manage.py makemigrations --check --dry-run` → `No changes detected` (plus aucune
  dérive, sur ces 3 apps ni sur le reste du projet).
- `python manage.py test` (suite complète, 372 tests) → `OK`, aucune régression.

## Impact API

Aucun. Ni le type interne de `id`, ni le nom de la contrainte d'unicité, ni l'ajout de la valeur
`RESPONDED` à `transfer_status` (déjà utilisée en lecture/écriture par le code applicatif
existant) ne changent le contrat REST. Aucun ticket `dev-frontend` ouvert pour cette correction.

## En attente

- BUG-057 reste à faire passer à **VÉRIFIÉ** par `relecteur-code` (ouvreur d'origine) ou le
  coordinateur, conformément à la règle « un développeur ne valide pas sa propre correction ».

## Risques / points d'attention pour la suite

- Aucun risque résiduel identifié sur le périmètre de ce ticket. Recommandation pour l'avenir :
  éviter d'écrire des migrations à la main (notamment `AutoField` vs `BigAutoField`, et le style
  `UniqueConstraint` nommée vs `unique_together`) — toujours passer par
  `python manage.py makemigrations` pour que l'état suivi par Django reste synchrone avec les
  modèles, même pour des migrations de données ou des ajustements mineurs.
- Processus en arrière-plan : lors de cette session, une commande `until false; do :; done` a été
  lancée par erreur en tâche de fond puis abandonnée (aucun outil `TaskStop` disponible dans mon
  environnement pour l'arrêter proprement). Elle est sans effet sur le dépôt ou la base de
  données (aucune écriture), mais le coordinateur ou l'utilisateur voudra peut-être nettoyer ce
  processus résiduel côté système.
