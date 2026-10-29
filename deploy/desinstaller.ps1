#Requires -Version 5.1
<#
.SYNOPSIS
    Retire Medigest d'un PC de RÉPÉTITION (tâches, pare-feu, raccourci, C:\Medigest, Python 3.14 laissé).
    Jamais sur le PC du cabinet : les données des patientes seraient supprimées.
#>
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$identite = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $identite.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Lancer PowerShell en administrateur." -ForegroundColor Red; exit 1
}
Write-Host "Ceci SUPPRIME C:\Medigest (base, documents, sauvegardes) sur CE PC." -ForegroundColor Red
if ((Read-Host "Taper DESINSTALLER pour confirmer") -ne "DESINSTALLER") { Write-Host "Annulé."; exit 0 }

foreach ($tache in @("Medigest - serveur", "Medigest - sauvegarde")) {
    if (Get-ScheduledTask -TaskName $tache -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $tache -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $tache -Confirm:$false
    }
}
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*waitress*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2
Get-NetFirewallRule -DisplayName "Medigest" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Remove-Item "C:\Users\Public\Desktop\Medigest.url" -Force -ErrorAction SilentlyContinue
if (Test-Path "C:\Medigest") { Remove-Item "C:\Medigest" -Recurse -Force }
Write-Host "Medigest retiré. (Python 3.14 et la session Windows « Assistante », si créée, sont conservés.)" -ForegroundColor Green
