@echo off
setlocal
cd /d "%~dp0\.."
if not exist .venv\Scripts\python.exe (
    py -3 -m venv .venv
    if errorlevel 1 goto error
)
.venv\Scripts\python.exe -c "import PySide6, PIL, cryptography, argon2, cv2, numpy" >nul 2>nul
if errorlevel 1 (
    .venv\Scripts\python.exe -m pip install -e ".[full]"
    if errorlevel 1 goto error
)
.venv\Scripts\python.exe -m veilpng.gui
if errorlevel 1 goto error
exit /b 0
:error
echo Unable to start VeilPNG. Check Python installation and network for package downloads.
pause
exit /b 1
