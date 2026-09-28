# ==============================================================================
# PharmaCare Pro Enterprise — Standalone Windows Setup Wizard Builder
# Run from PowerShell: .\build_setup.ps1
# Output: C:\Users\Leke\Desktop\pharm\desktop\dist\PharmaCarePro_Setup.exe
# ==============================================================================

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DesktopDir  = $PSScriptRoot
$VenvPython  = Join-Path $DesktopDir "venv\Scripts\python.exe"
$VenvPip     = Join-Path $DesktopDir "venv\Scripts\pip.exe"
$PyInstallerExe = Join-Path $DesktopDir "venv\Scripts\pyinstaller.exe"
$IconPath    = Join-Path $DesktopDir "app\ui\resources\pharmacare.ico"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Building PharmaCare Pro Enterprise Setup Wizard (.exe)..." -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Ensure PyInstaller is installed in the virtual environment
if (-not (Test-Path $PyInstallerExe)) {
    Write-Host "[1/4] Installing PyInstaller into desktop\venv..." -ForegroundColor Yellow
    & $VenvPip install pyinstaller
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to install PyInstaller."
        exit 1
    }
} else {
    Write-Host "[1/4] PyInstaller is already installed." -ForegroundColor Green
}

# 2. Generate application icon (.ico)
Write-Host "[2/4] Generating multi-resolution Windows icon (pharmacare.ico)..." -ForegroundColor Yellow
& $VenvPython (Join-Path $DesktopDir "installer\make_icon.py")

# 3. Bundle the application with all UI resources, QSS themes, and migrations
Write-Host "[3/4] Packaging PharmaCarePro application runtime..." -ForegroundColor Yellow
$ResourcesSrc = Join-Path $DesktopDir "app\ui\resources"
$MigrationsSrc = Join-Path $DesktopDir "app\db\migrations\versions"
$SharedSrc = Join-Path $ProjectRoot "shared"

Push-Location $ProjectRoot
try {
    & $VenvPython -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --name "PharmaCarePro" `
        --icon "$IconPath" `
        --paths "$ProjectRoot" `
        --paths "$DesktopDir" `
        --add-data "$ResourcesSrc;desktop/app/ui/resources" `
        --add-data "$MigrationsSrc;desktop/app/db/migrations/versions" `
        --add-data "$SharedSrc;shared" `
        --collect-submodules "desktop.app.db.migrations.versions" `
        --hidden-import "shared.enums" `
        --hidden-import "bcrypt" `
        --hidden-import "sqlalchemy.dialects.sqlite" `
        --distpath "$DesktopDir\dist" `
        --workpath "$DesktopDir\build" `
        --specpath "$DesktopDir" `
        "$DesktopDir\app\main.py"

    if ($LASTEXITCODE -ne 0) {
        Write-Error "PyInstaller build failed."
        exit 1
    }
} finally {
    Pop-Location
}

# 4. Compile Single-File Graphical Windows Installation Wizard (PharmaCarePro_Setup.exe)
Write-Host "[4/4] Compiling Graphical Windows Installation Wizard (PharmaCarePro_Setup.exe)..." -ForegroundColor Yellow
& $VenvPython (Join-Path $DesktopDir "installer\compile_wizard.py")
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to compile Setup Wizard."
    exit 1
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " BUILD COMPLETE!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host " Single-File Setup Wizard: $DesktopDir\dist\PharmaCarePro_Setup.exe" -ForegroundColor White
Write-Host ""
