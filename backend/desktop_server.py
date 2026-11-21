"""
Point d'entrée du backend Django en mode desktop (Electron + PyInstaller),
docs/architecture/DESKTOP.md §5/§6/§8.

Appelé par Electron (`desktop/src/backend.ts`) comme :

    kiese-server.exe --port 18234 --data-dir "C:\\Users\\...\\AppData\\Roaming\\KIESE" --host 127.0.0.1

Toutes les informations sensibles (SECRET_KEY du poste, jeton de nœud) sont
reçues par variables d'environnement (`KIESE_SECRET_KEY`, `KIESE_NODE_TOKEN`),
jamais en argument de ligne de commande (visible dans le gestionnaire des
tâches Windows) ni en clair sur disque — Electron les déchiffre depuis
`safeStorage` juste avant de lancer ce processus (DESKTOP.md §13).

Séquence (DESKTOP.md §5) :
  1. sauvegarde la base si des migrations sont en attente, sinon sauvegarde
     quotidienne au plus une fois par jour ;
  2. applique les migrations ;
  3. active le mode WAL ;
  4. démarre Waitress ;
  5. démarre le service de synchronisation en tâche de fond (best-effort).
"""

import argparse
import gzip
import logging
import logging.handlers
import os
import re
import shutil
import sqlite3
import sys
import time
import zlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# Code de sortie dédié à un échec d'application des migrations (BUG-073).
# Distinct du code 1 (erreur générique) pour que `desktop/src/backend.ts`
# puisse le reconnaître sans parser les logs et afficher un message
# d'erreur précis plutôt que de tenter un redémarrage automatique en
# boucle. Décision client (M. NDUNGA NSAYI PIERRE, ADG, 2026-10-23) :
# restauration manuelle guidée, pas de rollback automatique.
MIGRATION_FAILED_EXIT_CODE = 2


def _bundle_dir() -> Path:
    """Dossier des ressources packagées par PyInstaller (--onedir)."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def parse_args():
    parser = argparse.ArgumentParser(description="Backend KIESE (mode desktop)")
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--data-dir', type=str, required=True)
    parser.add_argument('--host', type=str, default='127.0.0.1')
    return parser.parse_args()


def ensure_data_dirs(data_dir: Path) -> None:
    for sub in ('media', 'logs', 'backups'):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)


def configure_logging(data_dir: Path) -> logging.Logger:
    log_path = data_dir / 'logs' / 'backend.log'
    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=10, encoding='utf-8'
    )
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    root.addHandler(logging.StreamHandler(sys.stdout))  # repris dans logs\backend.log côté Electron
    return logging.getLogger('kiese.desktop_server')


def _checkpoint_wal(db_path: Path) -> None:
    if not db_path.exists():
        return
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute('PRAGMA wal_checkpoint(FULL);')
        conn.close()
    except sqlite3.Error:
        pass


def backup_database(
    db_path: Path,
    backups_dir: Path,
    logger: logging.Logger,
    label: str = '',
    with_seconds: bool = False,
    unique: bool = False,
) -> Optional[Path]:
    """Sauvegarde cohérente via l'API de sauvegarde SQLite (DESKTOP.md §8),
    compressée, utilisable même pendant que la base est en cours d'usage
    (appelée aussi depuis l'API d'administration avant restauration/clôture).

    `sqlite3.Connection.backup()` lit la base ET son journal WAL : les
    transactions validées mais non checkpointées sont incluses (BUG-403).
    `label` s'insère dans le nom (`kiese-<label>-<horodatage>.sqlite3.gz`) ;
    le préfixe `kiese-` est conservé pour rester dans la liste blanche de
    restauration et dans la rotation sur 30 jours.

    Renvoie le chemin du fichier `.sqlite3.gz` créé (ou `None` s'il n'y
    avait rien à sauvegarder) — utilisé par `_apply_migrations` pour que
    l'utilisateur puisse identifier sans ambiguïté la sauvegarde prise
    juste avant une mise à jour qui échouerait (BUG-073)."""
    if not db_path.exists():
        logger.info('Aucune base existante à sauvegarder (premier démarrage).')
        return None
    _checkpoint_wal(db_path)
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S' if with_seconds else '%Y%m%d-%H%M')
    stem = f'kiese-{label}-{stamp}' if label else f'kiese-{stamp}'
    if unique:
        # BUG-410 : ne jamais écraser une copie existante (même seconde) -> suffixe -2, -3...
        base_stem, n = stem, 1
        while (backups_dir / f'{stem}.sqlite3.gz').exists():
            n += 1
            stem = f'{base_stem}-{n}'
    dest_plain = backups_dir / f'{stem}.sqlite3.tmp'
    dest_gz = backups_dir / f'{stem}.sqlite3.gz'
    dest_gz_part = backups_dir / f'{stem}.sqlite3.gz.part'
    src = sqlite3.connect(str(db_path))
    dest = sqlite3.connect(str(dest_plain))
    try:
        try:
            src.backup(dest)
        finally:
            src.close()
            dest.close()
        with open(dest_plain, 'rb') as f_in, gzip.open(dest_gz_part, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
        os.replace(dest_gz_part, dest_gz)
    finally:
        for leftover in (dest_plain, dest_gz_part):
            try:
                leftover.unlink()
            except OSError:
                pass
    logger.info('Sauvegarde créée : %s', dest_gz.name)
    _rotate_backups(backups_dir, logger)
    return dest_gz


BACKUP_NAME_RE = re.compile(r'kiese-[A-Za-z0-9_.-]+\.sqlite3\.gz')  # utilisé avec fullmatch (BUG-409)


class RestoreError(Exception):
    """Erreur de restauration : le message est destiné à l'utilisateur (français)."""


