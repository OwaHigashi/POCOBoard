@echo off
REM ---- POCOBoard — build POCOBoard.exe ---------------------------------
REM Produces dist\POCOBoard\POCOBoard.exe + support DLLs.
REM Zip the whole dist\POCOBoard folder to share with others.

setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [!] Python が見つかりません。
    pause
    exit /b 1
)

REM Make sure PyInstaller + PySide6 are available.
python -c "import PySide6" 2>nul || python -m pip install --user PySide6
python -c "import PyInstaller" 2>nul || python -m pip install --user pyinstaller

REM Locate pyinstaller.exe under the user-script dir (pip --user install).
set "PYI_BIN=%APPDATA%\Python\Python313\Scripts\pyinstaller.exe"
if not exist "%PYI_BIN%" set "PYI_BIN=pyinstaller"

"%PYI_BIN%" --noconfirm --clean pocoboard.spec
if errorlevel 1 (
    echo [!] ビルドに失敗しました。
    pause
    exit /b 1
)

echo.
echo [ok] ビルド完了。  dist\POCOBoard\POCOBoard.exe を実行してください。
echo [ok] 配布する場合は dist\POCOBoard フォルダごと ZIP に固めて送ってください。
endlocal
