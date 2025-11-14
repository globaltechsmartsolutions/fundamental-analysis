"""
Configuración de logging para Fundamental Analysis Engine
"""
import logging
import sys
import zipfile
import os
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler


class CompressedRotatingFileHandler(RotatingFileHandler):
    """
    Handler que comprime los archivos rotados en ZIP para ahorrar espacio.
    Cuando un archivo se rota, se comprime automáticamente en un ZIP.
    """
    
    def __init__(self, filename, mode='a', maxBytes=0, backupCount=0, encoding=None, delay=False):
        super().__init__(filename, mode, maxBytes, backupCount, encoding, delay)
        self.log_dir = Path(filename).parent
        self.base_name = Path(filename).stem  # Nombre sin extensión
        
    def doRollover(self):
        """
        Sobrescribe el método de rotación para comprimir archivos antiguos en ZIP.
        """
        if self.stream:
            self.stream.close()
            self.stream = None
            
        if self.backupCount > 0:
            # Primero, comprimir archivos antiguos que excedan backupCount
            for i in range(self.backupCount + 1, self.backupCount + 10):  # Buscar hasta 10 archivos antiguos
                sfn = self.baseFilename + "." + str(i)
                if os.path.exists(sfn):
                    # Comprimir en ZIP
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    zip_name = self.log_dir / f"{self.base_name}_{timestamp}.log.{i}.zip"
                    try:
                        with zipfile.ZipFile(str(zip_name), 'w', zipfile.ZIP_DEFLATED) as zipf:
                            zipf.write(sfn, os.path.basename(sfn))
                        os.remove(sfn)  # Eliminar archivo original después de comprimir
                    except Exception as e:
                        # Si falla la compresión, dejar el archivo como está
                        pass
        
        # Rotar archivos existentes (lógica estándar de RotatingFileHandler)
        for i in range(self.backupCount - 1, 0, -1):
            sfn = self.baseFilename + "." + str(i)
            dfn = self.baseFilename + "." + str(i + 1)
            if os.path.exists(sfn):
                if os.path.exists(dfn):
                    os.remove(dfn)
                os.rename(sfn, dfn)
        
        dfn = self.baseFilename + ".1"
        if os.path.exists(dfn):
            os.remove(dfn)
        if os.path.exists(self.baseFilename):
            os.rename(self.baseFilename, dfn)
            
        if not self.delay:
            self.stream = self._open()


def setup_logging(log_dir: str = "var/logs", level: str = "INFO"):
    """
    Configura logging estructurado
    
    Args:
        log_dir: Directorio para logs
        level: Nivel de logging (DEBUG, INFO, WARNING, ERROR)
    """
    # Crear directorio de logs si no existe
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    
    # Configurar formato con fecha y hora más visible
    # Formato: [YYYY-MM-DD HH:MM:SS] NIVEL | Módulo | Mensaje
    log_format = "[%(asctime)s] %(levelname)-8s | %(name)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    
    # Configurar handlers
    handlers = []
    
    # Handler para consola (con flush inmediato)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(log_format, date_format))
    # Forzar flush inmediato para ver logs en tiempo real
    console_handler.stream.flush = lambda: None  # Deshabilitar buffering
    handlers.append(console_handler)
    
    # Handler para archivo (todos los logs) - con rotación y compresión ZIP
    # Rotación: máximo 10MB por archivo, mantener 2 archivos de respaldo
    # Reducido de 50MB a 10MB para evitar problemas de serialización en Cursor
    # Los archivos antiguos se comprimen automáticamente en ZIP para ahorrar espacio
    all_logs_file = log_path / "fundamental_analysis.log"
    file_handler = CompressedRotatingFileHandler(
        str(all_logs_file),
        encoding="utf-8",
        mode='a',
        maxBytes=10 * 1024 * 1024,  # 10 MB por archivo (reducido para evitar problemas en Cursor)
        backupCount=2  # Mantener 2 archivos de respaldo (los más antiguos se comprimen en ZIP)
    )
    file_handler.setFormatter(logging.Formatter(log_format, date_format))
    # Forzar escritura inmediata sin buffering
    if hasattr(file_handler.stream, 'flush'):
        file_handler.stream.flush()
    handlers.append(file_handler)
    
    # Handler para errores solamente - también con rotación y compresión ZIP
    error_logs_file = log_path / "fundamental_analysis_errors.log"
    error_handler = CompressedRotatingFileHandler(
        str(error_logs_file),
        encoding="utf-8",
        maxBytes=10 * 1024 * 1024,  # 10 MB por archivo de errores
        backupCount=2  # Mantener 2 archivos de respaldo (los más antiguos se comprimen en ZIP)
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter(log_format, date_format))
    handlers.append(error_handler)
    
    # Configurar root logger
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        handlers=handlers,
        format=log_format,
        datefmt=date_format
    )
    
    return logging.getLogger("fundamental_analysis")


def get_logger(name: str) -> logging.Logger:
    """
    Obtiene logger con nombre específico
    
    Nota: Los loggers hijos propagan mensajes al logger padre por defecto.
    Esto está bien porque el root logger ya tiene los handlers configurados.
    No necesitamos deshabilitar propagación ni copiar handlers manualmente.
    """
    return logging.getLogger(f"fundamental_analysis.{name}")

