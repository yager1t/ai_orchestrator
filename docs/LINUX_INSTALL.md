# Linux Install Guide

This is the simplest Ubuntu/Linux path for installing `ai-orch` from a
checked-out or extracted repository.

The installer creates a local virtual environment, installs the package,
generates a machine-local `.ai-orch/config.yaml`, creates local state/report
directories, and runs `ai-orch doctor`.

It does not ask for API keys and does not store secrets.

## One-Command Install

From the repository root:

```bash
bash INSTALL_LINUX.sh
```

If Python 3.12+ is missing, the installer asks whether it should try installing
Python 3.12 through `apt`. To skip the question:

```bash
bash INSTALL_LINUX.sh --install-python
```

If `apt` cannot install Python 3.12 on your Ubuntu release, install
`python3.12` and `python3.12-venv` manually, then rerun `bash INSTALL_LINUX.sh`.

## After Installation

Run:

```bash
./ai-orch
./ai-orch doctor
./ai-orch doctor agents
./ai-orch start --task "Check setup"
```

The `./ai-orch` launcher prepends `.venv/bin` to `PATH`, so verification
commands such as `python -m pytest` work even when you did not run
`source .venv/bin/activate`. Running `./ai-orch` without arguments prints common
commands, runs `doctor`, and then runs `doctor agents`.

If Codex is not installed on the machine, setup selects another detected worker
or falls back to `mock`. This is expected for a first smoke test.

## Keep Existing Config

By default, the installer refreshes `.ai-orch/config.yaml` for the current
machine. To keep an existing config:

```bash
bash INSTALL_LINUX.sh --keep-config
```

## Development Install

```bash
bash INSTALL_LINUX.sh --dev
```

## Troubleshooting

If `doctor` reports `default_agent_unavailable`, regenerate the local config:

```bash
./.venv/bin/python -m ai_orchestrator setup --repo . --agent mock --force
./.venv/bin/python -m ai_orchestrator doctor --repo .
./.venv/bin/python -m ai_orchestrator doctor agents --repo .
```

If Python exists but venv creation fails, install the venv package for your
Python version, for example:

```bash
sudo apt-get install python3.12-venv
```
