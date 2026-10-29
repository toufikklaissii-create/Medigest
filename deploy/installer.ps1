#Requires -Version 5.1
<#
.SYNOPSIS
    Installe Medigest sur le PC du cabinet, ou le met à jour. Lancer INSTALLER.cmd (droits administrateur).

    Première fois : Python, code, base neuve, comptes Medigest, session Windows « Assistante »,
    serveur au démarrage du PC, pare-feu, sauvegardes, raccourci.
    Ensuite (C:\Medigest\medigest.env existe) : mise à jour. Sauvegarde d'abord, puis nouveau code ;
    en cas d'échec, l'ancien code et la base d'avant sont remis automatiquement.

    C:\Medigest\app          le code (remplacé à chaque mise à jour)
    C:\Medigest\donnees      la base et les documents des patientes (jamais touchés par une mise à jour)
    C:\Medigest\sauvegardes  copies de la base et des documents
    C:\Medigest\medigest.env la configuration et la clé secrète
    Le dossier n'est lisible que par les administrateurs et le système : pas par la session Assistante.
#>
param(
    [switch]$SansSessionAssistante
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$Racine        = "C:\Medigest"
$App           = Join-Path $Racine "app"
$AppPrecedente = Join-Path $Racine "app_precedente"
$Venv          = Join-Path $Racine "venv"
$VenvPython    = Join-Path $Venv "Scripts\python.exe"
$Donnees       = Join-Path $Racine "donnees"
$Base          = Join-Path $Donnees "db.sqlite3"
$Logs          = Join-Path $Racine "logs"
$Sauvegardes   = Join-Path $Racine "sauvegardes"
$EnvFile       = Join-Path $Racine "medigest.env"
$Port          = 8000
$Slug          = "cabinet-dr-errmili"
$UrlLocale     = "http://localhost:$Port/c/$Slug/login/"

$PythonVersion = "3.14.5"
$PythonUrl     = "https://www.python.org/ftp/python/3.14.5/python-3.14.5-amd64.exe"
$PythonSha256  = "F9C09F5ED6F796FD1A8BC5DDFA41715A494B453C4781F0E35D5077CF9FA58F6D"
$PythonDir     = "C:\Program Files\Python314"
$PythonExe     = Join-Path $PythonDir "python.exe"

$TacheServeur    = "Medigest - serveur"
$TacheSauvegarde = "Medigest - sauvegarde"
$SessionAssistante = "Assistante"

$Source = Split-Path -Parent $PSScriptRoot

function Etape([string]$texte) { Write-Host "`n== $texte ==" -ForegroundColor Cyan }
function Ok([string]$texte)    { Write-Host "   OK  $texte" -ForegroundColor Green }
function Info([string]$texte)  { Write-Host "   ..  $texte" }
function Attention([string]$texte) { Write-Host "   !!  $texte" -ForegroundColor Yellow }
function Echec([string]$texte) { throw $texte }

function Lancer([string]$exe, [string[]]$arguments, [string]$messageErreur) {
    # Les programmes externes écrivent parfois sur stderr sans échouer : seul le code de sortie compte.
    $ancien = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $exe @arguments
    $code = $LASTEXITCODE
    $ErrorActionPreference = $ancien
    if ($code -ne 0) { Echec "$messageErreur (code $code)" }
}

function Django([string[]]$arguments, [string]$messageErreur) {
    Push-Location $App
    try { Lancer $VenvPython (@("manage.py") + $arguments) $messageErreur }
    finally { Pop-Location }
}

function Question([string]$texte) {
    while ($true) {
        $reponse = (Read-Host "   ?   $texte (O/N)").Trim().ToUpper()
        if ($reponse -in @("O", "OUI")) { return $true }
        if ($reponse -in @("N", "NON")) { return $false }
    }
}

function Arreter-Serveur {
    if (Get-ScheduledTask -TaskName $TacheServeur -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TacheServeur -ErrorAction SilentlyContinue
    }
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like "*waitress*" -and $_.CommandLine -like "*config.wsgi*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}

function Attendre-Serveur([int]$secondes = 60) {
    $limite = (Get-Date).AddSeconds($secondes)
    while ((Get-Date) -lt $limite) {
        try {
            $reponse = Invoke-WebRequest -Uri $UrlLocale -UseBasicParsing -TimeoutSec 5
            if ($reponse.StatusCode -eq 200) { return $true }
        } catch { Start-Sleep -Seconds 2 }
    }
    return $false
}

function Adresses-Reseau {
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" -and $_.PrefixOrigin -ne "WellKnown" } |
        Select-Object -ExpandProperty IPAddress
}

# --- Vérifications -------------------------------------------------------------------------------

$identite = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $identite.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Lancer INSTALLER.cmd : il demande lui-même les droits administrateur." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path (Join-Path $Source "manage.py"))) {
    Write-Host "manage.py introuvable dans $Source : lancer le script depuis le dossier deploy du projet téléchargé." -ForegroundColor Red
    exit 1
}
if ($Source.TrimEnd("\") -ieq $App) {
    Write-Host "Ne pas lancer l'installation depuis C:\Medigest\app : utiliser le dossier téléchargé." -ForegroundColor Red
    exit 1
}

$MiseAJour = Test-Path $EnvFile
foreach ($dossier in @($Racine, $Donnees, $Logs, $Sauvegardes)) {
    New-Item -ItemType Directory -Force -Path $dossier | Out-Null
}
$journal = Join-Path $Logs ("installation_" + (Get-Date -Format "yyyy-MM-dd_HH-mm") + ".log")
Start-Transcript -Path $journal | Out-Null

$codeRetour = 0
try {
    if ($MiseAJour) {
        Write-Host "`nMISE À JOUR de Medigest (les données des patientes sont conservées)." -ForegroundColor Magenta
    } else {
        Write-Host "`nINSTALLATION de Medigest sur ce PC." -ForegroundColor Magenta
    }

    # --- 1. Python -------------------------------------------------------------------------------
    Etape "1/10  Python $PythonVersion"
    if (Test-Path $PythonExe) {
        Ok "déjà installé ($PythonDir)"
    } else {
        $installeur = Join-Path $env:TEMP "python-$PythonVersion-amd64.exe"
        Info "téléchargement depuis python.org (environ 30 Mo)..."
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $PythonUrl -OutFile $installeur -UseBasicParsing
        if ((Get-FileHash $installeur -Algorithm SHA256).Hash -ne $PythonSha256) {
            Echec "le fichier Python téléchargé est corrompu (empreinte différente) : relancer l'installation."
        }
        Info "installation silencieuse..."
        $arguments = "/quiet InstallAllUsers=1 PrependPath=0 Include_launcher=0 Include_test=0 Include_doc=0 Include_tcltk=0 Shortcuts=0 TargetDir=`"$PythonDir`""
        $processus = Start-Process -FilePath $installeur -ArgumentList $arguments -Wait -PassThru
        if ($processus.ExitCode -ne 0 -or -not (Test-Path $PythonExe)) { Echec "installation de Python impossible (code $($processus.ExitCode))." }
        Remove-Item $installeur -Force -ErrorAction SilentlyContinue
        Ok "installé dans $PythonDir"
    }

    # --- 2. Arrêt et sauvegarde ------------------------------------------------------------------
    Etape "2/10  Arrêt du serveur et sauvegarde"
    Arreter-Serveur
    $sauvegardeAvant = $null
    if ((Test-Path $Base) -and (Test-Path $VenvPython) -and (Test-Path (Join-Path $App "deploy\sauvegarde.py"))) {
        Lancer $VenvPython @((Join-Path $App "deploy\sauvegarde.py")) "sauvegarde avant mise à jour impossible : rien n'a été modifié"
        $sauvegardeAvant = Get-ChildItem (Join-Path $Sauvegardes "base") -Filter *.sqlite3 | Sort-Object LastWriteTime | Select-Object -Last 1
        Ok "base sauvegardée : $($sauvegardeAvant.Name)"
    } else {
        Ok "rien à sauvegarder (première installation)"
    }

    try {
        # --- 3. Code ---------------------------------------------------------------------------------
        Etape "3/10  Copie du code dans $App"
        if (Test-Path $App) {
            if (Test-Path $AppPrecedente) { Remove-Item $AppPrecedente -Recurse -Force }
            Rename-Item -Path $App -NewName (Split-Path $AppPrecedente -Leaf)
            Info "ancienne version gardée dans $AppPrecedente"
        }
        $exclusDossiers = @(".git", ".claude", ".agents", ".codex", ".design_refs", ".impeccable", ".pytest_cache",
                            "design_reference", "docs", "tests", "venv", ".venv", "env", "media", "backups",
                            "staticfiles", "node_modules", "__pycache__", "logs")
        $exclusFichiers = @(".mcp.json", ".env", "db.sqlite3", "db.sqlite3-journal", "*.pyc",
                            "medigest_code_complet.txt", "skills-lock.json", "Questions_Dr_Errmili.html")
        $ancien = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        & robocopy $Source $App /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1 /XD @exclusDossiers /XF @exclusFichiers | Out-Null
        $codeRobocopy = $LASTEXITCODE; $ErrorActionPreference = $ancien
        if ($codeRobocopy -ge 8) { Echec "copie du code impossible (robocopy $codeRobocopy)." }
        Ok "code copié"

        # --- 4. Environnement Python ---------------------------------------------------------------
        Etape "4/10  Librairies Python (internet nécessaire)"
        if (-not (Test-Path $VenvPython)) {
            Lancer $PythonExe @("-m", "venv", $Venv) "création de l'environnement Python impossible"
        }
        Lancer $VenvPython @("-m", "pip", "install", "--disable-pip-version-check", "--quiet",
                             "-r", (Join-Path $App "deploy\requirements-prod.txt")) `
            "installation des librairies impossible : vérifier la connexion internet puis relancer"
        Ok "librairies à jour"

        # --- 5. Configuration ----------------------------------------------------------------------
        Etape "5/10  Configuration"
        if (Test-Path $EnvFile) {
            Ok "configuration existante conservée ($EnvFile)"
        } else {
            $secret = & $VenvPython -c "import secrets; print(secrets.token_urlsafe(50))"
            $racineSlash = $Racine.Replace("\", "/")
            @(
                "# Configuration Medigest du cabinet. NE PAS PARTAGER : contient la clé secrète.",
                "DJANGO_SECRET_KEY=$secret",
                "DEBUG=False",
                "ALLOWED_HOSTS=*",
                "DATABASE_URL=sqlite:///$racineSlash/donnees/db.sqlite3",
                "MEDIA_ROOT=$racineSlash/donnees/media",
                "LOG_DIR=$racineSlash/logs",
                "# Adresse donnée aux téléphones (QR code) : auto = IP actuelle du PC, recalculée au démarrage.",
                "PUBLIC_BASE_URL=auto",
                "# Copie supplémentaire des sauvegardes (disque USB par exemple) : SAUVEGARDE_COPIE=E:\Medigest",
                "SAUVEGARDE_COPIE="
            ) | Set-Content -Path $EnvFile -Encoding ASCII
            Ok "configuration créée avec une clé secrète unique"
        }

        # --- 6. Base de données --------------------------------------------------------------------
        Etape "6/10  Base de données et fichiers"
        Django @("migrate", "--noinput") "mise à jour de la base impossible"
        Django @("collectstatic", "--noinput") "préparation des fichiers de l'interface impossible"
        if (-not $MiseAJour) {
            Write-Host ""
            Write-Host "   Choisir maintenant les mots de passe Medigest (8 caractères minimum, pas que des chiffres)." -ForegroundColor Yellow
            Write-Host "   Ils ne s'affichent pas pendant la frappe : c'est normal." -ForegroundColor Yellow
        }
        # Ne demande un mot de passe qu'aux comptes qui n'en ont pas encore : rien en mise à jour normale.
        Django @("installer_cabinet") "création du cabinet impossible"
        Ok "base prête"
    } catch {
        if ($MiseAJour -and (Test-Path $AppPrecedente)) {
            Attention "échec : retour à la version précédente..."
            if (Test-Path $App) { Remove-Item $App -Recurse -Force -ErrorAction SilentlyContinue }
            Rename-Item -Path $AppPrecedente -NewName (Split-Path $App -Leaf)
            if ($sauvegardeAvant) { Copy-Item $sauvegardeAvant.FullName $Base -Force }
            try { Start-ScheduledTask -TaskName $TacheServeur } catch { }
            Attention "version précédente remise en service, base d'avant restaurée."
        }
        throw
    }

    # --- 7. Droits sur C:\Medigest ---------------------------------------------------------------
    Etape "7/10  Protection du dossier C:\Medigest"
    # SID et non noms de groupes : fonctionne sur un Windows français comme anglais.
    Lancer "icacls" @($Racine, "/inheritance:r", "/grant:r", "*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F", "/Q") `
        "protection du dossier impossible"
    Ok "accès réservé aux administrateurs et au système (la session Assistante ne peut pas l'ouvrir)"

    # --- 8. Session Windows Assistante -------------------------------------------------------------
    Etape "8/10  Session Windows « $SessionAssistante »"
    if ($SansSessionAssistante) {
        Info "ignorée (option -SansSessionAssistante)"
    } elseif (Get-LocalUser -Name $SessionAssistante -ErrorAction SilentlyContinue) {
        Ok "la session existe déjà"
    } elseif (Question "Créer la session Windows standard « $SessionAssistante » (sans droits administrateur) ?") {
        while ($true) {
            $mdp1 = Read-Host "   Mot de passe Windows de la session $SessionAssistante" -AsSecureString
            $mdp2 = Read-Host "   Retapez-le" -AsSecureString
            $t1 = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($mdp1))
            $t2 = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($mdp2))
            if ($t1 -ne $t2) { Attention "les deux saisies sont différentes"; continue }
            if ($t1.Length -lt 4) { Attention "4 caractères minimum"; continue }
            break
        }
        New-LocalUser -Name $SessionAssistante -Password $mdp1 -FullName "Assistante" -Description "Accueil du cabinet" -PasswordNeverExpires | Out-Null
        Add-LocalGroupMember -SID "S-1-5-32-545" -Member $SessionAssistante -ErrorAction SilentlyContinue
        Ok "session $SessionAssistante créée (utilisateur standard)"
    } else {
        Info "non créée"
    }

    # --- 9. Réseau, veille, tâches planifiées -----------------------------------------------------
    Etape "9/10  Démarrage automatique, pare-feu, sauvegardes"
    foreach ($profil in Get-NetConnectionProfile -ErrorAction SilentlyContinue) {
        if ($profil.NetworkCategory -eq "Public") {
            if (Question "Le réseau « $($profil.Name) » est en mode Public : le PC de la doctoresse ne pourra pas se connecter. Le passer en Privé ?") {
                Set-NetConnectionProfile -InterfaceIndex $profil.InterfaceIndex -NetworkCategory Private
                Ok "réseau « $($profil.Name) » passé en Privé"
            }
        }
    }
    Get-NetFirewallRule -DisplayName "Medigest" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName "Medigest" -Description "Medigest : PC de la doctoresse et téléphones du cabinet" `
        -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Private,Domain | Out-Null
    Ok "pare-feu : port $Port ouvert sur le réseau privé uniquement"

    # Le PC sert la doctoresse : pas de veille sur secteur, pas de redémarrage Windows Update en consultation.
    & powercfg /change standby-timeout-ac 0 | Out-Null
    & powercfg /change hibernate-timeout-ac 0 | Out-Null
    $cleWU = "HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings"
    if (Test-Path $cleWU) {
        Set-ItemProperty -Path $cleWU -Name ActiveHoursStart -Value 8 -Type DWord
        Set-ItemProperty -Path $cleWU -Name ActiveHoursEnd -Value 19 -Type DWord
    }
    Ok "pas de mise en veille sur secteur, heures d'activité Windows Update 8h-19h"

    $systeme = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $reglagesServeur = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
        -StartWhenAvailable -MultipleInstances IgnoreNew
    $actionServeur = New-ScheduledTaskAction -Execute $VenvPython -WorkingDirectory $App `
        -Argument "-m waitress --listen=*:$Port --threads=8 config.wsgi:application"
    Register-ScheduledTask -TaskName $TacheServeur -Force -Principal $systeme -Settings $reglagesServeur `
        -Action $actionServeur -Trigger (New-ScheduledTaskTrigger -AtStartup) `
        -Description "Serveur Medigest (http://localhost:$Port)" | Out-Null
    Ok "serveur lancé à chaque démarrage du PC, relancé automatiquement en cas d'arrêt"

    $reglagesSauvegarde = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    $actionSauvegarde = New-ScheduledTaskAction -Execute $VenvPython -WorkingDirectory $App `
        -Argument "`"$(Join-Path $App 'deploy\sauvegarde.py')`""
    Register-ScheduledTask -TaskName $TacheSauvegarde -Force -Principal $systeme -Settings $reglagesSauvegarde `
        -Action $actionSauvegarde `
        -Trigger @((New-ScheduledTaskTrigger -Daily -At "12:30"), (New-ScheduledTaskTrigger -Daily -At "16:45")) `
        -Description "Sauvegarde Medigest dans $Sauvegardes" | Out-Null
    Ok "sauvegardes à 12h30 et 16h45 (rattrapées au démarrage si le PC était éteint)"

    # --- 10. Démarrage et vérification -------------------------------------------------------------
    Etape "10/10  Démarrage du serveur"
    Start-ScheduledTask -TaskName $TacheServeur
    if (-not (Attendre-Serveur 90)) { Echec "le serveur ne répond pas : voir $Logs\medigest.log" }
    Ok "Medigest répond sur $UrlLocale"
    if ($MiseAJour -and (Test-Path $AppPrecedente)) {
        Info "ancienne version conservée dans $AppPrecedente jusqu'à la prochaine mise à jour"
    }

    $raccourci = "[InternetShortcut]`r`nURL=$UrlLocale`r`n"
    Set-Content -Path "C:\Users\Public\Desktop\Medigest.url" -Value $raccourci -Encoding ASCII
    Ok "raccourci « Medigest » sur le bureau de toutes les sessions"

    $adresses = @("http://$($env:COMPUTERNAME):$Port/c/$Slug/login/") + (Adresses-Reseau | ForEach-Object { "http://$($_):$Port/c/$Slug/login/" })
    $adresses | Set-Content -Path (Join-Path $Racine "ADRESSES.txt") -Encoding UTF8

    Write-Host "`n============================================================" -ForegroundColor Green
    Write-Host " Medigest est prêt." -ForegroundColor Green
    Write-Host " Sur ce PC        : $UrlLocale"
    Write-Host " PC de la doctoresse (essayer dans l'ordre) :"
    $adresses | ForEach-Object { Write-Host "                    $_" }
    Write-Host " Journal          : $journal"
    Write-Host "============================================================" -ForegroundColor Green
} catch {
    $codeRetour = 1
    Write-Host "`nERREUR : $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Journal complet : $journal" -ForegroundColor Red
} finally {
    Stop-Transcript | Out-Null
}
exit $codeRetour
