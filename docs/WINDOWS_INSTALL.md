# Windows Install Guide

This is the simplest Windows path for installing `ai-orch` from a checked-out
repository. It creates a local virtual environment, installs the package,
generates a safe local config when needed, and runs `ai-orch doctor`.

The installer does not ask for API keys, does not create `.env` files, and does
not read private auth files. Authenticate worker CLIs such as Codex, Claude,
Kimi, or Gemini through their own login/setup flows before using them as real
workers.

## Prerequisites

- Windows 10 or newer.
- Python 3.12 or newer from the Microsoft Store, python.org, or another trusted
  Python distribution.
- The project repository downloaded or cloned locally.

Optional real worker CLIs:

- `codex`
- `claude`
- `kimi`
- `gemini`

If none are installed, `ai-orch setup` falls back to the safe `mock` worker for
smoke tests.

## One-Command Install

First extract the downloaded release ZIP. Then from the extracted project folder
run the root installer:

```cmd
INSTALL_WINDOWS.cmd
```

The installer window stays open when it finishes so you can read the result.
For scripted smoke tests, pass `/nopause`.

The lower-level script is also available from Command Prompt:

```cmd
scripts\install_windows.cmd
```

From PowerShell:

```powershell
.\scripts\install_windows.ps1
```

The script will:

1. Check for Python 3.12+.
2. Create `.venv` when it does not exist.
3. Install `ai-orchestrator` into `.venv`.
4. Run `python -m ai_orchestrator --version`.
5. Create `.ai-orch/state` and `.ai-orch/reports`.
6. Run `ai-orch setup --repo . --force` to generate a safe config for the
   current machine.
7. Create a simple root launcher: `ai-orch.cmd`.
8. Run `ai-orch doctor --repo .`.
9. Write an install log under `.ai-orch/install-logs/`.

The default behavior intentionally refreshes `.ai-orch/config.yaml` because the
checked-out repository may contain a maintainer or example config that is not
right for your machine.

To keep an existing config during install:

```powershell
.\scripts\install_windows.ps1 -KeepConfig
```

To explicitly regenerate config:

```powershell
.\scripts\install_windows.ps1 -ForceSetup
```

## Development Install

Use editable mode with development tools:

```powershell
.\scripts\install_windows.ps1 -Dev
```

## Regenerate Config

By default, the installer regenerates `.ai-orch/config.yaml` for the current
machine.

To be explicit:

```powershell
.\scripts\install_windows.ps1 -ForceSetup
```

## Skip Doctor

Use this only when you want installation without readiness diagnostics:

```powershell
.\scripts\install_windows.ps1 -SkipDoctor
```

## After Installation

Run commands through the root launcher:

```powershell
.\ai-orch.cmd doctor
.\ai-orch.cmd agents --check
.\ai-orch.cmd start --task "Check setup"
```

In Command Prompt, omit the leading `.\`:

```cmd
ai-orch.cmd doctor
ai-orch.cmd agents --check
ai-orch.cmd start --task "Check setup"
```

If you run `.\ai-orch.cmd` without arguments, it prints common commands and
runs `doctor`.

If you installed Codex, Claude, Kimi, or Gemini and want a real worker, log in
with that tool first. Keep raw provider keys outside `.ai-orch/config.yaml`;
use the worker CLI's native login, environment variables, OS/user secret store,
service manager, or CI secrets.

## Troubleshooting

If Python is not found, install Python 3.12+ and rerun the script.

If `doctor` reports `default_agent_unavailable`, either install/authenticate the
selected worker CLI or run:

```powershell
.\.venv\Scripts\ai-orch.exe setup --repo . --agent mock --force
```

If installation fails because pip cannot access the package index, check network
access or install from an environment that already has the required development
tools cached.

If the installer output disappears or is hard to understand, open the newest
file in `.ai-orch/install-logs/`. It contains the full installation transcript.
