@echo off
setlocal

pushd "%~dp0" >nul
if errorlevel 1 (
  echo Could not open installer folder.
  pause
  exit /b 1
)

set "PAUSE_AT_END=1"
set "FORWARD_ARGS="

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="/nopause" (
  set "PAUSE_AT_END=0"
  set "FORWARD_ARGS=%FORWARD_ARGS% /nopause"
  shift
  goto parse_args
)
set "FORWARD_ARGS=%FORWARD_ARGS% %1"
shift
goto parse_args

:args_done

if not exist "scripts\install_windows.cmd" (
  echo Could not find scripts\install_windows.cmd.
  echo Make sure you extracted the full release ZIP before running this file.
  echo.
  if "%PAUSE_AT_END%"=="1" pause
  popd >nul
  exit /b 1
)

call "scripts\install_windows.cmd" %FORWARD_ARGS%
set "EXIT_CODE=%ERRORLEVEL%"
popd >nul
exit /b %EXIT_CODE%
