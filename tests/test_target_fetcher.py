#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script de prueba para el módulo target_value_fetcher
Prueba la obtención de valores objetivo desde la web
"""
import sys
from pathlib import Path

# Agregar src al path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from target_value_fetcher import (
    fetch_target_from_web,
    fetch_multiple_targets,
    clear_cache
)
from logs import setup_logging
import logging

# Configurar logging
log_dir = Path(__file__).parent / "var" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
setup_logging(log_dir=str(log_dir), level="INFO")
logger = logging.getLogger(__name__)


def test_single_symbol():
    """Prueba obtener un valor objetivo para un símbolo"""
    print("=" * 60)
    print("PRUEBA: Obtener valor objetivo para AAPL")
    print("=" * 60)
    
    symbol = "AAPL"
    fair_value = fetch_target_from_web(symbol, use_cache=True, rate_limit_delay=1.0)
    
    if fair_value:
        print(f"\n[OK] Fair value obtenido para {symbol}: ${fair_value:.2f}")
    else:
        print(f"\n[ERROR] No se pudo obtener fair value para {symbol}")
        print("   Verifica que tengas SERPAPI_KEY configurada o que Alpha Spread esté accesible")


def test_multiple_symbols():
    """Prueba obtener valores objetivo para múltiples símbolos"""
    print("\n" + "=" * 60)
    print("PRUEBA: Obtener valores objetivo para múltiples símbolos")
    print("=" * 60)
    
    symbols = ["AAPL", "MSFT", "GOOGL"]
    results = fetch_multiple_targets(symbols, use_cache=True, rate_limit_delay=2.0)
    
    print("\nResultados:")
    for symbol, value in results.items():
        if value:
            print(f"  [OK] {symbol}: ${value:.2f}")
        else:
            print(f"  [ERROR] {symbol}: No disponible")


def main():
    """Función principal"""
    print("MÓDULO DE OBTENCIÓN DE VALORES OBJETIVO DESDE LA WEB")
    print("=" * 60)
    print("\nEste script prueba el módulo target_value_fetcher.py")
    print("que obtiene fair values dinámicamente desde:")
    print("  1. Alpha Spread (scraping)")
    print("  2. SerpAPI (búsqueda Google)")
    print("  3. Alpha Vantage (precio actual como proxy)")
    print("\n" + "-" * 60)
    
    # Opciones
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "clear":
            print("\nLimpiando cache...")
            clear_cache()
            print("[OK] Cache limpiado")
            return
        elif command == "multi":
            test_multiple_symbols()
            return
        elif command.startswith("symbol="):
            symbol = command.split("=")[1].upper()
            print(f"\nObteniendo valor para {symbol}...")
            fair_value = fetch_target_from_web(symbol, use_cache=True, rate_limit_delay=1.0)
            if fair_value:
                print(f"[OK] {symbol}: ${fair_value:.2f}")
            else:
                print(f"[ERROR] No se pudo obtener valor para {symbol}")
            return
    
    # Prueba por defecto
    test_single_symbol()
    
    print("\n" + "=" * 60)
    print("USO:")
    print("  python test_target_fetcher.py              # Prueba con AAPL")
    print("  python test_target_fetcher.py multi         # Prueba múltiples símbolos")
    print("  python test_target_fetcher.py symbol=MSFT  # Prueba símbolo específico")
    print("  python test_target_fetcher.py clear         # Limpia cache")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[INFO] Interrumpido por el usuario")
    except Exception as e:
        print(f"\n[ERROR] Error: {e}")
        import traceback
        traceback.print_exc()

