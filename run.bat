@echo off
REM run.bat - start LOWASS (console). Use run-silent.bat for no console window.
REM First start creates .venv and installs the packages. The "py" launcher is NOT installed with the Microsoft Store
REM Python, so several names are tried. Written without labels/goto (they misbehave in .bat files with LF line endings).
setlocal
cd /d "%~dp0"

if exist .venv\Scripts\python.exe (
  .venv\Scripts\python -m lowass %*
  if errorlevel 1 pause
  exit /b
)

set "PY="
for %%C in ("py -3.13" "py -3" "python" "python3") do (
  if not defined PY (
    %%~C -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PY=%%~C"
  )
)
if not defined PY (
  echo No Python 3.11 or newer found. Install Python 3.13 from python.org or the Microsoft Store, then open a NEW window.
  pause
  exit /b 1
)

echo Creating the virtual environment with: %PY%
%PY% -m venv .venv
if errorlevel 1 (
  echo Could not create .venv.
  pause
  exit /b 1
)
.venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 (
  echo Installing the packages failed.
  pause
  exit /b 1
)
.venv\Scripts\python -m lowass %*
if errorlevel 1 pause
