@echo off
setlocal
set "ROOT=%~dp0."
set "AI_ORCH=%ROOT%\.venv\Scripts\ai-orch.exe"
set "PATH=%ROOT%\.venv\Scripts;%PATH%"

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
  echo   ai-orch.cmd doctor agents
  echo   ai-orch.cmd start --task "Check setup"
  echo   ai-orch.cmd status TASK_ID
  echo.
  echo Running doctor now:
  echo.
  "%AI_ORCH%" doctor --repo "%ROOT%"
  if errorlevel 1 exit /b %ERRORLEVEL%
  echo.
  echo Running agent diagnostics now:
  echo.
  "%AI_ORCH%" doctor agents --repo "%ROOT%"
  exit /b %ERRORLEVEL%
)

"%AI_ORCH%" %* --repo "%ROOT%"
exit /b %ERRORLEVEL%
