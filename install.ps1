param(
    [string]$Workspace = (Get-Location).Path,
    [switch]$SkipDownloaderClone
)

$ErrorActionPreference = "Stop"
$workspacePath = [IO.Path]::GetFullPath($Workspace)
if (-not (Test-Path -LiteralPath $workspacePath)) {
    New-Item -ItemType Directory -Path $workspacePath -Force | Out-Null
}
$packageRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$venvPath = Join-Path $workspacePath ".venv"
$pythonPath = Join-Path $venvPath "Scripts\python.exe"
$downloaderPath = Join-Path $workspacePath "douyin-downloader"
$requirementsPath = Join-Path $packageRoot "requirements.txt"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw "Python 3.9 or newer is required."
    }
    Write-Host "Creating Python virtual environment..."
    & python -m venv $venvPath
    if ($LASTEXITCODE -ne 0) { throw "Failed to create the Python virtual environment." }
}

Write-Host "Installing local dependencies..."
& $pythonPath -m pip install --disable-pip-version-check --progress-bar off --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Failed to upgrade pip." }
& $pythonPath -m pip install --disable-pip-version-check --progress-bar off -r $requirementsPath
if ($LASTEXITCODE -ne 0) { throw "Failed to install Python dependencies." }
& $pythonPath -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw "Failed to install the Playwright Chromium browser." }
& $pythonPath -m pip check
if ($LASTEXITCODE -ne 0) { throw "Installed Python packages have incompatible dependencies." }

if (-not $SkipDownloaderClone -and -not (Test-Path -LiteralPath (Join-Path $downloaderPath "run.py"))) {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "git is required to download douyin-downloader. Install Git or rerun with -SkipDownloaderClone."
    }
    Write-Host "Downloading the independent douyin-downloader dependency..."
    & git clone "https://github.com/jiji262/douyin-downloader.git" $downloaderPath
    if ($LASTEXITCODE -ne 0) { throw "Failed to clone douyin-downloader." }
}

if (Test-Path -LiteralPath $downloaderPath) {
    $exampleConfig = Join-Path $downloaderPath "config.example.yml"
    $localConfig = Join-Path $downloaderPath "config.yml"
    if ((Test-Path -LiteralPath $exampleConfig) -and -not (Test-Path -LiteralPath $localConfig)) {
        Copy-Item -LiteralPath $exampleConfig -Destination $localConfig
        Write-Host "Created config.yml from config.example.yml. Complete local login configuration before processing."
    }
}

Write-Host "Running readiness diagnostics..."
& $pythonPath (Join-Path $packageRoot "scripts\doctor.py") --workspace $workspacePath
if ($LASTEXITCODE -ne 0) { throw "Readiness diagnostics failed unexpectedly." }

Write-Host "Installation complete. Finish Douyin login locally before processing favorites."
