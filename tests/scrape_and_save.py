#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script INDEPENDIENTE para obtener valores desde scraping y guardarlos en JSON
NO entrena el modelo, solo obtiene y guarda valores
"""
import sys
import os
from pathlib import Path

# Forzar modo scraping ANTES de importar el módulo
os.environ['USE_SCRAPING_ONLY'] = 'true'

# Agregar src al path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from target_value_fetcher import (
    fetch_multiple_targets,
    save_target_values_to_json
)
from logs import setup_logging
import logging

# Configurar logging
log_dir = Path(__file__).parent / "var" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
setup_logging(log_dir=str(log_dir), level="INFO")
logger = logging.getLogger(__name__)


def main():
    """Función principal - Solo scraping y guardado, NO entrenamiento"""
    
    print("=" * 70)
    print("SCRAPING Y GUARDADO DE VALORES OBJETIVO")
    print("=" * 70)
    print("\nEste script SOLO obtiene valores desde scraping y los guarda en JSON")
    print("NO entrena el modelo - solo scraping y guardado")
    print("=" * 70)
    sys.stdout.flush()
    
    # Obtener símbolos desde argumentos o usar lista por defecto
    if len(sys.argv) > 1:
        # Símbolos desde argumentos: python scrape_and_save.py AAPL MSFT GOOGL
        symbols = [s.upper().strip() for s in sys.argv[1:]]
        print(f"\nSimbolos desde argumentos: {', '.join(symbols)}")
    else:
        # Lista por defecto (puedes modificar esto)
        symbols = [
            'AAPL', 'MSFT', 'GOOGL', 'META', 'AMZN', 'NVDA',
            'AVGO', 'NFLX', 'TSLA', 'DELL', 'HPE', 'UNH',
            'JNJ', 'JPM', 'PYPL', 'MA', 'BAC', 'GS', 'C',
            'SCHW', 'RKT', 'WMT', 'DIS', 'PG', 'VZ', 'BLOCK'
        ]
        print(f"\nUsando lista por defecto ({len(symbols)} simbolos)")
        print(f"Simbolos: {', '.join(symbols[:10])}...")
        print("\nPara usar simbolos especificos:")
        print("  python scrape_and_save.py AAPL MSFT GOOGL")
    sys.stdout.flush()
    
    # Obtener archivo JSON de salida
    output_json = os.environ.get('TARGET_VALUES_JSON', 'target_values_scraped.json')
    output_path = Path(__file__).parent / output_json
    
    print("\n" + "=" * 70)
    print("INICIANDO SCRAPING...")
    print("=" * 70)
    print(f"Archivo de salida: {output_path}")
    print(f"Esto puede tardar varios minutos ({len(symbols)} simbolos)...")
    print("=" * 70 + "\n")
    sys.stdout.flush()
    
    # Obtener valores desde scraping
    try:
        results = fetch_multiple_targets(
            symbols,
            use_cache=True,
            rate_limit_delay=2.0
        )
        
        # Filtrar solo valores exitosos
        successful_values = {k: v for k, v in results.items() if v is not None}
        failed_symbols = [k for k, v in results.items() if v is None]
        
        print("\n" + "=" * 70)
        print("RESULTADOS DEL SCRAPING")
        print("=" * 70)
        print(f"[OK] Exitosos: {len(successful_values)}/{len(symbols)}")
        if failed_symbols:
            print(f"[ERROR] Fallidos: {len(failed_symbols)}")
            print(f"   Simbolos: {', '.join(failed_symbols)}")
        sys.stdout.flush()
        
        if successful_values:
            print("\nValores obtenidos:")
            for symbol, value in sorted(successful_values.items()):
                print(f"  {symbol}: ${value:.2f}")
            sys.stdout.flush()
            
            # Guardar en JSON
            print("\n" + "=" * 70)
            print("GUARDANDO EN JSON...")
            print("=" * 70)
            sys.stdout.flush()
            
            if save_target_values_to_json(successful_values, output_path):
                print(f"\n[OK] Valores guardados exitosamente en: {output_path}")
                print(f"   Total: {len(successful_values)} simbolos")
                print(f"\nPara usar este JSON en entrenamiento:")
                print(f'   $env:TARGET_VALUES_JSON = "{output_json}"')
                print(f'   $env:USE_SCRAPING_ONLY = "false"')
                sys.stdout.flush()
            else:
                print(f"\n[ERROR] Error guardando valores en JSON")
                sys.stdout.flush()
                return 1
        else:
            print("\n[ERROR] No se obtuvieron valores exitosamente")
            print("   Verifica tu conexion a internet y configuracion de APIs")
            sys.stdout.flush()
            return 1
        
        print("\n" + "=" * 70)
        print("SCRAPING COMPLETADO")
        print("=" * 70)
        sys.stdout.flush()
        return 0
        
    except KeyboardInterrupt:
        print("\n\n[INFO] Scraping interrumpido por el usuario")
        print("Los valores obtenidos hasta ahora se pueden guardar manualmente")
        sys.stdout.flush()
        return 1
    except Exception as e:
        print(f"\n[ERROR] Error durante scraping: {e}")
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        return 1


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except Exception as e:
        print(f"\n[ERROR CRITICO] Error fatal: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
