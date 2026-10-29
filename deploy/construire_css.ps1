<#
.SYNOPSIS
    Recompile le CSS du cabinet (static\vendor\medigest.css) après une modification des templates
    ou du thème (static\js\tailwind-theme.js). À lancer sur le PC de développement (Node.js requis).
    Le test tests\test_offline_assets.py échoue tant que ce n'est pas fait.
#>
$ErrorActionPreference = "Stop"
$Racine = Split-Path -Parent $PSScriptRoot
Set-Location $Racine

& npx --yes tailwindcss@3.4.17 -c tailwind.config.js -i static/css/tailwind.input.css -o static/vendor/medigest.css --minify
if ($LASTEXITCODE -ne 0) { throw "Compilation Tailwind impossible." }

$Python = Join-Path $Racine "venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }
& $Python manage.py marquer_css
if ($LASTEXITCODE -ne 0) { throw "Marquage du CSS impossible." }
Write-Host "CSS du cabinet à jour." -ForegroundColor Green
