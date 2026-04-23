@echo off
REM POCOBoard - build POCOBoard.exe
REM Works on Windows 10/11 (cmd.exe). ASCII messages only so nothing
REM garbles regardless of the console code page.

setlocal ENABLEEXTENSIONS ENABLEDELAYEDEXPANSION
cd /d "%~dp0"

REM -------- locate a usable Python --------
REM In order: python on PATH, py launcher, common install locations.
set "PY="
for %%C in (python.exe) do set "PY=%%~$PATH:C"
if not defined PY (
    where /q py && set "PY=py -3"
)
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if not defined PY if exist "C:\Python313\python.exe" set "PY=C:\Python313\python.exe"
if not defined PY if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe"
if not defined PY if exist "C:\Python311\python.exe" set "PY=C:\Python311\python.exe"

if not defined PY (
    echo.
    echo =====================================================================
    echo  Python was not found on this machine.
    echo.
    echo  Install Python 3.10 or newer from:
    echo    https://www.python.org/downloads/
    echo.
    echo  During installation, CHECK "Add python.exe to PATH" on the first
    echo  page of the installer.  Then re-run build.bat.
    echo =====================================================================
    echo.
    pause
    exit /b 1
)

echo [+] Python: %PY%
"%PY%" --version
if errorlevel 1 (
    echo [!] "%PY%" did not run.  Reinstall Python and try again.
    pause
    exit /b 1
)

REM -------- install build deps if missing --------
"%PY%" -c "import PySide6" 2>nul
if errorlevel 1 (
    echo [+] Installing PySide6 ...
    "%PY%" -m pip install --user PySide6
    if errorlevel 1 (
        echo [!] PySide6 install failed.
        pause
        exit /b 1
    )
)

"%PY%" -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [+] Installing PyInstaller ...
    "%PY%" -m pip install --user pyinstaller
    if errorlevel 1 (
        echo [!] PyInstaller install failed.
        pause
        exit /b 1
    )
)

REM -------- build --------
REM Invoke PyInstaller as a module so we don't depend on pyinstaller.exe
REM being on PATH (pip --user sometimes puts it outside PATH).
echo [+] Building POCOBoard.exe (this takes about a minute) ...
"%PY%" -m PyInstaller --noconfirm --clean pocoboard.spec
if errorlevel 1 (
    echo [!] Build failed.  Scroll up for the PyInstaller error.
    pause
    exit /b 1
)

echo.
echo =====================================================================
echo  [OK] Build complete.
echo       Run:        dist\POCOBoard\POCOBoard.exe
echo       Distribute: zip the entire  dist\POCOBoard  folder and send it.
echo =====================================================================
echo.
pause
endlocal