def validate_backup_file_name(file_name: str) -> str:
    """Liste blanche `kiese-*.sqlite3.gz`, sans composant de chemin (BUG-404)."""
    if (
        not isinstance(file_name, str)
        or not file_name
        or '/' in file_name
        or '\\' in file_name
        or '..' in file_name
        or not BACKUP_NAME_RE.fullmatch(file_name)
    ):
        raise RestoreError(f"Nom de sauvegarde invalide : « {file_name} ».")
    return file_name


def _integrity_ok(path: Path) -> bool:
    try:
        conn = sqlite3.connect(str(path))
        try:
            rows = conn.execute('PRAGMA integrity_check;').fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    return len(rows) == 1 and rows[0][0] == 'ok'


def _has_tables(path: Path) -> bool:
    """Vrai si la base contient au moins une table (une base SQLite vide réussit
    `integrity_check`) - BUG-408."""
    try:
        conn = sqlite3.connect(str(path))
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    return bool(row and row[0] > 0)


def restore_database(db_path: Path, backups_dir: Path, file_name: str, logger: logging.Logger) -> Path:
    """Restaure `file_name` (dans `backups_dir`) sur `db_path`. Le backend doit
    être arrêté. Ordre (BUG-404) : validation du nom, décompression vers un
    fichier temporaire, `PRAGMA integrity_check`, copie de sécurité
    `kiese-avant-restauration-*` de la base actuelle, puis seulement
    remplacement atomique. En cas d'échec avant le remplacement, la base
    courante n'est pas touchée. Renvoie la copie de sécurité (ou la base
    restaurée si aucune base n'existait)."""
    validate_backup_file_name(file_name)
    src = backups_dir / file_name
    if not src.is_file():
        raise RestoreError(f'Sauvegarde introuvable : {file_name}.')

    tmp = db_path.with_name(db_path.name + '.restore.tmp')
    safety: Optional[Path] = None
    try:
        try:
            with gzip.open(src, 'rb') as f_in, open(tmp, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        except (OSError, EOFError, zlib.error) as exc:
            raise RestoreError(
                f"La sauvegarde {file_name} est illisible ou corrompue ; la base actuelle n'a pas été modifiée."
            ) from exc
        if not _integrity_ok(tmp):
            raise RestoreError(
                f"La sauvegarde {file_name} ne contient pas une base valide ; la base actuelle n'a pas été modifiée."
            )
        if not tmp.exists() or tmp.stat().st_size == 0 or not _has_tables(tmp):
            raise RestoreError(
                f"La sauvegarde {file_name} est vide ; la base actuelle n'a pas été modifiée."
            )

        if db_path.exists():
            try:
                safety = backup_database(db_path, backups_dir, logger, label='avant-restauration', with_seconds=True, unique=True)
            except Exception as exc:  # noqa: BLE001
                raise RestoreError(
                    "Impossible de créer la copie de sécurité de la base actuelle ; restauration annulée, "
                    "la base actuelle n'a pas été modifiée."
                ) from exc
            if safety is None or not safety.is_file() or safety.stat().st_size == 0:
                raise RestoreError(
                    "La copie de sécurité de la base actuelle n'est pas valide ; restauration annulée."
                )

        for suffix in ('-wal', '-shm'):
            stale = Path(str(db_path) + suffix)
            try:
                stale.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise RestoreError(
                    f'Impossible de remplacer la base (fichier {stale.name} verrouillé) ; fermez KIESE puis réessayez.'
                ) from exc
        try:
            os.replace(tmp, db_path)
        except OSError as exc:
            raise RestoreError(
                "Impossible de remplacer la base actuelle ; une copie de sécurité est disponible dans le dossier backups."
            ) from exc
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    logger.info('Base restaurée depuis %s (copie de sécurité : %s).', file_name, safety.name if safety else 'aucune')
    return safety if safety else db_path


def _rotate_backups(backups_dir: Path, logger: logging.Logger, keep_days: int = 30) -> None:
    cutoff = datetime.now() - timedelta(days=keep_days)
    for f in backups_dir.glob('kiese-*.sqlite3.gz'):
        try:
            if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                f.unlink()
                logger.info('Sauvegarde expirée supprimée : %s', f.name)
        except OSError:
            continue


def _maybe_daily_backup(db_path: Path, backups_dir: Path, logger: logging.Logger) -> None:
    """Sauvegarde quotidienne : une fois par jour, à la première ouverture
    (DESKTOP.md §8). Les clôtures journalières déclenchent leur propre
    sauvegarde via l'API (hors de ce script, voir backend/treasury)."""
    marker = backups_dir / '.last_daily_backup'
    today = datetime.now().strftime('%Y-%m-%d')
    if marker.exists():
        try:
            if marker.read_text(encoding='utf-8').strip() == today:
                return
        except OSError:
            pass
    backup_database(db_path, backups_dir, logger)
    backups_dir.mkdir(parents=True, exist_ok=True)
    marker.write_text(today, encoding='utf-8')


def _configure_environment(args, data_dir: Path, logger: logging.Logger) -> None:
    import os

    secret_key = os.environ.get('KIESE_SECRET_KEY')
    if not secret_key:
        logger.error("KIESE_SECRET_KEY absent de l'environnement — abandon du démarrage.")
        sys.exit(1)

    # Ces variables doivent être posées AVANT `django.setup()` : c'est
    # `kiese/settings.py` (importé par `kiese/settings_desktop.py`) qui les
    # lit pour construire SECRET_KEY/ALLOWED_HOSTS/DATABASES (voir le
    # commentaire en tête de settings_desktop.py).
    os.environ['DJANGO_SECRET_KEY'] = secret_key
    os.environ['DJANGO_DEBUG'] = 'False'
    os.environ['DJANGO_ALLOWED_HOSTS'] = f'{args.host},127.0.0.1,localhost'
    os.environ['DB_ENGINE'] = 'django.db.backends.sqlite3'
    os.environ['DB_NAME'] = str(data_dir / 'kiese.sqlite3')
    os.environ['KIESE_DATA_DIR'] = str(data_dir)
    os.environ['KIESE_BUNDLE_DIR'] = str(_bundle_dir())
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'kiese.settings_desktop')


