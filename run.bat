@echo off
REM POCOBoard - source-run launcher (developer convenience).
REM For end users, just use the POCOBoard.exe produced by build.bat.

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
if not defined PY if exist "C:\Python313\python.exe" set "PY=C:\Python313\python.exe"
if not defined PY if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe"

if not defined PY (
    echo.
    echo =====================================================================
    echo  Python was not found on this machine.
    echo.
    echo  Install Python 3.10 or newer from:
    echo    https://www.python.org/downloads/
    echo.
    echo  During installation, CHECK "Add python.exe to PATH".
    echo =====================================================================
    echo.
    pause
    exit /b 1
)

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

"%PY%" pocoboard.py %*
endlocal
