@echo off
title Tatura MT5 Bridge - Desktop App
cd /d "%~dp0"

set "PY="

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys" >nul 2>nul
  if not errorlevel 1 set "PY=.venv\Scripts\python.exe"
)
if defined PY goto :found_py

py -3.12 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=py -3.12"
if defined PY goto :found_py

py -3.11 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=py -3.11"
if defined PY goto :found_py

py -3.10 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=py -3.10"
if defined PY goto :found_py

python -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto :found_py

echo [ERROR] Python 3.10 - 3.12 (64-bit) was not found.
echo Download Python 3.12 (64-bit) from https://www.python.org/downloads/
echo Make sure to check "Add Python to PATH" during installation.
pause
exit /b 1

:found_py
echo Using Python: %PY%
%PY% -c "import sys, struct; print('Python', sys.version.split()[0], str(struct.calcsize('P')*8) + '-bit')"

if not exist "config.json" (
  if exist "config.example.json" copy "config.example.json" "config.json" >nul
)

%PY% -c "import MetaTrader5" >nul 2>nul
if not errorlevel 1 goto :launch

echo.
echo Installing MetaTrader5 package...
%PY% -c "import sys; sys.exit(0 if sys.prefix != sys.base_prefix else 1)" >nul 2>nul
if not errorlevel 1 goto :pip_venv

%PY% -m pip install --user --disable-pip-version-check --no-input MetaTrader5
goto :after_pip

:pip_venv
%PY% -m pip install --disable-pip-version-check --no-input MetaTrader5

:after_pip
if errorlevel 1 (
  echo.
  echo [WARNING] Could not install MetaTrader5 automatically.
  echo Note: The official MetaTrader5 package requires 64-bit Python 3.10, 3.11, or 3.12.
  echo The GUI will still open so you can check settings.
  pause
)

:launch
echo.
echo Launching Tatura MT5 Desktop Terminal...
%PY% tatura_desktop.py
if errorlevel 1 (
  echo.
  echo [ERROR] Tatura Desktop exited with an error. Check tatura_crash.log if created.
)
echo.
pause
