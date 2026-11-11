@echo off
echo ===================================================
echo Building Context-Aware Screenshots Standalone EXE...
echo ===================================================

python -m PyInstaller --noconfirm --noconsole --onefile --icon=icon.ico --add-data "icon.ico;." --hidden-import=pynput.keyboard._win32 --hidden-import=pynput.mouse._win32 --hidden-import=tkinter --hidden-import=tkinter.filedialog --name "ContextScreenshots" app.py

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ===================================================
    echo BUILD SUCCESSFUL!
    echo Your standalone EXE is ready at:
    echo   dist\ContextScreenshots.exe
    echo ===================================================
) else (
    echo.
    echo BUILD FAILED! Check the error log above.
)
pause

