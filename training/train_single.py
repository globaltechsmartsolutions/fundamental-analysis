#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script para entrenar una empresa individual
Uso: python train_single.py SYMBOL
Ejemplo: python train_single.py AAPL
"""
import sys
import io
from pathlib import Path

# Configurar encoding UTF-8 para stdout/stderr en Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Agregar raíz del proyecto al path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Importar módulos
from training.train_model import ModelTrainer, load_config
from src.utils import setup_logging
import logging

def main():
    """Entrena una empresa individual"""
    if len(sys.argv) < 2:
        print("Uso: python train_single.py SYMBOL [target_error] [max_iterations]")
        print("Ejemplo: python train_single.py AAPL 10.0 500")
        print("\nSímbolos disponibles:")
        print("  AAPL, MSFT, GOOGL, META, AMZN, NVDA, AVGO, NFLX, TSLA, DELL, HPE, DIS, MA")
        return 1
    
    symbol = sys.argv[1].upper()
    target_error = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
    max_iterations = int(sys.argv[3]) if len(sys.argv) > 3 else 500
    
    # Configurar logging
    log_dir = project_root / "var" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(log_dir=str(log_dir), level="INFO")
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 80)
    logger.info(f"ENTRENAMIENTO INDIVIDUAL: {symbol}")
    logger.info("=" * 80)
    logger.info(f"Objetivo: Error < {target_error}%")
    logger.info(f"Iteraciones máximas: {max_iterations}")
    logger.info("=" * 80)
    
    # Cargar configuración
    config_path = project_root / "settings.ini"
    if not config_path.exists():
        logger.error(f"ERROR: No se encontró settings.ini en {config_path}")
        return 1
    
    config = load_config(str(config_path))
    api_key = config.get("finnhub_api_key", "")
    
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        logger.error("ERROR: API key no configurada en settings.ini")
        return 1
    
    # Valores objetivo (mismo que en train_model.py)
    TARGET_VALUES = {
        "AAPL": 178.20,
        "MSFT": 413.12,
        "GOOGL": 179.13,
        "META": 544.05,
        "AMZN": 169.08,
        "NVDA": 156.86,
        "AVGO": 249.89,
        "NFLX": 523.93,
        "TSLA": 43.50,
        "DELL": 216.87,
        "HPE": 33.42,
        "DIS": 138.13,
        "MA": 188.49,
    }
    
    if symbol not in TARGET_VALUES:
        logger.error(f"ERROR: Símbolo {symbol} no está en la lista de valores objetivo")
        logger.error(f"Símbolos disponibles: {', '.join(TARGET_VALUES.keys())}")
        return 1
    
    try:
        # Crear trainer
        logger.info(f"Creando ModelTrainer para {symbol}...")
        trainer = ModelTrainer(api_key)
        
        # Establecer valor objetivo solo para esta empresa
        target_value = TARGET_VALUES[symbol]
        trainer.set_target_values({symbol: target_value}, fetch_missing_from_web=False)
        logger.info(f"Valor objetivo Alpha Spread para {symbol}: ${target_value:.2f}")
        
        # Cargar caché si existe
        trainer.load_cache()
        
        # Calcular error inicial
        logger.info("Calculando error inicial...")
        initial_params = {
            'dcf_weight': 0.5,
            'comparables_weight': 0.5,
            'growth_adjustment_factor': 1.0,
            'wacc_adjustment_factor': 1.0,
        }
        _, initial_errors = trainer.calculate_error(initial_params, return_details=True)
        initial_error_log1p = None
        for sym, err in initial_errors:
            if sym == symbol:
                initial_error_log1p = err
                break
        
        if initial_error_log1p is None:
            initial_error_pct = 100.0
        else:
            # Convertir de log1p a porcentaje
            import numpy as np
            initial_error_pct = np.expm1(initial_error_log1p) if initial_error_log1p > 0 else 100.0
        
        logger.info(f"Error inicial: {initial_error_pct:.2f}%")
        
        # Entrenar
        logger.info(f"Iniciando entrenamiento...")
        trainer._current_initial_error = initial_error_pct  # Para detección de empresas problemáticas
        
        best_params = trainer.train_single_company(
            symbol,
            target_error=target_error,
            max_iterations=max_iterations,
            initial_error=initial_error_pct
        )
        
        final_error_pct = best_params.get('error_pct', initial_error_pct)
        improvement = initial_error_pct - final_error_pct
        
        logger.info("=" * 80)
        logger.info(f"✅ ENTRENAMIENTO COMPLETADO: {symbol}")
        logger.info("=" * 80)
        logger.info(f"Error inicial: {initial_error_pct:.2f}%")
        logger.info(f"Error final: {final_error_pct:.2f}%")
        logger.info(f"Mejora: {improvement:.2f}%")
        logger.info(f"Parámetros:")
        logger.info(f"  growth_adjustment_factor: {best_params.get('growth_adjustment_factor', 1.0):.3f}")
        logger.info(f"  wacc_adjustment_factor: {best_params.get('wacc_adjustment_factor', 1.0):.3f}")
        logger.info(f"Objetivo alcanzado: {'✅ Sí' if final_error_pct <= target_error else '❌ No'}")
        logger.info("=" * 80)
        
        return 0
        
    except Exception as e:
        logger.error(f"ERROR: {e}", exc_info=True)
        return 1

if __name__ == "__main__":
    sys.exit(main())

