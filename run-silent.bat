@echo off
REM run-silent.bat - start LOWASS without a console window (everything goes to lowass.log).
REM Uses the virtual environment made by run.bat; without it falls back to the Python on the PATH.
cd /d "%~dp0"
if exist .venv\Scripts\pythonw.exe (
  start "" .venv\Scripts\pythonw.exe -m lowass %*
) else (
  start "" pythonw -m lowass %*
)
