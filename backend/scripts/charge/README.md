# Scripts de charge — testeur-charge

Scripts et notes conservés pour réutilisation future (mission testeur-charge,
2026-10-22/23). Rien ici ne modifie le code applicatif.

## Règle d'isolation (obligatoire, voir incident documenté ci-dessous)

**Ne jamais faire tourner un script de charge contre `backend/db.sqlite3`.**
`volumetrie.py` crée sa propre base SQLite temporaire (fichier distinct dans
le répertoire temporaire du système, détruit en fin d'exécution) et refuse
de démarrer (`RuntimeError` explicite) si la connexion par défaut ne pointe
pas vers ce fichier temporaire.

### Incident constaté en écrivant ce script — pour mémoire

Une première version du script positionnait `os.environ['DB_NAME']` AVANT
`django.setup()`. Cela ne suffit pas : `kiese/settings.py` appelle
`load_dotenv(BASE_DIR / '.env', override=True)`, qui **écrase** toute
variable déjà présente dans `os.environ` avec la valeur du fichier `.env`
local (même vide, ex. `DB_NAME=`) — la variable qu'on venait de positionner
disparaissait donc avant que `DATABASES` ne soit construit, et le script
retombait sur la vraie base de développement. La tentative a échoué tôt
(`IntegrityError` sur un `Node` déjà existant) avant d'écrire la moindre
donnée de charge, et une vérification complète a confirmé qu'aucune trace
(`ClientCharge*`, nœud `ZZZ`, etc.) n'avait atteint `db.sqlite3`. La leçon
retenue, appliquée dans la version actuelle du script : patcher
`django.conf.settings.DATABASES['default']['NAME']` **après**
`django.setup()` (donc après que `.env` a déjà été chargé), avec un
garde-fou qui arrête le script si la connexion effective ne correspond pas
au fichier temporaire attendu.

Un second incident, distinct et plus grave, s'est produit **pendant le
débogage manuel** (pas dans le script lui-même) : une commande
`python manage.py shell -c "..."` a été lancée directement, sans aucune
isolation, pour comprendre un comportement de l'API — ce qui a écrit un
nœud `ZZZ`, un utilisateur et un client fictifs dans `backend/db.sqlite3`
réel. Repéré immédiatement, nettoyé (suppression ciblée des objets créés),
et vérifié après coup (comparaison des nœuds/`BreadPrice`/comptage
clients avant/après). Pour toute exploration manuelle future : utiliser
`manage.py test` avec un fichier de test temporaire (comme fait ensuite
dans cette mission), jamais `manage.py shell` nu contre les vrais settings.

## `volumetrie.py`

Mesure les temps de réponse (médiane sur 5 appels à chaud après une
chauffe ignorée) et le nombre de requêtes SQL (`CaptureQueriesContext`,
détection de N+1) de : recherche client, liste de factures (filtrée et
non filtrée), résumé des commissions, états financiers comparatifs N/N-1,
réconciliation production, liste du Livre de Caisse Direction.

```bash
cd backend
./.venv/Scripts/python.exe scripts/charge/volumetrie.py \
    --days 10 --invoices-per-day-per-node 300 --n-clients 700
```

Échelle par défaut : 8 boulangeries, ~700 clients, 300 factures/jour/
boulangerie — mais sur un nombre de jours réduit (10, pas 365) : un an
complet (~876 000 factures) prendrait bien trop longtemps à insérer sur ce
poste pour un gain de preuve supplémentaire (la plupart des endpoints
mesurés sont filtrés par nœud+date, donc indépendants du volume total
accumulé). Voir `docs/qa/REGISTRE_BUGS.md` (BUG-064) pour l'extrapolation
explicite à l'échelle d'un exercice complet.

Durée observée pour l'échelle par défaut : ~18 minutes (dominé par le seed
des factures/lignes via `bulk_create`), dont une anomalie isolée non
réinvestiguée (un jour simulé sur dix a pris ~16 min contre ~20 s pour les
9 autres — probablement une interférence externe à l'application, voir
BUG-064).

## Scénarios de concurrence (dans les suites de tests, pas des scripts à part)

Conservés directement dans les suites `manage.py test` de chaque app
concernée plutôt que comme scripts indépendants, pour bénéficier de
l'isolation automatique de la base de test (jamais `db.sqlite3`) :

- `backend/sales/tests/test_charge_morning_peak.py` — pic du matin
  multi-boulangeries (numéros de reçu, déstockage, erreurs serveur). Deux
  anomalies confirmées, voir BUG-062 (`@expectedFailure` sur
  `test_no_500_no_duplicate_receipt_number_no_lost_stock_under_concurrent_morning_peak`) ;
  BUG-063 documenté en commentaire (hors test automatisé).
- `backend/sync/tests/test_charge_sync_volume.py` — synchronisation
  multi-nœuds à plus grande échelle que `sync/tests/test_sync.py`
  (4 nœuds × 5 mouvements en ordre aléatoire, rejeu concurrent et rejeu
  séquentiel rapide × 100). Une anomalie confirmée, voir BUG-062
  (`@expectedFailure` sur
  `test_replaying_the_same_batch_id_concurrently_many_times_never_duplicates`).

```bash
cd backend
./.venv/Scripts/python.exe manage.py test sales.tests.test_charge_morning_peak sync.tests.test_charge_sync_volume -v 2
```
