# Install Guide

This project can be installed directly from the repository. The package exposes
both module execution and the `ai-orch` console command.

## Development Install

Use an editable install when developing or running local autopilot iterations:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
ai-orch --version
```

## Local User Install

Use a regular install when testing the packaged command surface:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install .
ai-orch --help
```

The module entrypoint remains available:

```bash
python -m ai_orchestrator --help
```

## Windows Installer

On Windows, use the repository-local installer:

```cmd
INSTALL_WINDOWS.cmd
```

For PowerShell options, development mode, and troubleshooting, see
`docs/WINDOWS_INSTALL.md`. The Windows installer refreshes
`.ai-orch/config.yaml` for the current machine by default; use `-KeepConfig`
when you intentionally want to preserve an existing config. After installation,
run `ai-orch.cmd` from the repository root to see common next commands. If
Python is missing, run `INSTALL_WINDOWS.cmd /install-python` to let the
installer try installing Python 3.12 through winget.

## Smoke Path

After installation, initialize state and run the local mock path:

```bash
ai-orch setup
ai-orch doctor
ai-orch agents --repo . --check
ai-orch start --task "Check the install path" --repo .
ai-orch status TASK_ID --repo .
```

`ai-orch setup` does not ask for, write, or validate raw API keys. For real
workers, authenticate the worker CLI with its native login/setup flow before
running tasks, or inject provider keys outside `.ai-orch/config.yaml` through
environment variables, an OS/user secret store, a service manager, or CI
secrets. The project config should contain commands and policy only, not
credentials.

For release verification, run:

```bash
python -m pytest
python -m compileall ai_orchestrator
ai-orch verify --repo .
ai-orch release-check --repo .
git diff --check
```