def _apply_migrations(logger: logging.Logger, db_path: Path, backups_dir: Path) -> None:
    from django.core.management import call_command
    from django.db import connections
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connections['default'])
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    if plan:
        logger.info('%d migration(s) en attente — sauvegarde préalable obligatoire.', len(plan))
        pre_migration_backup = backup_database(db_path, backups_dir, logger)
        _mark_pre_migration_backup(backups_dir, pre_migration_backup, logger)
    else:
        _maybe_daily_backup(db_path, backups_dir, logger)

    logger.info('Application des migrations...')
    call_command('migrate', interactive=False, verbosity=1)

    with connections['default'].cursor() as cur:
        cur.execute('PRAGMA journal_mode=WAL;')
        cur.execute('PRAGMA synchronous=NORMAL;')
        cur.execute('PRAGMA busy_timeout=5000;')
    logger.info('Mode WAL confirmé.')


def _mark_pre_migration_backup(backups_dir: Path, backup_path: Optional[Path], logger: logging.Logger) -> None:
    """Écrit le nom de la sauvegarde prise juste avant `migrate` dans un
    marqueur texte (BUG-073), pour que `desktop/src/main.ts` puisse citer
    ce fichier précis dans le message d'erreur si la migration échoue
    ensuite — l'utilisateur n'a alors pas à deviner laquelle, parmi les
    sauvegardes listées dans l'écran Administration, est « celle d'avant
    la mise à jour »."""
    marker = backups_dir / '.last_pre_migration_backup'
    if backup_path is None:
        return
    try:
        marker.write_text(backup_path.name, encoding='utf-8')
    except OSError:
        logger.warning('Impossible d\'écrire le marqueur de sauvegarde pré-migration (non bloquant).')


