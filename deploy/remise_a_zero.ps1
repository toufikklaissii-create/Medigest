#Requires -Version 5.1
<#
.SYNOPSIS
    Après les essais d'installation : repartir d'une base vierge (aucune patiente, aucune facture).
    Les données d'essai ne sont PAS effacées : elles sont déplacées dans C:\Medigest\sauvegardes.
    Ensuite, relancer INSTALLER.cmd (il recrée la base et redemande les mots de passe Medigest).
    Ne jamais utiliser une fois le cabinet en activité.
#>
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Racine  = "C:\Medigest"
$Donnees = Join-Path $Racine "donnees"

$identite = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $identite.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Lancer PowerShell en administrateur." -ForegroundColor Red; exit 1
}
if (-not (Test-Path $Donnees)) { Write-Host "Rien à remettre à zéro." ; exit 0 }

Write-Host "Toutes les patientes, RDV et factures vont être retirés de Medigest." -ForegroundColor Yellow
if ((Read-Host "Taper REMISE A ZERO pour confirmer") -ne "REMISE A ZERO") { Write-Host "Annulé."; exit 0 }

Stop-ScheduledTask -TaskName "Medigest - serveur" -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*waitress*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

$cible = Join-Path $Racine ("sauvegardes\donnees_essais_" + (Get-Date -Format "yyyy-MM-dd_HH-mm"))
Move-Item $Donnees $cible
Write-Host "Données d'essai déplacées dans $cible" -ForegroundColor Green
Write-Host "Relancer maintenant INSTALLER.cmd pour recréer une base vierge." -ForegroundColor Green
