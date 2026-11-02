# Empaquette le backend Django en exécutable autonome (DESKTOP.md §12).
# À exécuter sur une machine Windows (PyInstaller ne fait pas de
# compilation croisée).
#
# Usage :
#   cd desktop
#   .\scripts\build-backend.ps1
#
# Historique (BUG-078/BUG-079, docs/qa/REGISTRE_BUGS.md) : la version
# précédente de ce script produisait un ".exe" qui soit ne se construisait
# pas du tout (BUG-079 : `--add-data "clients/templates;..."` référence un
# dossier inexistant), soit démarrait mais était totalement inutilisable
# (BUG-078 : `kiese.settings_desktop` et les 9 apps Django du projet ne sont
# jamais analysées statiquement par PyInstaller tant qu'on ne les force pas
# explicitement — ni `--hidden-import` ni `--collect-submodules` ne
# suffisent à eux seuls, voir la fiche BUG-078 pour le détail des 5
# symptômes en cascade). Correction retenue ici : copier l'intégralité du
# code source des 9 apps + du package `kiese` comme fichiers de données
# PyInstaller (`--add-data`), en plus de l'analyse statique habituelle.
# Un fichier `.py` présent tel quel sur le disque, dans un dossier déjà sur
# `sys.path` (voir `backend/desktop_server.py::_bundle_dir()`, inséré en
# tête de `sys.path` avant `django.setup()`), est importable par l'import
# standard de Python QUELLE QUE SOIT la liste des modules déjà repérés par
# l'analyse statique de PyInstaller — ce qui règle d'un coup les symptômes
# 2, 3, 4 et 5 de BUG-078 (settings_desktop manquant, apps du projet non
# chargées, migrations invisibles, sous-modules manquants comme
# `treasury.hashing`/`core.views`/`core.urls`/`treasury.urls`), sans avoir
# à deviner au cas par cas quels sous-modules de chaque app sont réellement
# importés par la chaîne de démarrage.
#
# Un test de fumée FONCTIONNEL (pas seulement « le process démarre ») est
# exécuté en fin de script, sur le binaire réellement produit, dans un
# dossier de données temporaire isolé : si l'exécutable ne répond pas, si la
# table `core_user` n'existe pas après migration, ou si une route API réelle
# ne répond pas 200/301, le script échoue avec un code de sortie non nul et
# NE COPIE PAS le résultat dans `desktop/resources/backend` — il est hors de
# question de livrer silencieusement un ".exe" cassé comme c'était le cas
# avant (voir BUG-078/BUG-079).

$ErrorActionPreference = 'Stop'

$DesktopDir  = Split-Path -Parent $PSScriptRoot
$RepoRoot    = Split-Path -Parent $DesktopDir
$BackendDir  = Join-Path $RepoRoot 'backend'
$VenvDir     = Join-Path $BackendDir '.venv-build'
$OutputDir   = Join-Path $DesktopDir 'resources\backend'
$StagingDir  = Join-Path $BackendDir '.build-staging'
$DistDir     = Join-Path $BackendDir 'dist'
$BuildDir    = Join-Path $BackendDir 'build'
$SpecFile    = Join-Path $BackendDir 'kiese-server.spec'

# Les 9 apps Django du projet (kiese/settings.py::INSTALLED_APPS, section
# « Project apps »). Toute nouvelle app ajoutée au projet DOIT être ajoutée
# ici, sous peine de reproduire exactement BUG-078.
$ProjectApps = @(
    'core', 'clients', 'sales', 'production', 'treasury',
    'commissions', 'finance', 'blockchain', 'sync'
)

function Find-FreeLocalPort {
    $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, 0)
    $listener.Start()
    $port = $listener.LocalEndpoint.Port
    $listener.Stop()
    return $port
}

Write-Host "=== 1/6 : environnement de build Python ==="
if (-not (Test-Path $VenvDir)) {
    python -m venv $VenvDir
}
& "$VenvDir\Scripts\pip.exe" install --upgrade pip
& "$VenvDir\Scripts\pip.exe" install -r "$BackendDir\requirements.txt" waitress pyinstaller

