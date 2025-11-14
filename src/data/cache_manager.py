"""
Sistema de caché para datos financieros que cambian con poca frecuencia
"""
import json
import logging
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class CacheManager:
    """Gestor de caché para datos financieros"""
    
    # Configuración de validez por tipo de caché (en días)
    CACHE_VALIDITY = {
        'earnings': 7,      # Earnings cambian trimestralmente
        'profile': 90,     # Perfil cambia muy poco (solo cambios corporativos)
        'peers': 30,       # Peers cambian poco (cambios en industria)
        'financials': 90,  # Estados financieros anuales cambian 1 vez al año
        'metrics': 30,     # Métricas cambian cuando cambian estados financieros
    }
    
    def __init__(self, cache_dir: Path):
        """
        Inicializa el gestor de caché
        
        Args:
            cache_dir: Directorio donde se guardan los archivos de caché
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._caches = {}
        self._load_all_caches()
    
    def _load_all_caches(self):
        """Carga todos los cachés desde disco"""
        for cache_type in self.CACHE_VALIDITY.keys():
            cache_file = self.cache_dir / f"{cache_type}_cache.json"
            self._caches[cache_type] = {}
            
            if cache_file.exists():
                try:
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        self._caches[cache_type] = json.load(f)
                    logger.debug(f"Caché {cache_type} cargado: {len(self._caches[cache_type])} entradas")
                except Exception as e:
                    logger.warning(f"Error cargando caché {cache_type}: {e}", exc_info=True)
                    self._caches[cache_type] = {}
    
    def _save_cache(self, cache_type: str):
        """Guarda un caché específico en disco"""
        if cache_type not in self.CACHE_VALIDITY:
            logger.warning(f"Tipo de caché desconocido: {cache_type}")
            return
        
        cache_file = self.cache_dir / f"{cache_type}_cache.json"
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(self._caches[cache_type], f, indent=2, ensure_ascii=False)
            logger.debug(f"Caché {cache_type} guardado: {len(self._caches[cache_type])} entradas")
        except Exception as e:
            logger.warning(f"Error guardando caché {cache_type}: {e}", exc_info=True)
    
    def get(self, cache_type: str, key: str) -> Optional[Dict]:
        """
        Obtiene un valor del caché si es válido
        
        Args:
            cache_type: Tipo de caché ('earnings', 'profile', 'peers', 'financials', 'metrics')
            key: Clave del caché (normalmente el símbolo de la empresa)
        
        Returns:
            Dict con los datos cacheados y metadata, o None si no existe o está expirado
        """
        if cache_type not in self.CACHE_VALIDITY:
            logger.warning(f"Tipo de caché desconocido: {cache_type}")
            return None
        
        if cache_type not in self._caches:
            return None
        
        if key not in self._caches[cache_type]:
            return None
        
        cached_data = self._caches[cache_type][key]
        
        # Verificar validez
        if not self._is_valid(cached_data, cache_type):
            logger.debug(f"Caché {cache_type} para {key} expirado, eliminando...")
            del self._caches[cache_type][key]
            self._save_cache(cache_type)
            return None
        
        return cached_data.get('data')
    
    def set(self, cache_type: str, key: str, data: Any, save_immediately: bool = True):
        """
        Guarda un valor en el caché
        
        Args:
            cache_type: Tipo de caché
            key: Clave del caché (normalmente el símbolo de la empresa)
            data: Datos a cachear
            save_immediately: Si True, guarda inmediatamente en disco
        """
        if cache_type not in self.CACHE_VALIDITY:
            logger.warning(f"Tipo de caché desconocido: {cache_type}")
            return
        
        if cache_type not in self._caches:
            self._caches[cache_type] = {}
        
        self._caches[cache_type][key] = {
            'data': data,
            'cached_date': datetime.now().isoformat(),
            'cache_type': cache_type
        }
        
        if save_immediately:
            self._save_cache(cache_type)
    
    def _is_valid(self, cached_data: Dict, cache_type: str) -> bool:
        """
        Verifica si los datos cacheados son válidos
        
        Args:
            cached_data: Datos cacheados con metadata
            cache_type: Tipo de caché
        
        Returns:
            True si los datos son válidos, False si están expirados
        """
        if 'cached_date' not in cached_data:
            return False
        
        try:
            cached_date = datetime.fromisoformat(cached_data['cached_date'])
            validity_days = self.CACHE_VALIDITY[cache_type]
            expiration_date = cached_date + timedelta(days=validity_days)
            
            return datetime.now() < expiration_date
        except Exception as e:
            logger.warning(f"Error validando caché: {e}")
            return False
    
    def invalidate(self, cache_type: str, key: str):
        """
        Invalida una entrada específica del caché
        
        Args:
            cache_type: Tipo de caché
            key: Clave del caché
        """
        if cache_type in self._caches and key in self._caches[cache_type]:
            del self._caches[cache_type][key]
            self._save_cache(cache_type)
            logger.debug(f"Caché {cache_type} para {key} invalidado")
    
    def clear(self, cache_type: Optional[str] = None):
        """
        Limpia el caché
        
        Args:
            cache_type: Tipo de caché específico a limpiar, o None para limpiar todos
        """
        if cache_type:
            if cache_type in self._caches:
                self._caches[cache_type] = {}
                self._save_cache(cache_type)
        else:
            for cache_type in self.CACHE_VALIDITY.keys():
                self._caches[cache_type] = {}
                self._save_cache(cache_type)
    
    def get_stats(self) -> Dict[str, int]:
        """
        Obtiene estadísticas de los cachés
        
        Returns:
            Dict con el número de entradas por tipo de caché
        """
        stats = {}
        for cache_type in self.CACHE_VALIDITY.keys():
            stats[cache_type] = len(self._caches.get(cache_type, {}))
        return stats

