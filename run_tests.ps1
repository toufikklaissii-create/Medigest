<#
.SYNOPSIS
    Exécute la suite complète de tests Django (pytest-django) avec rapport de synthèse.
#>

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$VenvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Error "Environnement virtuel introuvable : $VenvPython."
}

Write-Host "== Exécution de la suite de tests Medigest ==" -ForegroundColor Cyan

& $VenvPython -m pytest -v --tb=short
$ExitCode = $LASTEXITCODE

Write-Host ""
if ($ExitCode -eq 0) {
    Write-Host "== Tous les tests sont passés avec succès ==" -ForegroundColor Green
} else {
    Write-Host "== Des tests ont échoué (code de sortie $ExitCode) ==" -ForegroundColor Red
}

exit $ExitCode