Write-Host "=== 2/6 : collectstatic ==="
# IMPORTANT : jamais `backend/.env` (venv Windows historique OU clé exposée,
# voir CLAUDE.md §6 points 7/9) ne doit être présent ni copié dans le build.
# `collectstatic`/`check` ci-dessous tournent avec `DJANGO_SECRET_KEY`/
# `DJANGO_DEBUG` posés explicitement en variable d'environnement de CETTE
# invocation PowerShell, jamais lus depuis un fichier `.env` du dépôt.
$env:DJANGO_SECRET_KEY = 'build-time-only-not-used-at-runtime'
$env:DJANGO_DEBUG = 'False'
& "$VenvDir\Scripts\python.exe" "$BackendDir\manage.py" collectstatic --noinput --clear

Write-Host "=== 3/6 : préparation des sources applicatives (sans tests/__pycache__) ==="
# BUG-078 : copie l'intégralité du code source des 9 apps du projet + du
# package `kiese` (settings, settings_desktop, urls, wsgi, asgi) dans un
# dossier de préparation, en retirant les dossiers `tests/`/`__pycache__`
# (jamais nécessaires à l'exécution, et `tests/` ne doit jamais contenir de
# vraie donnée client — CLAUDE.md §4 — mais on l'exclut quand même du
# paquet livré par principe de minimalité). Ces dossiers seront ensuite
# ajoutés tels quels via `--add-data`, ce qui les rend importables comme de
# simples fichiers `.py` sur disque, indépendamment de ce que l'analyse
# statique de PyInstaller a ou n'a pas détecté.
if (Test-Path $StagingDir) { Remove-Item $StagingDir -Recurse -Force }
New-Item -ItemType Directory -Path $StagingDir -Force | Out-Null

$PackagesToStage = $ProjectApps + @('kiese')
foreach ($pkg in $PackagesToStage) {
    $src = Join-Path $BackendDir $pkg
    if (-not (Test-Path $src)) {
        throw "Dossier de package introuvable : $src (vérifier la liste `$ProjectApps / `$PackagesToStage dans build-backend.ps1)."
    }
    $dest = Join-Path $StagingDir $pkg
    Copy-Item $src $dest -Recurse -Force
    Get-ChildItem -Path $dest -Recurse -Directory -Include '__pycache__', 'tests' -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force
}

