@echo off
setlocal

pushd "%~dp0" >nul
if errorlevel 1 (
  echo Could not open installer folder.
  pause
  exit /b 1
)

set "PAUSE_AT_END=1"
if /I "%~1"=="/nopause" (
  set "PAUSE_AT_END=0"
  shift
)

if not exist "scripts\install_windows.cmd" (
  echo Could not find scripts\install_windows.cmd.
  echo Make sure you extracted the full release ZIP before running this file.
  echo.
  if "%PAUSE_AT_END%"=="1" pause
  popd >nul
  exit /b 1
)

if "%PAUSE_AT_END%"=="1" (
  call "scripts\install_windows.cmd" %*
) else (
  call "scripts\install_windows.cmd" /nopause %*
)
set "EXIT_CODE=%ERRORLEVEL%"
popd >nul
exit /b %EXIT_CODE%
