# Install Guide

`ai-orch` exposes both module execution and the `ai-orch` console command. There
are two install modes:

- package-style install for end users;
- repository-local install for contributors, release ZIPs, and smoke testing.

## Package Install

For packaged releases, prefer `pipx` because it installs command-line
applications into isolated environments:

```bash
pipx install ai-orch
ai-orch --version
ai-orch demo
```

The Python import package remains `ai_orchestrator`; the published
distribution and console command are both named `ai-orch`.

WinGet and Homebrew remain planned platform channels until maintainable
manifests/formulae exist. A Linux `curl | bash` install route should be treated
as a future distribution artifact that requires the same release review as any
installer script, not as an ad hoc command copied into docs.

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
ai-orch demo
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

## Linux Installer

On Ubuntu/Linux, use the repository-local installer:

```bash
bash INSTALL_LINUX.sh
```

The Linux installer refreshes `.ai-orch/config.yaml` for the current machine by
default, creates `.ai-orch/state` and `.ai-orch/reports`, and falls back to
`mock` when no real worker CLI is detected. If Python 3.12+ is missing, it
offers an opt-in `apt` bootstrap:

```bash
bash INSTALL_LINUX.sh --install-python
```

After installation, run `./ai-orch` from the repository root to see common next
commands.

## macOS Install

See `docs/MAC_INSTALL.md` for the dedicated macOS path. The short local route is:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
ai-orch demo
```

Homebrew is the planned platform package channel for macOS and Linux once a tap
exists. Until then, use `pipx` for packaged releases or the local install path
from a checkout/release ZIP.

## Smoke Path

After installation, initialize state and run the local mock path:

```bash
ai-orch setup
ai-orch doctor
ai-orch doctor agents --repo .
ai-orch demo
ai-orch onboard
ai-orch fix --task "Check the install path" --repo .
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
