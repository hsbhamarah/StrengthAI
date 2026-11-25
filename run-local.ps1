param([ValidateSet('setup', 'api', 'web')][string]$Mode = 'setup')

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
New-Item -ItemType Directory -Force -Path 'data' | Out-Null
trap {
    Set-Content -LiteralPath 'data\run-status.txt' -Value "Failed: $($_.Exception.Message)"
    Write-Host "Startup failed: $($_.Exception.Message)" -ForegroundColor Red
    break
}
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$npm = 'C:\Program Files\nodejs\npm.cmd'

if ($Mode -eq 'api') {
    & $python -m uvicorn strengthos.main:app --host 127.0.0.1 --port 8000 --no-access-log
    exit $LASTEXITCODE
}
if ($Mode -eq 'web') {
    & $npm run dev
    exit $LASTEXITCODE
}

Set-Content -LiteralPath 'data\run-status.txt' -Value 'Creating Python environment'
if (-not (Test-Path -LiteralPath $python)) {
    $systemPython = Get-Command py -ErrorAction SilentlyContinue
    if ($systemPython) {
        & $systemPython.Source -3.12 -m venv .venv
    } else {
        $systemPython = Get-Command python -ErrorAction SilentlyContinue
        if ($systemPython) {
            & $systemPython.Source -m venv .venv
        } else {
            $runtimePython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
            if (-not (Test-Path -LiteralPath $runtimePython)) { throw 'Python 3.12 is required to create .venv' }
            & $runtimePython -m venv .venv
        }
    }
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed' }
}

$ErrorActionPreference = 'Continue'
& $python -m pip install --no-index -r requirements.txt *> $null
$pythonReady = $LASTEXITCODE -eq 0
$ErrorActionPreference = 'Stop'
if (-not $pythonReady) {
    Set-Content -LiteralPath 'data\run-status.txt' -Value 'Installing Python packages'
    $ErrorActionPreference = 'Continue'
    & $python -m pip install -r requirements.txt 2>&1 | Tee-Object -FilePath 'data\pip-install.log'
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) { throw 'Python package installation failed. Check data\pip-install.log; package registry access is required.' }
}

$ErrorActionPreference = 'Continue'
& $npm ls --depth=0 --silent *> $null
$frontendReady = $LASTEXITCODE -eq 0
$ErrorActionPreference = 'Stop'
if (-not $frontendReady) {
    Set-Content -LiteralPath 'data\run-status.txt' -Value 'Installing frontend packages'
    $ErrorActionPreference = 'Continue'
    & $npm install 2>&1 | Tee-Object -FilePath 'data\npm-install.log'
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) { throw 'Frontend package installation failed. Check data\npm-install.log; package registry access is required.' }
}

Set-Content -LiteralPath 'data\run-status.txt' -Value 'Building frontend'
& $npm run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }

Set-Content -LiteralPath 'data\run-status.txt' -Value 'Initializing database'
& $python -m strengthos.storage migrate
if ($LASTEXITCODE -ne 0) { throw "Private workspace migration failed. Original data retained." }
& $python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed' }

$needsEmail = & $python -c "from strengthos.main import setup_status; print(int(setup_status()['needs_email_setup']))"
if ($needsEmail -eq '1') {
    & $python -m strengthos.setup
    if ($LASTEXITCODE -ne 0) { throw 'Coach account setup failed' }
}

Set-Content -LiteralPath 'data\run-status.txt' -Value 'Starting services'
$shell = (Get-Command powershell.exe).Source
Start-Process -FilePath $shell -ArgumentList @('-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', '.\run-local.ps1', '-Mode', 'api') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden

Start-Sleep -Seconds 5
try {
    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/health' -TimeoutSec 5
    $page = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000' -TimeoutSec 5
    if ($health.status -ne 'ok' -or $page.StatusCode -ne 200) { throw 'Health check failed' }
    $setup = Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/auth/setup-status'
    $landing = if ($setup.signup_available) { 'http://127.0.0.1:8000/sign-up' } else { 'http://127.0.0.1:8000/sign-in' }
    Set-Content -LiteralPath 'data\run-status.txt' -Value "Running at $landing"
    Start-Process $landing
    Write-Host "StrengthOS AI is running at $landing"
} catch {
    Set-Content -LiteralPath 'data\run-status.txt' -Value "Services started but health check failed: $($_.Exception.Message)"
    throw
}
