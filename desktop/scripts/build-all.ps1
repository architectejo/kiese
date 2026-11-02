# Construction complète de l'installeur KIESE (DESKTOP.md §12).
# À exécuter sur une machine de build Windows (PyInstaller ne fait pas de
# compilation croisée depuis Linux/macOS).
#
# Usage :
#   cd desktop
#   .\scripts\build-all.ps1
#
# Résultat : desktop\dist-installer\KIESE-Setup-<version>.exe

$ErrorActionPreference = 'Stop'
$ScriptDir = $PSScriptRoot

Write-Host "=== Étape 1/3 : frontend ==="
& "$ScriptDir\build-frontend.ps1"

Write-Host "=== Étape 2/3 : backend ==="
& "$ScriptDir\build-backend.ps1"

Write-Host "=== Étape 3/3 : electron-builder (NSIS) ==="
$DesktopDir = Split-Path -Parent $ScriptDir
Push-Location $DesktopDir
try {
    npm ci
    npm run build
    npx electron-builder --win nsis --config electron-builder.yml
} finally {
    Pop-Location
}

Write-Host "Terminé. Voir desktop\dist-installer\"
