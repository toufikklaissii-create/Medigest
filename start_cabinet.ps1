<#
.SYNOPSIS
    Démarre le cabinet Medigest : active le venv, applique les migrations si besoin,
    lance le serveur Django et ouvre la page de connexion dans le navigateur.
#>

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$VenvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Error "Environnement virtuel introuvable : $VenvPython. Créez-le avec 'python -m venv venv'."
}

Write-Host "== Vérification des migrations en attente ==" -ForegroundColor Cyan
$pending = & $VenvPython manage.py showmigrations --plan 2>&1 | Select-String -Pattern "^\[ \]"
if ($pending) {
    Write-Host "Migrations en attente détectées, application en cours..." -ForegroundColor Yellow
    & $VenvPython manage.py migrate
} else {
    Write-Host "Base de données à jour." -ForegroundColor Green
}

$Url = "http://127.0.0.1:8000/accounts/login/"
Write-Host "== Démarrage du serveur Medigest sur $Url ==" -ForegroundColor Cyan

Start-Job -ScriptBlock {
    Start-Sleep -Seconds 2
    Start-Process $using:Url
} | Out-Null

& $VenvPython manage.py runserver 127.0.0.1:8000
