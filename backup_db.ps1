<#
.SYNOPSIS
    Sauvegarde cohérente de la base SQLite (via l'API de backup SQLite) et archive
    les médias (PDFs) dans backups\YYYY-MM-DD_HH-mm\, avec vérification d'intégrité.
#>

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$VenvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Error "Environnement virtuel introuvable : $VenvPython."
}

$SourceDb = Join-Path $ProjectRoot "db.sqlite3"
if (-not (Test-Path $SourceDb)) {
    Write-Error "Base de données introuvable : $SourceDb."
}

$Timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm"
$BackupDir = Join-Path $ProjectRoot "backups\$Timestamp"
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

$DestDb = Join-Path $BackupDir "db.sqlite3"

Write-Host "== Copie cohérente de la base SQLite (API backup) ==" -ForegroundColor Cyan
$backupScript = @'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dest = sqlite3.connect(sys.argv[2])
with dest:
    src.backup(dest)
src.close()
dest.close()
'@
$backupScriptPath = Join-Path $env:TEMP "medigest_sqlite_backup.py"
Set-Content -Path $backupScriptPath -Value $backupScript -Encoding UTF8

& $VenvPython $backupScriptPath $SourceDb $DestDb
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de la copie de la base de données."
}

Write-Host "== Vérification d'intégrité (PRAGMA integrity_check) ==" -ForegroundColor Cyan
$integrityScript = @'
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
result = conn.execute("PRAGMA integrity_check;").fetchone()[0]
conn.close()
print(result)
sys.exit(0 if result == "ok" else 1)
'@
$integrityScriptPath = Join-Path $env:TEMP "medigest_sqlite_integrity.py"
Set-Content -Path $integrityScriptPath -Value $integrityScript -Encoding UTF8

$integrityResult = & $VenvPython $integrityScriptPath $DestDb
if ($LASTEXITCODE -ne 0) {
    Write-Error "PRAGMA integrity_check a échoué : $integrityResult"
} else {
    Write-Host "Intégrité de la sauvegarde : $integrityResult" -ForegroundColor Green
}

$MediaSource = Join-Path $ProjectRoot "media\documents"
if (Test-Path $MediaSource) {
    Write-Host "== Archivage des médias (PDFs) ==" -ForegroundColor Cyan
    $MediaDest = Join-Path $BackupDir "media\documents"
    New-Item -ItemType Directory -Force -Path $MediaDest | Out-Null
    Copy-Item -Path "$MediaSource\*" -Destination $MediaDest -Recurse -Force
    Write-Host "Médias archivés dans $MediaDest" -ForegroundColor Green
} else {
    Write-Host "Aucun média à archiver (dossier media\documents introuvable)." -ForegroundColor Yellow
}

Write-Host "`nSauvegarde terminée : $BackupDir" -ForegroundColor Green