def _start_sync_loop(logger: logging.Logger) -> None:
    """Service de synchronisation en tâche de fond (DESKTOP.md §5/§9), best
    effort : son absence ou son échec ne doit jamais empêcher Waitress de
    démarrer (continuité de service locale avant tout, objectif n°4 du
    cahier des charges)."""
    import os
    import threading

    if not (os.environ.get('KIESE_NODE_TOKEN') and os.environ.get('KIESE_CLOUD_URL')):
        logger.info('Synchronisation non configurée (hors-ligne volontaire) — aucune boucle démarrée.')
        return

    def _loop():
        try:
            from sync.desktop_client import run_sync_forever
            run_sync_forever(logger)
        except Exception:  # noqa: BLE001 - ne doit jamais remonter au thread principal
            logger.exception('Service de synchronisation : arrêt inattendu, Waitress continue.')

    thread = threading.Thread(target=_loop, name='kiese-sync-loop', daemon=True)
    thread.start()
    logger.info('Service de synchronisation démarré en tâche de fond.')


def _run_single_management_command(argv) -> None:
    """
    Mode ponctuel : `kiese-server.exe manage --data-dir <dir> <commande> [args...]`.

    Utilisé par `desktop/src/main.ts` pour exécuter une commande `manage.py`
    isolée (ex. `ensure_local_admin`) sans démarrer Waitress — par exemple
    juste après l'assistant de première installation (DESKTOP.md §7 étape
    5), en réutilisant exactement le même environnement/la même base que le
    mode serveur (pas de second process Python avec un contrat différent).
    """
    import os

    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', required=True)
    ns, remaining = parser.parse_known_args(argv)

    data_dir = Path(ns.data_dir)
    ensure_data_dirs(data_dir)
    logger = configure_logging(data_dir)

    fake_args = argparse.Namespace(host='127.0.0.1')
    _configure_environment(fake_args, data_dir, logger)
    sys.path.insert(0, str(_bundle_dir()))

    import django
    django.setup()

    from django.core.management import call_command

    logger.info('Commande de gestion ponctuelle : %s', remaining)
    call_command(*remaining)
    logger.info('Commande de gestion ponctuelle terminée avec succès.')


