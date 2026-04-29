@echo off
REM POCOBoard - install Python dependencies for source-run (run.bat).
REM The pre-built POCOBoard.exe does NOT need this.

setlocal ENABLEEXTENSIONS
cd /d "%~dp0"

set "PY="
for %%C in (python.exe) do set "PY=%%~$PATH:C"
if not defined PY (
    where /q py && set "PY=py -3"
)
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"

if not defined PY (
    echo.
    echo =====================================================================
    echo  Python was not found on this machine.
    echo.
    echo  Install Python 3.10 or newer from:
    echo    https://www.python.org/downloads/
    echo.
    echo  During installation, CHECK "Add python.exe to PATH", then re-run.
    echo =====================================================================
    echo.
    pause
    exit /b 1
)

echo [+] Python: %PY%
"%PY%" -m pip install --user PySide6
if errorlevel 1 (
    echo [!] PySide6 install failed.
    pause
    exit /b 1
)
REM USB MIDI input for the piano-roll mode uses Win32 winmm.dll directly
REM through ctypes (stdlib), so NO additional Python packages are needed.
echo.
echo [OK] PySide6 installed.  Now double-click run.bat to start POCOBoard.
pause
endlocal
