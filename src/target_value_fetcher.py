"""
Módulo para cargar valores objetivo desde archivo JSON
"""
import os
import logging
from typing import Optional, Dict
from pathlib import Path
import json

logger = logging.getLogger(__name__)

# Archivo JSON por defecto (puede cambiarse con variable de entorno)
DEFAULT_JSON_FILE = os.environ.get('TARGET_VALUES_JSON', 'data/target_values_example.json')


def load_target_values_from_json(json_path: Optional[Path] = None) -> Dict[str, float]:
    """
    Carga valores objetivo desde archivo JSON
    
    Args:
        json_path: Ruta al archivo JSON. Si None, usa DEFAULT_JSON_FILE
    
    Returns:
        Dict con símbolo -> valor objetivo
    """
    if json_path is None:
        json_path = Path(__file__).parent.parent / DEFAULT_JSON_FILE
    
    if not json_path.exists():
        logger.warning(f"Archivo JSON no encontrado: {json_path}")
        return {}
    
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        target_values = data.get('target_values', {})
        logger.info(f"Cargados {len(target_values)} valores objetivo desde {json_path.name}")
        return target_values
    except Exception as e:
        logger.error(f"Error cargando JSON {json_path}: {e}")
        return {}


def fetch_target_from_web(symbol: str, **kwargs) -> Optional[float]:
    """
    Función de compatibilidad - solo carga desde JSON
    (El scraping fue eliminado)
    
    Args:
        symbol: Símbolo de la acción
        **kwargs: Ignorados (compatibilidad)
    
    Returns:
        Valor objetivo desde JSON o None
    """
    values = load_target_values_from_json()
    return values.get(symbol.upper())


def fetch_multiple_targets(symbols: list, **kwargs) -> Dict[str, Optional[float]]:
    """
    Función de compatibilidad - solo carga desde JSON
    (El scraping fue eliminado)
    
    Args:
        symbols: Lista de símbolos
        **kwargs: Ignorados (compatibilidad)
    
    Returns:
        Dict con símbolo -> valor objetivo desde JSON
    """
    values = load_target_values_from_json()
    results = {symbol.upper(): values.get(symbol.upper()) for symbol in symbols}
    successful = sum(1 for v in results.values() if v is not None)
    logger.info(f"Cargados {successful}/{len(symbols)} valores desde JSON")
    return results


def save_target_values_to_json(target_values: Dict[str, float], json_path: Optional[Path] = None) -> bool:
    """
    Guarda valores objetivo en un archivo JSON
    
    Args:
        target_values: Dict con símbolo -> valor objetivo
        json_path: Ruta al archivo JSON. Si None, usa DEFAULT_JSON_FILE
    
    Returns:
        True si se guardó correctamente, False si hubo error
    """
    if json_path is None:
        json_filename = DEFAULT_JSON_FILE if DEFAULT_JSON_FILE.endswith('.json') else "target_values.json"
        json_path = Path(__file__).parent.parent / json_filename
    
    try:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "comment": "Valores objetivo - Generado manualmente",
            "target_values": target_values
        }
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Valores guardados en JSON: {json_path} ({len(target_values)} símbolos)")
        return True
    except Exception as e:
        logger.error(f"Error guardando JSON: {e}")
        return False
