@echo off
setlocal
REM Script para ejecutar la interfaz gráfica con el entorno virtual de GlobalTech

set "CURRENT_DIR=%~dp0"
set "GLOBALTECH_DIR=%CURRENT_DIR%..\"
for %%i in ("%GLOBALTECH_DIR%") do set "GLOBALTECH_DIR=%%~fi"
set "VENV_DIR=%GLOBALTECH_DIR%\.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Entorno virtual no encontrado.
    echo Ejecuta primero: install.bat
    pause
    exit /b 1
)

call "%VENV_DIR%\Scripts\activate.bat"
cd /d "%CURRENT_DIR%"
python run_ui.py

endlocal

