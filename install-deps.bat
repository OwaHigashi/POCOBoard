@echo off
REM ---- POCOBoard — install Python dependencies -----------------------
REM For source-run only (run.bat). 完成版 POCOBoard.exe は依存不要です。

setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [!] Python が見つかりません。
    echo     https://www.python.org/downloads/ から Python 3.10 以降を入れてください。
    echo     インストーラで "Add python.exe to PATH" を必ずチェックしてください。
    pause
    exit /b 1
)

python -m pip install --user PySide6
if errorlevel 1 (
    echo [!] PySide6 のインストールに失敗しました。
    pause
    exit /b 1
)
echo.
echo [ok] PySide6 を導入しました。run.bat をダブルクリックで起動できます。
pause
endlocal
