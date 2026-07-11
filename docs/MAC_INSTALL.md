# macOS Install Guide

This guide covers the supported macOS path for running `ai-orch` from a
checked-out repository or release ZIP. It also documents the intended package
channels for future releases.

## Recommended Package Path

For packaged releases, prefer `pipx`:

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
pipx install ai-orch
ai-orch --version
ai-orch demo
```

The Python import package remains `ai_orchestrator`; the published
distribution and console command are both named `ai-orch`.

## Local Repository Install

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
ai-orch --version
ai-orch demo
```

For development:

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

## Codex-First Setup

Install and authenticate the worker CLI outside `ai-orch`, then configure the
project:

```bash
ai-orch setup --profile codex-safe --agent codex
ai-orch doctor agents
ai-orch start --task "Check setup" --repo .
```

`ai-orch` does not store raw provider keys. Codex, Claude, Gemini, Kimi, or a
generic wrapper should manage login and credentials through their native
workflow or environment.

## Homebrew

Homebrew is the planned platform package channel for macOS and Linux. Do not
document `brew install ai-orch` as a supported command until a tap and formula
exist. Use `pipx` or the local repository install path until then.

## Troubleshooting

- If `python3` is older than 3.12, install a newer Python from python.org,
  Homebrew, or your preferred macOS package manager.
- If `ai-orch` is not found after `pipx install`, run `python3 -m pipx
  ensurepath`, then open a new shell.
- If `doctor agents` reports `available=no` for Codex or another real worker,
  install that worker CLI and complete its native login outside `ai-orch`.
- If you only want to confirm the product flow, run `ai-orch demo`; it uses
  `mock` mode and does not require external AI credentials.
