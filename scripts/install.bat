@echo off
setlocal
echo ================================================================
echo   Fundamental Analysis - Install Dependencies
echo ================================================================
echo.

REM Obtener directorio raíz de GlobalTech (subir dos niveles)
set "CURRENT_DIR=%~dp0"
set "GLOBALTECH_DIR=%CURRENT_DIR%..\"
for %%i in ("%GLOBALTECH_DIR%") do set "GLOBALTECH_DIR=%%~fi"
set "VENV_DIR=%GLOBALTECH_DIR%\.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

REM Verificar si existe el entorno virtual
if not exist "%PYTHON_EXE%" (
    echo [ERROR] Entorno virtual no encontrado en: %VENV_DIR%
    echo.
    echo Por favor ejecuta primero: setup_common_env.bat
    echo desde el directorio raíz de GlobalTech
    echo.
    pause
    exit /b 1
)

echo [*] Activando entorno virtual...
call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 (
    echo [ERROR] No se pudo activar el entorno virtual.
    pause
    exit /b 1
)

echo.
echo [*] Actualizando pip...
python -m pip install --upgrade pip

echo.
echo [*] Instalando dependencias de Fundamental Analysis...
cd /d "%CURRENT_DIR%"
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Error al instalar dependencias.
    pause
    exit /b 1
)

echo.
echo ================================================================
echo   Dependencias instaladas correctamente!
echo ================================================================
echo.
echo Puedes ejecutar:
echo   python run_ui.py        (Interfaz gráfica)
echo   python run_analysis.py  (Línea de comandos)
echo.
pause
endlocal

