#!/usr/bin/env bash
set -u

DEV=0
KEEP_CONFIG=0
INSTALL_PYTHON=0
SKIP_DOCTOR=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dev)
      DEV=1
      shift
      ;;
    --keep-config)
      KEEP_CONFIG=1
      shift
      ;;
    --install-python)
      INSTALL_PYTHON=1
      shift
      ;;
    --skip-doctor)
      SKIP_DOCTOR=1
      shift
      ;;
    *)
      echo "Unknown option: $1"
      echo "Supported: --dev --keep-config --install-python --skip-doctor"
      exit 1
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$REPO_ROOT/.ai-orch/install-logs"
mkdir -p "$LOG_DIR"
LOG_PATH="$LOG_DIR/install-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG_PATH") 2>&1

fail() {
  echo
  echo "INSTALL FAILED"
  echo "$1"
  echo
  echo "Log file: $LOG_PATH"
  exit 1
}

step() {
  echo
  echo "==> $1"
}

python_ok() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1
}

find_python() {
  for candidate in python3.12 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && python_ok "$candidate"; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

install_python_with_apt() {
  if ! command -v apt-get >/dev/null 2>&1; then
    fail "Python 3.12+ was not found, and apt-get is not available. Install Python 3.12+ manually, then rerun bash INSTALL_LINUX.sh."
  fi
  if ! command -v sudo >/dev/null 2>&1; then
    fail "Python 3.12+ was not found, and sudo is not available. Install python3.12 and python3.12-venv manually, then rerun bash INSTALL_LINUX.sh."
  fi

  step "Installing Python 3.12 with apt"
  sudo apt-get update || fail "apt-get update failed."
  sudo apt-get install -y python3.12 python3.12-venv || fail "apt-get install python3.12 python3.12-venv failed. Your Ubuntu release may need a Python 3.12 repository, or you can install Python 3.12 manually."
}

resolve_python() {
  local python_path
  if python_path="$(find_python)"; then
    echo "$python_path"
    return 0
  fi

  if [[ "$INSTALL_PYTHON" -eq 1 ]]; then
    install_python_with_apt
    if python_path="$(find_python)"; then
      echo "$python_path"
      return 0
    fi
    fail "Python was installed, but this terminal cannot see it yet. Open a new terminal in this folder and run: bash INSTALL_LINUX.sh"
  fi

  echo
  echo "Python 3.12+ was not found."
  echo "ai-orch needs Python 3.12 or newer."
  echo
  read -r -p "Install Python 3.12 now with apt? Type Y and press Enter, or press Enter to cancel: " answer
  if [[ "$answer" =~ ^([Yy]|[Yy][Ee][Ss])$ ]]; then
    install_python_with_apt
    if python_path="$(find_python)"; then
      echo "$python_path"
      return 0
    fi
    fail "Python was installed, but this terminal cannot see it yet. Open a new terminal in this folder and run: bash INSTALL_LINUX.sh"
  fi

  fail "Python 3.12+ was not found. Fast fix: bash INSTALL_LINUX.sh --install-python. Manual fix: install python3.12 and python3.12-venv, then rerun bash INSTALL_LINUX.sh."
}

VENV_DIR="$REPO_ROOT/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
LAUNCHER_PATH="$REPO_ROOT/ai-orch"

echo "AI Orchestrator Linux installer"
echo "Repository: $REPO_ROOT"
if [[ "$DEV" -eq 1 ]]; then
  echo "Mode: editable dev install"
else
  echo "Mode: local user install"
fi

step "Checking Python"
PYTHON="$(resolve_python)"
echo "Using Python: $PYTHON"

if [[ ! -x "$VENV_PYTHON" ]]; then
  step "Creating virtual environment"
  "$PYTHON" -m venv "$VENV_DIR" || fail "Could not create .venv. On Ubuntu, install python3.12-venv and rerun bash INSTALL_LINUX.sh."
else
  step "Using existing virtual environment"
fi

step "Installing ai-orch"
if [[ "$DEV" -eq 1 ]]; then
  "$VENV_PYTHON" -m pip install -e "$REPO_ROOT[dev]" || fail "Package installation failed."
else
  "$VENV_PYTHON" -m pip install "$REPO_ROOT" || fail "Package installation failed."
fi

step "Checking ai-orch command"
"$VENV_PYTHON" -m ai_orchestrator --version || fail "ai-orch version check failed."

step "Creating local ai-orch config"
mkdir -p "$REPO_ROOT/.ai-orch/state" "$REPO_ROOT/.ai-orch/reports"
if [[ "$KEEP_CONFIG" -eq 1 && -f "$REPO_ROOT/.ai-orch/config.yaml" ]]; then
  echo "Keeping existing config: $REPO_ROOT/.ai-orch/config.yaml"
  echo "Remove --keep-config to regenerate it for this machine."
else
  "$VENV_PYTHON" -m ai_orchestrator setup --repo "$REPO_ROOT" --force || fail "ai-orch setup failed."
fi

if [[ "$SKIP_DOCTOR" -eq 0 ]]; then
  step "Running ai-orch doctor"
  "$VENV_PYTHON" -m ai_orchestrator doctor --repo "$REPO_ROOT" || fail "ai-orch doctor reported setup issues."
  "$VENV_PYTHON" -m ai_orchestrator doctor agents --repo "$REPO_ROOT" || fail "ai-orch doctor agents reported setup issues."
fi

step "Creating launcher"
cat > "$LAUNCHER_PATH" <<'EOF'
#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AI_ORCH="$ROOT/.venv/bin/ai-orch"
export PATH="$ROOT/.venv/bin:$PATH"

if [[ ! -x "$AI_ORCH" ]]; then
  echo "ai-orch is not installed yet."
  echo "Run: bash INSTALL_LINUX.sh"
  exit 1
fi

cd "$ROOT" || exit 1

if [[ $# -eq 0 ]]; then
  echo "AI Orchestrator is installed."
  echo
  echo "Common commands:"
  echo "  ./ai-orch doctor"
  echo "  ./ai-orch doctor agents"
  echo '  ./ai-orch start --task "Check setup"'
  echo "  ./ai-orch status TASK_ID"
  echo
  echo "Running doctor now:"
  echo
  "$AI_ORCH" doctor --repo "$ROOT" || exit $?
  echo
  echo "Running agent diagnostics now:"
  echo
  "$AI_ORCH" doctor agents --repo "$ROOT"
  exit $?
fi

"$AI_ORCH" "$@"
EOF
chmod +x "$LAUNCHER_PATH"

step "INSTALL COMPLETE"
echo "Installed version:"
"$VENV_PYTHON" -m ai_orchestrator --version
echo
echo "Project folder:"
echo "  $REPO_ROOT"
echo
echo "Launcher created:"
echo "  ./ai-orch"
echo
echo "What to do next:"
echo "  1. Run diagnostics:"
echo "     ./ai-orch doctor"
echo "  2. See detected workers:"
echo "     ./ai-orch doctor agents"
echo "  3. Run a first safe task:"
echo '     ./ai-orch start --task "Check setup"'
echo
echo "If Codex is not installed, setup will use another detected worker or mock."
echo "The installer does not store API keys."
echo
echo "Log file:"
echo "  $LOG_PATH"
