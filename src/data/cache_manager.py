"""
Sistema de caché persistente para datos financieros.

La versión original utilizaba múltiples archivos JSON. Esta versión migra el
almacenamiento a SQLite para mejorar la concurrencia, permitir consultas
selectivas y evitar archivos gigantes dentro del repositorio.
"""
import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class CacheManager:
    """Gestor de caché persistente respaldado por SQLite."""

    # Configuración de validez por tipo de caché (en días)
    CACHE_VALIDITY = {
        "earnings": 7,      # Earnings cambian trimestralmente
        "profile": 90,      # Perfil cambia muy poco (solo cambios corporativos)
        "peers": 30,        # Peers cambian poco
        "financials": 90,   # Estados financieros anuales cambian 1 vez al año
        "metrics": 30,      # Métricas cambian cuando cambian estados financieros
    }

    def __init__(self, cache_dir: Path, db_filename: str = "cache.db"):
        """
        Inicializa el gestor de caché.

        Args:
            cache_dir: Directorio donde se guardará la base de datos SQLite.
            db_filename: Nombre del archivo de base de datos (default: cache.db).
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.cache_dir / db_filename
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.row_factory = sqlite3.Row
        self._create_tables()
        self._migrate_from_json_files()

    def _create_tables(self):
        """Crea la tabla de caché si no existe."""
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_entries (
                    cache_type TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    data TEXT NOT NULL,
                    cached_date TEXT NOT NULL,
                    PRIMARY KEY (cache_type, cache_key)
                )
                """
            )
            self._conn.commit()

    def get(self, cache_type: str, key: str) -> Optional[Any]:
        """
        Obtiene un valor del caché si todavía es válido.
        """
        if not self._is_valid_type(cache_type):
            return None

        with self._lock:
            row = self._conn.execute(
                """
                SELECT data, cached_date
                FROM cache_entries
                WHERE cache_type = ? AND cache_key = ?
                """,
                (cache_type, key),
            ).fetchone()

        if not row:
            return None

        cached_record = {
            "data": json.loads(row["data"]),
            "cached_date": row["cached_date"],
        }

        if not self._is_valid(cached_record, cache_type):
            logger.debug("Caché %s para %s expirado, eliminando...", cache_type, key)
            self.invalidate(cache_type, key)
            return None

        return cached_record["data"]

    def set(self, cache_type: str, key: str, data: Any, save_immediately: bool = True):
        """
        Guarda un valor en el caché.

        Nota: el parámetro `save_immediately` se mantiene por compatibilidad,
        pero todos los inserts/updates se confirman inmediatamente.
        """
        if not self._is_valid_type(cache_type):
            return

        payload = json.dumps(data, ensure_ascii=False)
        cached_date = datetime.now().isoformat()

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO cache_entries (cache_type, cache_key, data, cached_date)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(cache_type, cache_key) DO UPDATE SET
                    data = excluded.data,
                    cached_date = excluded.cached_date
                """,
                (cache_type, key, payload, cached_date),
            )
            self._conn.commit()

    def invalidate(self, cache_type: str, key: str):
        """Invalida una entrada específica del caché."""
        if not self._is_valid_type(cache_type):
            return

        with self._lock:
            self._conn.execute(
                "DELETE FROM cache_entries WHERE cache_type = ? AND cache_key = ?",
                (cache_type, key),
            )
            self._conn.commit()
        logger.debug("Caché %s para %s invalidado", cache_type, key)

    def clear(self, cache_type: Optional[str] = None):
        """Limpia uno o todos los tipos de caché."""
        with self._lock:
            if cache_type:
                if not self._is_valid_type(cache_type):
                    return
                self._conn.execute(
                    "DELETE FROM cache_entries WHERE cache_type = ?", (cache_type,)
                )
            else:
                self._conn.execute("DELETE FROM cache_entries")
            self._conn.commit()

    def get_stats(self) -> Dict[str, int]:
        """Obtiene conteo de entradas por tipo de caché."""
        stats = {cache_type: 0 for cache_type in self.CACHE_VALIDITY.keys()}

        with self._lock:
            rows = self._conn.execute(
                """
                SELECT cache_type, COUNT(*) AS total
                FROM cache_entries
                GROUP BY cache_type
                """
            ).fetchall()

        for row in rows:
            stats[row["cache_type"]] = row["total"]

        return stats

    def close(self):
        """Cierra la conexión SQLite."""
        with self._lock:
            self._conn.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _is_valid_type(self, cache_type: str) -> bool:
        if cache_type not in self.CACHE_VALIDITY:
            logger.warning("Tipo de caché desconocido: %s", cache_type)
            return False
        return True

    def _is_valid(self, cached_data: Dict[str, Any], cache_type: str) -> bool:
        """Verifica si los datos cacheados son válidos."""
        cached_date_str = cached_data.get("cached_date")
        if not cached_date_str:
            return False

        try:
            cached_date = datetime.fromisoformat(cached_date_str)
            validity_days = self.CACHE_VALIDITY[cache_type]
            expiration_date = cached_date + timedelta(days=validity_days)
            return datetime.now() < expiration_date
        except Exception as exc:
            logger.warning("Error validando caché: %s", exc)
            return False

    def _migrate_from_json_files(self):
        """
        Migra los archivos de caché legacy (*.json) hacia SQLite y los elimina.
        Se ejecuta solo si la base aún no contiene datos.
        """
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS total FROM cache_entries").fetchone()
            existing_entries = row["total"]

        if existing_entries > 0:
            return

        for cache_type in self.CACHE_VALIDITY.keys():
            cache_file = self.cache_dir / f"{cache_type}_cache.json"
            if not cache_file.exists():
                continue

            try:
                with open(cache_file, "r", encoding="utf-8") as fh:
                    legacy_cache = json.load(fh)
            except Exception as exc:
                logger.warning(
                    "No se pudo leer el caché legacy %s: %s", cache_file.name, exc
                )
                continue

            inserted = 0
            for key, entry in legacy_cache.items():
                if isinstance(entry, dict) and "data" in entry:
                    data_payload = entry.get("data")
                    cached_date = entry.get("cached_date")
                else:
                    data_payload = entry
                    cached_date = None

                if cached_date is None:
                    cached_date = datetime.now().isoformat()

                try:
                    payload = json.dumps(data_payload, ensure_ascii=False)
                except TypeError:
                    logger.debug(
                        "Entrada no serializable para %s:%s. Se omite.", cache_type, key
                    )
                    continue

                with self._lock:
                    self._conn.execute(
                        """
                        INSERT INTO cache_entries (cache_type, cache_key, data, cached_date)
                        VALUES (?, ?, ?, ?)
                        """,
                        (cache_type, key, payload, cached_date),
                    )
                inserted += 1

            if inserted:
                with self._lock:
                    self._conn.commit()
                try:
                    cache_file.unlink()
                    logger.info(
                        "Migradas %s entradas desde %s a SQLite",
                        inserted,
                        cache_file.name,
                    )
                except Exception as exc:
                    logger.warning(
                        "No se pudo eliminar el caché legacy %s después de migrar: %s",
                        cache_file.name,
                        exc,
                    )


