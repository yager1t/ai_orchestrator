param(
    [switch]$Dev,
    [switch]$ForceSetup,
    [switch]$KeepConfig,
    [switch]$SkipDoctor
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message"
}

function Resolve-Python {
    $candidates = @(
        @{ Command = "py"; Args = @("-3.12") },
        @{ Command = "py"; Args = @("-3") },
        @{ Command = "python"; Args = @() }
    )

    foreach ($candidate in $candidates) {
        $command = Get-Command $candidate.Command -ErrorAction SilentlyContinue
        if ($null -eq $command) {
            continue
        }

        $versionArgs = @($candidate.Args) + @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)")
        & $command.Source @versionArgs | Out-Null
        if ($LASTEXITCODE -eq 0) {
            return @{ Command = $command.Source; Args = $candidate.Args }
        }
    }

    throw "Python 3.12+ was not found. Install Python from https://www.python.org/downloads/windows/ and re-run this script."
}

function Invoke-Python {
    param(
        [hashtable]$Python,
        [string[]]$Arguments
    )

    $AllArgs = @($Python.Args) + $Arguments
    & $Python.Command @AllArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $($Python.Command) $($Python.Args -join ' ') $($Arguments -join ' ')"
    }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$VenvDir = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvAiOrch = Join-Path $VenvDir "Scripts\ai-orch.exe"
$ConfigPath = Join-Path $RepoRoot ".ai-orch\config.yaml"
$StateDir = Join-Path $RepoRoot ".ai-orch\state"
$ReportsDir = Join-Path $RepoRoot ".ai-orch\reports"

Write-Host "AI Orchestrator Windows installer"
Write-Host "Repository: $RepoRoot"
Write-Host "Mode: $(if ($Dev) { 'editable dev install' } else { 'local user install' })"

Write-Step "Checking Python"
$Python = Resolve-Python
Write-Host "Using Python launcher: $($Python.Command) $($Python.Args -join ' ')"

if (-not (Test-Path $VenvPython)) {
    Write-Step "Creating virtual environment"
    Invoke-Python -Python $Python -Arguments @("-m", "venv", $VenvDir)
} else {
    Write-Step "Using existing virtual environment"
}

Write-Step "Installing ai-orch"
if ($Dev) {
    & $VenvPython -m pip install -e "$RepoRoot[dev]"
} else {
    & $VenvPython -m pip install $RepoRoot
}
if ($LASTEXITCODE -ne 0) {
    throw "Package installation failed."
}

Write-Step "Checking ai-orch command"
& $VenvPython -m ai_orchestrator --version
if ($LASTEXITCODE -ne 0) {
    throw "ai-orch version check failed."
}

Write-Step "Creating local ai-orch config"
$null = New-Item -ItemType Directory -Force -Path $StateDir
$null = New-Item -ItemType Directory -Force -Path $ReportsDir
$SetupArgs = @("-m", "ai_orchestrator", "setup", "--repo", $RepoRoot)
if ($ForceSetup -or (-not $KeepConfig)) {
    $SetupArgs += "--force"
}

if ((Test-Path $ConfigPath) -and $KeepConfig -and (-not $ForceSetup)) {
    Write-Host "Keeping existing config: $ConfigPath"
    Write-Host "Remove -KeepConfig or use -ForceSetup to regenerate it."
} else {
    & $VenvPython @SetupArgs
    if ($LASTEXITCODE -ne 0) {
        throw "ai-orch setup failed."
    }
}

if (-not $SkipDoctor) {
    Write-Step "Running ai-orch doctor"
    & $VenvPython -m ai_orchestrator doctor --repo $RepoRoot
    if ($LASTEXITCODE -ne 0) {
        throw "ai-orch doctor reported setup issues."
    }
}

Write-Step "Done"
Write-Host "Run ai-orch from this repository with:"
Write-Host "  .\.venv\Scripts\ai-orch.exe doctor --repo ."
Write-Host "  .\.venv\Scripts\ai-orch.exe start --repo . --task `"Check setup`""
Write-Host ""
Write-Host "API keys are not stored by this installer. Authenticate Codex, Claude, Kimi, or Gemini with their own login/setup flow before using them as real workers."
