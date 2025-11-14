#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Monitor de entrenamiento automático
Ejecuta train_model.py y lo monitorea continuamente, reiniciando si es necesario
"""
import subprocess
import time
import sys
import os
import io
from pathlib import Path
import re
from datetime import datetime

# Configurar encoding UTF-8 para stdout/stderr en Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Agregar raíz del proyecto al path para imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Configuración
TRAIN_SCRIPT = "train_model.py"
LOG_FILE = Path("../var/logs/fundamental_analysis.log")
CHECK_INTERVAL = 20  # Segundos entre checks
MAX_RESTARTS = 100  # Máximo de reinicios antes de parar
ERROR_PATTERNS = [
    r"ERROR.*fatal",
    r"Traceback \(most recent call last\)",
    r"KeyboardInterrupt",
    r"SystemExit",
    r"API key.*no configurada",
]

# Patrones de éxito (cuando todas las empresas están entrenadas)
SUCCESS_PATTERNS = [
    r"RESUMEN FINAL DEL ENTRENAMIENTO",
    r"Empresas que alcanzaron objetivo",
]

def check_log_for_errors(log_content):
    """Verifica si hay errores críticos en los logs"""
    errors = []
    for pattern in ERROR_PATTERNS:
        matches = re.findall(pattern, log_content, re.IGNORECASE)
        if matches:
            errors.extend(matches)
    return errors

def check_log_for_success(log_content):
    """Verifica si el entrenamiento completó exitosamente"""
    for pattern in SUCCESS_PATTERNS:
        if re.search(pattern, log_content, re.IGNORECASE):
            return True
    return False

def get_last_log_lines(n=50):
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

def validate_script():
    """Valida que el script pueda ejecutarse antes de lanzarlo"""
    script_path = Path(__file__).parent / TRAIN_SCRIPT
    python_exe = Path("C:/Users/aleja/OneDrive/Documents/GLOBALTECH/.venv/Scripts/python.exe")
    
    if not script_path.exists():
        print(f"[MONITOR] ❌ ERROR: Script no existe: {script_path}")
        return False
    
    if not python_exe.exists():
        print(f"[MONITOR] ❌ ERROR: Python no existe: {python_exe}")
        return False
    
    # Validar sintaxis del script
    try:
        print(f"[MONITOR] Validando sintaxis de {script_path}...")
        result = subprocess.run(
            [str(python_exe), "-m", "py_compile", str(script_path)],
            cwd=str(script_path.parent),
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            print(f"[MONITOR] ❌ ERROR: Sintaxis inválida en {TRAIN_SCRIPT}")
            print(f"[MONITOR] {result.stderr}")
            return False
        print(f"[MONITOR] ✅ Sintaxis válida")
    except Exception as e:
        print(f"[MONITOR] ⚠️  No se pudo validar sintaxis: {e}")
        # Continuar de todas formas, puede ser un problema de validación
    
    # Validar imports básicos
    try:
        print(f"[MONITOR] Validando imports básicos...")
        result = subprocess.run(
            [str(python_exe), "-c", f"import sys; sys.path.insert(0, '{script_path.parent.parent}'); exec(open('{script_path}').read().split('if __name__')[0])"],
            cwd=str(script_path.parent),
            capture_output=True,
            text=True,
            timeout=15
        )
        if result.returncode != 0:
            print(f"[MONITOR] ❌ ERROR: Error en imports o código inicial:")
            print(f"[MONITOR] {result.stderr[:500]}")
            return False
        print(f"[MONITOR] ✅ Imports válidos")
    except subprocess.TimeoutExpired:
        print(f"[MONITOR] ⚠️  Validación de imports tardó mucho, continuando...")
    except Exception as e:
        print(f"[MONITOR] ⚠️  No se pudo validar imports: {e}")
        # Continuar de todas formas
    
    return True

def run_training():
    """Ejecuta el script de entrenamiento"""
    script_path = Path(__file__).parent / TRAIN_SCRIPT
    python_exe = Path("C:/Users/aleja/OneDrive/Documents/GLOBALTECH/.venv/Scripts/python.exe")
    
    # Validar antes de ejecutar
    if not validate_script():
        print(f"[MONITOR] ❌ Validación falló, no se ejecutará el script")
        return None
    
    print(f"[MONITOR] Ejecutando {script_path}...")
    print(f"[MONITOR] Python: {python_exe}")
    print(f"[MONITOR] Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        # Ejecutar con stderr visible para detectar errores inmediatamente
        # Usar PIPE para stderr pero redirigir a un archivo temporal para monitoreo
        import tempfile
        stderr_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.log', encoding='utf-8')
        stderr_path = stderr_file.name
        stderr_file.close()
        
        process = subprocess.Popen(
            [str(python_exe), str(script_path)],
            cwd=str(script_path.parent),
            stdout=sys.stdout,
            stderr=open(stderr_path, 'w', encoding='utf-8'),
            text=True
        )
        
        # Verificar inmediatamente si hay errores de importación
        import time
        time.sleep(3)  # Esperar un poco más para detectar errores de import
        
        # Leer stderr para ver si hay errores
        try:
            with open(stderr_path, 'r', encoding='utf-8', errors='replace') as f:
                stderr_content = f.read()
            if stderr_content:
                # Verificar si hay errores críticos
                if 'Traceback' in stderr_content or 'Error' in stderr_content or 'ImportError' in stderr_content:
                    error_msg = f"\n[MONITOR] ❌ ERROR DETECTADO EN STDERR:\n{stderr_content[:800]}"
                    print(error_msg)
                    # Escribir a logs también
                    try:
                        import logging
                        logging.getLogger("monitor").error(error_msg)
                    except:
                        pass
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except:
                        process.kill()
                    os.unlink(stderr_path)
                    return None
        except Exception as e:
            print(f"[MONITOR] ⚠️  No se pudo leer stderr: {e}")
        
        # Si el proceso ya terminó, verificar código de salida
        if process.poll() is not None:
            return_code = process.poll()
            if return_code != 0:
                error_msg = f"[MONITOR] ❌ El proceso terminó con código {return_code}"
                print(error_msg)
                # Leer stderr completo
                try:
                    with open(stderr_path, 'r', encoding='utf-8', errors='replace') as f:
                        stderr_content = f.read()
                    if stderr_content:
                        print(f"[MONITOR] {stderr_content[:800]}")
                        error_msg += f"\n[MONITOR] STDERR: {stderr_content[:800]}"
                except:
                    pass
                # Escribir a logs
                try:
                    import logging
                    logging.getLogger("monitor").error(error_msg)
                except:
                    pass
                os.unlink(stderr_path)
                return None
        
        # Limpiar archivo temporal después de un tiempo
        import threading
        def cleanup_stderr():
            time.sleep(10)
            try:
                if os.path.exists(stderr_path):
                    os.unlink(stderr_path)
            except:
                pass
        threading.Thread(target=cleanup_stderr, daemon=True).start()
        
        # Si llegó aquí, el proceso sigue corriendo
        return process
        
    except Exception as e:
        print(f"[MONITOR] Error ejecutando script: {e}")
        import traceback
        traceback.print_exc()
        return None

def monitor_training():
    """Monitorea el entrenamiento continuamente"""
    # Configurar logging para que el monitor también escriba a los logs
    import logging
    monitor_logger = logging.getLogger("monitor")
    monitor_logger.setLevel(logging.INFO)
    
    # Si no tiene handlers, agregar uno que escriba al mismo archivo
    if not monitor_logger.handlers:
        try:
            from src.utils import setup_logging
            log_dir = Path(__file__).parent.parent / "var" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            setup_logging(log_dir=str(log_dir), level="INFO")
            monitor_logger = logging.getLogger("monitor")
        except ImportError:
            # Si no puede importar, usar logging básico
            log_dir = Path(__file__).parent.parent / "var" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "fundamental_analysis.log"
            handler = logging.FileHandler(log_file, encoding='utf-8')
            handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)-8s | %(name)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
            monitor_logger.addHandler(handler)
            monitor_logger.setLevel(logging.INFO)
    
    print("=" * 80)
    print("MONITOR DE ENTRENAMIENTO AUTOMÁTICO")
    print("=" * 80)
    print(f"Script: {TRAIN_SCRIPT}")
    print(f"Log: {LOG_FILE}")
    print(f"Intervalo de check: {CHECK_INTERVAL} segundos")
    print(f"Máximo reinicios: {MAX_RESTARTS}")
    print("=" * 80)
    print("\n[MONITOR] Iniciando monitoreo...")
    print("[MONITOR] Presiona Ctrl+C para detener el monitoreo\n")
    
    monitor_logger.info("=" * 80)
    monitor_logger.info("MONITOR DE ENTRENAMIENTO AUTOMÁTICO INICIADO")
    monitor_logger.info(f"Script: {TRAIN_SCRIPT}")
    monitor_logger.info(f"Log: {LOG_FILE}")
    monitor_logger.info(f"Intervalo de check: {CHECK_INTERVAL} segundos")
    monitor_logger.info("=" * 80)
    
    restart_count = 0
    process = None
    last_check_time = time.time()
    
    try:
        while restart_count < MAX_RESTARTS:
            # Iniciar proceso si no está corriendo
            if process is None or process.poll() is not None:
                if process is not None:
                    return_code = process.poll()
                    print(f"\n[MONITOR] {'='*80}")
                    print(f"[MONITOR] Proceso terminó con código {return_code}")
                    print(f"[MONITOR] Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                    
                    # Verificar logs para entender por qué terminó
                    log_content = get_last_log_lines(50)
                    if "RESUMEN FINAL" in log_content:
                        print("[MONITOR] Entrenamiento completó normalmente")
                        # Verificar si todas las empresas están optimizadas
                        if "Error final:" in log_content:
                            error_lines = [l for l in log_content.split('\n') if 'Error final:' in l]
                            high_errors = []
                            for line in error_lines:
                                match = re.search(r'Error final:\s*([\d.]+)%', line)
                                if match:
                                    error_pct = float(match.group(1))
                                    if error_pct > 10.0:
                                        symbol_match = re.search(r'(\w+):', line)
                                        if symbol_match:
                                            high_errors.append((symbol_match.group(1), error_pct))
                            
                            if not high_errors:
                                print("[MONITOR] ✅ Todas las empresas tienen error < 10%")
                                print("[MONITOR] Entrenamiento completado exitosamente!")
                                break
                            else:
                                print(f"[MONITOR] ⚠️ {len(high_errors)} empresas aún con error > 10%, continuando...")
                    else:
                        print("[MONITOR] Proceso terminó inesperadamente, revisando logs...")
                        if log_content:
                            error_lines = [l for l in log_content.split('\n') if 'ERROR' in l.upper()][-5:]
                            if error_lines:
                                print("[MONITOR] Últimos errores en log:")
                                for err_line in error_lines:
                                    print(f"  {err_line[-150:]}")
                
                restart_count += 1
                if restart_count > MAX_RESTARTS:
                    print(f"[MONITOR] ⚠️ Alcanzado máximo de reinicios ({MAX_RESTARTS})")
                    break
                
                print(f"\n[MONITOR] {'='*80}")
                print(f"[MONITOR] Reiniciando entrenamiento (intento {restart_count}/{MAX_RESTARTS})...")
                print(f"[MONITOR] {'='*80}\n")
                
                # Escribir a logs también
                try:
                    import logging
                    logging.getLogger("monitor").info(f"[MONITOR] Reiniciando entrenamiento (intento {restart_count}/{MAX_RESTARTS})")
                except:
                    pass
                
                process = run_training()
                
                if process is None:
                    print("[MONITOR] Error: No se pudo iniciar el proceso")
                    time.sleep(10)
                    continue
                
                time.sleep(5)  # Esperar a que inicie
                last_check_time = time.time()
            
            # Verificar cada CHECK_INTERVAL segundos
            elapsed = time.time() - last_check_time
            if elapsed >= CHECK_INTERVAL:
                last_check_time = time.time()
                
                # Leer logs recientes
                log_content = get_last_log_lines(100)
                
                # Verificar errores críticos (solo errores fatales, no warnings)
                fatal_errors = []
                for pattern in [r"ERROR.*fatal", r"Traceback.*most recent", r"SystemExit", r"KeyboardInterrupt"]:
                    matches = re.findall(pattern, log_content, re.IGNORECASE)
                    if matches:
                        fatal_errors.extend(matches)
                
                if fatal_errors:
                    print(f"\n[MONITOR] ⚠️ Errores críticos detectados:")
                    for error in fatal_errors[:2]:  # Mostrar solo primeros 2
                        print(f"  - {error[:100]}")
                    
                    # Verificar si el proceso sigue vivo
                    if process.poll() is not None:
                        print("[MONITOR] Proceso terminó inesperadamente después de error crítico")
                        process = None
                        time.sleep(2)
                        continue
                
                # Verificar éxito
                if check_log_for_success(log_content):
                    print("\n[MONITOR] ✅ Entrenamiento completado exitosamente!")
                    print("[MONITOR] Verificando si todas las empresas están optimizadas...")
                    
                    # Verificar si hay empresas con error alto
                    # Buscar en logs el resumen final
                    if "Error final:" in log_content:
                        # Extraer errores finales
                        error_lines = [line for line in log_content.split('\n') if 'Error final:' in line]
                        high_errors = []
                        for line in error_lines:
                            match = re.search(r'Error final:\s*([\d.]+)%', line)
                            if match:
                                error_pct = float(match.group(1))
                                if error_pct > 10.0:  # Error > 10%
                                    symbol_match = re.search(r'(\w+):', line)
                                    if symbol_match:
                                        high_errors.append((symbol_match.group(1), error_pct))
                        
                        if high_errors:
                            print(f"[MONITOR] ⚠️ {len(high_errors)} empresas aún con error > 10%:")
                            for symbol, error in high_errors:
                                print(f"  - {symbol}: {error:.2f}%")
                            print("[MONITOR] Continuando entrenamiento...")
                            process.terminate()
                            process.wait(timeout=5)
                            process = None
                            time.sleep(2)
                            continue
                        else:
                            print("[MONITOR] ✅ Todas las empresas tienen error < 10%")
                            print("[MONITOR] Entrenamiento completado exitosamente!")
                            break
                
                # Mostrar progreso cada minuto
                if int(elapsed) % 60 == 0 or "Ronda" in log_content or "Iter" in log_content:
                    # Extraer última línea relevante
                    lines = log_content.split('\n')
                    relevant_lines = [l for l in lines if any(x in l for x in ['Ronda', 'Iter', 'Error final', 'Mejora', 'AUTO_LOOP'])]
                    if relevant_lines:
                        last_line = relevant_lines[-1]
                        if len(last_line) > 0:
                            # Limpiar y mostrar
                            clean_line = last_line.strip()
                            if len(clean_line) > 0:
                                print(f"[MONITOR] {datetime.now().strftime('%H:%M:%S')} - {clean_line[-120:]}")
            
            # Pequeña pausa para no saturar CPU
            time.sleep(1)
        
        if restart_count >= MAX_RESTARTS:
            print(f"\n[MONITOR] ⚠️ Alcanzado máximo de reinicios ({MAX_RESTARTS})")
            print("[MONITOR] Deteniendo monitoreo")
        
        # Esperar a que termine el proceso actual
        if process is not None:
            print("[MONITOR] Esperando a que termine el proceso actual...")
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                print("[MONITOR] Proceso no terminó en 30s, forzando terminación...")
                process.terminate()
                process.wait()
        
    except KeyboardInterrupt:
        print("\n[MONITOR] Interrumpido por usuario (Ctrl+C)")
        if process is not None:
            print("[MONITOR] Terminando proceso...")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        print("[MONITOR] Monitoreo detenido")
    
    except Exception as e:
        print(f"\n[MONITOR] Error en monitoreo: {e}")
        import traceback
        traceback.print_exc()
        if process is not None:
            process.terminate()

if __name__ == "__main__":
    monitor_training()