Write-Host "=== 4/6 : PyInstaller (--onedir) ==="
# BUG-079 : l'ancien `--add-data "clients/templates;clients/templates"` a
# été retiré — ce dossier n'a jamais existé dans `backend/clients/`
# (confirmé par recherche exhaustive dans le dépôt), et aucun gabarit HTML
# n'est référencé par `clients/imports.py` ni par aucun autre module de
# cette app : la ligne était soit obsolète, soit une confusion avec un
# autre dossier qui n'a jamais été créé. Les templates HTML réellement
# utilisés par le projet sont ceux de Django lui-même (admin) et de
# `drf_spectacular`, déjà couverts par APP_DIRS=True et les hooks
# PyInstaller tiers (`--collect-submodules django`, etc. ci-dessous).
Push-Location $BackendDir
try {
    # Variables posées pour que toute inspection/éventuel `django.setup()`
    # déclenché par un hook PyInstoller pendant l'analyse voie un
    # environnement cohérent avec le mode desktop réel (BUG-078, piste
    # « DJANGO_SETTINGS_MODULE jamais positionné pendant le build »).
    $BuildProbeDataDir = Join-Path $env:TEMP 'kiese-build-settings-probe'
    New-Item -ItemType Directory -Path $BuildProbeDataDir -Force | Out-Null
    $env:DJANGO_SETTINGS_MODULE = 'kiese.settings_desktop'
    $env:KIESE_SECRET_KEY = 'build-time-only-not-used-at-runtime'
    $env:KIESE_DATA_DIR = $BuildProbeDataDir
    $env:KIESE_BUNDLE_DIR = $BackendDir

    $AddDataArgs = @()
    foreach ($pkg in $PackagesToStage) {
        $AddDataArgs += '--add-data'
        $AddDataArgs += "$(Join-Path $StagingDir $pkg);$pkg"
    }

    # `--contents-directory .` : PyInstaller >= 6.0 place par défaut les
    # données/dépendances d'un build --onedir dans un sous-dossier
    # `_internal/`, plus à côté de l'exécutable. `backend/kiese/
    # settings_desktop.py::BUNDLE_DIR` (donc `STATIC_ROOT`) suppose que
    # `staticfiles/` est un voisin direct de `kiese-server.exe` (cohérent
    # avec `desktop_server.py::_bundle_dir()` = dossier de l'exécutable).
    # Sans ce drapeau, WhiteNoise ne trouve jamais `staticfiles/` (avertit
    # « No directory at ... » mais ne bloque pas le démarrage) — remis à
    # plat ici pour retrouver la disposition « à plat » historique.
    #
    # `--collect-all openpyxl/requests/PIL/reportlab` : ces imports tiers
    # ne sont utilisés que par du code des 9 apps du projet
    # (`clients/imports.py::import openpyxl`,
    # `sync/desktop_client.py::import requests`, Pillow via les champs
    # `ImageField` de Django, reportlab pour les exports PDF) — code
    # désormais fourni comme simples fichiers `.py` sur disque (voir
    # `--add-data` ci-dessous), donc jamais vu par l'analyse statique
    # normale de PyInstoller, qui ne peut alors pas deviner qu'il faut
    # embarquer ces paquets tiers eux-mêmes. Confirmé par un premier build
    # réel sans ces lignes : `ModuleNotFoundError: No module named
    # 'openpyxl'` à la première requête touchant `clients.urls`.
    #
    # `--collect-all` (plutôt que `--collect-submodules`) pour
    # rest_framework/corsheaders/whitenoise/drf_spectacular/django_filters/
    # rest_framework_simplejwt : confirmé nécessaire par un premier test de
    # fumée réel — `--collect-submodules` n'embarque que le code Python,
    # pas les gabarits HTML `APP_DIRS=True` de ces paquets
    # (`drf_spectacular/templates/drf_spectacular/swagger_ui.html`
    # notamment) : `GET /api/docs/swagger/` échouait avec
    # `TemplateDoesNotExist: drf_spectacular/swagger_ui.html` tant que
    # seul `--collect-submodules drf_spectacular` était utilisé.
    & "$VenvDir\Scripts\pyinstaller.exe" `
        --onedir --noconfirm --clean `
        --name kiese-server `
        --contents-directory . `
        --add-data "staticfiles;staticfiles" `
        @AddDataArgs `
        --hidden-import kiese.settings_desktop `
        --hidden-import core.management.commands.ensure_local_admin `
        --hidden-import sync.desktop_client `
        --hidden-import sync.desktop_status `
        --collect-submodules django `
        --collect-all rest_framework `
        --collect-all corsheaders `
        --collect-all whitenoise `
        --collect-all drf_spectacular `
        --collect-all django_filters `
        --collect-all rest_framework_simplejwt `
        --collect-all openpyxl `
        --collect-all requests `
        --collect-all PIL `
        --collect-all reportlab `
        desktop_server.py

    Remove-Item Env:\DJANGO_SETTINGS_MODULE -ErrorAction SilentlyContinue
    Remove-Item Env:\KIESE_SECRET_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:\KIESE_DATA_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:\KIESE_BUNDLE_DIR -ErrorAction SilentlyContinue
} finally {
    Pop-Location
}

$BuiltExe = Join-Path $DistDir 'kiese-server\kiese-server.exe'
if (-not (Test-Path $BuiltExe)) {
    throw "PyInstaller n'a produit aucun exécutable ($BuiltExe introuvable) — build interrompu."
}

Write-Host "=== 5/6 : test de fumée fonctionnel (build réel, dossier de données isolé) ==="
# BUG-078 (addendum) : ne JAMAIS se contenter de vérifier que le process
# démarre — il faut prouver que la base migre réellement (table métier
# créée) ET qu'une route API réelle de CHAQUE couche (core direct, puis
# schéma OpenAPI qui importe les vues/sérialiseurs de toutes les apps via
# `kiese/urls.py`) répond. En cas d'échec : le script s'arrête avec un
# code de sortie non nul, SANS copier quoi que ce soit dans
# `desktop/resources/backend`.
$SmokeDataDir = Join-Path $env:TEMP ("kiese-smoke-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $SmokeDataDir -Force | Out-Null
$SmokePort = Find-FreeLocalPort
$SmokeStdout = Join-Path $SmokeDataDir 'stdout.log'
$SmokeStderr = Join-Path $SmokeDataDir 'stderr.log'

# Jamais `backend/db.sqlite3` réel : `--data-dir` pointe exclusivement vers
# ce dossier temporaire neuf, créé pour ce test uniquement.
$SmokeEnv = @{
    KIESE_SECRET_KEY = 'smoke-test-' + [guid]::NewGuid().ToString('N')
}

$proc = $null
try {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $BuiltExe
    $psi.Arguments = "--port $SmokePort --data-dir `"$SmokeDataDir`" --host 127.0.0.1"
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.EnvironmentVariables.Clear()
    foreach ($kv in [System.Environment]::GetEnvironmentVariables().GetEnumerator()) {
        $psi.EnvironmentVariables[$kv.Key] = $kv.Value
    }
    foreach ($key in $SmokeEnv.Keys) { $psi.EnvironmentVariables[$key] = $SmokeEnv[$key] }
    # Ni jeton de nœud ni URL cloud : le test de fumée vérifie le
    # fonctionnement 100% hors-ligne (contrainte DESKTOP.md), la boucle de
    # synchronisation ne doit pas démarrer.
    $psi.EnvironmentVariables.Remove('KIESE_NODE_TOKEN')
    $psi.EnvironmentVariables.Remove('KIESE_CLOUD_URL')

    $proc = [System.Diagnostics.Process]::Start($psi)

    $stdoutBuffer = New-Object System.Text.StringBuilder
    $stdoutEvent = Register-ObjectEvent -InputObject $proc -EventName OutputDataReceived -Action {
        if ($EventArgs.Data) { [void]$Event.MessageData.AppendLine($EventArgs.Data) }
    } -MessageData $stdoutBuffer
    $stderrBuffer = New-Object System.Text.StringBuilder
    $stderrEvent = Register-ObjectEvent -InputObject $proc -EventName ErrorDataReceived -Action {
        if ($EventArgs.Data) { [void]$Event.MessageData.AppendLine($EventArgs.Data) }
    } -MessageData $stderrBuffer
    $proc.BeginOutputReadLine()
    $proc.BeginErrorReadLine()

    Write-Host "Attente de KIESE_READY (jusqu'à 60 s)..."
    $deadline = (Get-Date).AddSeconds(60)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        if ($proc.HasExited) { break }
        if ($stdoutBuffer.ToString() -match 'KIESE_READY') { $ready = $true; break }
        Start-Sleep -Milliseconds 300
    }

    $stdoutBuffer.ToString() | Out-File -FilePath $SmokeStdout -Encoding utf8
    $stderrBuffer.ToString() | Out-File -FilePath $SmokeStderr -Encoding utf8

    if (-not $ready) {
        if ($proc.HasExited) {
            throw "Le backend empaqueté s'est arrêté avant d'être prêt (code=$($proc.ExitCode)). " +
                  "Voir $SmokeStdout / $SmokeStderr."
        }
        throw "Le backend empaqueté n'a pas affiché KIESE_READY dans le délai de 60 s. Voir $SmokeStdout / $SmokeStderr."
    }
    Write-Host "Backend prêt (port=$SmokePort)."

    Write-Host "Vérification de la table métier 'core_user' (preuve que les migrations des 9 apps du projet s'appliquent réellement)..."
    $dbPath = Join-Path $SmokeDataDir 'kiese.sqlite3'
    if (-not (Test-Path $dbPath)) {
        throw "Base de données absente après démarrage ($dbPath) — migrations non appliquées."
    }
    $checkScript = @"
