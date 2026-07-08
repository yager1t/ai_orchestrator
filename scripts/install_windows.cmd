@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PAUSE_AT_END=1"
if /I "%~1"=="/nopause" (
  set "PAUSE_AT_END=0"
  shift
)

echo AI Orchestrator Windows installer
echo This window will stay open when installation finishes.
echo.

if not exist "%SCRIPT_DIR%install_windows.ps1" (
  echo Could not find "%SCRIPT_DIR%install_windows.ps1".
  echo If you downloaded a ZIP release, extract the ZIP first and run INSTALL_WINDOWS.cmd from the extracted folder.
  echo.
  if "%PAUSE_AT_END%"=="1" pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%install_windows.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
  echo Installation command finished.
  echo Next:
  echo   PowerShell: .\ai-orch.cmd
  echo   Command Prompt: ai-orch.cmd
) else (
  echo Installation failed with exit code %EXIT_CODE%.
  echo If a log was created, check .ai-orch\install-logs in the extracted project folder.
)
echo.
if "%PAUSE_AT_END%"=="1" pause
exit /b %EXIT_CODE%
