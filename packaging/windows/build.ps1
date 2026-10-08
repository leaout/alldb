param([switch]$SkipFrontend, [switch]$SkipInstall, [switch]$Clean)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$BuildPython = Join-Path $ProjectRoot ".venv-win-build\Scripts\python.exe"
$env:PYTHONNOUSERSITE = "1"
Set-Location $ProjectRoot

if (-not $SkipFrontend) {
    Push-Location (Join-Path $ProjectRoot "frontend")
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed" }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
    Pop-Location
}

$StaticDir = Join-Path $ProjectRoot "backend\app\static"
if (Test-Path -LiteralPath $StaticDir) { Remove-Item -LiteralPath $StaticDir -Recurse -Force }
New-Item -ItemType Directory -Path $StaticDir | Out-Null
Copy-Item -Path (Join-Path $ProjectRoot "frontend\dist\*") -Destination $StaticDir -Recurse -Force

if (-not (Test-Path -LiteralPath $BuildPython)) {
    python -m venv (Join-Path $ProjectRoot ".venv-win-build")
}
if (-not $SkipInstall) {
    & $BuildPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
    & $BuildPython -m pip install -r (Join-Path $ProjectRoot "backend\requirements-desktop.txt")
    if ($LASTEXITCODE -ne 0) { throw "Backend dependency installation failed" }
    Push-Location (Join-Path $ProjectRoot "desktop")
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "Desktop dependency installation failed" }
    Pop-Location
}

if ($Clean) {
    foreach ($Target in @("build\AllDB-Core", "dist-sidecar", "dist-windows")) {
        $Path = Join-Path $ProjectRoot $Target
        if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path -Recurse -Force }
    }
}

& $BuildPython -m PyInstaller --noconfirm --distpath (Join-Path $ProjectRoot "dist-sidecar") `
    --workpath (Join-Path $ProjectRoot "build\AllDB-Core") `
    (Join-Path $PSScriptRoot "AllDB-Core.spec")
if ($LASTEXITCODE -ne 0) { throw "Python sidecar build failed" }

Push-Location (Join-Path $ProjectRoot "desktop")
npm run dist
if ($LASTEXITCODE -ne 0) { throw "Electron package build failed" }
Pop-Location

$Executable = Get-ChildItem (Join-Path $ProjectRoot "dist-windows\AllDB-Portable-*.exe") | Select-Object -First 1
if (-not $Executable) { throw "Windows portable executable was not produced" }
Write-Host "AllDB Windows package created: $($Executable.FullName)" -ForegroundColor Green
