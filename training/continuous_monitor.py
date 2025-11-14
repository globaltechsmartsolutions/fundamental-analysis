#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Monitor continuo que verifica el estado cada 30 segundos
"""
import subprocess
import time
import sys
import os
import io
from pathlib import Path
import re
from datetime import datetime
import json

# Configurar encoding UTF-8 para stdout/stderr en Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Configuración
LOG_FILE = Path("../var/logs/fundamental_analysis.log")
CHECK_INTERVAL = 30  # Segundos entre checks
MONITOR_SCRIPT = "monitor_training.py"
TRAIN_SCRIPT = "train_model.py"

def get_last_log_lines(n=100):
    """Obtiene las últimas N líneas del log"""
    if not LOG_FILE.exists():
        return ""
    
    try:
        with open(LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            return ''.join(lines[-n:])
    except Exception as e:
        print(f"[MONITOR] Error leyendo log: {e}")
        return ""

def check_process_running():
    """Verifica si hay procesos Python de entrenamiento corriendo"""
    try:
        result = subprocess.run(
            ['powershell', '-Command', 
             "Get-Process python -ErrorAction SilentlyContinue | Where-Object {$_.Path -like '*GLOBALTECH*'} | Measure-Object | Select-Object -ExpandProperty Count"],
            capture_output=True,
            text=True,
            timeout=5
        )
        count = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0
        return count > 0, count
    except Exception as e:
        print(f"[MONITOR] Error verificando procesos: {e}")
        return False, 0

def analyze_logs(log_content):
    """Analiza los logs y detecta problemas"""
    issues = []
    warnings = []
    progress = []
    
    # Buscar errores críticos
    error_patterns = [
        (r"ERROR.*fatal", "Error fatal"),
        (r"Traceback.*most recent", "Excepción Python"),
        (r"UnicodeEncodeError", "Error de encoding"),
        (r"KeyboardInterrupt", "Interrupción manual"),
    ]
    
    for pattern, description in error_patterns:
        if re.search(pattern, log_content, re.IGNORECASE):
            issues.append(description)
    
    # Buscar advertencias
    if re.search(r"WARNING.*Sin mejoras", log_content, re.IGNORECASE):
        warnings.append("Optimizador sin mejoras")
    
    # Buscar progreso
    if re.search(r"AUTO_LOOP.*Ronda", log_content, re.IGNORECASE):
        rounds = re.findall(r"Ronda (\d+)/(\d+)", log_content)
        if rounds:
            last_round = rounds[-1]
            progress.append(f"Ronda {last_round[0]}/{last_round[1]}")
    
    # Buscar errores finales
    error_finals = re.findall(r"Error final:\s*([\d.]+)%", log_content)
    if error_finals:
        last_error = float(error_finals[-1])
        if last_error > 10.0:
            warnings.append(f"Error alto: {last_error:.2f}%")
        else:
            progress.append(f"Error bajo: {last_error:.2f}%")
    
    # Buscar empresas completadas
    if re.search(r"Ya optimizado|Saltando entrenamiento", log_content, re.IGNORECASE):
        progress.append("Empresas optimizadas detectadas")
    
    return issues, warnings, progress

def print_status(is_running, process_count, issues, warnings, progress, last_check):
    """Imprime el estado actual"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n{'='*80}")
    print(f"[MONITOR] Estado: {timestamp}")
    print(f"{'='*80}")
    
    # Estado del proceso
    if is_running:
        print(f"✅ Procesos Python: {process_count} corriendo")
    else:
        print(f"⚠️  Procesos Python: {process_count} (NINGUNO corriendo!)")
    
    # Problemas críticos
    if issues:
        print(f"\n🔴 PROBLEMAS CRÍTICOS:")
        for issue in issues:
            print(f"   - {issue}")
    else:
        print(f"\n✅ Sin problemas críticos")
    
    # Advertencias
    if warnings:
        print(f"\n⚠️  ADVERTENCIAS:")
        for warning in warnings:
            print(f"   - {warning}")
    
    # Progreso
    if progress:
        print(f"\n📊 PROGRESO:")
        for p in progress[-5:]:  # Últimas 5 líneas de progreso
            print(f"   - {p}")
    
    print(f"\n⏱️  Última verificación: {last_check}")
    print(f"{'='*80}\n")

def restart_monitor():
    """Reinicia el monitor principal"""
    print("[MONITOR] ⚠️  Reiniciando monitor principal...")
    try:
        script_path = Path(__file__).parent / MONITOR_SCRIPT
        python_exe = Path("C:/Users/aleja/OneDrive/Documents/GLOBALTECH/.venv/Scripts/python.exe")
        
        subprocess.Popen(
            [str(python_exe), str(script_path)],
            cwd=str(script_path.parent),
            stdout=sys.stdout,
            stderr=sys.stderr,
            text=True
        )
        print("[MONITOR] ✅ Monitor principal reiniciado")
        return True
    except Exception as e:
        print(f"[MONITOR] ❌ Error reiniciando monitor: {e}")
        return False

def continuous_monitor():
    """Monitor continuo que verifica cada 30 segundos"""
    print("=" * 80)
    print("MONITOR CONTINUO DE ENTRENAMIENTO")
    print("=" * 80)
    print(f"Verificando cada {CHECK_INTERVAL} segundos...")
    print("Presiona Ctrl+C para detener\n")
    
    consecutive_failures = 0
    max_consecutive_failures = 3
    
    try:
        while True:
            last_check = datetime.now().strftime('%H:%M:%S')
            
            # Verificar procesos
            is_running, process_count = check_process_running()
            
            # Leer logs
            log_content = get_last_log_lines(200)
            
            # Analizar logs
            issues, warnings, progress = analyze_logs(log_content)
            
            # Imprimir estado
            print_status(is_running, process_count, issues, warnings, progress, last_check)
            
            # Si no hay procesos corriendo, intentar reiniciar
            if not is_running:
                consecutive_failures += 1
                print(f"[MONITOR] ⚠️  No hay procesos corriendo (fallo #{consecutive_failures})")
                
                if consecutive_failures >= max_consecutive_failures:
                    print(f"[MONITOR] 🔴 {consecutive_failures} fallos consecutivos, reiniciando monitor...")
                    restart_monitor()
                    consecutive_failures = 0
                    time.sleep(10)  # Esperar a que inicie
            else:
                consecutive_failures = 0
            
            # Si hay problemas críticos, alertar
            if issues:
                print(f"[MONITOR] 🔴 PROBLEMAS CRÍTICOS DETECTADOS!")
                # No reiniciar automáticamente, solo alertar
            
            # Esperar antes de la siguiente verificación
            time.sleep(CHECK_INTERVAL)
            
    except KeyboardInterrupt:
        print("\n[MONITOR] Detenido por usuario (Ctrl+C)")
    except Exception as e:
        print(f"\n[MONITOR] Error en monitor continuo: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    continuous_monitor()

