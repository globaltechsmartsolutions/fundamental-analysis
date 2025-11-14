@echo off
REM Script para entrenar múltiples empresas en paralelo
REM Uso: train_parallel.bat AAPL MSFT GOOGL

echo ========================================
echo Entrenamiento Paralelo de Empresas
echo ========================================
echo.

if "%1"=="" (
    echo Uso: train_parallel.bat SYMBOL1 SYMBOL2 SYMBOL3 ...
    echo Ejemplo: train_parallel.bat AAPL MSFT GOOGL
    exit /b 1
)

set PYTHON=C:\Users\aleja\OneDrive\Documents\GLOBALTECH\.venv\Scripts\python.exe
set TRAIN_SCRIPT=%~dp0train_single.py

echo Iniciando entrenamiento paralelo de %* empresas...
echo.

REM Ejecutar cada empresa en una ventana separada
for %%s in (%*) do (
    echo Iniciando entrenamiento de %%s...
    start "Entrenando %%s" cmd /k "%PYTHON%" "%TRAIN_SCRIPT%" %%s
    timeout /t 2 /nobreak >nul
)

echo.
echo ========================================
echo Todas las empresas iniciadas
echo ========================================
echo Revisa las ventanas individuales para ver el progreso
pause

