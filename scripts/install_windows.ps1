param(
    [switch]$Dev,
    [switch]$ForceSetup,
    [switch]$KeepConfig,
    [switch]$InstallPython,
    [switch]$SkipDoctor
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$InstallLogDir = Join-Path $RepoRoot ".ai-orch\install-logs"
$null = New-Item -ItemType Directory -Force -Path $InstallLogDir
$InstallLogPath = Join-Path $InstallLogDir ("install-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
Start-Transcript -Path $InstallLogPath -Force | Out-Null

trap {
    Write-Host ""
    Write-Host "INSTALL FAILED" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    Write-Host "Log file: $InstallLogPath"
    Write-Host "Fix the issue above and run scripts\install_windows.cmd again."
    Stop-Transcript | Out-Null
    exit 1
}

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message"
}

function Get-PythonCandidate {
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

    return $null
}

function Update-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

function Install-PythonWithWinget {
    $winget = Get-Command "winget" -ErrorAction SilentlyContinue
    if ($null -eq $winget) {
        throw @"
Python 3.12+ was not found, and winget is not available.

Install Python manually:
  1. Open https://www.python.org/downloads/windows/
  2. Install Python 3.12 or newer.
  3. Enable "Add python.exe to PATH" if the installer asks.
  4. Run INSTALL_WINDOWS.cmd again.
"@
    }

    Write-Step "Installing Python 3.12 with winget"
    & $winget.Source install --exact --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw @"
Python installation through winget failed.

Manual fix:
  1. Open https://www.python.org/downloads/windows/
  2. Install Python 3.12 or newer.
  3. Run INSTALL_WINDOWS.cmd again.
"@
    }
    Update-ProcessPath
}

function Resolve-Python {
    $python = Get-PythonCandidate
    if ($null -ne $python) {
        return $python
    }

    if ($InstallPython) {
        Install-PythonWithWinget
        $python = Get-PythonCandidate
        if ($null -ne $python) {
            return $python
        }
        throw @"
Python was installed, but this terminal cannot see it yet.

Close this window, open the extracted project folder again, and run:
  INSTALL_WINDOWS.cmd
"@
    }

    throw @"
Python 3.12+ was not found.

Fast fix:
  Double-click INSTALL_WINDOWS.cmd again with automatic Python install enabled:
    INSTALL_WINDOWS.cmd /install-python

Manual fix:
  1. Open https://www.python.org/downloads/windows/
  2. Install Python 3.12 or newer.
  3. Enable "Add python.exe to PATH" if the installer asks.
  4. Run INSTALL_WINDOWS.cmd again.
"@
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

$VenvDir = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvAiOrch = Join-Path $VenvDir "Scripts\ai-orch.exe"
$ConfigPath = Join-Path $RepoRoot ".ai-orch\config.yaml"
$StateDir = Join-Path $RepoRoot ".ai-orch\state"
$ReportsDir = Join-Path $RepoRoot ".ai-orch\reports"
$LauncherPath = Join-Path $RepoRoot "ai-orch.cmd"

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

Write-Step "Creating launcher"
$LauncherText = @'
@echo off
setlocal
set "ROOT=%~dp0."
set "AI_ORCH=%ROOT%\.venv\Scripts\ai-orch.exe"

if not exist "%AI_ORCH%" (
  echo ai-orch is not installed yet.
  echo Run scripts\install_windows.cmd first.
  exit /b 1
)

if "%~1"=="" (
  echo AI Orchestrator is installed.
  echo.
  echo Common commands:
  echo   ai-orch.cmd doctor
  echo   ai-orch.cmd agents --check
  echo   ai-orch.cmd start --task "Check setup"
  echo   ai-orch.cmd status TASK_ID
  echo.
  echo Running doctor now:
  echo.
  "%AI_ORCH%" doctor --repo "%ROOT%"
  exit /b %ERRORLEVEL%
)

"%AI_ORCH%" %* --repo "%ROOT%"
exit /b %ERRORLEVEL%
'@
$LauncherText | Set-Content -Path $LauncherPath -Encoding ASCII

Write-Step "INSTALL COMPLETE"
Write-Host "Installed version:"
& $VenvPython -m ai_orchestrator --version
Write-Host ""
Write-Host "Project folder:"
Write-Host "  $RepoRoot"
Write-Host ""
Write-Host "Launcher created:"
Write-Host "  .\ai-orch.cmd"
Write-Host ""
Write-Host "What to do next:"
Write-Host "  1. Run diagnostics:"
Write-Host "     PowerShell: .\ai-orch.cmd doctor"
Write-Host "     Command Prompt: ai-orch.cmd doctor"
Write-Host "  2. See detected workers:"
Write-Host "     PowerShell: .\ai-orch.cmd agents --check"
Write-Host "     Command Prompt: ai-orch.cmd agents --check"
Write-Host "  3. Run a first safe task:"
Write-Host "     PowerShell: .\ai-orch.cmd start --task `"Check setup`""
Write-Host "     Command Prompt: ai-orch.cmd start --task `"Check setup`""
Write-Host ""
Write-Host "If you want Codex, Claude, Kimi, or Gemini as real workers, log in with that tool first."
Write-Host "The installer does not store API keys."
Write-Host ""
Write-Host "Log file:"
Write-Host "  $InstallLogPath"
Stop-Transcript | Out-Null