import sqlite3, sys
conn = sqlite3.connect(r'$dbPath')
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('core_user','clients_client','treasury_cashbookentry')")
found = {row[0] for row in cur.fetchall()}
missing = {'core_user', 'clients_client', 'treasury_cashbookentry'} - found
if missing:
    print('MISSING_TABLES:' + ','.join(sorted(missing)))
    sys.exit(1)
print('OK')
"@
    $checkScriptPath = Join-Path $SmokeDataDir 'check_tables.py'
    $checkScript | Out-File -FilePath $checkScriptPath -Encoding utf8
    & "$VenvDir\Scripts\python.exe" $checkScriptPath
    if ($LASTEXITCODE -ne 0) {
        throw "Tables métier manquantes après migration (voir sortie ci-dessus) — les migrations des 9 apps du projet n'ont pas été appliquées."
    }

    Write-Host "Vérification d'une route API réelle (core) : GET /api/core/config/ ..."
    try {
        $respCore = Invoke-WebRequest -Uri "http://127.0.0.1:$SmokePort/api/core/config/" -UseBasicParsing -TimeoutSec 10
        $coreStatus = $respCore.StatusCode
    } catch [System.Net.WebException] {
        $coreStatus = [int]$_.Exception.Response.StatusCode
    }
    if ($coreStatus -ge 500) {
        throw "GET /api/core/config/ a renvoyé $coreStatus (>=500) — route core non fonctionnelle."
    }
    Write-Host "  -> $coreStatus (attendu : <500)"

    Write-Host "Vérification du schéma OpenAPI (force l'import des vues/sérialiseurs des 9 apps via kiese/urls.py) : GET /api/docs/swagger/ ..."
    $respSwagger = Invoke-WebRequest -Uri "http://127.0.0.1:$SmokePort/api/docs/swagger/" -UseBasicParsing -TimeoutSec 15
    if ($respSwagger.StatusCode -ne 200) {
        throw "GET /api/docs/swagger/ a renvoyé $($respSwagger.StatusCode) (attendu 200) — au moins un sous-module d'une app n'est pas importable dans le binaire figé."
    }
    Write-Host "  -> 200 OK (toutes les apps ont bien chargé leurs vues/urls/sérialiseurs)."

    Write-Host "Test de fumée réussi."
} finally {
    if ($null -ne $proc -and -not $proc.HasExited) {
        try { $proc.Kill() } catch {}
    }
    if ($stdoutEvent) { Unregister-Event -SourceIdentifier $stdoutEvent.Name -ErrorAction SilentlyContinue }
    if ($stderrEvent) { Unregister-Event -SourceIdentifier $stderrEvent.Name -ErrorAction SilentlyContinue }
    Remove-Item $SmokeDataDir -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "=== 6/6 : copie vers desktop/resources/backend ==="
if (Test-Path $OutputDir) { Remove-Item $OutputDir -Recurse -Force }
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
Copy-Item "$DistDir\kiese-server\*" $OutputDir -Recurse -Force

# Garde-fou explicite : refuse de livrer un `.env` dans le paquet, quelle
# que soit la façon dont il aurait pu s'y glisser (CLAUDE.md §6 point 7).
Get-ChildItem -Path $OutputDir -Recurse -Filter '.env*' | ForEach-Object {
    Write-Warning "Suppression d'un fichier .env trouvé dans le paquet backend : $($_.FullName)"
    Remove-Item $_.FullName -Force
}

# Nettoyage des artefacts de build temporaires (dist/, build/, .spec,
# dossier de préparation) : seul `desktop/resources/backend` est le livrable
# attendu par `electron-builder` (voir `desktop/src/paths.ts`).
Remove-Item $StagingDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $DistDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $BuildDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $SpecFile -Force -ErrorAction SilentlyContinue

Write-Host "Backend empaqueté et vérifié par test de fumée : $OutputDir\kiese-server.exe"
