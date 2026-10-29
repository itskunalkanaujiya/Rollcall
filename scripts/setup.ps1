<#
 One-time setup for Windows 10/11 (PowerShell 5.1+).
   powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
 Options: -SkipModel (do not download the face model)  -SkipFrontend (do not run npm install)
 Creates backend\.venv, installs dependencies, generates backend\.env with fresh random secrets,
 creates the database, downloads the face model and installs the frontend packages.
#>
param([switch]$SkipModel, [switch]$SkipFrontend)
$ErrorActionPreference = 'Stop'
$root    = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$front   = Join-Path $root 'frontend'

function Find-Python {
    foreach ($c in @(@('py','-3.12'), @('py','-3.11'), @('py','-3.13'), @('py','-3.10'), @('python'))) {
        try {
            $v = & $c[0] @($c[1..($c.Length-1)] + '--version') 2>&1
            if ($LASTEXITCODE -eq 0 -and "$v" -match 'Python 3\.(\d+)' -and [int]$Matches[1] -ge 10 -and [int]$Matches[1] -le 13) { return ,$c }
        } catch { }
    }
    throw 'Python 3.10 - 3.13 was not found. Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH") and run this script again.'
}
function New-Secret { $b = New-Object byte[] 48; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); ([Convert]::ToBase64String($b)).Replace('+','-').Replace('/','_').TrimEnd('=') }

Write-Host '== 1/6 Python virtual environment' -ForegroundColor Cyan
$py = Find-Python
Set-Location $backend
if (-not (Test-Path '.venv\Scripts\python.exe')) { & $py[0] @($py[1..($py.Length-1)] + @('-m','venv','.venv')) }
$venvPy = Join-Path $backend '.venv\Scripts\python.exe'
& $venvPy -m pip install --upgrade pip
Write-Host '== 2/6 Installing backend packages (a few minutes)' -ForegroundColor Cyan
& $venvPy -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }

Write-Host '== 3/6 Configuration (backend\.env)' -ForegroundColor Cyan
$envFile = Join-Path $backend '.env'
if (-not (Test-Path $envFile)) {
    $tpl = (Get-Content (Join-Path $backend '.env.example') -Raw)
    $tpl = $tpl -replace '(?m)^SECRET_KEY=.*$', "SECRET_KEY=$(New-Secret)"
    $tpl = $tpl -replace '(?m)^EMBEDDING_ENCRYPTION_KEY=.*$', "EMBEDDING_ENCRYPTION_KEY=$(New-Secret)"
    Set-Content -Path $envFile -Value $tpl -Encoding UTF8
    Write-Host "Created $envFile with new random secrets. Back this file up: without EMBEDDING_ENCRYPTION_KEY enrolled faces cannot be read." -ForegroundColor Yellow
} else { Write-Host '.env already exists - left unchanged.' }

Write-Host '== 4/6 Database' -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path (Join-Path $backend 'data') | Out-Null
& $venvPy -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'database migration failed' }

Write-Host '== 5/6 Face recognition model (InsightFace buffalo_l, ~280 MB)' -ForegroundColor Cyan
if ($SkipModel) { Write-Host 'Skipped. Run: backend\.venv\Scripts\python scripts\download_model.py' } else {
    & $venvPy (Join-Path $PSScriptRoot 'download_model.py')
    if ($LASTEXITCODE -ne 0) { Write-Warning 'Model download failed. See README > Face recognition model setup (manual download with --from-zip).' }
}

Write-Host '== 6/6 Frontend packages' -ForegroundColor Cyan
if ($SkipFrontend) { Write-Host 'Skipped.' } else {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw 'Node.js 20+ was not found. Install it from https://nodejs.org/ and run this script again.' }
    Set-Location $front; npm install; if ($LASTEXITCODE -ne 0) { throw 'npm install failed' }
}
Write-Host "`nSetup finished. Next:" -ForegroundColor Green
Write-Host '  1) powershell -File .\scripts\create-admin.ps1     (create the first administrator)'
Write-Host '  2) powershell -File .\scripts\run.ps1              (start backend + frontend, then open http://localhost:5173)'
