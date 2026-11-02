# Construit le frontend React (Vite) et le copie dans desktop/resources/frontend
# (DESKTOP.md §12). Aucune valeur `VITE_API_URL` figée n'est nécessaire : le
# port est injecté à l'exécution par `desktop/src/preload.ts`
# (`window.kiese.apiUrl`), voir frontend/src/api/client.ts.

$ErrorActionPreference = 'Stop'

$DesktopDir  = Split-Path -Parent $PSScriptRoot
$RepoRoot    = Split-Path -Parent $DesktopDir
$FrontendDir = Join-Path $RepoRoot 'frontend'
$OutputDir   = Join-Path $DesktopDir 'resources\frontend'

Write-Host "=== 1/2 : npm ci && npm run build ==="
Push-Location $FrontendDir
try {
    npm ci
    npm run build
} finally {
    Pop-Location
}

Write-Host "=== 2/2 : copie vers desktop/resources/frontend ==="
if (Test-Path $OutputDir) { Remove-Item $OutputDir -Recurse -Force }
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
Copy-Item "$FrontendDir\dist\*" $OutputDir -Recurse -Force

Write-Host "Frontend empaqueté : $OutputDir"