def _run_backup_or_restore(mode: str, argv) -> int:
    """Modes ponctuels `backup` / `restore` (BUG-403/404), sans Django ni
    secrets : `kiese-server.exe backup --data-dir D` ou
    `kiese-server.exe restore --data-dir D --file kiese-XXXX.sqlite3.gz`.
    Écrit une ligne JSON sur stdout (`{"ok": true, ...}`) ; code 0 si OK."""
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--file')
    ns = parser.parse_args(argv)
    data_dir = Path(ns.data_dir)
    ensure_data_dirs(data_dir)
    logger = configure_logging(data_dir)
    db_path = data_dir / 'kiese.sqlite3'
    backups_dir = data_dir / 'backups'
    try:
        if mode == 'backup':
            dest = backup_database(db_path, backups_dir, logger, label='manuelle', with_seconds=True)
            if dest is None:
                raise RestoreError('Aucune base de données à sauvegarder.')
            result = {'ok': True, 'path': str(dest)}
        else:
            safety = restore_database(db_path, backups_dir, ns.file or '', logger)
            result = {'ok': True, 'safetyCopy': safety.name}
    except RestoreError as exc:
        result = {'ok': False, 'error': str(exc)}
    except Exception:  # noqa: BLE001
        logger.exception('Échec du mode %s.', mode)
        result = {'ok': False, 'error': 'Erreur inattendue (voir logs\\backend.log).'}
    print(json.dumps(result, ensure_ascii=True), flush=True)
    return 0 if result['ok'] else 1


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == 'manage':
        _run_single_management_command(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] in ('backup', 'restore'):
        sys.exit(_run_backup_or_restore(sys.argv[1], sys.argv[2:]))

    args = parse_args()
    data_dir = Path(args.data_dir)
    ensure_data_dirs(data_dir)
    logger = configure_logging(data_dir)
    logger.info('=== Démarrage du backend KIESE (port=%s, data_dir=%s) ===', args.port, data_dir)

    _configure_environment(args, data_dir, logger)
    sys.path.insert(0, str(_bundle_dir()))

    import django
    django.setup()

    db_path = data_dir / 'kiese.sqlite3'
    try:
        _apply_migrations(logger, db_path, data_dir / 'backups')
    except Exception:
        # Code de sortie dédié (BUG-073) : une sauvegarde automatique a
        # déjà été créée juste avant `migrate` (voir `_apply_migrations` /
        # `_mark_pre_migration_backup`) ; les données sont intactes. La
        # décision du client (restauration manuelle guidée, pas de
        # rollback automatique) est appliquée côté Electron
        # (`desktop/src/main.ts`), qui reconnaît ce code de sortie précis
        # pour afficher un message actionnable plutôt que de redémarrer
        # le process en boucle.
        logger.exception(
            "Échec de l'application des migrations — abandon. Une sauvegarde automatique "
            "a été créée juste avant la migration (voir %s/backups) ; aucune donnée n'a été "
            "perdue. Restauration manuelle requise depuis l'écran Administration.",
            data_dir,
        )
        sys.exit(MIGRATION_FAILED_EXIT_CODE)

    _start_sync_loop(logger)

    from kiese.wsgi import application
    from waitress import serve

    logger.info('Prêt. Démarrage de Waitress sur %s:%s', args.host, args.port)
    print(f'KIESE_READY port={args.port}', flush=True)  # repéré par desktop/src/backend.ts dans les logs
    serve(application, host=args.host, port=args.port, threads=8)


if __name__ == '__main__':
    main()
