#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script rápido para verificar el estado del entrenamiento
"""
import sys
import io
from pathlib import Path
import re
from datetime import datetime
import subprocess

# Configurar encoding UTF-8 para stdout/stderr en Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

LOG_FILE = Path("../var/logs/fundamental_analysis.log")

def check_processes():
    """Verifica procesos Python corriendo"""
    try:
        result = subprocess.run(
            ['powershell', '-Command', 
             "Get-Process python -ErrorAction SilentlyContinue | Where-Object {$_.Path -like '*GLOBALTECH*'} | Select-Object Id, @{Name='Runtime';Expression={(Get-Date) - $_.StartTime}}, @{Name='Memory(MB)';Expression={[math]::Round($_.WorkingSet64/1MB,2)}} | Format-Table -AutoSize"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.stdout
    except:
        return "Error verificando procesos"

def get_recent_logs(n=30):
    """Obtiene logs recientes"""
    if not LOG_FILE.exists():
        return "Log file no existe"
    
    try:
        with open(LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            return ''.join(lines[-n:])
    except Exception as e:
        return f"Error leyendo log: {e}"

def analyze_status():
    """Analiza el estado actual"""
    print("=" * 80)
    print(f"ESTADO DEL ENTRENAMIENTO - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    
    # Procesos
    print("\n📊 PROCESOS:")
    print(check_processes())
    
    # Logs recientes
    log_content = get_recent_logs(50)
    
    # Buscar empresa actual
    current_company = None
    current_round = None
    current_error = None
    
    lines = log_content.split('\n')
    for line in reversed(lines):
        if 'AUTO_LOOP' in line and 'Ronda' in line:
            match = re.search(r'(\w+).*Ronda (\d+)/(\d+)', line)
            if match:
                current_company = match.group(1)
                current_round = f"{match.group(2)}/{match.group(3)}"
                break
        
        if 'Error final:' in line or 'Mejor error hasta ahora:' in line:
            match = re.search(r'([\d.]+)%', line)
            if match:
                current_error = match.group(1)
    
    if current_company:
        print(f"\n🏢 EMPRESA ACTUAL: {current_company}")
        if current_round:
            print(f"   Ronda: {current_round}")
        if current_error:
            print(f"   Error: {current_error}%")
    
    # Buscar problemas
    if 'ERROR' in log_content.upper():
        print("\n⚠️  ERRORES RECIENTES:")
        error_lines = [l for l in lines if 'ERROR' in l.upper()][-3:]
        for err in error_lines:
            print(f"   {err[-100:]}")
    
    # Buscar advertencias
    if 'WARNING' in log_content.upper():
        warnings = [l for l in lines if 'WARNING' in l.upper()][-3:]
        if warnings:
            print("\n⚠️  ADVERTENCIAS:")
            for warn in warnings:
                print(f"   {warn[-100:]}")
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    analyze_status()

