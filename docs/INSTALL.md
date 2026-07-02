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

## Smoke Path

After installation, initialize state and run the local mock path:

```bash
ai-orch init
ai-orch agents --repo . --check
ai-orch start --task "Check the install path" --repo .
ai-orch status TASK_ID --repo .
```

For release verification, run:

```bash
python -m pytest
python -m compileall ai_orchestrator
ai-orch verify --repo .
ai-orch release-check --repo .
git diff --check
```
