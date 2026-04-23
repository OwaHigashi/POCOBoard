@echo off
REM ---- POCOBoard — source-run launcher ---------------------------------
REM Use this when you want to run from Python source (e.g. after editing).
REM For end users, the POCOBoard.exe produced by build.bat is easier.

setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [!] Python が見つかりません。
    echo     https://www.python.org/downloads/ から Python 3.10 以降をインストールしてください。
    echo     インストール時に "Add python.exe to PATH" にチェックを入れてください。
    pause
    exit /b 1
)

python -c "import PySide6" 2>nul
if errorlevel 1 (
    echo [*] PySide6 が未インストールです。pip で導入します...
    python -m pip install --user PySide6
    if errorlevel 1 (
        echo [!] PySide6 のインストールに失敗しました。
        pause
        exit /b 1
    )
)

python pocoboard.py %*
endlocal
