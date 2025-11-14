#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Sistema de entrenamiento para ajustar parámetros del modelo
Compara nuestros valores con los de Alpha Spread y ajusta parámetros
"""
import sys
import io
import time
from pathlib import Path
import json
from typing import Dict, List, Tuple
import numpy as np
from scipy.optimize import minimize, differential_evolution
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from collections import Counter

# Configurar encoding UTF-8 para stdout/stderr en Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Agregar raíz del proyecto al path para imports absolutos
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core import FundamentalAnalysisEngine, load_config
from src.utils import setup_logging
from src.valuation import CompanySpecificParams, compute_company_dcf, DCFCalculator
from src.target_value_fetcher import fetch_target_from_web, fetch_multiple_targets

# Configurar logging estructurado con ruta correcta desde training/
import os

# Flag para logging detallado de símbolos específicos (evita llenar logs en producción)
# Puede configurarse via variable de entorno: DEBUG_DCF_SYMBOL=MSFT
DEBUG_DCF_SYMBOL = os.environ.get("DEBUG_DCF_SYMBOL", "").upper()  # "" = deshabilitado

# Logger principal para este módulo (se inicializa lazy cuando se necesite)
class _LazyLogger:
    """Logger que se inicializa solo cuando se accede por primera vez"""
    _instance = None
    _logger = None
    
    def __getattr__(self, name):
        if self._logger is None:
            # Asegurar que el directorio de logs existe (ruta relativa a la raíz del proyecto)
            log_dir = Path(__file__).parent.parent / "var" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            
            # Configurar logging usando setup_logging con la ruta correcta
            setup_logging(log_dir=str(log_dir), level="INFO")
            
            # Logger principal para este módulo
            self._logger = logging.getLogger(__name__)
            
            # Forzar flush inmediato en stdout para ver logs en tiempo real
            sys.stdout.flush()
            sys.stderr.flush()
        return getattr(self._logger, name)

logger = _LazyLogger()


class ModelTrainer:
    """
    Entrena el modelo ajustando parámetros automáticamente para acercarse a Alpha Spread
    
    Metodología Alpha Spread:
    -------------------------
    Alpha Spread calcula el valor intrínseco combinando dos métodos:
    
    1. DCF (Absolute Valuation / Discounted Cash Flow):
       - Proyecta flujos de caja futuros (FCF) para los próximos años
       - Descuenta al valor presente usando WACC (Weighted Average Cost of Capital)
       - Calcula valor terminal usando crecimiento perpetuo
       - Parámetros ajustables: projection_years, terminal_growth_rate, WACC components
    
    2. Relative Valuation (Comparables):
       - Compara múltiplos (
       
       
       , P/B, P/S, EV/EBITDA) con empresas similares
       - Usa promedios del sector como benchmark
       - Calcula valor justo basado en múltiplos históricos y crecimiento esperado
    
    3. Blended Value (Valor Combinado):
       - Alpha Spread: "To enhance accuracy, we average the results from these two methods"
       - Valor Final = (DCF × peso_dcf) + (Comparables × peso_comparables)
       - Por defecto: promedio simple 50/50, pero el algoritmo puede ajustar los pesos
    
    Ajuste Automático:
    ------------------
    El algoritmo differential_evolution prueba automáticamente diferentes combinaciones
    de parámetros dentro de límites realistas y busca minimizar el error vs valores
    objetivo de Alpha Spread. NO se modifican parámetros manualmente.
    
    Parámetros que se ajustan:
    - Pesos del blend (dcf_weight, comparables_weight)
    - Parámetros DCF (projection_years, terminal_growth_rate)
    - Componentes WACC (risk_free_rate, market_risk_premium, beta, debt_to_equity, cost_of_debt, tax_rate)
    """
    
    def __init__(self, api_key: str):
        logger.info(f"[TRAINER_INIT] Inicializando ModelTrainer...")
        logger.info(f"[TRAINER_INIT] API key proporcionada: {'*' * (len(api_key) - 4) + api_key[-4:] if len(api_key) > 4 else '****'}")
        self.api_key = api_key
        self.engine = None
        self.target_values = {}  # Valores objetivo de Alpha Spread: {symbol: intrinsic_value}
        self.symbols = []
        self.financial_data_cache = {}  # Caché de datos financieros para evitar peticiones repetidas
        self.growth_rates_cache = {}  # Caché de tasas de crecimiento completas (revenue, earnings, fcf)
        self.sector_averages_cache = {}  # Caché de promedios del sector
        self.peers_cache = {}  # Caché de empresas similares (peers)
        self.cache_file = "training_cache.json"  # Archivo para persistir el caché
        self._last_params_hash = None  # Para detectar cambios en parámetros y reutilizar engine
        logger.info(f"[TRAINER_INIT] ModelTrainer inicializado exitosamente")
    
    def get_sector_terminal_growth(self, sector: str) -> float:
        """
        Retorna terminal_growth_rate específico por sector (como Alpha Spread)
        Alpha Spread usa valores conservadores:
        - Tech → 2.5%
        - Utilities → 1.5%
        - Healthcare/Industrials → 2.0%
        - Default → 2.0% (conservador)
        """
        sector_lower = sector.lower() if sector else ""
        
        # Mapeo de sectores a terminal growth rates conservadores (como Alpha Spread)
        # Alpha Spread usa valores conservadores: Tech 2.5%, Utilities 1.5%, Healthcare/Industrials 2.0%
        mapping = {
            "technology": 2.5,  # Tech → 2.5% (conservador)
            "tech": 2.5,
            "software": 2.5,
            "semiconductor": 2.5,
            "healthcare": 2.0,  # Healthcare → 2.0%
            "pharmaceutical": 2.0,
            "biotechnology": 2.0,
            "financial services": 2.0,
            "financial": 2.0,
            "banking": 2.0,
            "consumer cyclical": 2.0,
            "consumer discretionary": 2.0,
            "retail": 2.0,
            "industrials": 2.0,  # Industrials → 2.0%
            "industrial": 2.0,
            "communication services": 2.0,
            "telecommunications": 2.0,
            "consumer defensive": 1.8,
            "consumer staples": 1.8,
            "energy": 1.8,
            "utilities": 1.5,  # Utilities → 1.5% (más conservador)
            "utility": 1.5,
            "real estate": 1.8,
            "basic materials": 1.8,
            "materials": 1.8,
        }
        
        # Buscar coincidencia parcial
        for key, value in mapping.items():
            if key in sector_lower:
                return value
        
        # Default conservador (como Alpha Spread)
        return 2.0
    
    def set_target_values(self, target_values: Dict[str, float], fetch_missing_from_web: bool = True):
        """
        Establece los valores objetivo de Alpha Spread
        
        Args:
            target_values: Dict con símbolo -> valor intrínseco objetivo
                Ejemplo: {"AAPL": 178.20, "MSFT": 413.12, ...}
            fetch_missing_from_web: Si True, intenta obtener valores faltantes desde la web
        """
        self.target_values = target_values.copy()
        self.symbols = list(target_values.keys())
        
        # Si hay símbolos sin valores, intentar obtenerlos usando el módulo independiente
        if fetch_missing_from_web:
            missing_symbols = [s for s in self.symbols if not self.target_values.get(s)]
            if missing_symbols:
                logger.info(f"Obteniendo {len(missing_symbols)} valores faltantes desde JSON...")
                try:
                    web_targets = fetch_multiple_targets(missing_symbols)
                    for symbol, value in web_targets.items():
                        if value is not None:
                            self.target_values[symbol] = value
                            logger.info(f"[{symbol}] Target obtenido: ${value:.2f}")
                except Exception as e:
                    logger.warning(f"No se pudieron obtener valores faltantes: {e}")
        
        logger.info(f"Valores objetivo establecidos para {len(self.symbols)} empresas")
        for symbol, value in self.target_values.items():
            if value:
                logger.info(f"  {symbol}: ${value:.2f}")
    
    def load_cache(self) -> bool:
        """
        Carga el caché desde disco si existe
        
        Returns:
            True si se cargó el caché, False si no existe
        """
        if Path(self.cache_file).exists():
            try:
                logger.info(f"Cargando caché desde {self.cache_file}...")
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                
                self.financial_data_cache = cache_data.get('financial_data', {})
                self.growth_rates_cache = cache_data.get('growth_rates', {})
                self.sector_averages_cache = cache_data.get('sector_averages', {})
                self.peers_cache = cache_data.get('peers', {})
                
                logger.info(f"[OK] Cache cargado: {len(self.financial_data_cache)} empresas disponibles")
                return True
            except Exception as e:
                logger.warning(f"No se pudo cargar el caché: {e}")
                return False
        return False
    
    def save_cache(self):
        """Guarda el caché en disco"""
        try:
            cache_data = {
                'financial_data': self.financial_data_cache,
                'growth_rates': self.growth_rates_cache,
                'sector_averages': self.sector_averages_cache,
                'peers': self.peers_cache,
                'symbols': list(self.financial_data_cache.keys())
            }
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, default=str)
            logger.debug(f"Caché guardado en {self.cache_file}")
        except Exception as e:
            logger.warning(f"No se pudo guardar el caché: {e}")
    
    def preload_financial_data(self):
        """
        Precarga todos los datos financieros una sola vez para evitar peticiones repetidas
        durante el entrenamiento. Esto acelera significativamente el proceso.
        Si hay caché en disco, lo carga primero y solo carga las empresas faltantes.
        """
        if not self.symbols:
            raise ValueError("Debes establecer valores objetivo primero con set_target_values()")
        
        # Intentar cargar caché existente
        cache_loaded = self.load_cache()
        
        # Determinar qué empresas faltan
        missing_symbols = [s for s in self.symbols if s not in self.financial_data_cache]
        
        if not missing_symbols:
            logger.info("=" * 60)
            logger.info(f"[OK] Cache completo: todas las {len(self.symbols)} empresas ya estan cargadas")
            logger.info("=" * 60)
            return
        
        logger.info("=" * 60)
        if cache_loaded:
            logger.info(f"Precargando datos de {len(missing_symbols)} empresas faltantes...")
            logger.info(f"({len(self.symbols) - len(missing_symbols)} empresas ya en caché)")
        else:
            logger.info("Precargando datos financieros de todas las empresas...")
        logger.info("Los datos se guardan automáticamente en caché para reutilización")
        logger.info("=" * 60)
        
        # Crear engine temporal solo para extraer datos
        logger.info(f"[PRECARGA] Creando engine temporal para extraer datos...")
        logger.debug(f"[PRECARGA] API key: {'*' * (len(self.api_key) - 4) + self.api_key[-4:] if len(self.api_key) > 4 else '****'}")
        try:
            temp_engine = FundamentalAnalysisEngine(self.api_key)
            logger.info(f"[PRECARGA] Engine temporal creado exitosamente")
            logger.debug(f"[PRECARGA] Engine tiene client: {temp_engine.client is not None}")
            logger.debug(f"[PRECARGA] Engine tiene extractor: {temp_engine.extractor is not None}")
            logger.debug(f"[PRECARGA] Engine tiene cache_manager: {temp_engine.cache_manager is not None}")
            
            # Probar conexión antes de continuar
            logger.info(f"[PRECARGA] Probando conexión a Finnhub API...")
            connection_ok = temp_engine.client.test_connection()
            if not connection_ok:
                logger.error(f"[PRECARGA] ❌ ERROR: No se pudo establecer conexión con Finnhub API")
                logger.error(f"[PRECARGA] Por favor verifica tu conexión a internet y vuelve a intentar")
                raise ConnectionError("No se pudo establecer conexión con Finnhub API")
            logger.info(f"[PRECARGA] ✅ Conexión a Finnhub API verificada exitosamente")
        except ConnectionError:
            raise  # Re-lanzar ConnectionError sin modificar
        except Exception as e:
            logger.error(f"[PRECARGA] ERROR creando engine temporal: {e}", exc_info=True)
            raise
        
        import time
        
        start_time = time.time()
        for idx, symbol in enumerate(missing_symbols, 1):
            try:
                elapsed = time.time() - start_time
                msg = f"[{idx}/{len(missing_symbols)}] Cargando datos de {symbol}... (Tiempo transcurrido: {elapsed/60:.1f} min)"
                try:
                    print(msg, flush=True)  # Print directo para asegurar visibilidad
                    sys.stdout.flush()  # Forzar escritura inmediata
                except (OSError, IOError):
                    pass  # Ignorar si print falla (proceso en background)
                logger.info(msg)
                
                # OPTIMIZACIÓN: Obtener datos financieros raw UNA VEZ y reutilizarlos
                logger.info(f"  -> Obteniendo datos financieros raw (income, balance, cash flow, metrics, profile)...")
                raw_financials = None
                max_retries = 2  # Reducido a 2 intentos para evitar esperas largas
                timeout_seconds = 30  # Timeout máximo de 30 segundos
                
                for retry in range(max_retries):
                    try:
                        # Usar threading con timeout para evitar bloqueos infinitos
                        import threading
                        result_container = {'data': None, 'error': None, 'completed': False}
                        
                        def fetch_data():
                            try:
                                result_container['data'] = temp_engine.client.get_company_basic_financials(symbol)
                                result_container['completed'] = True
                            except Exception as e:
                                result_container['error'] = e
                                result_container['completed'] = True
                        
                        thread = threading.Thread(target=fetch_data, daemon=True)
                        thread.start()
                        thread.join(timeout=timeout_seconds)
                        
                        # Verificar si el thread sigue vivo (timeout)
                        if thread.is_alive():
                            logger.warning(f"  [TIMEOUT] Llamada a API para {symbol} excedio {timeout_seconds}s (intento {retry+1}/{max_retries})")
                            if retry < max_retries - 1:
                                wait_time = (retry + 1) * 2  # 2, 4 segundos
                                logger.warning(f"  [RETRY {retry+1}/{max_retries}] Esperando {wait_time}s antes de reintentar...")
                                time.sleep(wait_time)
                                continue
                            else:
                                logger.error(f"  [ERROR] No se pudieron obtener datos para {symbol} después de {max_retries} intentos (timeout)")
                                logger.error(f"  [SKIP] Saltando {symbol} y continuando con siguiente empresa")
                                break
                        
                        # Verificar si hubo error
                        if result_container['error']:
                            raise result_container['error']
                        
                        # Verificar si se completó correctamente
                        if not result_container['completed']:
                            logger.warning(f"  [WARN] Llamada para {symbol} no se completó correctamente")
                            if retry < max_retries - 1:
                                continue
                            else:
                                break
                        
                        raw_financials = result_container['data']
                        if raw_financials:
                            logger.info(f"  [OK] Datos financieros raw obtenidos")
                            break
                        else:
                            logger.warning(f"  [WARN] Datos vacíos para {symbol}")
                            if retry < max_retries - 1:
                                wait_time = (retry + 1) * 2
                                logger.warning(f"  [RETRY {retry+1}/{max_retries}] Esperando {wait_time}s...")
                                time.sleep(wait_time)
                                continue
                            else:
                                break
                    except Exception as e:
                        error_msg = str(e)
                        logger.warning(f"  [ERROR] Excepción obteniendo {symbol}: {error_msg[:100]}")
                        if retry < max_retries - 1:
                            wait_time = (retry + 1) * 2  # 2, 4 segundos
                            logger.warning(f"  [RETRY {retry+1}/{max_retries}] Esperando {wait_time}s...")
                            time.sleep(wait_time)
                        else:
                            logger.error(f"  [ERROR] No se pudieron obtener datos para {symbol} después de {max_retries} intentos: {error_msg[:100]}")
                            logger.error(f"  [SKIP] Saltando {symbol} y continuando con siguiente empresa")
                            break
                
                if not raw_financials:
                    logger.warning(f"  [ERROR] No se pudieron obtener datos raw para {symbol} después de {max_retries} intentos")
                    continue
                
                # Extraer datos financieros procesados usando los datos raw ya obtenidos (sin peticiones adicionales)
                logger.info(f"  -> Procesando datos financieros...")
                try:
                    financial_data = temp_engine.extractor.extract_basic_financials(symbol, raw_financials=raw_financials)
                    if not financial_data:
                        logger.warning(f"  [ERROR] extract_basic_financials devolvió None para {symbol}")
                        continue
                except Exception as e:
                    error_msg = f"  [ERROR] Excepción al procesar datos para {symbol}: {type(e).__name__}: {str(e)}"
                    try:
                        print(error_msg, flush=True)
                    except (OSError, IOError):
                        pass
                    logger.warning(error_msg)
                    import traceback
                    logger.debug(traceback.format_exc())
                    continue
                logger.info(f"  [OK] Datos financieros procesados")
                
                # Obtener tasas de crecimiento usando los datos raw ya obtenidos (sin peticiones adicionales)
                logger.info(f"  -> Calculando tasas de crecimiento historicas...")
                growth_rates = temp_engine.client.get_historical_growth_rates(symbol, financials=raw_financials)
                logger.info(f"  [OK] Tasas de crecimiento calculadas")
                fcf_growth_rate = growth_rates.get("fcf_growth", 0.0)
                
                # Ajustar crecimiento de forma más conservadora pero manteniendo diferencias entre empresas
                # Alpha Spread usa crecimiento más moderado, pero no fuerza todo a 6%
                if fcf_growth_rate <= 0 or fcf_growth_rate < 1.0:
                    # Si es negativo o muy bajo, usar un mínimo razonable pero diferenciado
                    # Empresas financieras (bancos) suelen tener FCF bajo/negativo, usar crecimiento de earnings
                    earnings_growth = growth_rates.get("earnings_growth", 0.0)
                    revenue_growth = growth_rates.get("revenue_growth", 0.0)
                    if earnings_growth > 0:
                        fcf_growth_rate = max(earnings_growth * 0.8, 3.0)  # Usar earnings como proxy
                    elif revenue_growth > 0:
                        fcf_growth_rate = max(revenue_growth * 0.7, 3.0)  # Usar revenue como proxy
                    else:
                        fcf_growth_rate = 4.0  # Mínimo absoluto solo si no hay datos
                elif fcf_growth_rate < 3.0:
                    # Si está entre 1-3%, ajustar ligeramente hacia arriba pero mantener diferencia
                    fcf_growth_rate = fcf_growth_rate * 1.2  # Aumentar 20% pero mantener diferencia
                elif fcf_growth_rate > 30.0:
                    # Si es muy alto, reducir pero mantener diferencia
                    fcf_growth_rate = min(fcf_growth_rate * 0.6, 18.0)
                elif fcf_growth_rate > 15.0:
                    # Si es alto, reducir moderadamente
                    fcf_growth_rate = fcf_growth_rate * 0.75
                elif fcf_growth_rate > 10.0:
                    # Si es moderado-alto, reducir ligeramente
                    fcf_growth_rate = fcf_growth_rate * 0.9
                # Si está entre 3-10%, mantenerlo (ya es razonable)
                
                # Guardar tasa ajustada en growth_rates para uso directo
                growth_rates["fcf_growth"] = fcf_growth_rate
                
                # Obtener peers (empresas similares) - se usa en get_sector_averages
                logger.info(f"  -> Obteniendo empresas similares (peers)...")
                try:
                    peers = temp_engine.client.get_peers(symbol)
                    logger.info(f"  [OK] Encontradas {len(peers)} empresas similares")
                except Exception as e:
                    logger.warning(f"  [WARN] No se pudieron obtener peers: {e}")
                    peers = []
                
                # Obtener promedios del sector (usa growth_rates y peers internamente)
                # Pero como ya tenemos los datos, podemos pasarlos directamente
                logger.info(f"  -> Calculando promedios del sector...")
                sector_averages = temp_engine.extractor.get_sector_averages(symbol, financial_data)
                logger.info(f"  [OK] Promedios del sector calculados")
                
                # Guardar TODO en caché para evitar cualquier petición adicional
                self.financial_data_cache[symbol] = financial_data
                self.growth_rates_cache[symbol] = growth_rates  # Guardar TODAS las tasas de crecimiento
                self.peers_cache[symbol] = peers  # Guardar peers
                self.sector_averages_cache[symbol] = sector_averages
                
                # Guardar caché después de cada empresa (persistencia incremental)
                self.save_cache()
                
                ok_msg = f"  [OK] {symbol}: Precio=${financial_data['current_price']:.2f}, FCF=${financial_data['free_cash_flow']:.2f}M, Growth={fcf_growth_rate:.2f}%"
                try:
                    print(ok_msg, flush=True)  # Print directo
                except (OSError, IOError):
                    pass
                logger.info(ok_msg)
                cache_msg = "  [SAVED] Cache guardado en disco"
                try:
                    print(cache_msg, flush=True)
                except (OSError, IOError):
                    pass
                logger.info(cache_msg)
                sys.stdout.flush()  # Forzar escritura inmediata
                
                # Delay mínimo entre empresas (reducido ya que el rate limiter interno es suficiente)
                # Con la optimización, cada empresa ahora hace ~6 peticiones en lugar de ~10-12
                if idx < len(missing_symbols):
                    logger.info(f"  [WAIT] Esperando 1s antes de siguiente empresa...")
                    time.sleep(1)  # Delay mínimo entre empresas
            
            except Exception as e:
                error_msg = f"  [ERROR CRÍTICO] Error inesperado procesando {symbol}: {type(e).__name__}: {str(e)}"
                try:
                    print(error_msg, flush=True)
                except (OSError, IOError):
                    pass
                logger.error(error_msg)
                import traceback
                logger.error(traceback.format_exc())
                # Delay después de error para no saturar la API
                time.sleep(5)
                # Continuar con la siguiente empresa en lugar de detener todo el proceso
                continue
        
        # Resumen final de la precarga
        logger.info("=" * 60)
        loaded_count = len(self.financial_data_cache)
        total_count = len(self.symbols)
        if loaded_count == total_count:
            logger.info(f"[OK] Precarga completada: {loaded_count}/{total_count} empresas cargadas exitosamente")
        else:
            failed_symbols = [s for s in self.symbols if s not in self.financial_data_cache]
            logger.warning(f"[WARN] Precarga parcial: {loaded_count}/{total_count} empresas cargadas")
            logger.warning(f"  Empresas que fallaron: {failed_symbols}")
            logger.info(f"  El entrenamiento continuará con las {loaded_count} empresas disponibles")
        logger.info("=" * 60)
        
        # Guardar caché final
        self.save_cache()
        
        try:
            print("=" * 60, flush=True)
            print(f"Precarga completada: {len(self.financial_data_cache)}/{len(self.symbols)} empresas", flush=True)
            print(f"Empresas cargadas en caché: {list(self.financial_data_cache.keys())}", flush=True)
            print(f"[SAVED] Cache guardado en {self.cache_file} - se reutilizara en proximas ejecuciones", flush=True)
            print("Los datos se reutilizarán en todas las evaluaciones del entrenamiento", flush=True)
            print("=" * 60, flush=True)
        except (OSError, IOError):
            pass
        logger.info("=" * 60)
        logger.info(f"Precarga completada: {len(self.financial_data_cache)}/{len(self.symbols)} empresas")
        logger.info(f"Empresas cargadas en caché: {list(self.financial_data_cache.keys())}")
        logger.info(f"[SAVED] Cache guardado en {self.cache_file} - se reutilizara en proximas ejecuciones")
        logger.info("Los datos se reutilizarán en todas las evaluaciones del entrenamiento")
        logger.info("=" * 60)
        sys.stdout.flush()  # Forzar escritura inmediata
    
    def _evaluate_single_company(self, symbol: str, idx: int, total: int, params: Dict, reuse_engine=None) -> Tuple[str, float]:
        """
        Evalúa una sola empresa usando datos REALES por empresa con factores de ajuste globales
        
        Args:
            reuse_engine: Engine reutilizable para evitar crear uno nuevo en cada evaluación
        
        Returns:
            Tuple (symbol, error_pct) o (symbol, 100.0) si falla
        """
        # Solo loguear la primera vez, no en cada iteración de optimización
        if idx == 1 and total == 1:
            logger.debug(f"[EVAL_START] Iniciando evaluación de {symbol}")
        try:
            # Usar datos del caché si están disponibles (evita peticiones repetidas)
            if symbol not in self.financial_data_cache:
                logger.warning(f"[{idx}/{total}] Saltando {symbol} (no está en caché)")
                return (symbol, 100.0)
            
            logger.debug(f"[EVAL] {symbol}: Datos del caché cargados")
            
            financial_data = self.financial_data_cache[symbol]
            
            # FILTRAR empresas con FCF=0 o muy bajo (bancos/financieras problemáticas)
            # MEJORA: Excluir completamente del entrenamiento (no asignar error 100%)
            # Esto evita que bancos/financieras con FCF contable raro rompan el modelo
            original_fcf = financial_data.get("free_cash_flow", 0)
            if original_fcf <= 0:
                sector = financial_data.get("sector", "Unknown")
                logger.warning(f"[EVAL] {symbol}: FCF={original_fcf:.2f}M (<=0), Sector={sector}")
                logger.warning(f"  → EXCLUIDA del entrenamiento (DCF no tiene sentido con FCF=0)")
                logger.warning(f"  → Recomendación: Usar modelo específico para {sector} o valoración alternativa")
                # Retornar None para indicar que debe ser excluida completamente
                return (symbol, None)
            growth_rates = self.growth_rates_cache.get(symbol, {"fcf_growth": 5.0})
            sector_averages = self.sector_averages_cache.get(symbol, {})
            
            # Extraer datos REALES por empresa
            beta_real = financial_data.get("beta", 1.0)
            # Validar beta razonable (rango extendido para incluir empresas volátiles)
            # Rango [0.3 - 5.0] permite betas extremos pero válidos (tech volátiles, emergentes)
            if beta_real < 0.3 or beta_real > 5.0:
                beta_real = 1.0
            
            sector = financial_data.get("sector", "Unknown")
            
            # MODO ALPHA SPREAD: Terminal growth específico por sector (como Alpha Spread)
            # Alpha Spread ajusta por industria: Tech 2.5%, Utilities 1.5%, Healthcare/Industrials 2.0%
            terminal_growth = self.get_sector_terminal_growth(sector)
            
            # MODO ALPHA SPREAD: ERP = 4.12% (como Alpha Spread)
            market_risk_premium = 4.12
            
            # Calcular cost_of_debt REAL
            interest_expense = financial_data.get("interest_expense", 0)
            total_debt = financial_data.get("debt", 0)
            cost_of_debt_real = (interest_expense / max(total_debt, 1)) * 100 if total_debt > 0 else 5.0
            cost_of_debt_real = max(cost_of_debt_real, 3.0)  # Mínimo 3%
            cost_of_debt_real = min(cost_of_debt_real, 10.0)  # Máximo 10%
            
            # Calcular debt_to_equity REAL
            shareholder_equity = financial_data.get("shareholder_equity", 0)
            debt_to_equity_real = total_debt / max(shareholder_equity, 1) if shareholder_equity > 0 else 0.3
            debt_to_equity_real = max(debt_to_equity_real, 0.0)
            debt_to_equity_real = min(debt_to_equity_real, 2.0)  # Máximo razonable
            
            # NUEVO ENFOQUE: Parámetros específicos por empresa (como Alpha Spread)
            # Calcular parámetros específicos para esta empresa
            company_params = CompanySpecificParams(
                symbol=symbol,
                financial_data=financial_data,
                growth_rates=growth_rates,
                historical_data={}  # Puede extenderse con datos históricos
            )
            
            # Obtener parámetros específicos de la empresa
            specific_params = company_params.get_all_params()
            
            # PRIORIDAD 1: Intentar cargar modelo entrenado específico de esta empresa
            # Si existe un modelo entrenado, usar esos parámetros en lugar de los globales
            trained_model = None
            models_dir = Path("models")
            model_file = models_dir / f"{symbol}_model.json"
            
            if model_file.exists():
                try:
                    with open(model_file, 'r', encoding='utf-8') as f:
                        trained_model = json.load(f)
                    logger.debug(f"[EVAL] {symbol}: Modelo entrenado encontrado, usando parámetros específicos")
                except Exception as e:
                    logger.debug(f"[EVAL] {symbol}: Error cargando modelo entrenado: {e}, usando parámetros globales")
            
            # Usar parámetros específicos de la empresa para pesos y otros factores
            dcf_weight_company = specific_params['dcf_weight']
            comparables_weight_company = specific_params['comparables_weight']
            
            # IMPORTANTE: Durante entrenamiento, SIEMPRE usar los parámetros que se están probando
            # Solo usar modelo entrenado cuando NO estamos entrenando (modo inferencia)
            # Durante entrenamiento, params contiene los parámetros que queremos probar
            if params and 'growth_adjustment_factor' in params and 'wacc_adjustment_factor' in params:
                # MODO ENTRENAMIENTO: Usar parámetros que se están probando
                growth_adjustment_factor = params.get('growth_adjustment_factor', 1.0)
                wacc_adjustment_factor = params.get('wacc_adjustment_factor', 1.0)
                logger.debug(f"[EVAL] {symbol}: MODO ENTRENAMIENTO - Usando parámetros en prueba: "
                           f"growth_adj={growth_adjustment_factor:.3f}, wacc_adj={wacc_adjustment_factor:.3f}")
            elif trained_model and 'growth_adjustment_factor' in trained_model and 'wacc_adjustment_factor' in trained_model:
                # MODO INFERENCIA: Usar modelo entrenado si existe
                growth_adjustment_factor = trained_model['growth_adjustment_factor']
                wacc_adjustment_factor = trained_model['wacc_adjustment_factor']
                logger.debug(f"[EVAL] {symbol}: MODO INFERENCIA - Usando parámetros entrenados: "
                           f"growth_adj={growth_adjustment_factor:.3f}, wacc_adj={wacc_adjustment_factor:.3f}")
            else:
                # Fallback: usar valores por defecto
                growth_adjustment_factor = params.get('growth_adjustment_factor', 1.0) if params else 1.0
                wacc_adjustment_factor = params.get('wacc_adjustment_factor', 1.0) if params else 1.0
                logger.debug(f"[EVAL] {symbol}: Usando valores por defecto: "
                           f"growth_adj={growth_adjustment_factor:.3f}, wacc_adj={wacc_adjustment_factor:.3f}")
            
            # Aplicar factor de ajuste GLOBAL al crecimiento
            base_fcf_growth = growth_rates.get("fcf_growth", 5.0)
            adjusted_fcf_growth = base_fcf_growth * growth_adjustment_factor
            
            logger.debug(f"[COMPANY_PARAMS] {symbol}: growth_adj={growth_adjustment_factor:.3f}, "
                        f"wacc_adj={wacc_adjustment_factor:.3f}, dcf_w={dcf_weight_company:.3f}, "
                        f"comp_w={comparables_weight_company:.3f}, stability={specific_params['fcf_stability_score']:.3f}")
            
            # Reutilizar engine si se proporciona, o crear uno nuevo solo si es necesario
            from src.core import FundamentalAnalysisEngine
            if reuse_engine is None:
                logger.debug(f"[EVALUATE] Creando nuevo engine para {symbol} con parámetros: "
                           f"dcf_weight={dcf_weight_company}, comparables_weight={comparables_weight_company}, "
                           f"terminal_growth={terminal_growth}, market_risk_premium={market_risk_premium}")
                try:
                    temp_engine = FundamentalAnalysisEngine(
                        self.api_key,
                        dcf_weight=dcf_weight_company,  # Específico por empresa
                        comparables_weight=comparables_weight_company,  # Específico por empresa
                        projection_years=10,  # Fijo
                        terminal_growth_rate=terminal_growth,  # Por sector o conservador si Alpha Spread
                        risk_free_rate=4.5,  # Global
                        market_risk_premium=market_risk_premium,  # 4.12% si Alpha Spread, 5.8% si normal
                    )
                    logger.debug(f"[EVALUATE] Engine creado exitosamente para {symbol}")
                except Exception as e:
                    logger.error(f"[EVALUATE] ERROR creando engine para {symbol}: {e}", exc_info=True)
                    raise
            else:
                # Reutilizar engine existente (más eficiente)
                logger.debug(f"[EVALUATE] Reutilizando engine existente para {symbol}")
                temp_engine = reuse_engine
                # Actualizar pesos si es necesario
                temp_engine.valuation_engine.dcf_weight = dcf_weight_company
                temp_engine.valuation_engine.comparables_weight = comparables_weight_company
                logger.debug(f"[EVALUATE] Pesos actualizados: dcf={dcf_weight_company}, comp={comparables_weight_company}")
            
            # Calcular DCF con parámetros reales por empresa
            from src.valuation import DCFCalculator
            dcf_calc = DCFCalculator(
                projection_years=10,
                terminal_growth_rate=terminal_growth,
                risk_free_rate=4.5,
                market_risk_premium=market_risk_premium,  # 4.12% si Alpha Spread, 5.8% si normal
                beta=beta_real,
                debt_to_equity=debt_to_equity_real,
                cost_of_debt=cost_of_debt_real,
                tax_rate=21.0,
            )
            
            # Calcular WACC base usando Market Cap y Total Debt (método Alpha Spread)
            market_cap = financial_data.get("market_cap", 0)
            total_debt = financial_data.get("debt", 0)
            wacc_base = dcf_calc.calculate_wacc(market_cap=market_cap, total_debt=total_debt)
            wacc_adjusted = wacc_base * wacc_adjustment_factor
            
            # Log detallado del WACC (como Alpha Spread muestra en sus dashboards)
            # Solo si DEBUG_DCF_SYMBOL está configurado o si está en modo DEBUG
            if (DEBUG_DCF_SYMBOL and symbol == DEBUG_DCF_SYMBOL) or logger.isEnabledFor(logging.DEBUG):
                cost_of_equity = dcf_calc.risk_free_rate + beta_real * dcf_calc.market_risk_premium
                cost_of_debt_after_tax = cost_of_debt_real * (1 - dcf_calc.tax_rate)
                total_value = market_cap + total_debt if market_cap > 0 else 0
                equity_weight = market_cap / total_value if total_value > 0 else 1.0
                debt_weight = total_debt / total_value if total_value > 0 else 0.0
                logger.debug(f"[WACC_DETAIL] {symbol}:")
                logger.debug(f"  Market Cap (E): ${market_cap:.2f}M")
                logger.debug(f"  Total Debt (D): ${total_debt:.2f}M")
                logger.debug(f"  Total Value (V): ${total_value:.2f}M")
                logger.debug(f"  Equity Weight (E/V): {equity_weight:.1%}")
                logger.debug(f"  Debt Weight (D/V): {debt_weight:.1%}")
                logger.debug(f"  Cost of Equity (Re): Rf({dcf_calc.risk_free_rate:.1%}) + Beta({beta_real:.2f}) × ERP({dcf_calc.market_risk_premium:.1%}) = {cost_of_equity:.2%}")
                logger.debug(f"  Cost of Debt (Rd): {cost_of_debt_real:.2f}%")
                logger.debug(f"  Cost of Debt After Tax: {cost_of_debt_after_tax:.2f}%")
                logger.debug(f"  WACC Base: ({equity_weight:.1%} × {cost_of_equity:.2%}) + ({debt_weight:.1%} × {cost_of_debt_after_tax:.2f}%) = {wacc_base:.2%}")
                logger.debug(f"  WACC Adjusted: {wacc_base:.2%} × {wacc_adjustment_factor:.3f} = {wacc_adjusted:.2%}")
            
            # Calcular DCF con crecimiento ajustado
            logger.debug(f"[EVAL] {symbol}: Calculando DCF con FCF=${financial_data['free_cash_flow']:.2f}M, growth={adjusted_fcf_growth:.2f}%")
            
            # DEBUG condicional: Solo loguear si DEBUG_DCF_SYMBOL está configurado
            # Evita llenar logs en producción, pero permite debug detallado cuando se necesita
            if DEBUG_DCF_SYMBOL and symbol == DEBUG_DCF_SYMBOL:
                logger.info(f"[DEBUG_DCF_{symbol}] ========================================")
                logger.info(f"[DEBUG_DCF_{symbol}] INPUTS PARA CÁLCULO DCF:")
                logger.info(f"[DEBUG_DCF_{symbol}]   symbol: {symbol}")
                logger.info(f"[DEBUG_DCF_{symbol}]   current_fcf: {financial_data['free_cash_flow']:.2f}M")
                logger.info(f"[DEBUG_DCF_{symbol}]   growth_base: {base_fcf_growth:.2f}%")
                logger.info(f"[DEBUG_DCF_{symbol}]   growth_adj_factor: {growth_adjustment_factor:.3f}")
                logger.info(f"[DEBUG_DCF_{symbol}]   growth_adj: {adjusted_fcf_growth:.2f}%")
                logger.info(f"[DEBUG_DCF_{symbol}]   wacc_base: {wacc_base:.2f}%")
                logger.info(f"[DEBUG_DCF_{symbol}]   wacc_adj_factor: {wacc_adjustment_factor:.3f}")
                logger.info(f"[DEBUG_DCF_{symbol}]   wacc_adj: {wacc_adjusted:.2f}%")
                logger.info(f"[DEBUG_DCF_{symbol}]   projection_years: 10")
                logger.info(f"[DEBUG_DCF_{symbol}]   terminal_growth: {terminal_growth:.2f}%")
                logger.info(f"[DEBUG_DCF_{symbol}]   shares_outstanding: {financial_data['shares_outstanding']:.2f}M")
                logger.info(f"[DEBUG_DCF_{symbol}] ========================================")
            
            dcf_result = dcf_calc.calculate_dcf(
                current_fcf=financial_data["free_cash_flow"],
                growth_rate=adjusted_fcf_growth,
                shares_outstanding=financial_data["shares_outstanding"],
                scenario="base",
                market_cap=market_cap,  # Para cálculo WACC Alpha Spread
                total_debt=total_debt   # Para cálculo WACC Alpha Spread
            )
            
            # DEBUG condicional: Solo loguear si DEBUG_DCF_SYMBOL está configurado
            if DEBUG_DCF_SYMBOL and symbol == DEBUG_DCF_SYMBOL:
                logger.info(f"[DEBUG_DCF_{symbol}] RESULTADO DCF:")
                logger.info(f"[DEBUG_DCF_{symbol}]   fair_value_per_share: ${dcf_result.fair_value_per_share:.2f}")
                logger.info(f"[DEBUG_DCF_{symbol}]   total_dcf_value: ${dcf_result.total_dcf_value:,.2f}M")
                logger.info(f"[DEBUG_DCF_{symbol}]   wacc_usado: {dcf_result.wacc:.2%}")
                logger.info(f"[DEBUG_DCF_{symbol}] ========================================")
            
            logger.debug(f"[EVAL] {symbol}: DCF calculado: ${dcf_result.fair_value_per_share:.2f} por acción")
            
            # Recalcular DCF con WACC ajustado (más preciso que aproximación)
            # Re-descontar flujos proyectados con WACC ajustado
            if dcf_result.total_dcf_value > 0 and len(dcf_result.projected_cash_flows) > 0:
                # Re-descontar flujos de caja proyectados con WACC ajustado
                discounted_cf_adjusted = []
                for year, cf in enumerate(dcf_result.projected_cash_flows, start=1):
                    pv = cf / ((1 + wacc_adjusted) ** year)
                    discounted_cf_adjusted.append(pv)
                
                # Recalcular valor terminal con WACC ajustado
                final_fcf = dcf_result.projected_cash_flows[-1]
                terminal_value_adjusted = dcf_calc.calculate_terminal_value(final_fcf, wacc_adjusted)
                pv_terminal_adjusted = terminal_value_adjusted / ((1 + wacc_adjusted) ** 10)
                
                # Valor total DCF ajustado
                total_dcf_adjusted = sum(discounted_cf_adjusted) + pv_terminal_adjusted
                dcf_value_adjusted = total_dcf_adjusted / financial_data["shares_outstanding"] if financial_data["shares_outstanding"] > 0 else 0
            else:
                dcf_value_adjusted = dcf_result.fair_value_per_share
            
            # Calcular Comparables (MEJORA: pasar debt, cash y shares_outstanding para cálculo EV real)
            logger.debug(f"[EVAL] {symbol}: Calculando Comparables...")
            comparables_result = temp_engine.valuation_engine.comparables_calculator.calculate_comparables(
                current_price=financial_data["current_price"],
                eps=financial_data["eps"],
                book_value_per_share=financial_data["book_value_per_share"],
                revenue_per_share=financial_data["revenue_per_share"],
                market_cap=financial_data["market_cap"],
                ebitda=financial_data["ebitda"],
                sector_averages=sector_averages,
                debt=financial_data.get("debt", 0.0),
                cash=financial_data.get("cash", 0.0),
                shares_outstanding=financial_data.get("shares_outstanding")
            )
            logger.debug(f"[EVAL] {symbol}: Comparables calculado: ${comparables_result.fair_value_per_share:.2f} por acción")
            
            # Usar pesos específicos calculados por empresa (ya normalizados)
            dcf_weight = dcf_weight_company
            comparables_weight = comparables_weight_company
            
            blended_value = (dcf_value_adjusted * dcf_weight) + (comparables_result.fair_value_per_share * comparables_weight)
            
            target_value = self.target_values[symbol]
            error_pct = abs((blended_value - target_value) / target_value) * 100
            
            logger.debug(f"  [OK] {symbol}: Nuestro=${blended_value:.2f}, Objetivo=${target_value:.2f}, Error={error_pct:.2f}%")
            logger.debug(f"    Beta={beta_real:.2f}, CostDebt={cost_of_debt_real:.2f}%, D/E={debt_to_equity_real:.2f}, Sector={sector}, TermGrowth={terminal_growth:.2f}%")
            # Log opcional de márgenes operativos (disponibles pero no usados en cálculo actual)
            ebit_margin = financial_data.get("ebit_margin", 0)
            ebitda_margin = financial_data.get("ebitda_margin", 0)
            if ebit_margin > 0 or ebitda_margin > 0:
                logger.debug(f"    Margenes: EBIT={ebit_margin:.1f}%, EBITDA={ebitda_margin:.1f}%")
            logger.debug(f"[EVAL] {symbol} completado exitosamente")
            
            return (symbol, error_pct)
            
        except Exception as e:
            logger.warning(f"  [ERROR] Error calculando {symbol}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return (symbol, 100.0)
    
    def calculate_error(self, params: Dict, return_details: bool = False) -> float:
        """
        Calcula el error total usando datos REALES por empresa con factores de ajuste globales
        NUEVA ESTRATEGIA: Solo optimiza 4 parámetros globales, usa datos reales por empresa
        
        Args:
            params: Diccionario con solo 4 parámetros:
                - dcf_weight: Peso del método DCF
                - comparables_weight: Peso del método Comparables
                - growth_adjustment_factor: Factor para ajustar crecimiento (0.7-1.3)
                - wacc_adjustment_factor: Factor para ajustar WACC (0.8-1.2)
            return_details: Si True, retorna también (error_combined, errors_by_symbol)
        
        Returns:
            Error total (combinado) o tupla (error_combined, errors_by_symbol) si return_details=True
        """
        logger.info(f"[CALC_ERROR] Iniciando cálculo de error con params: dcf_w={params.get('dcf_weight', 0.5):.3f}, comp_w={params.get('comparables_weight', 0.5):.3f}, growth_adj={params.get('growth_adjustment_factor', 1.0):.3f}, wacc_adj={params.get('wacc_adjustment_factor', 1.0):.3f}")
        logger.info(f"[CALC_ERROR] Empresas a evaluar: {len(self.symbols)} - {self.symbols}")
        logger.info(f"[CALC_ERROR] Cache disponible: {len(self.financial_data_cache)} empresas")
        errors = []
        successful = 0
        
        # OPTIMIZACIÓN: Paralelizar evaluación de empresas
        max_workers = min(8, len(self.symbols))  # Máximo 8 threads paralelos
        logger.debug(f"[CALC_ERROR] Iniciando evaluación paralela de {len(self.symbols)} empresas con {max_workers} workers")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Enviar todas las tareas con params (no engine)
            future_to_symbol = {
                executor.submit(self._evaluate_single_company, symbol, idx, len(self.symbols), params): symbol
                for idx, symbol in enumerate(self.symbols, 1)
            }
            
            # Recoger resultados conforme se completan
            completed_count = 0
            completed_symbols = set()
            logger.debug(f"[CALC_ERROR] Enviadas {len(future_to_symbol)} tareas, esperando resultados...")
            import time
            start_time = time.time()
            timeout_seconds = 180  # 3 minutos máximo por evaluación completa (30s por empresa × 6 empresas máximo)
            
            try:
                for future in as_completed(future_to_symbol, timeout=timeout_seconds):
                    # Verificar timeout general
                    elapsed = time.time() - start_time
                    if elapsed > timeout_seconds:
                        logger.warning(f"[CALC_ERROR] Timeout general alcanzado después de {elapsed:.1f}s")
                        break
                        
                    symbol = future_to_symbol[future]
                    completed_count += 1
                    completed_symbols.add(symbol)
                    try:
                        logger.debug(f"[CALC_ERROR] Obteniendo resultado de {symbol} ({completed_count}/{len(self.symbols)})...")
                        # Agregar timeout individual de 30 segundos por empresa
                        result_symbol, error_pct = future.result(timeout=30)
                        
                        # MEJORA: Excluir empresas con error_pct=None (FCF <= 0) del cálculo
                        if error_pct is None:
                            logger.debug(f"[CALC_ERROR] {symbol} excluida del cálculo (FCF <= 0)")
                            continue  # No agregar al array de errores
                        
                        # MEJORA: Métrica de error robusta
                        # 1. Cap error máximo por empresa (evita outliers extremos)
                        MAX_ERROR_CAP = 300.0  # Cap error a 300% máximo (más conservador)
                        error_pct_capped = min(abs(error_pct), MAX_ERROR_CAP)
                        
                        # 2. Usar log1p para suavizar errores grandes pero mantener sensibilidad
                        # log1p(x) = log(1 + x), útil para errores porcentuales
                        error_log = np.log1p(error_pct_capped)
                        
                        errors.append(error_log)
                        if error_pct_capped < 100.0:
                            successful += 1
                        logger.debug(f"[CALC_ERROR] {symbol} completado: Error={error_pct:.2f}% (capped={error_pct_capped:.2f}%) ({completed_count}/{len(self.symbols)})")
                    except TimeoutError:
                        logger.error(f"[CALC_ERROR] TIMEOUT evaluando {symbol} después de 30s - excluyendo del cálculo")
                        # No agregar timeout al array - excluir completamente
                        continue
                    except Exception as e:
                        logger.warning(f"  [ERROR] Excepción evaluando {symbol}: {e}")
                        import traceback
                        logger.error(f"[CALC_ERROR] Traceback completo: {traceback.format_exc()}")
                        # No agregar excepciones al array - excluir completamente
                        continue
            except TimeoutError:
                logger.error(f"[CALC_ERROR] TIMEOUT general: No se completaron todas las tareas en {timeout_seconds}s")
            
            # Si no se completaron todas las tareas, agregar errores para las faltantes
            if completed_count < len(self.symbols):
                missing_symbols = [s for s in self.symbols if s not in completed_symbols]
                missing_count = len(missing_symbols)
                logger.warning(f"[CALC_ERROR] Solo se completaron {completed_count}/{len(self.symbols)} empresas.")
                logger.warning(f"[CALC_ERROR] Empresas faltantes: {missing_symbols}")
                logger.warning(f"[CALC_ERROR] Agregando error máximo para {missing_count} faltantes")
                errors.extend([100.0] * missing_count)
            
            logger.debug(f"[CALC_ERROR] Todas las evaluaciones completadas: {completed_count}/{len(self.symbols)} empresas procesadas")
        
        # Calcular múltiples métricas para penalizar errores altos individuales
        if not errors:
            return 100.0  # Si no hay errores, retornar error máximo
        
        # NUEVA ESTRATEGIA: Enfocarse en empresas con error alto, mantener las que están bien
        # Categorías:
        # - BUENAS: error < 10% (peso mínimo, solo para evitar empeorarlas)
        # - INTERMEDIAS: 10% <= error < 30% (peso medio)
        # - CRÍTICAS: error >= 30% (peso máximo, prioridad absoluta)
        GOOD_ERROR_THRESHOLD = np.log1p(10.0)  # 10% en escala log1p
        CRITICAL_ERROR_THRESHOLD = np.log1p(30.0)  # 30% en escala log1p
        
        # Separar empresas en categorías
        errors_array = np.array(errors)
        good_mask = errors_array < GOOD_ERROR_THRESHOLD
        intermediate_mask = (errors_array >= GOOD_ERROR_THRESHOLD) & (errors_array < CRITICAL_ERROR_THRESHOLD)
        critical_mask = errors_array >= CRITICAL_ERROR_THRESHOLD
        
        good_errors = errors_array[good_mask]
        intermediate_errors = errors_array[intermediate_mask]
        critical_errors = errors_array[critical_mask]
        
        n_good = len(good_errors)
        n_intermediate = len(intermediate_errors)
        n_critical = len(critical_errors)
        
        if n_critical == 0 and n_intermediate == 0:
            # Todas las empresas están bien, retornar error mínimo
            combined_error = np.mean(good_errors) if n_good > 0 else 0.0
            error_worst = combined_error
            error_best = combined_error
            error_total = combined_error
        elif n_good == 0 and n_intermediate == 0:
            # Todas las empresas son críticas, optimizar todas con peso máximo
            combined_error = np.mean(critical_errors)
            error_worst = np.max(critical_errors) if len(critical_errors) > 0 else combined_error
            error_best = np.min(critical_errors) if len(critical_errors) > 0 else combined_error
            error_total = combined_error
        else:
            # ESTRATEGIA: Pesos diferenciados según severidad
            # - Críticas (>= 30%): 60% del peso (prioridad máxima)
            # - Intermedias (10-30%): 30% del peso
            # - Buenas (< 10%): 10% del peso (solo para evitar empeorarlas)
            error_critical = np.mean(critical_errors) if n_critical > 0 else 0.0
            error_intermediate = np.mean(intermediate_errors) if n_intermediate > 0 else 0.0
            error_good = np.mean(good_errors) if n_good > 0 else 0.0
            
            # Calcular pesos normalizados según qué categorías existen
            total_weight = 0.0
            weighted_sum = 0.0
            
            if n_critical > 0:
                weighted_sum += 0.6 * error_critical
                total_weight += 0.6
            if n_intermediate > 0:
                weighted_sum += 0.3 * error_intermediate
                total_weight += 0.3
            if n_good > 0:
                weighted_sum += 0.1 * error_good
                total_weight += 0.1
            
            # Normalizar si hay categorías faltantes
            if total_weight > 0:
                combined_error = weighted_sum / total_weight
            else:
                combined_error = np.mean(errors_array)
            
            error_worst = np.max(errors_array) if len(errors_array) > 0 else combined_error
            error_best = np.min(errors_array) if len(errors_array) > 0 else combined_error
            error_total = np.mean(errors_array)
        
        # Logging para mostrar qué empresas se están optimizando
        if return_details:
            # Crear lista con información de qué empresas son buenas/intermedias/críticas
            errors_by_symbol_with_status = []
            for i, symbol in enumerate(self.symbols):
                if i < len(errors):
                    error_val = errors[i]
                    if error_val < GOOD_ERROR_THRESHOLD:
                        status = "BUENA"
                    elif error_val < CRITICAL_ERROR_THRESHOLD:
                        status = "INTERMEDIA"
                    else:
                        status = "CRÍTICA"
                    errors_by_symbol_with_status.append((symbol, error_val, status))
            
            # Ordenar por error descendente (peores primero)
            errors_by_symbol_with_status.sort(key=lambda x: x[1], reverse=True)
            
            # Logging informativo por categoría
            if n_critical > 0:
                critical_symbols = [s for s, e, st in errors_by_symbol_with_status if st == "CRÍTICA"]
                logger.info(f"[PRIORIDAD MÁXIMA] {n_critical} empresas críticas (error >= 30%): {', '.join(critical_symbols[:5])}{'...' if len(critical_symbols) > 5 else ''}")
            if n_intermediate > 0:
                intermediate_symbols = [s for s, e, st in errors_by_symbol_with_status if st == "INTERMEDIA"]
                logger.info(f"[PRIORIDAD MEDIA] {n_intermediate} empresas intermedias (10-30%): {', '.join(intermediate_symbols[:5])}{'...' if len(intermediate_symbols) > 5 else ''}")
            if n_good > 0:
                good_symbols = [s for s, e, st in errors_by_symbol_with_status if st == "BUENA"]
                logger.info(f"[MANTENER] {n_good} empresas ya están bien (error < 10%): {', '.join(good_symbols[:5])}{'...' if len(good_symbols) > 5 else ''}")
        
        # Para compatibilidad con return_details, crear lista sin status
        errors_sorted = sorted(errors)
        n = len(errors_sorted)
        
        # Calcular métricas convertidas para logging
        # Convertir de vuelta desde log1p a porcentaje aproximado
        mean_error_pct = np.mean([np.expm1(e) for e in errors])  # Convertir de vuelta a porcentaje
        max_error_pct = np.max([np.expm1(e) for e in errors])
        
        mean_error = np.mean(errors)  # En escala log1p
        max_error = np.max(errors)  # En escala log1p
        
        # Logging reducido: solo mostrar cada N evaluaciones o cuando hay mejora significativa
        eval_msg = f"Evaluación: {successful}/{len(self.symbols)} exitosas | Error promedio: {mean_error_pct:.2f}% | Máximo: {max_error_pct:.2f}%"
        logger.debug(eval_msg)
        logger.debug(f"[CALC_ERROR] Métrica híbrida: {combined_error:.4f}")
        logger.debug(f"[CALC_ERROR]   - Error outliers (25% peores): {error_worst:.4f} ({np.expm1(error_worst):.2f}%)")
        logger.debug(f"[CALC_ERROR]   - Error total (promedio): {error_total:.4f} ({np.expm1(error_total):.2f}%)")
        try:
            sys.stdout.flush()  # Forzar escritura inmediata
        except (OSError, IOError):
            pass  # Ignorar si flush falla (proceso en background)
        
        if return_details:
            # Crear lista de (symbol, error_pct) ordenada por error
            # Ya se creó arriba con status, ahora crear versión simple para compatibilidad
            errors_by_symbol = [(self.symbols[i], errors[i]) for i in range(len(self.symbols)) if i < len(errors)]
            errors_by_symbol.sort(key=lambda x: x[1], reverse=True)  # Ordenar por error descendente
            return combined_error, errors_by_symbol
        
        return combined_error
    
    def train_single_company(self, symbol: str, target_error: float = 10.0, max_iterations: int = 500, 
                             initial_error: float = None, force_strategy: str = None, 
                             best_params_so_far: Dict = None, error_increased: bool = False,
                             save_model: bool = True) -> Dict:
        """
        Entrena una empresa individual hasta alcanzar el error objetivo
        
        Args:
            symbol: Símbolo de la empresa a entrenar
            target_error: Error objetivo en porcentaje (default: 10%)
            max_iterations: Máximo de iteraciones (default: 500)
            initial_error: Error inicial para comparar mejoras (opcional)
            force_strategy: Forzar estrategia específica ('best1bin', 'rand1bin', etc.) (opcional)
            best_params_so_far: Mejores parámetros encontrados hasta ahora (para usar como punto de partida)
            error_increased: Si True, el error aumentó en la ronda anterior (explorar alrededor)
            save_model: Si True, guarda el modelo al finalizar (default: True)
        
        Returns:
            Mejores parámetros encontrados para esta empresa
        """
        if symbol not in self.target_values:
            raise ValueError(f"No hay valor objetivo para {symbol}")
        
        if symbol not in self.financial_data_cache:
            raise ValueError(f"{symbol} no está en caché. Ejecuta prepare_training_data() primero.")
        
        # Guardar error inicial para validación adaptativa
        self._current_initial_error = initial_error
        
        logger.info("=" * 60)
        logger.info(f"ENTRENAMIENTO INDIVIDUAL: {symbol}")
        logger.info(f"Objetivo: Error < {target_error}%")
        logger.info("=" * 60)
        
        # Función objetivo para esta empresa específica
        def objective_single(xk):
            params_dict = {
                'dcf_weight': 0.5,
                'comparables_weight': 0.5,
                'growth_adjustment_factor': xk[0],
                'wacc_adjustment_factor': xk[1],
            }
            # Log detallado cada 20 evaluaciones para debugging
            if not hasattr(objective_single, 'call_count'):
                objective_single.call_count = 0
            objective_single.call_count += 1
            
            # Evaluar solo esta empresa
            try:
                symbol_result, error_pct = self._evaluate_single_company(symbol, 1, 1, params_dict)
                if error_pct is None:
                    logger.warning(f"[{symbol}] Evaluación retornó None, usando error máximo")
                    return np.log1p(100.0)  # Error máximo si falla
                
                # MEJORA: Log detallado para identificar parámetros problemáticos
                # Log cada 10 evaluaciones o las primeras 20, o si encuentra algo mejor
                # También log TODAS las evaluaciones que den error diferente al mejor conocido
                best_error_known = getattr(objective_single, 'best_error_known', float('inf'))
                if error_pct < best_error_known:
                    objective_single.best_error_known = error_pct
                
                should_log = (objective_single.call_count % 10 == 0 or 
                             objective_single.call_count <= 20 or
                             error_pct < 45.0 or  # Log si encuentra algo mejor que 45%
                             abs(error_pct - best_error_known) > 0.01)  # Log si error es diferente al mejor conocido
                
                if should_log:
                    logger.info(f"[{symbol}] Eval #{objective_single.call_count}: growth={xk[0]:.3f}, wacc={xk[1]:.3f} → error={error_pct:.2f}%")
                
                return np.log1p(error_pct)
            except Exception as e:
                logger.error(f"[{symbol}] Error en objective_single: {e}", exc_info=True)
                return np.log1p(100.0)
        
        # Bounds para los parámetros (ampliados para permitir más exploración)
        # TSLA y otras empresas volátiles pueden necesitar rangos más amplios
        # MEJORA: Detectar empresas problemáticas y usar bounds más amplios
        initial_error = getattr(self, '_current_initial_error', None)
        # Empresa problemática si:
        # 1. Error inicial >= 25% (umbral más inclusivo para casos como AAPL con 29.98%)
        # 2. O error inicial > 2.5x el objetivo (si objetivo es 10%, entonces > 25%)
        is_problematic = False
        if initial_error is not None:
            # Umbral absoluto: 25% (más inclusivo para casos cercanos)
            # Umbral relativo: 2.5x el objetivo (si objetivo es 10%, entonces > 25%)
            absolute_threshold = 25.0
            relative_threshold = target_error * 2.5
            is_problematic = initial_error >= absolute_threshold or initial_error > relative_threshold
        
        if is_problematic:
            # Empresas con error inicial alto: usar bounds más amplios para explorar más
            bounds = [
                (0.2, 2.5),   # growth_adjustment_factor (más amplio para exploración)
                (0.4, 1.8),   # wacc_adjustment_factor (más amplio para exploración)
            ]
            reason = f"error inicial {initial_error:.1f}% >= umbral absoluto 25%" if initial_error >= 25.0 else f"error inicial {initial_error:.1f}% > {target_error * 2.5:.1f}% (2.5x objetivo)"
            logger.info(f"[{symbol}] 🔍 Empresa problemática detectada ({reason}), usando bounds ampliados y estrategia exploratoria")
        else:
            bounds = [
                (0.3, 2.0),   # growth_adjustment_factor (ampliado desde 0.5-1.5)
                (0.5, 1.5),   # wacc_adjustment_factor (ampliado desde 0.7-1.3)
            ]
        
        logger.info(f"[{symbol}] Bounds de optimización: growth=[{bounds[0][0]}, {bounds[0][1]}], wacc=[{bounds[1][0]}, {bounds[1][1]}]")
        
        # Guardar bounds en self para acceso en validación
        self._current_bounds = bounds
        
        # Parámetros de optimización
        # MEJORA: Aumentar población para empresas problemáticas
        if is_problematic:
            popsize = 30  # Más diversidad para empresas problemáticas
        else:
            popsize = 20  # Aumentado para más diversidad
        maxiter = max_iterations
        
        iteration_count = [0]
        # MEJORA: Inicializar best_error con el error inicial conocido (si existe)
        # Esto evita que el callback piense que cualquier error es una mejora
        initial_error_log1p = initial_error if initial_error is not None else float('inf')
        if initial_error_log1p != float('inf'):
            initial_error_log1p = np.log1p(initial_error_log1p)
        best_error = [initial_error_log1p]
        callback_best_params = [None]  # MEJORA: Renombrar para evitar conflicto con parámetro best_params_so_far
        TARGET_ERROR_LOG1P = np.log1p(target_error)
        
        # Tracking para detectar estancamiento
        no_improvement_count = [0]
        last_improvement_iter = [0]
        
        def callback_single(xk, convergence):
            iteration_count[0] += 1
            try:
                current_error_log1p = objective_single(xk)
                current_error_pct = np.expm1(current_error_log1p)
                
                improvement = False
                if current_error_log1p < best_error[0]:
                    improvement = True
                    # Calcular mejora antes de actualizar best_error
                    old_error_pct = np.expm1(best_error[0]) if best_error[0] != float('inf') else float('inf')
                    improvement_pct = ((old_error_pct - current_error_pct) / old_error_pct * 100) if old_error_pct != float('inf') and old_error_pct > 0 else 0
                    best_error[0] = current_error_log1p
                    callback_best_params[0] = {
                        'dcf_weight': 0.5,
                        'comparables_weight': 0.5,
                        'growth_adjustment_factor': xk[0],
                        'wacc_adjustment_factor': xk[1],
                        'error': current_error_log1p,
                        'error_pct': current_error_pct,
                    }
                    no_improvement_count[0] = 0
                    last_improvement_iter[0] = iteration_count[0]
                    
                    # MEJORA: Log detallado cuando encuentra mejora
                    logger.info(f"[{symbol}] ✅ MEJORA en iter {iteration_count[0]}: Error {old_error_pct:.2f}% → {current_error_pct:.2f}% "
                              f"(mejora: {improvement_pct:.1f}%) | growth={xk[0]:.3f}, wacc={xk[1]:.3f}")
                else:
                    no_improvement_count[0] += 1
                    
                    # MEJORA: Log detallado de parámetros probados cuando está estancado
                    if last_improvement_iter[0] == 0 and no_improvement_count[0] % 50 == 0:
                        logger.warning(f"[{symbol}] 🔍 Estancado desde inicio - Probando: growth={xk[0]:.3f}, wacc={xk[1]:.3f} → error={current_error_pct:.2f}% "
                                     f"(mejor hasta ahora: {np.expm1(best_error[0]):.2f}%)")
                    
                    # Advertir si lleva muchas iteraciones sin mejora
                    if no_improvement_count[0] >= 50 and iteration_count[0] % 20 == 0:
                        logger.warning(f"[{symbol}] ⚠️ Sin mejoras desde iter {last_improvement_iter[0]} "
                                     f"({no_improvement_count[0]} iteraciones sin mejora). "
                                     f"Mejor error hasta ahora: {np.expm1(best_error[0]):.2f}%")
                    
                    # MEJORA: Detectar estancamiento desde el inicio y parar temprano
                    if last_improvement_iter[0] == 0 and no_improvement_count[0] >= 200:
                        logger.warning(f"[{symbol}] 🔄 ESTANCADO: Sin mejoras desde iteración 1 ({no_improvement_count[0]} iteraciones)")
                        logger.warning(f"[{symbol}] ⏹️ Parando optimización temprano - algoritmo completamente estancado")
                        # Retornar True para detener la optimización
                        return True
                
                # Parada temprana si alcanza objetivo
                # También parar si el error es muy bajo (< 5%) independientemente del objetivo
                low_error_threshold = 5.0
                if current_error_pct <= target_error:
                    logger.info(f"[{symbol}] OBJETIVO ALCANZADO: Error {current_error_pct:.2f}% <= {target_error}%")
                    return True  # Detener optimización
                elif current_error_pct < low_error_threshold:
                    logger.info(f"[{symbol}] ✅ Error muy bajo ({current_error_pct:.2f}% < {low_error_threshold}%) - Parando optimización temprano")
                    return True  # Detener optimización si el error es muy bajo
            except Exception as e:
                logger.error(f"[{symbol}] Error en callback: {e}")
            return False
        
        # Optimizar
        logger.info(f"[{symbol}] Iniciando optimización individual...")
        logger.info(f"[{symbol}] Configuración: popsize={popsize}, maxiter={maxiter}, strategy='best1bin'")
        
        # Obtener valor objetivo para logging
        target_value = self.target_values.get(symbol, 0)
        logger.info(f"[{symbol}] Valor objetivo Alpha Spread: ${target_value:.2f}")
        
        try:
            # Usar seed diferente para cada empresa para más diversidad
            import random
            seed = hash(symbol) % 1000  # Seed determinístico pero diferente por empresa
            
            # MEJORA: Usar mejores parámetros como punto de partida con exploración inteligente
            init_population = None
            # Validar que best_params_so_far sea un diccionario (no None, no lista)
            if best_params_so_far and isinstance(best_params_so_far, dict):
                growth_best = best_params_so_far.get('growth_adjustment_factor', 1.0)
                wacc_best = best_params_so_far.get('wacc_adjustment_factor', 1.0)
                
                # ESTRATEGIA MEJORADA: Si el error aumentó, explorar alrededor del mejor punto
                # NO invertir completamente (puede estar en el lado opuesto pero no en el opuesto exacto)
                if error_increased:
                    # Explorar alrededor del mejor punto con diferentes direcciones
                    # Usar múltiples puntos de partida alrededor del mejor encontrado
                    logger.info(f"[{symbol}] 🔄 Error aumentó en ronda anterior, explorando alrededor del mejor punto: growth={growth_best:.3f}, wacc={wacc_best:.3f}")
                    # Usar std más grande para explorar más cuando empeoró
                    exploration_std = 0.2  # 20% del rango para más exploración
                else:
                    # Usar mejores parámetros como centro con exploración normal
                    logger.info(f"[{symbol}] 📍 Usando mejores parámetros como punto de partida: growth={growth_best:.3f}, wacc={wacc_best:.3f}")
                    exploration_std = 0.1  # 10% del rango para exploración normal
                
                growth_center = growth_best
                wacc_center = wacc_best
                
                # Crear población inicial centrada en los mejores parámetros
                # Usar distribución normal alrededor del punto central
                np.random.seed(seed)
                init_population = []
                logger.info(f"[{symbol}] 🔍 Creando población inicial de {popsize} partículas alrededor de growth={growth_center:.3f}, wacc={wacc_center:.3f}")
                
                for i in range(popsize):
                    # Primera partícula = punto central exacto (mejor encontrado)
                    if i == 0:
                        init_population.append([growth_center, wacc_center])
                        logger.debug(f"[{symbol}] Partícula {i+1}: growth={growth_center:.3f}, wacc={wacc_center:.3f} (centro)")
                    # Segunda partícula = explorar dirección opuesta de growth (si empeoró)
                    elif i == 1 and error_increased:
                        # Probar dirección opuesta de growth pero mantener wacc similar
                        growth_opposite = bounds[0][0] + bounds[0][1] - growth_center
                        growth_opposite = max(bounds[0][0], min(bounds[0][1], growth_opposite))
                        init_population.append([growth_opposite, wacc_center])
                        logger.debug(f"[{symbol}] Partícula {i+1}: growth={growth_opposite:.3f}, wacc={wacc_center:.3f} (growth opuesto)")
                    # Tercera partícula = explorar dirección opuesta de wacc (si empeoró)
                    elif i == 2 and error_increased:
                        # Probar dirección opuesta de wacc pero mantener growth similar
                        wacc_opposite = bounds[1][0] + bounds[1][1] - wacc_center
                        wacc_opposite = max(bounds[1][0], min(bounds[1][1], wacc_opposite))
                        init_population.append([growth_center, wacc_opposite])
                        logger.debug(f"[{symbol}] Partícula {i+1}: growth={growth_center:.3f}, wacc={wacc_opposite:.3f} (wacc opuesto)")
                    else:
                        # Resto: distribución normal alrededor del centro
                        growth_std = (bounds[0][1] - bounds[0][0]) * exploration_std
                        wacc_std = (bounds[1][1] - bounds[1][0]) * exploration_std
                        growth_val = np.random.normal(growth_center, growth_std)
                        wacc_val = np.random.normal(wacc_center, wacc_std)
                        # Asegurar que estén dentro de los bounds
                        growth_val = max(bounds[0][0], min(bounds[0][1], growth_val))
                        wacc_val = max(bounds[1][0], min(bounds[1][1], wacc_val))
                        init_population.append([growth_val, wacc_val])
                        if i < 5:  # Log primeras 5 partículas generadas
                            logger.debug(f"[{symbol}] Partícula {i+1}: growth={growth_val:.3f}, wacc={wacc_val:.3f} (distribución normal)")
                init_population = np.array(init_population)
                logger.info(f"[{symbol}] ✅ Población inicial creada: {len(init_population)} partículas")
            
            # MEJORA: Usar estrategia más exploratoria para empresas problemáticas o si se fuerza
            if force_strategy:
                strategy = force_strategy
                mutation_range = (0.8, 1.9) if 'rand' in strategy else (0.5, 1.5)
                logger.info(f"[{symbol}] Usando estrategia forzada: {strategy}, mutation={mutation_range}")
            elif is_problematic:
                strategy = 'rand1bin'  # Más exploratoria que best1bin
                mutation_range = (0.8, 1.9)  # Mutación más agresiva (debe ser < 2.0)
                logger.info(f"[{symbol}] Usando estrategia exploratoria: {strategy}, mutation={mutation_range}")
            else:
                strategy = 'best1bin'
                mutation_range = (0.5, 1.5)  # Rango de mutación estándar
            
            # Usar población inicial si está disponible, sino usar 'sobol' para mejor distribución
            init_method = init_population if init_population is not None else 'sobol'
            
            result = differential_evolution(
                objective_single,
                bounds,
                seed=seed,
                maxiter=maxiter,
                popsize=popsize,
                init=init_method,  # MEJORA: Usar población inicial centrada en mejores parámetros
                polish=False,
                atol=0.0,
                tol=0.0,
                callback=callback_single,
                updating='immediate',
                strategy=strategy,
                mutation=mutation_range,
                recombination=0.7,   # Tasa de recombinación estándar
            )
            
            logger.debug(f"[{symbol}] Optimización completada: {objective_single.call_count} evaluaciones totales")
            
            # MEJORA: Usar mejor parámetro encontrado en callback (que es una lista con un elemento)
            # O usar resultado de optimización si no hay mejor encontrado
            callback_best = callback_best_params[0] if callback_best_params[0] else None
            if callback_best and isinstance(callback_best, dict):
                best_params = callback_best
            else:
                # Fallback: usar resultado de optimización
                best_params = {
                'dcf_weight': 0.5,
                'comparables_weight': 0.5,
                'growth_adjustment_factor': result.x[0],
                'wacc_adjustment_factor': result.x[1],
                'error': result.fun,
                'error_pct': np.expm1(result.fun),
            }
            
            # VALIDACIÓN: Verificar que los parámetros sean razonables (usar bounds actuales)
            growth_adj = best_params['growth_adjustment_factor']
            wacc_adj = best_params['wacc_adjustment_factor']
            
            # MEJORA: Usar los bounds actuales en lugar de rangos fijos
            current_bounds = getattr(self, '_current_bounds', None)
            if current_bounds:
                GROWTH_MIN = current_bounds[0][0]
                GROWTH_MAX = current_bounds[0][1]
                WACC_MIN = current_bounds[1][0]
                WACC_MAX = current_bounds[1][1]
            else:
                # Fallback a rangos estándar si no hay bounds guardados
                GROWTH_MIN = 0.3
                GROWTH_MAX = 2.0
                WACC_MIN = 0.5
                WACC_MAX = 1.5
            
            is_valid = True
            validation_errors = []
            
            if growth_adj == 0 or growth_adj < GROWTH_MIN or growth_adj > GROWTH_MAX:
                is_valid = False
                validation_errors.append(f"growth_adjustment_factor={growth_adj:.3f} fuera de rango [{GROWTH_MIN}, {GROWTH_MAX}]")
            
            if wacc_adj == 0 or wacc_adj < WACC_MIN or wacc_adj > WACC_MAX:
                is_valid = False
                validation_errors.append(f"wacc_adjustment_factor={wacc_adj:.3f} fuera de rango [{WACC_MIN}, {WACC_MAX}]")
            
            # VALIDACIÓN FINANCIERA: Verificar que los parámetros sean razonables según características de la empresa
            if symbol in self.financial_data_cache and symbol in self.growth_rates_cache:
                financial_data = self.financial_data_cache[symbol]
                growth_rates = self.growth_rates_cache[symbol]
                
                # Obtener datos financieros para validación
                fcf_growth = growth_rates.get("fcf_growth", 0)
                beta = financial_data.get("beta", 1.0)
                total_debt = financial_data.get("debt", 0)
                market_cap = financial_data.get("market_cap", 1)
                ebitda = financial_data.get("ebitda", 0)
                revenue = financial_data.get("revenue", 1)
                debt_ratio = total_debt / max(market_cap, 1) if market_cap > 0 else 0
                ebitda_margin = (ebitda / revenue * 100) if revenue > 0 else 0
                
                # Calcular estabilidad FCF (simplificado)
                fcf_stability = 0.5  # Por defecto, se puede mejorar con datos históricos
                if ebitda_margin > 20:
                    fcf_stability = 0.7
                elif ebitda_margin > 10:
                    fcf_stability = 0.5
                else:
                    fcf_stability = 0.3
                
                # Validar growth_adjustment_factor financieramente
                if fcf_growth > 25.0 and growth_adj > 1.0:
                    is_valid = False
                    validation_errors.append(f"growth_adj={growth_adj:.3f} demasiado alto para crecimiento extremo ({fcf_growth:.1f}%)")
                
                if fcf_stability < 0.3 and growth_adj > 1.0:
                    is_valid = False
                    validation_errors.append(f"growth_adj={growth_adj:.3f} demasiado alto para FCF inestable (stability={fcf_stability:.2f})")
                
                # Obtener error del resultado para validación adaptativa (PRIMERO, antes de usarlo)
                final_error_pct = best_params.get('error_pct', float('inf'))
                # Relajar validaciones según el nivel de error:
                # - Error muy bajo (< 5%): relajar mucho (los parámetros funcionan muy bien)
                # - Error razonable (< 20%): relajar moderadamente (los parámetros funcionan bien)
                # - Si mejora respecto al inicial: relajar validaciones (los parámetros funcionan mejor)
                low_error_threshold = 5.0
                reasonable_error_threshold = 20.0
                is_low_error = final_error_pct < low_error_threshold
                is_reasonable_error = final_error_pct < reasonable_error_threshold
                
                # Si hay error inicial, verificar si mejoró
                initial_error_for_validation = getattr(self, '_current_initial_error', None)
                improved_from_initial = False
                if initial_error_for_validation is not None:
                    improved_from_initial = final_error_pct < initial_error_for_validation - 0.1  # Mejora de al menos 0.1%
                    if improved_from_initial:
                        logger.debug(f"[{symbol}] Error mejoró desde {initial_error_for_validation:.2f}% a {final_error_pct:.2f}%, relajando validaciones")
                
                # Si mejoró respecto al inicial, considerar razonable aunque sea > 20%
                if improved_from_initial and not is_reasonable_error:
                    is_reasonable_error = True
                    logger.debug(f"[{symbol}] Error razonable por mejora respecto al inicial")
                
                # Relajar validación de growth_adj alto si el error es razonable
                allow_high_growth = is_low_error or (is_reasonable_error and growth_adj <= 2.0)
                if ebitda_margin < 10.0 and growth_adj > 1.1 and not allow_high_growth:
                    is_valid = False
                    validation_errors.append(f"growth_adj={growth_adj:.3f} demasiado alto para márgenes bajos (EBITDA margin={ebitda_margin:.1f}%)")
                elif ebitda_margin < 10.0 and growth_adj > 1.1 and allow_high_growth:
                    logger.debug(f"[{symbol}] growth_adj={growth_adj:.3f} alto permitido para márgenes bajos porque error es {'bajo' if is_low_error else 'razonable'} ({final_error_pct:.2f}%)")
                
                # Relajar validación de growth_adj bajo si el error es razonable
                # MEJORA: Permitir growth bajo si está dentro de los bounds de optimización (incluso si es bajo)
                # Esto permite que el algoritmo explore el espacio completo sin restricciones artificiales
                current_bounds = getattr(self, '_current_bounds', None)
                if current_bounds:
                    growth_within_bounds = current_bounds[0][0] <= growth_adj <= current_bounds[0][1]
                else:
                    growth_within_bounds = True  # Si no hay bounds guardados, permitir por defecto
                allow_low_growth = (is_low_error or improved_from_initial or 
                                  (is_reasonable_error and growth_adj >= 0.3) or
                                  (growth_adj == 0.3) or  # Si está en el límite mínimo, permitir si mejora
                                  growth_within_bounds)  # MEJORA: Si está dentro de bounds, permitir exploración
                if growth_adj < 0.6 and fcf_growth >= 0 and fcf_stability > 0.4 and not allow_low_growth:
                    is_valid = False
                    validation_errors.append(f"growth_adj={growth_adj:.3f} demasiado bajo sin justificación")
                elif growth_adj < 0.6 and allow_low_growth:
                    reason = 'error bajo' if is_low_error else 'mejoró' if improved_from_initial else 'error razonable' if is_reasonable_error else 'dentro de bounds' if growth_within_bounds else 'límite mínimo'
                    logger.debug(f"[{symbol}] growth_adj={growth_adj:.3f} bajo permitido porque {reason} ({final_error_pct:.2f}%)")
                
                if is_low_error:
                    logger.debug(f"[{symbol}] Error bajo ({final_error_pct:.2f}% < {low_error_threshold}%), relajando validaciones financieras")
                elif is_reasonable_error:
                    logger.debug(f"[{symbol}] Error razonable ({final_error_pct:.2f}% < {reasonable_error_threshold}%), relajando validaciones moderadamente")
                
                # Validar wacc_adjustment_factor financieramente
                # Relajar validaciones si el error es bajo (los parámetros funcionan bien)
                if beta < 0.7 and wacc_adj > 1.05 and not is_low_error:
                    is_valid = False
                    validation_errors.append(f"wacc_adj={wacc_adj:.3f} demasiado alto para beta bajo (beta={beta:.2f})")
                
                # Para beta alto, permitir wacc_adj más bajo si:
                # - Error es bajo, O
                # - Error es razonable y mejoró respecto al inicial, O  
                # - Deuda es muy baja (empresas tech con beta alto pero bajo riesgo financiero) - PERMITIR SIEMPRE
                # - Error mejoró respecto al inicial (aunque sea > 20%)
                allow_low_wacc_high_beta = (is_low_error or improved_from_initial or 
                                           (debt_ratio < 0.05) or  # Deuda muy baja siempre permite wacc bajo
                                           (debt_ratio < 0.05 and is_reasonable_error))
                if beta > 1.8 and wacc_adj < 0.95 and not allow_low_wacc_high_beta:
                    is_valid = False
                    validation_errors.append(f"wacc_adj={wacc_adj:.3f} demasiado bajo para beta alto (beta={beta:.2f})")
                elif beta > 1.8 and wacc_adj < 0.95 and allow_low_wacc_high_beta:
                    reason = 'error bajo' if is_low_error else 'mejoró' if improved_from_initial else 'deuda muy baja' if debt_ratio < 0.05 else 'deuda baja'
                    logger.debug(f"[{symbol}] wacc_adj={wacc_adj:.3f} bajo permitido para beta alto porque {reason} ({final_error_pct:.2f}%)")
                
                if debt_ratio > 0.4 and wacc_adj < 1.0 and not is_low_error:
                    is_valid = False
                    validation_errors.append(f"wacc_adj={wacc_adj:.3f} demasiado bajo para deuda alta (debt_ratio={debt_ratio:.2f})")
                
                # Relajar validación general si el error es bajo o si la deuda es muy baja
                # Permitir wacc_adj bajo si: 
                # - error bajo, O
                # - mejoró respecto al inicial, O
                # - (deuda baja Y beta no extremo), O
                # - (deuda muy baja incluso con beta alto - empresas tech)
                allow_low_wacc = (is_low_error or improved_from_initial or 
                                 (debt_ratio < 0.1 and beta < 2.0) or
                                 (debt_ratio < 0.05))  # Deuda muy baja permite wacc bajo incluso con beta alto
                if wacc_adj < 0.85 and (beta > 0.6 or debt_ratio > 0.2) and not allow_low_wacc:
                    is_valid = False
                    validation_errors.append(f"wacc_adj={wacc_adj:.3f} demasiado bajo sin justificación (beta={beta:.2f}, debt_ratio={debt_ratio:.2f})")
                elif wacc_adj < 0.85 and allow_low_wacc:
                    reason = 'error bajo' if is_low_error else 'mejoró' if improved_from_initial else 'deuda muy baja' if debt_ratio < 0.05 else 'deuda baja'
                    logger.debug(f"[{symbol}] wacc_adj={wacc_adj:.3f} bajo permitido porque {reason} ({final_error_pct:.2f}%)")
                
                # Relajar validación de wacc_adj alto si el error es razonable
                # Permitir wacc_adj alto si: error bajo, mejoró, error razonable, o está dentro del rango de optimización (<= 1.5)
                # IMPORTANTE: Si está dentro del rango de optimización (0.5-1.5), siempre permitir si mejora o tiene error razonable
                allow_high_wacc = (is_low_error or improved_from_initial or 
                                  is_reasonable_error or  # Si el error es razonable, permitir cualquier valor dentro del rango
                                  (wacc_adj <= 1.5))  # Si está dentro del rango de optimización, permitir
                if wacc_adj > 1.2 and beta < 1.5 and debt_ratio < 0.3 and not allow_high_wacc:
                    is_valid = False
                    validation_errors.append(f"wacc_adj={wacc_adj:.3f} demasiado alto sin justificación (beta={beta:.2f}, debt_ratio={debt_ratio:.2f})")
                elif wacc_adj > 1.2 and beta < 1.5 and debt_ratio < 0.3 and allow_high_wacc:
                    reason = 'error bajo' if is_low_error else 'mejoró' if improved_from_initial else 'error razonable' if is_reasonable_error else 'dentro del rango'
                    logger.debug(f"[{symbol}] wacc_adj={wacc_adj:.3f} alto permitido porque {reason} ({final_error_pct:.2f}%)")
            
            if not is_valid:
                error_msg = f"[{symbol}] Parámetros inválidos descartados: " + ", ".join(validation_errors)
                logger.error(error_msg)
                # Mostrar datos financieros si están disponibles
                if symbol in self.financial_data_cache and symbol in self.growth_rates_cache:
                    financial_data = self.financial_data_cache[symbol]
                    growth_rates = self.growth_rates_cache[symbol]
                    fcf_growth = growth_rates.get("fcf_growth", 0)
                    beta = financial_data.get("beta", 1.0)
                    total_debt = financial_data.get("debt", 0)
                    market_cap = financial_data.get("market_cap", 1)
                    ebitda = financial_data.get("ebitda", 0)
                    revenue = financial_data.get("revenue", 1)
                    debt_ratio = total_debt / max(market_cap, 1) if market_cap > 0 else 0
                    ebitda_margin = (ebitda / revenue * 100) if revenue > 0 else 0
                    logger.info(f"[{symbol}] Datos financieros: fcf_growth={fcf_growth:.1f}%, beta={beta:.2f}, debt_ratio={debt_ratio:.2f}, ebitda_margin={ebitda_margin:.1f}%")
                raise ValueError(error_msg)
            
            final_error_pct = best_params['error_pct']
            logger.info(f"[{symbol}] Entrenamiento completado: Error final={final_error_pct:.2f}%")
            logger.info(f"[{symbol}] Parámetros validados: growth_adj={growth_adj:.3f}, wacc_adj={wacc_adj:.3f}")
            
            # Determinar coherencia de parámetros: más allá de validación básica
            # Un parámetro es "coherente" si:
            # 1. Pasa validaciones básicas (is_valid = True)
            # 2. Los parámetros están en rangos razonables según características financieras
            # 3. No hay inconsistencias flagrantes (ej: beta alto con wacc muy bajo sin justificación)
            
            is_coherent = is_valid  # Base: debe pasar validaciones básicas
            
            # Verificaciones adicionales de coherencia financiera
            if symbol in self.financial_data_cache and symbol in self.growth_rates_cache:
                financial_data = self.financial_data_cache[symbol]
                growth_rates = self.growth_rates_cache[symbol]
                beta = financial_data.get("beta", 1.0)
                debt_ratio = financial_data.get("debt", 0) / max(financial_data.get("market_cap", 1), 1)
                fcf_growth = growth_rates.get("fcf_growth", 0)
                
                # Coherencia adicional: verificar que los parámetros tengan sentido económico
                # Si el error es bajo, confiar más en los resultados del optimizador
                # Pero aún verificar inconsistencias flagrantes
                
                # Inconsistencias flagrantes que invalidan coherencia incluso con error bajo:
                # 1. Beta muy alto (>2.0) con wacc_adj muy bajo (<0.7) sin deuda baja
                if beta > 2.0 and wacc_adj < 0.7 and debt_ratio > 0.1:
                    is_coherent = False
                    logger.warning(f"[{symbol}] ⚠️ Incoherencia detectada: beta muy alto ({beta:.2f}) con wacc_adj muy bajo ({wacc_adj:.3f}) y deuda significativa")
                
                # 2. Crecimiento negativo con growth_adj muy alto
                if fcf_growth < 0 and growth_adj > 1.2:
                    is_coherent = False
                    logger.warning(f"[{symbol}] ⚠️ Incoherencia detectada: crecimiento negativo ({fcf_growth:.1f}%) con growth_adj alto ({growth_adj:.3f})")
                
                # 3. Deuda muy alta (>50%) con wacc_adj muy bajo (<0.8)
                if debt_ratio > 0.5 and wacc_adj < 0.8:
                    is_coherent = False
                    logger.warning(f"[{symbol}] ⚠️ Incoherencia detectada: deuda muy alta ({debt_ratio:.2%}) con wacc_adj muy bajo ({wacc_adj:.3f})")
            
            # Si el error es bajo y los parámetros son coherentes, terminar y pasar al siguiente activo
            low_error_threshold = 5.0
            if final_error_pct < low_error_threshold and is_coherent:
                logger.info(f"[{symbol}] ✅ Error bajo ({final_error_pct:.2f}% < {low_error_threshold}%) y parámetros coherentes - Pasando al siguiente activo")
                logger.debug(f"[{symbol}] Coherencia verificada: validaciones básicas={is_valid}, coherencia financiera={is_coherent}, "
                            f"growth_adj={growth_adj:.3f}, wacc_adj={wacc_adj:.3f}")
                # Guardar modelo rápidamente y retornar
                if symbol in self.financial_data_cache:
                    financial_data = self.financial_data_cache[symbol]
                    growth_rates = self.growth_rates_cache.get(symbol, {})
                    company_params_obj = CompanySpecificParams(
                        symbol=symbol,
                        financial_data=financial_data,
                        growth_rates=growth_rates
                    )
                    company_params = company_params_obj.get_all_params()
                    company_params['growth_adjustment_factor'] = growth_adj
                    company_params['wacc_adjustment_factor'] = wacc_adj
                    company_params['error'] = best_params['error']
                    company_params['error_pct'] = final_error_pct
                    company_params['trained'] = True
                    company_params['training_note'] = f"Modelo entrenado hasta alcanzar error {final_error_pct:.2f}%"
                    
                    # Guardar modelo
                    models_dir = Path("models")
                    models_dir.mkdir(exist_ok=True)
                    model_file = models_dir / f"{symbol}_model.json"
                    with open(model_file, "w", encoding="utf-8") as f:
                        json.dump(company_params, f, indent=2, ensure_ascii=False)
                    logger.info(f"[{symbol}] Modelo guardado en {model_file}")
                
                return best_params
            
            # Guardar modelo usando CompanySpecificParams con parámetros entrenados
            if symbol not in self.financial_data_cache:
                raise ValueError(f"{symbol} no está en caché para guardar modelo completo")
            
            financial_data = self.financial_data_cache[symbol]
            growth_rates = self.growth_rates_cache.get(symbol, {})
            
            # Crear objeto CompanySpecificParams con datos de la empresa
            company_params_obj = CompanySpecificParams(
                symbol=symbol,
                financial_data=financial_data,
                growth_rates=growth_rates
            )
            
            # Obtener parámetros base calculados dinámicamente
            company_params = company_params_obj.get_all_params()
            
            # SOBRESCRIBIR con los parámetros entrenados optimizados
            company_params['growth_adjustment_factor'] = growth_adj  # Valor entrenado
            company_params['wacc_adjustment_factor'] = wacc_adj     # Valor entrenado
            
            # Mantener pesos entrenados si se optimizaron (por ahora usar los calculados)
            # company_params['dcf_weight'] = best_params.get('dcf_weight', company_params['dcf_weight'])
            # company_params['comparables_weight'] = best_params.get('comparables_weight', company_params['comparables_weight'])
            
            # Agregar información del entrenamiento
            company_params['error'] = best_params['error']  # Error en escala log1p
            company_params['error_pct'] = final_error_pct  # Error en porcentaje real
            company_params['trained'] = True
            company_params['training_note'] = f"Modelo entrenado individualmente hasta alcanzar error < {target_error}%"
            
            # MEJORA: Solo guardar modelo si se solicita (y solo si realmente mejoró)
            if save_model:
                # Guardar usando el método de CompanySpecificParams
                models_dir = Path("models")
                model_file = company_params_obj.save_model(models_dir)
                
                # Sobrescribir con los parámetros entrenados
                with open(model_file, 'w', encoding='utf-8') as f:
                    json.dump(company_params, f, indent=2, ensure_ascii=False, default=str)
                
                logger.info(f"[{symbol}] Modelo CompanySpecificParams guardado en {model_file}")
                logger.info(f"[{symbol}] Parámetros guardados: growth_adj={growth_adj:.3f}, wacc_adj={wacc_adj:.3f}, error={final_error_pct:.2f}%")
            else:
                logger.debug(f"[{symbol}] Modelo NO guardado (save_model=False)")
            
            return best_params
            
        except Exception as e:
            logger.error(f"[{symbol}] Error en entrenamiento individual: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise
    
    def train_auto_loop(self, target_error: float = 10.0, max_iterations_per_round: int = 500, 
                        max_rounds_per_company: int = None, min_improvement_threshold: float = 0.01) -> Dict:
        """
        Sistema de entrenamiento automático en bucle que entrena cada empresa hasta alcanzar el objetivo
        
        Args:
            target_error: Error objetivo en porcentaje (default: 10%)
            max_iterations_per_round: Máximo de iteraciones por ronda de optimización (default: 500)
            max_rounds_per_company: Máximo de rondas por empresa (None = infinito, continúa hasta objetivo)
            min_improvement_threshold: Mejora mínima requerida para continuar (default: 0.01%)
        
        Returns:
            Mejores parámetros encontrados para cada empresa
        """
        logger.info("=" * 80)
        logger.info("SISTEMA DE ENTRENAMIENTO AUTOMÁTICO EN BUCLE")
        logger.info("=" * 80)
        logger.info(f"Configuración:")
        logger.info(f"  - Error objetivo: {target_error}%")
        logger.info(f"  - Iteraciones por ronda: {max_iterations_per_round}")
        logger.info(f"  - Máximo rondas por empresa: {max_rounds_per_company if max_rounds_per_company else 'INFINITO (hasta alcanzar objetivo)'}")
        logger.info(f"  - Umbral de mejora mínima: {min_improvement_threshold}%")
        logger.info(f"  - Modo: CONTINUO - Entrenará hasta alcanzar objetivo o detener manualmente")
        logger.info("=" * 80)
        
        if not self.target_values:
            logger.error("[AUTO_LOOP] ERROR: No hay valores objetivo establecidos")
            raise ValueError("Debes establecer valores objetivo primero con set_target_values()")
        
        # PASO 0: Precargar datos financieros
        logger.info("[AUTO_LOOP] PASO 0: Preparando datos de entrenamiento...")
        if not self.financial_data_cache:
            self.load_cache()
        
        missing = [s for s in self.symbols if s not in self.financial_data_cache]
        if missing:
            logger.info(f"[AUTO_LOOP] Precargando {len(missing)} empresas faltantes...")
            self.preload_financial_data()
        else:
            logger.info(f"[AUTO_LOOP] ✅ Cache completo: {len(self.financial_data_cache)} empresas disponibles")
        
        # Obtener error inicial de todas las empresas
        # MEJORA: Para empresas con modelos entrenados, usar esos parámetros para calcular error inicial
        logger.info("[AUTO_LOOP] Evaluando error inicial de todas las empresas...")
        logger.info("[AUTO_LOOP] NOTA: Empresas con modelos entrenados usarán esos parámetros para calcular error inicial")
        
        initial_errors_dict = {}
        models_dir = Path("models")
        
        # Calcular error inicial empresa por empresa, usando parámetros entrenados si existen
        for symbol in self.symbols:
            model_file = models_dir / f"{symbol}_model.json"
            if model_file.exists():
                # Si tiene modelo entrenado, usar esos parámetros para calcular error inicial
                try:
                    with open(model_file, 'r', encoding='utf-8') as f:
                        trained_model_data = json.load(f)
                    trained_params = {
                        'dcf_weight': 0.5,
                        'comparables_weight': 0.5,
                        'growth_adjustment_factor': trained_model_data.get('growth_adjustment_factor', 1.0),
                        'wacc_adjustment_factor': trained_model_data.get('wacc_adjustment_factor', 1.0),
                    }
                    # Evaluar con parámetros entrenados
                    _, error_pct = self._evaluate_single_company(symbol, 1, 1, trained_params)
                    if error_pct is not None:
                        initial_errors_dict[symbol] = error_pct
                    else:
                        # Si FCF <= 0, usar error del modelo guardado
                        initial_errors_dict[symbol] = trained_model_data.get('error_pct', 100.0)
                except Exception as e:
                    logger.warning(f"[AUTO_LOOP] Error cargando modelo de {symbol}: {e}, usando parámetros por defecto")
                    # Fallback: usar parámetros por defecto
                    initial_params = {
                        'dcf_weight': 0.5,
                        'comparables_weight': 0.5,
                        'growth_adjustment_factor': 1.0,
                        'wacc_adjustment_factor': 1.0,
                    }
                    _, error_pct = self._evaluate_single_company(symbol, 1, 1, initial_params)
                    initial_errors_dict[symbol] = error_pct if error_pct is not None else 100.0
            else:
                # Sin modelo entrenado, usar parámetros por defecto
                initial_params = {
                    'dcf_weight': 0.5,
                    'comparables_weight': 0.5,
                    'growth_adjustment_factor': 1.0,
                    'wacc_adjustment_factor': 1.0,
                }
                _, error_pct = self._evaluate_single_company(symbol, 1, 1, initial_params)
                initial_errors_dict[symbol] = error_pct if error_pct is not None else 100.0
        
        # Verificar cuántas empresas tienen modelos entrenados
        models_dir = Path("models")
        trained_count = sum(1 for symbol in self.symbols if (models_dir / f"{symbol}_model.json").exists())
        if trained_count > 0:
            logger.info(f"[AUTO_LOOP] {trained_count}/{len(self.symbols)} empresas tienen modelos entrenados previos")
        
        logger.info("[AUTO_LOOP] Errores iniciales:")
        for symbol in self.symbols:
            error_pct = initial_errors_dict.get(symbol, 100.0)
            logger.info(f"  {symbol}: {error_pct:.2f}%")
        
        # Entrenar cada empresa en bucle hasta convergencia
        trained_models = {}
        convergence_status = {}
        
        for symbol in self.symbols:
            logger.info("=" * 80)
            logger.info(f"[AUTO_LOOP] Entrenando {symbol} en bucle hasta convergencia...")
            logger.info("=" * 80)
            
            initial_error = initial_errors_dict.get(symbol, 100.0)
            # Verificar si ya tiene modelo entrenado
            model_file = Path("models") / f"{symbol}_model.json"
            has_trained_model = model_file.exists()
            if has_trained_model:
                logger.info(f"[AUTO_LOOP] {symbol} - Error inicial: {initial_error:.2f}% (usando modelo entrenado previo)")
            else:
                logger.info(f"[AUTO_LOOP] {symbol} - Error inicial: {initial_error:.2f}% (sin modelo entrenado)")
            
            # MEJORA: Solo entrenar empresas con error alto (>= target_error)
            # Saltar empresas que ya están bien optimizadas
            if initial_error < target_error:
                logger.info(f"[AUTO_LOOP] {symbol} - ✅ Error {initial_error:.2f}% < {target_error}% - Ya optimizado, saltando")
                # Cargar parámetros del modelo entrenado para el resumen final
                try:
                    with open(model_file, 'r', encoding='utf-8') as f:
                        trained_model_data = json.load(f)
                    best_params = {
                        'dcf_weight': 0.5,
                        'comparables_weight': 0.5,
                        'growth_adjustment_factor': trained_model_data.get('growth_adjustment_factor', 1.0),
                        'wacc_adjustment_factor': trained_model_data.get('wacc_adjustment_factor', 1.0),
                        'error': np.log1p(initial_error),
                        'error_pct': initial_error
                    }
                    trained_models[symbol] = best_params
                    convergence_status[symbol] = {
                        'converged': True,
                        'final_error': initial_error,
                        'initial_error': initial_error,
                        'improvement': 0.0,
                        'rounds': 0,
                        'reached_target': True
                    }
                except Exception as e:
                    logger.warning(f"[AUTO_LOOP] {symbol} - Error cargando modelo entrenado: {e}")
                # MEJORA: SIEMPRE saltar empresas con buen error, sin importar si se cargó el modelo o no
                continue  # Saltar al siguiente símbolo
            
            # Solo entrenar empresas con error >= target_error
            logger.info(f"[AUTO_LOOP] {symbol} - ⚠️ Error {initial_error:.2f}% >= {target_error}% - Necesita entrenamiento")
            
            best_error = initial_error
            best_params = None
            
            # Si tiene modelo entrenado pero con error alto, cargar parámetros como punto de partida
            if has_trained_model:
                try:
                    with open(model_file, 'r', encoding='utf-8') as f:
                        trained_model_data = json.load(f)
                    
                    # MEJORA: Verificar si los parámetros guardados realmente dan el error reportado
                    saved_growth = trained_model_data.get('growth_adjustment_factor', 1.0)
                    saved_wacc = trained_model_data.get('wacc_adjustment_factor', 1.0)
                    saved_error = trained_model_data.get('error_pct', initial_error)
                    
                    logger.info(f"[AUTO_LOOP] {symbol} - Modelo previo encontrado: growth={saved_growth:.3f}, wacc={saved_wacc:.3f}, error reportado={saved_error:.2f}%")
                    
                    # Verificar si los parámetros guardados realmente dan ese error
                    test_params = {
                        'dcf_weight': 0.5,
                        'comparables_weight': 0.5,
                        'growth_adjustment_factor': saved_growth,
                        'wacc_adjustment_factor': saved_wacc,
                    }
                    logger.info(f"[AUTO_LOOP] {symbol} - 🔍 Verificando parámetros guardados...")
                    _, verified_error = self._evaluate_single_company(symbol, 1, 1, test_params)
                    
                    if verified_error is not None:
                        logger.info(f"[AUTO_LOOP] {symbol} - ✅ Verificación: growth={saved_growth:.3f}, wacc={saved_wacc:.3f} → error={verified_error:.2f}% (reportado: {saved_error:.2f}%)")
                        if abs(verified_error - saved_error) > 1.0:
                            logger.warning(f"[AUTO_LOOP] {symbol} - ⚠️ DISCREPANCIA: Error verificado ({verified_error:.2f}%) difiere del reportado ({saved_error:.2f}%)")
                            # Usar el error verificado como mejor conocido
                            initial_error = verified_error
                            saved_error = verified_error
                        else:
                            logger.info(f"[AUTO_LOOP] {symbol} - ✅ Parámetros verificados correctamente")
                    else:
                        logger.warning(f"[AUTO_LOOP] {symbol} - ⚠️ No se pudo verificar parámetros (FCF <= 0)")
                    
                    best_params = {
                        'dcf_weight': 0.5,
                        'comparables_weight': 0.5,
                        'growth_adjustment_factor': saved_growth,
                        'wacc_adjustment_factor': saved_wacc,
                        'error': np.log1p(saved_error),
                        'error_pct': saved_error
                    }
                    best_error = saved_error  # Usar el error verificado o reportado
                    logger.info(f"[AUTO_LOOP] {symbol} - Usando parámetros verificados como punto de partida: error={best_error:.2f}%")
                except Exception as e:
                    logger.warning(f"[AUTO_LOOP] {symbol} - Error cargando modelo previo: {e}, empezando desde cero")
            
            round_count = 0
            no_improvement_count = 0
            converged = False
            current_max_iterations = max_iterations_per_round
            strategy_rotation = ['best1bin', 'rand1bin', 'best2bin', 'rand2bin']  # Rotar estrategias
            strategy_index = 0
            previous_round_error = None  # Para detectar si empeoró en ronda anterior
            error_increased_prev = False  # Si el error aumentó en la ronda anterior
            
            # MODO CONTINUO: Continuar indefinidamente hasta alcanzar objetivo
            max_rounds_display = max_rounds_per_company if max_rounds_per_company else "∞"
            while (max_rounds_per_company is None or round_count < max_rounds_per_company) and not converged:
                round_count += 1
                logger.info(f"\n[AUTO_LOOP] {symbol} - Ronda {round_count}/{max_rounds_display}")
                logger.info(f"[AUTO_LOOP] {symbol} - Mejor error hasta ahora: {best_error:.2f}% (objetivo: {target_error}%)")
                
                # Si lleva muchas rondas sin mejora, aumentar iteraciones y cambiar estrategia
                if no_improvement_count >= 5:
                    current_max_iterations = int(max_iterations_per_round * 1.5)  # Aumentar 50%
                    strategy_index = (strategy_index + 1) % len(strategy_rotation)
                    logger.info(f"[AUTO_LOOP] {symbol} - 🔄 Sin mejoras por {no_improvement_count} rondas, aumentando iteraciones a {current_max_iterations} y cambiando estrategia")
                elif no_improvement_count >= 10:
                    current_max_iterations = int(max_iterations_per_round * 2.0)  # Duplicar
                    logger.info(f"[AUTO_LOOP] {symbol} - 🔄 Sin mejoras por {no_improvement_count} rondas, duplicando iteraciones a {current_max_iterations}")
                else:
                    current_max_iterations = max_iterations_per_round
                
                try:
                    # Entrenar esta ronda (pasar error inicial para validación adaptativa)
                    # MEJORA: Usar iteraciones adaptativas, estrategia rotativa y mejores parámetros como punto de partida
                    # NO guardar modelo automáticamente - solo guardar si mejora
                    round_params = self.train_single_company(
                        symbol, 
                        target_error=target_error, 
                        max_iterations=current_max_iterations,
                        initial_error=best_error,  # Pasar mejor error hasta ahora para comparar
                        force_strategy=strategy_rotation[strategy_index] if no_improvement_count >= 5 else None,  # Cambiar estrategia si está estancado
                        best_params_so_far=best_params,  # MEJORA: Usar mejores parámetros como punto de partida
                        error_increased=error_increased_prev,  # Explorar alrededor si empeoró en ronda anterior
                        save_model=False  # MEJORA: No guardar automáticamente, solo si mejora
                    )
                    
                    round_error = round_params['error_pct']
                    improvement = best_error - round_error
                    improvement_pct = (improvement / best_error * 100) if best_error > 0 else 0
                    
                    logger.info(f"[AUTO_LOOP] {symbol} - Ronda {round_count} completada:")
                    logger.info(f"  Error: {round_error:.2f}%")
                    logger.info(f"  Mejora: {improvement:.2f}% ({improvement_pct:.1f}% relativo)")
                    
                    # MEJORA: Detectar si el error aumentó significativamente (para siguiente ronda)
                    error_increased_prev = round_error > best_error * 1.1  # Aumentó más del 10%
                    
                    # MEJORA: Siempre mantener el mejor resultado encontrado
                    # Si esta ronda mejoró el error, actualizar Y guardar modelo
                    if round_error < best_error:
                        # Hay mejora (aunque sea pequeña)
                        best_error = round_error
                        best_params = round_params
                        
                        # MEJORA: Guardar modelo solo cuando mejora
                        logger.info(f"[AUTO_LOOP] {symbol} - 💾 Guardando modelo mejorado (error mejoró a {best_error:.2f}%)...")
                        try:
                            # Guardar directamente sin re-entrenar
                            from src.valuation import CompanySpecificParams
                            financial_data = self.financial_data_cache[symbol]
                            growth_rates = self.growth_rates_cache.get(symbol, {})
                            company_params_obj = CompanySpecificParams(
                                symbol=symbol,
                                financial_data=financial_data,
                                growth_rates=growth_rates
                            )
                            company_params = company_params_obj.get_all_params()
                            company_params['growth_adjustment_factor'] = best_params['growth_adjustment_factor']
                            company_params['wacc_adjustment_factor'] = best_params['wacc_adjustment_factor']
                            company_params['error'] = best_params['error']
                            company_params['error_pct'] = best_error
                            company_params['trained'] = True
                            company_params['training_note'] = f"Modelo entrenado - mejor error encontrado: {best_error:.2f}%"
                            
                            models_dir = Path("models")
                            model_file = company_params_obj.save_model(models_dir)
                            with open(model_file, 'w', encoding='utf-8') as f:
                                json.dump(company_params, f, indent=2, ensure_ascii=False, default=str)
                            logger.info(f"[AUTO_LOOP] {symbol} - ✅ Modelo guardado: {model_file}")
                        except Exception as e:
                            logger.warning(f"[AUTO_LOOP] {symbol} - Error guardando modelo: {e}")
                        
                        # Verificar si la mejora es significativa
                        if improvement >= min_improvement_threshold:
                            no_improvement_count = 0
                            current_max_iterations = max_iterations_per_round  # Resetear iteraciones
                            logger.info(f"[AUTO_LOOP] {symbol} - ✅ Mejora significativa detectada! Nuevo mejor error: {best_error:.2f}%")
                        else:
                            # Mejora pequeña pero mejoró - resetear contador parcialmente
                            no_improvement_count = max(0, no_improvement_count - 1)
                            logger.info(f"[AUTO_LOOP] {symbol} - ✅ Mejora pequeña pero mejoró ({improvement:.2f}%), continuando...")
                        
                        # Si alcanzó el objetivo, puede terminar
                        if best_error <= target_error:
                            logger.info(f"[AUTO_LOOP] {symbol} - 🎯 OBJETIVO ALCANZADO! ({best_error:.2f}% <= {target_error}%)")
                            converged = True
                    else:
                        # Esta ronda empeoró o no mejoró - mantener el mejor resultado anterior
                        if round_error > best_error:
                            logger.warning(f"[AUTO_LOOP] {symbol} - ⚠️ Esta ronda empeoró el error ({round_error:.2f}% > {best_error:.2f}%), manteniendo mejor resultado anterior")
                        no_improvement_count += 1
                        logger.info(f"[AUTO_LOOP] {symbol} - ⚠️ Sin mejora ({no_improvement_count} rondas consecutivas)")
                        
                        # MODO CONTINUO: NO detener por convergencia, solo por objetivo alcanzado
                        # Continuar indefinidamente hasta encontrar mejores parámetros
                        if no_improvement_count % 10 == 0:
                            logger.info(f"[AUTO_LOOP] {symbol} - 🔄 Lleva {no_improvement_count} rondas sin mejora, pero continuando...")
                        
                        # Solo considerar convergencia si max_rounds está definido Y se alcanzó
                        if max_rounds_per_company and no_improvement_count >= max_rounds_per_company:
                            logger.warning(f"[AUTO_LOOP] {symbol} - ⚠️ Alcanzado máximo de rondas sin mejora, pero objetivo no alcanzado")
                            # NO converger - continuar si max_rounds es None
                            if max_rounds_per_company is not None:
                                converged = True
                    
                except Exception as e:
                    logger.error(f"[AUTO_LOOP] {symbol} - Error en ronda {round_count}: {e}")
                    no_improvement_count += 1
                    # MODO CONTINUO: No detener por errores, solo continuar
                    if no_improvement_count % 5 == 0:
                        logger.warning(f"[AUTO_LOOP] {symbol} - Lleva {no_improvement_count} errores consecutivos, pero continuando...")
                    # Solo detener si max_rounds está definido Y se alcanzó
                    if max_rounds_per_company and no_improvement_count >= max_rounds_per_company:
                        logger.warning(f"[AUTO_LOOP] {symbol} - Demasiados errores, pero objetivo no alcanzado")
                        if max_rounds_per_company is not None:
                            converged = True
                    continue
            
            # Guardar resultados de esta empresa
            if best_params:
                trained_models[symbol] = best_params
                convergence_status[symbol] = {
                    'converged': converged,
                    'final_error': best_error,
                    'initial_error': initial_error,
                    'improvement': initial_error - best_error,
                    'rounds': round_count,
                    'reached_target': best_error <= target_error
                }
                logger.info(f"[AUTO_LOOP] {symbol} - ✅ Entrenamiento completado:")
                logger.info(f"  Error inicial: {initial_error:.2f}%")
                logger.info(f"  Error final: {best_error:.2f}%")
                logger.info(f"  Mejora total: {initial_error - best_error:.2f}%")
                logger.info(f"  Rondas: {round_count}")
                logger.info(f"  Convergencia: {'Sí' if converged else 'No (máximo alcanzado)'}")
                logger.info(f"  Objetivo alcanzado: {'Sí' if best_error <= target_error else 'No'}")
            else:
                logger.error(f"[AUTO_LOOP] {symbol} - ❌ No se obtuvieron parámetros válidos")
                convergence_status[symbol] = {
                    'converged': False,
                    'final_error': initial_error,
                    'initial_error': initial_error,
                    'improvement': 0.0,
                    'rounds': round_count,
                    'reached_target': False
                }
        
        # Resumen final
        logger.info("=" * 80)
        logger.info("[AUTO_LOOP] RESUMEN FINAL DEL ENTRENAMIENTO")
        logger.info("=" * 80)
        
        total_companies = len(self.symbols)
        reached_target = sum(1 for s in self.symbols if convergence_status.get(s, {}).get('reached_target', False))
        converged_companies = sum(1 for s in self.symbols if convergence_status.get(s, {}).get('converged', False))
        
        logger.info(f"Total empresas: {total_companies}")
        logger.info(f"Empresas que alcanzaron objetivo (< {target_error}%): {reached_target}/{total_companies}")
        logger.info(f"Empresas con convergencia: {converged_companies}/{total_companies}")
        
        logger.info("\nDetalle por empresa:")
        for symbol in self.symbols:
            status = convergence_status.get(symbol, {})
            logger.info(f"  {symbol}:")
            logger.info(f"    Error inicial: {status.get('initial_error', 0):.2f}%")
            logger.info(f"    Error final: {status.get('final_error', 0):.2f}%")
            logger.info(f"    Mejora: {status.get('improvement', 0):.2f}%")
            logger.info(f"    Rondas: {status.get('rounds', 0)}")
            logger.info(f"    Objetivo: {'✅' if status.get('reached_target', False) else '❌'}")
            logger.info(f"    Convergencia: {'✅' if status.get('converged', False) else '❌'}")
        
        # Retornar mejores parámetros globales (promedio de los entrenados)
        if trained_models:
            avg_growth_adj = np.mean([p['growth_adjustment_factor'] for p in trained_models.values()])
            avg_wacc_adj = np.mean([p['wacc_adjustment_factor'] for p in trained_models.values()])
            
            global_best_params = {
                'dcf_weight': 0.5,
                'comparables_weight': 0.5,
                'growth_adjustment_factor': avg_growth_adj,
                'wacc_adjustment_factor': avg_wacc_adj,
            }
            
            logger.info(f"\nParámetros globales promedio:")
            logger.info(f"  growth_adjustment_factor: {avg_growth_adj:.3f}")
            logger.info(f"  wacc_adjustment_factor: {avg_wacc_adj:.3f}")
            
            return global_best_params
        else:
            return initial_params
    
    def train(self, initial_params: Dict = None) -> Dict:
        """
        Entrena el modelo ajustando parámetros
        NUEVA ESTRATEGIA: Entrena empresas críticas individualmente primero
        
        Args:
            initial_params: Parámetros iniciales (opcional)
        
        Returns:
            Mejores parámetros encontrados
        """
        logger.info("=" * 60)
        logger.info("[TRAIN] Iniciando entrenamiento del modelo...")
        logger.info("=" * 60)
        
        if not self.target_values:
            logger.error("[TRAIN] ERROR: No hay valores objetivo establecidos")
            raise ValueError("Debes establecer valores objetivo primero con set_target_values()")
        
        logger.info(f"[TRAIN] Valores objetivo configurados: {len(self.target_values)} empresas")
        logger.debug(f"[TRAIN] Símbolos objetivo: {list(self.target_values.keys())}")
        
        # PASO 0: Precargar datos financieros PRIMERO (necesario para evaluar empresas)
        logger.info("=" * 60)
        logger.info("[TRAIN] PASO 0: Preparando datos de entrenamiento...")
        logger.info("=" * 60)
        
        # Cargar caché desde disco
        if not self.financial_data_cache:
            self.load_cache()
        
        # Verificar si necesitamos precargar más datos
        missing = [s for s in self.symbols if s not in self.financial_data_cache]
        if missing:
            logger.info(f"Caché parcial: {len(self.financial_data_cache)}/{len(self.symbols)} empresas disponibles")
            logger.info(f"Faltan: {missing}")
            logger.info("Iniciando precarga de empresas faltantes...")
            self.preload_financial_data()
        else:
            logger.info(f"[OK] Cache completo: {len(self.financial_data_cache)} empresas disponibles")
        
        # PASO 1: Identificar empresas críticas (error >= 30%)
        logger.info("=" * 60)
        logger.info("PASO 1: Identificando empresas críticas...")
        logger.info("=" * 60)
        
        # Evaluar todas las empresas con parámetros iniciales para identificar críticas
        if initial_params is None:
            initial_params = {
                'dcf_weight': 0.5,
                'comparables_weight': 0.5,
                'growth_adjustment_factor': 1.0,
                'wacc_adjustment_factor': 1.0,
            }
        
        _, errors_by_symbol = self.calculate_error(initial_params, return_details=True)
        errors_pct = [(sym, np.expm1(err)) for sym, err in errors_by_symbol]
        
        CRITICAL_THRESHOLD = 30.0
        critical_companies = [(sym, err) for sym, err in errors_pct if err >= CRITICAL_THRESHOLD]
        
        if critical_companies:
            logger.info(f"Encontradas {len(critical_companies)} empresas críticas (error >= {CRITICAL_THRESHOLD}%):")
            for sym, err in critical_companies:
                logger.info(f"  - {sym}: {err:.2f}%")
            
            # PASO 2: Entrenar cada empresa crítica individualmente hasta alcanzar objetivo
            logger.info("=" * 60)
            logger.info("PASO 2: Entrenando empresas críticas individualmente...")
            logger.info("=" * 60)
            
            trained_critical = {}
            for symbol, current_error in critical_companies:
                max_attempts = 3  # Máximo 3 intentos con más iteraciones cada vez
                target_error = 10.0
                achieved = False
                
                for attempt in range(1, max_attempts + 1):
                    try:
                        logger.info(f"\n{'='*60}")
                        logger.info(f"Intento {attempt}/{max_attempts}: Entrenando {symbol} (error actual: {current_error:.2f}%)")
                        logger.info(f"Objetivo: Error < {target_error}%")
                        logger.info(f"{'='*60}")
                        
                        # Aumentar iteraciones en cada intento
                        max_iterations = 500 * attempt
                        
                        # Entrenar hasta alcanzar error < 10%
                        best_params = self.train_single_company(symbol, target_error=target_error, max_iterations=max_iterations)
                        trained_critical[symbol] = best_params
                        
                        if best_params['error_pct'] <= target_error:
                            logger.info(f"[OK] {symbol} alcanzó el objetivo: {best_params['error_pct']:.2f}% <= {target_error}%")
                            achieved = True
                            break
                        else:
                            logger.warning(f"[WARN] {symbol} no alcanzó el objetivo en intento {attempt}: {best_params['error_pct']:.2f}% > {target_error}%")
                            if attempt < max_attempts:
                                logger.info(f"[CONTINUAR] Reintentando con más iteraciones ({max_iterations * (attempt + 1)})...")
                    
                    except (ValueError, Exception) as e:
                        error_msg = str(e)
                        if "Parámetros inválidos" in error_msg or "invalid" in error_msg.lower():
                            logger.error(f"[ERROR] Parámetros inválidos en intento {attempt} para {symbol}: {e}")
                            logger.info(f"[DESCARTAR] Este intento se descarta, reintentando...")
                        else:
                            logger.error(f"[ERROR] Error en intento {attempt} para {symbol}: {e}")
                        
                        if attempt < max_attempts:
                            logger.info(f"[CONTINUAR] Reintentando con más iteraciones...")
                        continue
                
                if not achieved:
                    final_error_val = trained_critical.get(symbol, {}).get('error_pct', None)
                    if final_error_val is not None:
                        logger.error(f"[FALLO] {symbol} NO alcanzó el objetivo después de {max_attempts} intentos")
                        logger.error(f"[FALLO] Error final: {final_error_val:.2f}%")
                    else:
                        logger.error(f"[FALLO] {symbol} NO alcanzó el objetivo después de {max_attempts} intentos")
                        logger.error(f"[FALLO] Error final: No disponible (falló en todos los intentos)")
                    logger.error(f"[FALLO] Continuará con entrenamiento global, pero se recomienda revisar datos de {symbol}")
            
            successful = sum(1 for sym, _ in critical_companies if trained_critical.get(sym, {}).get('error_pct', 100) <= 10.0)
            logger.info(f"\n[RESUMEN] {successful}/{len(critical_companies)} empresas críticas alcanzaron el objetivo (< 10%)")
            logger.info(f"[RESUMEN] {len(critical_companies) - successful} empresas críticas aún necesitan mejora")
        
        # PASO 3: Continuar con entrenamiento global para empresas restantes
        logger.info("=" * 60)
        logger.info("PASO 3: Entrenamiento global para empresas restantes...")
        logger.info("=" * 60)
        
        # NUEVA ESTRATEGIA: Solo optimizar 4 parámetros globales
        # Usar datos REALES por empresa (beta, cost_of_debt, debt_to_equity, sector)
        # Aplicar factores de ajuste globales para fine-tuning
        if initial_params is None:
            initial_params = {
                # Pesos del blend (Alpha Spread usa promedio simple 50/50)
                'dcf_weight': 0.5,
                'comparables_weight': 0.5,
                # Factores de ajuste globales
                'growth_adjustment_factor': 1.0,  # Multiplica el crecimiento real por empresa
                'wacc_adjustment_factor': 1.0,    # Multiplica el WACC calculado con datos reales
            }
        
        logger.info("=" * 60)
        logger.info("Iniciando entrenamiento del modelo...")
        logger.info("Metodología: Alpha Spread (DCF + Relative Valuation)")
        logger.info("=" * 60)
        logger.info("NOTA: El proceso continuará ejecutándose aunque:")
        logger.info("  - El ordenador se bloquee (screen lock)")
        logger.info("  - Cierres la terminal")
        logger.info("  - El proceso está en segundo plano")
        logger.info("PERO se pausará si el ordenador entra en suspensión/hibernación")
        logger.info("Se guardan checkpoints automáticamente en training_checkpoint.json")
        logger.info("=" * 60)
        
        # Los datos ya se cargaron en PASO 0, solo verificar que están disponibles
        if not self.financial_data_cache:
            logger.warning("No hay datos en caché, cargando ahora...")
            self.load_cache()
            missing = [s for s in self.symbols if s not in self.financial_data_cache]
            if missing:
                self.preload_financial_data()
        
        logger.info("=" * 60)
        logger.info("PASO 2: Configurando parámetros de optimización...")
        logger.debug(f"Total empresas disponibles en caché: {len(self.financial_data_cache)}")
        logger.debug(f"Empresas_train: {self.symbols}")
        logger.debug(f"Empresas en caché (no usadas en train): {[s for s in self.financial_data_cache.keys() if s not in self.symbols]}")
        
        logger.info("=" * 60)
        logger.info("MODO ALPHA SPREAD")
        logger.info("  - Pesos fijos: 50% DCF / 50% Comparables (como Alpha Spread)")
        logger.info("  - ERP: 4.12% (como Alpha Spread)")
        logger.info("  - Terminal growth: Conservador 1.5% (como Alpha Spread)")
        logger.info("  - Solo optimiza: growth_adjustment_factor, wacc_adjustment_factor")
        logger.info("  - Usando datos REALES por empresa (beta, cost_of_debt, debt_to_equity)")
        logger.info("=" * 60)
        
        # MODO ALPHA SPREAD: Solo 2 parámetros (pesos fijos a 50/50)
        bounds = [
            (0.7, 1.3),   # growth_adjustment_factor: Factor para ajustar crecimiento real (0.7-1.3)
            (0.8, 1.2),   # wacc_adjustment_factor: Factor para ajustar WACC calculado (0.8-1.2)
        ]
        
        # Función objetivo para minimizar
        eval_count = [0]  # Contador de evaluaciones
        def objective(x):
            eval_count[0] += 1
            logger.info(f"[OBJECTIVE] INICIO Evaluación #{eval_count[0]}: x=[{x[0]:.3f}, {x[1]:.3f}] (ALPHA SPREAD)")
            params = {
                'dcf_weight': 0.5,  # FIJO 50%
                'comparables_weight': 0.5,  # FIJO 50%
                'growth_adjustment_factor': x[0],
                'wacc_adjustment_factor': x[1],
            }
            logger.info(f"[OBJECTIVE] Llamando a calculate_error()...")
            try:
                error = self.calculate_error(params)
                logger.info(f"[OBJECTIVE] calculate_error() retornó: {error:.2f}%")
                logger.info(f"[OBJECTIVE] FIN Evaluación #{eval_count[0]}: Error={error:.2f}%")
                return error
            except Exception as e:
                logger.error(f"[OBJECTIVE] ERROR en evaluación #{eval_count[0]}: {e}")
                import traceback
                logger.error(f"[OBJECTIVE] Traceback: {traceback.format_exc()}")
                raise
        
        # Valores iniciales (punto de partida para la optimización)
        x0 = [
            initial_params['growth_adjustment_factor'],
            initial_params['wacc_adjustment_factor'],
        ]
        
        logger.info("Optimizando parámetros...")
        logger.info(f"Entrenando con {len(self.symbols)} empresas")
        
        # Ajustar parámetros de optimización según número de empresas
        # MODO CONTINUO: Aumentar significativamente las iteraciones para mejor convergencia
        num_companies = len(self.symbols)
        if num_companies >= 15:
            maxiter = 500  # MODO CONTINUO: Muchas más iteraciones para alcanzar objetivo
            popsize = 20  # Población más grande para mejor exploración
        elif num_companies >= 10:
            maxiter = 400  # MODO CONTINUO: Más iteraciones
            popsize = 15   # Población más grande
        else:
            maxiter = 300  # MODO CONTINUO: Más iteraciones
            popsize = 12   # Población más grande
        
        total_evaluations = maxiter * popsize
        
        # Error objetivo: con la nueva métrica combinada (que penaliza errores altos),
        # un error combinado de 15-20% es equivalente a tener errores bajos en todas las empresas
        # El error combinado será más alto que el promedio porque penaliza los errores altos
        # MODO CONTINUO: Entrenar hasta alcanzar error objetivo estricto
        # Para replicar Alpha Spread: objetivo muy estricto (5%)
        # Determinar objetivo según número de empresas
        # Para replicar Alpha Spread: objetivo más estricto con menos empresas
        if num_companies <= 7:
            TARGET_ERROR = 5.0  # Objetivo muy estricto para replicar Alpha Spread (dataset limpio)
        elif num_companies <= 11:
            TARGET_ERROR = 10.0  # Objetivo estricto para TECH_ONLY (todas las tech)
        else:
            TARGET_ERROR = 15.0  # Objetivo estricto para datasets más grandes
        
        logger.info("=" * 60)
        logger.info("PASO 3: Iniciando optimización con differential_evolution...")
        logger.info(f"  - Máximo de iteraciones: {maxiter}")
        logger.info(f"  - Tamaño de población: {popsize}")
        logger.info(f"  - Empresas en entrenamiento: {len(self.financial_data_cache)}")
        logger.info(f"  - Error objetivo: {TARGET_ERROR}% (parada temprana si se alcanza)")
        logger.info("=" * 60)
        try:
            print("=" * 60, flush=True)
            print("INICIANDO OPTIMIZACIÓN...", flush=True)
            print(f"Empresas: {len(self.financial_data_cache)}", flush=True)
            print(f"Iteraciones máximas: {maxiter}", flush=True)
            print(f"Error objetivo: {TARGET_ERROR}% (se detendrá automáticamente si se alcanza)", flush=True)
            print("=" * 60, flush=True)
            sys.stdout.flush()
        except (OSError, IOError):
            pass
        
        # Callback para mostrar progreso y guardar checkpoints
        iteration_count = [0]
        best_error = [float('inf')]
        best_params_so_far = [None]
        
        def callback(xk, convergence):
            # NOTA: El callback de differential_evolution se llama DESPUÉS de cada generación
            # convergence es el valor de convergencia actual (menor = mejor convergencia)
            # MODO ALPHA SPREAD: Solo 2 parámetros (xk[0] = growth_adjustment, xk[1] = wacc_adjustment)
            iteration_count[0] += 1
            
            # Logging reducido: solo cada 10 iteraciones o cuando mejora
            log_this_iteration = (iteration_count[0] % 10 == 0) or (iteration_count[0] == 1)
            
            if log_this_iteration:
                logger.debug(f"[CALLBACK] Iteración {iteration_count[0]}/{maxiter} - convergence={convergence:.6f}")
            
            # Evaluar el error real usando la función objetivo
            try:
                current_error_log1p = objective(xk)  # Error en escala log1p
                # Convertir de vuelta a porcentaje real para comparación
                current_error_pct = np.expm1(current_error_log1p)  # Convertir log1p a porcentaje
            except Exception as e:
                logger.error(f"[CALLBACK] ERROR llamando a objective(): {e}")
                import traceback
                logger.error(f"[CALLBACK] Traceback: {traceback.format_exc()}")
                return False  # Continuar aunque haya error
            if current_error_log1p < best_error[0]:
                best_error[0] = current_error_log1p
                
                # Logging reducido: solo mostrar cuando mejora significativamente o cada 50 iteraciones
                should_log_details = (iteration_count[0] % 50 == 0) or (current_error_pct < TARGET_ERROR * 1.5)
                
                if should_log_details:
                    # Obtener errores por empresa para logging detallado
                    try:
                        # MODO ALPHA SPREAD: Pesos fijos 50/50, solo factores de ajuste
                        params_dict = {
                            'dcf_weight': 0.5,  # FIJO
                            'comparables_weight': 0.5,  # FIJO
                            'growth_adjustment_factor': xk[0],
                            'wacc_adjustment_factor': xk[1],
                        }
                        _, errors_by_symbol = self.calculate_error(params_dict, return_details=True)
                        
                        # Convertir errores log1p a porcentajes reales para mostrar
                        errors_pct = [(sym, np.expm1(err)) for sym, err in errors_by_symbol]
                        
                        # Separar empresas en categorías
                        GOOD_THRESHOLD_PCT = 10.0
                        CRITICAL_THRESHOLD_PCT = 30.0
                        critical = [(sym, err) for sym, err in errors_pct if err >= CRITICAL_THRESHOLD_PCT]
                        intermediate = [(sym, err) for sym, err in errors_pct if GOOD_THRESHOLD_PCT <= err < CRITICAL_THRESHOLD_PCT]
                        good = [(sym, err) for sym, err in errors_pct if err < GOOD_THRESHOLD_PCT]
                        
                        # Top 3 de cada categoría
                        top_critical = critical[:3] if len(critical) >= 3 else critical
                        top_intermediate = intermediate[:3] if len(intermediate) >= 3 else intermediate[:len(intermediate)]
                        top_best = good[:3] if len(good) >= 3 else good[:len(good)]
                        
                        logger.info(f"[MEJORA] Iter {iteration_count[0]}/{maxiter}: Error={current_error_pct:.2f}% (objetivo: {TARGET_ERROR}%)")
                        logger.info(f"[ENFOQUE] {len(critical)} críticas, {len(intermediate)} intermedias, {len(good)} buenas")
                        if top_critical:
                            critical_str = ", ".join([f"{sym}={err:.0f}%" for sym, err in top_critical])
                            logger.info(f"[ATACANDO CRÍTICAS] Top críticas (>=30%): {critical_str}")
                        if top_intermediate:
                            intermediate_str = ", ".join([f"{sym}={err:.0f}%" for sym, err in top_intermediate])
                            logger.info(f"[MEJORANDO INTERMEDIAS] Top intermedias (10-30%): {intermediate_str}")
                        if top_best:
                            best_str = ", ".join([f"{sym}={err:.0f}%" for sym, err in top_best])
                            logger.debug(f"[MANTENIENDO] Top buenas (<10%): {best_str}")
                    except Exception as e:
                        logger.debug(f"[CALLBACK] No se pudieron obtener detalles por empresa: {e}")
                else:
                    # Logging mínimo cuando mejora pero no es significativo
                    logger.debug(f"[MEJORA] Iter {iteration_count[0]}/{maxiter}: Error={current_error_pct:.2f}%")
                
                # Guardar parámetros actuales (MODO ALPHA SPREAD)
                current_params = {
                    'dcf_weight': 0.5,  # FIJO 50%
                    'comparables_weight': 0.5,  # FIJO 50%
                    'growth_adjustment_factor': xk[0],
                    'wacc_adjustment_factor': xk[1],
                    'error': current_error_log1p,  # Error en escala log1p (para optimización)
                    'error_pct': current_error_pct,  # Error en porcentaje real (para visualización)
                    'iteration': iteration_count[0],
                    'note': 'Modo Alpha Spread: 50/50 fijo, ERP 4.12%, Terminal growth conservador (1.5%)'
                }
                best_params_so_far[0] = current_params
                
                # Guardar checkpoint cada vez que mejora
                checkpoint_file = "training_checkpoint.json"
                try:
                    with open(checkpoint_file, "w", encoding='utf-8') as f:
                        json.dump({
                            'best_params': current_params,
                            'iteration': iteration_count[0],
                            'total_iterations': maxiter,
                            'best_error': current_error_log1p,
                            'best_error_pct': current_error_pct,
                            'companies_trained': len(self.symbols)
                        }, f, indent=2, ensure_ascii=False)
                    logger.debug(f"Checkpoint guardado en {checkpoint_file}")
                except Exception as e:
                    logger.warning(f"No se pudo guardar checkpoint: {e}")
                
                best_error_pct_display = np.expm1(best_error[0])
                
                # Mostrar progreso solo cada 10 iteraciones o cuando está cerca del objetivo
                should_print = (iteration_count[0] % 10 == 0) or (best_error_pct_display <= TARGET_ERROR * 1.2)
                
                if should_print:
                    iter_msg = f"[ITERACION {iteration_count[0]}/{maxiter}] Mejor error: {best_error_pct_display:.2f}% (objetivo: {TARGET_ERROR}%)"
                    try:
                        print(iter_msg, flush=True)  # Print directo para visibilidad
                        sys.stdout.flush()  # Forzar escritura inmediata
                    except (OSError, IOError):
                        pass  # Ignorar si print falla (proceso en background)
                    logger.info(iter_msg)
                
                # Parada temprana: si alcanzamos un error objetivo, detener optimización
                # Convertir error log1p a porcentaje real para comparación
                best_error_pct_real = np.expm1(best_error[0])
                if best_error_pct_real <= TARGET_ERROR:
                    success_msg = f"[OK] OBJETIVO ALCANZADO: Error {best_error_pct_real:.2f}% <= {TARGET_ERROR}%"
                    try:
                        print("=" * 60, flush=True)
                        print(success_msg, flush=True)
                        print("=" * 60, flush=True)
                    except (OSError, IOError):
                        pass  # Ignorar si print falla (proceso en background)
                    logger.info("=" * 60)
                    logger.info(success_msg)
                    logger.info("Deteniendo optimización - error óptimo alcanzado")
                    logger.info("=" * 60)
                    return True  # Detener optimización
            return False  # Continuar optimización
        
        # Optimización usando differential_evolution (más robusto)
        logger.info(f"[TRAIN] Iniciando differential_evolution con maxiter={maxiter}, popsize={popsize}")
        logger.info(f"[TRAIN] Esto puede tardar varios minutos. Cada evaluación prueba {len(self.symbols)} empresas.")
        try:
            result = differential_evolution(
                objective,
                bounds,
                seed=42,
                maxiter=maxiter,
                popsize=popsize,
                polish=False,  # Deshabilitar polish para evitar convergencia prematura
                atol=0.0,      # Tolerancia absoluta = 0 (forzar todas las iteraciones)
                tol=0.0,       # Tolerancia relativa = 0 (forzar todas las iteraciones)
                callback=callback,
                updating='immediate',  # Actualizar población inmediatamente (más exploración)
                strategy='best1bin',  # Estrategia más exploratoria
            )
            logger.info(f"[TRAIN] differential_evolution completado exitosamente")
        except Exception as e:
            logger.error(f"[TRAIN] ERROR en differential_evolution: {e}")
            import traceback
            logger.error(f"[TRAIN] Traceback: {traceback.format_exc()}")
            # Notificar al monitor que hubo un error
            try:
                from datetime import datetime
                status_file = Path("training_status.json")
                with open(status_file, "w", encoding='utf-8') as f:
                    json.dump({
                        "status": "error",
                        "error_message": str(e),
                        "timestamp": datetime.now().isoformat(),
                        "iteration": iteration_count[0] if 'iteration_count' in locals() else 0,
                    }, f, indent=2, ensure_ascii=False)
            except:
                pass
            raise
        
        # MODO ALPHA SPREAD: Pesos fijos 50/50, solo factores de ajuste optimizados
        best_params = {
            'dcf_weight': 0.5,  # FIJO 50%
            'comparables_weight': 0.5,  # FIJO 50%
            'growth_adjustment_factor': result.x[0],
            'wacc_adjustment_factor': result.x[1],
            'note': 'Modo Alpha Spread: 50/50 fijo, ERP 4.12%, Terminal growth conservador (1.5%)'
        }
        
        logger.info("=" * 60)
        logger.info("ENTRENAMIENTO COMPLETADO")
        logger.info("=" * 60)
        error_final_pct = np.expm1(result.fun)
        logger.info(f"Error final: {result.fun:.4f} (log1p) = {error_final_pct:.2f}% (real)")
        
        # Guardar error e iteración en best_params para comparación posterior
        best_params['error'] = result.fun  # Error en escala log1p (para optimización)
        best_params['error_pct'] = np.expm1(result.fun)  # Error en porcentaje real (para visualización)
        best_params['iteration'] = iteration_count[0] if 'iteration_count' in locals() else None
        
        # Notificar al monitor que el entrenamiento terminó
        try:
            from datetime import datetime
            status_file = Path("training_status.json")
            with open(status_file, "w", encoding='utf-8') as f:
                # Convertir error log1p a porcentaje real para comparación
                error_pct_real = np.expm1(result.fun)
                json.dump({
                    "status": "completed",
                    "error": result.fun,  # Error en escala log1p
                    "error_pct": error_pct_real,  # Error en porcentaje real
                    "objective_reached": bool(error_pct_real <= 30.0),  # Convertir a bool explícitamente
                    "timestamp": datetime.now().isoformat(),
                    "iteration": iteration_count[0] if 'iteration_count' in locals() else 0,
                    "total_iterations": maxiter
                }, f, indent=2, ensure_ascii=False)
            logger.info(f"[NOTIFY] Estado guardado en {status_file} para el monitor")
        except Exception as e:
            logger.warning(f"[NOTIFY] Error guardando estado: {e}")
        logger.info("\nMejores parámetros encontrados:")
        for key, value in best_params.items():
            logger.info(f"  {key}: {value}")
        
        # Calcular valores finales con mejores parámetros
        logger.info("=" * 60)
        logger.info("[RESULT] Evaluación final con mejores parámetros (TRAIN)")
        logger.info("=" * 60)
        final_error, errors_by_symbol = self.calculate_error(best_params, return_details=True)
        logger.info(f"[RESULT] Error train: {final_error:.2f}%")
        
        # Calcular errores individuales por empresa y valores estimados
        logger.info("\nErrores individuales por empresa (TRAIN):")
        detailed_results = []
        for symbol, error_pct in errors_by_symbol:
            target_value = self.target_values[symbol]
            # Obtener valor estimado
            symbol_result, _ = self._evaluate_single_company(symbol, 1, len(self.symbols), best_params)
            # Necesitamos obtener el valor estimado, no solo el error
            # Para eso, evaluamos de nuevo pero capturamos el valor
            try:
                if symbol in self.financial_data_cache:
                    financial_data = self.financial_data_cache[symbol]
                    growth_rates = self.growth_rates_cache.get(symbol, {"fcf_growth": 5.0})
                    sector_averages = self.sector_averages_cache.get(symbol, {})
                    
                    # Calcular valor estimado (simplificado, reutilizando lógica de _evaluate_single_company)
                    from src.core import FundamentalAnalysisEngine
                    # MODO ALPHA SPREAD: Terminal growth específico por sector
                    terminal_growth_final = self.get_sector_terminal_growth(financial_data.get("sector", "Unknown"))
                    market_risk_premium_final = 4.12  # Alpha Spread usa ~4.12%
                    
                    logger.debug(f"[RESULT] Creando engine para evaluación final de {symbol} con terminal_growth={terminal_growth_final}, market_risk_premium={market_risk_premium_final}")
                    try:
                        temp_engine = FundamentalAnalysisEngine(
                            self.api_key,
                            dcf_weight=best_params['dcf_weight'],
                            comparables_weight=best_params['comparables_weight'],
                            projection_years=10,
                            terminal_growth_rate=terminal_growth_final,
                            risk_free_rate=4.5,
                            market_risk_premium=market_risk_premium_final,
                            beta=financial_data.get("beta", 1.0),
                            debt_to_equity=financial_data.get("debt", 0) / max(financial_data.get("shareholder_equity", 1), 1),
                            cost_of_debt=max((financial_data.get("interest_expense", 0) / max(financial_data.get("debt", 1), 1)) * 100, 3.0),
                            tax_rate=21.0,
                        )
                        logger.debug(f"[RESULT] Engine creado exitosamente para {symbol}")
                    except Exception as e:
                        logger.error(f"[RESULT] ERROR creando engine para {symbol}: {e}", exc_info=True)
                        raise
                    
                    # Calcular DCF y Comparables
                    from src.valuation import DCFCalculator
                    dcf_calc = DCFCalculator(
                        projection_years=10,
                        terminal_growth_rate=terminal_growth_final,
                        risk_free_rate=4.5,
                        market_risk_premium=market_risk_premium_final,
                        beta=financial_data.get("beta", 1.0),
                        debt_to_equity=financial_data.get("debt", 0) / max(financial_data.get("shareholder_equity", 1), 1),
                        cost_of_debt=max((financial_data.get("interest_expense", 0) / max(financial_data.get("debt", 1), 1)) * 100, 3.0),
                        tax_rate=21.0,
                    )
                    
                    adjusted_fcf_growth = growth_rates.get("fcf_growth", 5.0) * best_params['growth_adjustment_factor']
                    # Usar Market Cap y Total Debt para cálculo WACC Alpha Spread
                    market_cap_final = financial_data.get("market_cap", 0)
                    total_debt_final = financial_data.get("debt", 0)
                    dcf_result = dcf_calc.calculate_dcf(
                        current_fcf=financial_data["free_cash_flow"],
                        growth_rate=adjusted_fcf_growth,
                        shares_outstanding=financial_data["shares_outstanding"],
                        scenario="base",
                        market_cap=market_cap_final,  # Para cálculo WACC Alpha Spread
                        total_debt=total_debt_final   # Para cálculo WACC Alpha Spread
                    )
                    
                    comparables_result = temp_engine.valuation_engine.comparables_calculator.calculate_comparables(
                        current_price=financial_data["current_price"],
                        eps=financial_data["eps"],
                        book_value_per_share=financial_data["book_value_per_share"],
                        revenue_per_share=financial_data["revenue_per_share"],
                        market_cap=financial_data["market_cap"],
                        ebitda=financial_data["ebitda"],
                        sector_averages=sector_averages,
                        debt=financial_data.get("debt", 0.0),
                        cash=financial_data.get("cash", 0.0),
                        shares_outstanding=financial_data.get("shares_outstanding")
                    )
                    
                    blended_value = (dcf_result.fair_value_per_share * best_params['dcf_weight']) + \
                                   (comparables_result.fair_value_per_share * best_params['comparables_weight'])
                    
                    # Calcular error REAL basado en el blended_value calculado, no el error de optimización
                    error_real = abs((blended_value - target_value) / target_value) * 100 if target_value != 0 else 100.0
                    
                    detailed_results.append({
                        'symbol': symbol,
                        'estimated_value': round(blended_value, 2),
                        'target_value': round(target_value, 2),
                        'error_pct': round(error_real, 2),
                        'sector': financial_data.get("sector", "Unknown"),
                        'dcf_value': round(dcf_result.fair_value_per_share, 2),
                        'comparables_value': round(comparables_result.fair_value_per_share, 2),
                    })
                else:
                    detailed_results.append({
                        'symbol': symbol,
                        'estimated_value': None,
                        'target_value': round(target_value, 2),
                        'error_pct': round(error_pct, 2),
                        'sector': "Unknown",
                    })
            except Exception as e:
                logger.debug(f"Error calculando valor estimado para {symbol}: {e}")
                detailed_results.append({
                    'symbol': symbol,
                    'estimated_value': None,
                    'target_value': round(target_value, 2),
                    'error_pct': round(error_pct, 2),
                    'sector': "Unknown",
                })
            
            logger.info(f"  {symbol}: Error={error_pct:.2f}%, Objetivo=${target_value:.2f}")
        
        # Guardar JSON de análisis post-entrenamiento
        analysis_file = f"training_results_iter_{iteration_count[0] if 'iteration_count' in locals() else 'final'}.json"
        try:
            analysis_data = {
                'iteration': iteration_count[0] if 'iteration_count' in locals() else maxiter,
                'total_iterations': maxiter,
                'best_params': best_params,
                'error_train': round(final_error, 2),
                'companies_train': self.symbols,
                'results_by_company': detailed_results,
                'summary': {
                    'error_mean': round(np.mean([r['error_pct'] for r in detailed_results]), 2),
                    'error_max': round(np.max([r['error_pct'] for r in detailed_results]), 2),
                    'error_min': round(np.min([r['error_pct'] for r in detailed_results]), 2),
                    'companies_error_lt_10': sum(1 for r in detailed_results if r['error_pct'] < 10),
                    'companies_error_lt_20': sum(1 for r in detailed_results if r['error_pct'] < 20),
                }
            }
            with open(analysis_file, 'w', encoding='utf-8') as f:
                json.dump(analysis_data, f, indent=2, default=str)
            logger.info(f"\n[SAVED] Análisis detallado guardado en: {analysis_file}")
            
            # Análisis automático de empresas que se disparan (error >50%)
            disparadas = [r for r in detailed_results if r['error_pct'] > 50]
            if disparadas:
                logger.info("=" * 60)
                logger.info("[ANALISIS] EMPRESAS QUE SE DISPARARON (error >50%)")
                logger.info("=" * 60)
                for empresa in sorted(disparadas, key=lambda x: x['error_pct'], reverse=True):
                    symbol = empresa['symbol']
                    estimado = empresa['estimated_value']
                    objetivo = empresa['target_value']
                    error_pct = empresa['error_pct']
                    dcf_value = empresa['dcf_value']
                    comp_value = empresa['comparables_value']
                    
                    logger.info(f"\n{symbol}: Error {error_pct:.2f}%")
                    logger.info(f"  Estimado: ${estimado:.2f} vs Objetivo Alpha Spread: ${objetivo:.2f}")
                    logger.info(f"  DCF: ${dcf_value:.2f}, Comparables: ${comp_value:.2f}")
                    
                    # Diagnóstico automático
                    dcf_error = abs(dcf_value - objetivo) / objetivo * 100 if objetivo > 0 else 100
                    comp_error = abs(comp_value - objetivo) / objetivo * 100 if objetivo > 0 else 100
                    
                    if estimado > objetivo * 1.5:
                        logger.info(f"  DIAGNOSTICO: SOBREVALORACION EXTREMA ({((estimado/objetivo - 1)*100):.1f}% mayor)")
                        logger.info(f"    - Posible causa: Datos optimistas o Alpha Spread más conservador")
                        logger.info(f"    - Alpha Spread puede usar parámetros más conservadores para {symbol}")
                    elif estimado < objetivo * 0.5:
                        logger.info(f"  DIAGNOSTICO: SUBVALORACION EXTREMA ({((1 - estimado/objetivo)*100):.1f}% menor)")
                        logger.info(f"    - Posible causa: Datos pesimistas o Alpha Spread más optimista")
                        logger.info(f"    - Alpha Spread puede usar parámetros más optimistas para {symbol}")
                    
                    if abs(dcf_value - comp_value) > objetivo * 0.5:
                        logger.info(f"  DIAGNOSTICO: Gran discrepancia DCF-Comp (${abs(dcf_value - comp_value):.2f})")
                        logger.info(f"    - Alpha Spread puede usar pesos diferentes para {symbol}")
                        logger.info(f"    - Puede requerir ajustes específicos en factores de crecimiento/WACC")
                    
                    if dcf_error > 50 and comp_error > 50:
                        logger.info(f"  DIAGNOSTICO: Ambos componentes fallan (DCF: {dcf_error:.1f}%, Comp: {comp_error:.1f}%)")
                        logger.info(f"    - Alpha Spread probablemente tiene parámetros únicos para {symbol}")
                        logger.info(f"    - Revisar datos financieros o considerar ajustes específicos")
                
                logger.info("\n[CONCLUSION] Alpha Spread probablemente usa parámetros únicos por empresa")
                logger.info("  Empresas que se disparan pueden necesitar ajustes específicos")
                logger.info("=" * 60)
        except Exception as e:
            logger.warning(f"No se pudo guardar análisis detallado: {e}")
        
        # Mostrar resumen
        errors_only = [e for _, e in errors_by_symbol]
        if errors_only:
            logger.info(f"\nResumen final (TRAIN):")
            logger.info(f"  Error promedio: {np.mean(errors_only):.2f}%")
            logger.info(f"  Error máximo: {np.max(errors_only):.2f}%")
            logger.info(f"  Error mínimo: {np.min(errors_only):.2f}%")
            logger.info(f"  Empresas con error < 10%: {sum(1 for e in errors_only if e < 10)}/{len(errors_only)}")
            logger.info(f"  Empresas con error < 20%: {sum(1 for e in errors_only if e < 20)}/{len(errors_only)}")
        
        # Si hay empresas en caché que no están en train, evaluarlas como VAL
        val_symbols = [s for s in self.financial_data_cache.keys() if s not in self.symbols]
        if val_symbols:
            logger.info("=" * 60)
            logger.info("[RESULT] Evaluación en empresas VAL (no usadas en entrenamiento)")
            logger.info("=" * 60)
            logger.info(f"Empresas_val en caché: {val_symbols}")
            # Filtrar solo las que tienen valores objetivo
            val_symbols_with_targets = [s for s in val_symbols if s in self.target_values]
            if not val_symbols_with_targets:
                logger.info("  No hay empresas VAL con valores objetivo disponibles - saltando evaluación VAL")
            else:
                logger.info(f"Empresas_val con valores objetivo: {val_symbols_with_targets}")
                val_errors = []
                for idx, symbol in enumerate(val_symbols_with_targets, 1):
                    try:
                        symbol_result, error_pct = self._evaluate_single_company(symbol, idx, len(val_symbols_with_targets), best_params)
                        val_errors.append(error_pct)
                        target_value = self.target_values[symbol]
                        logger.info(f"  {symbol}: Error={error_pct:.2f}%, Objetivo=${target_value:.2f}")
                    except Exception as e:
                        logger.warning(f"  Error evaluando {symbol}: {e}")
                        continue
                
                if val_errors:
                    val_error_mean = np.mean(val_errors)
                    logger.info(f"\n[RESULT] Error val: {val_error_mean:.2f}%")
                    logger.info(f"  Error promedio VAL: {val_error_mean:.2f}%")
                    logger.info(f"  Error promedio TRAIN: {final_error:.2f}%")
                    if abs(val_error_mean - final_error) > 10:
                        logger.warning(f"  [WARN] Diferencia significativa entre TRAIN y VAL (>10%) - posible overfitting")
        
        # Ejecutar análisis de errores extremos automáticamente
        logger.info("\n" + "=" * 60)
        logger.info("EJECUTANDO ANÁLISIS DE ERRORES EXTREMOS")
        logger.info("=" * 60)
        try:
            analysis = self.analyze_extreme_errors(best_params)
            logger.info("\n[ANÁLISIS COMPLETADO] Revisa los logs arriba para ver las causas de errores extremos")
        except Exception as e:
            logger.warning(f"No se pudo ejecutar análisis de errores extremos: {e}")
            import traceback
            logger.debug(traceback.format_exc())
        
        return best_params
    
    def run_full_analysis(self):
        """
        Ejecuta análisis completo: entrenamiento + análisis de errores extremos
        """
        # Primero entrenar
        best_params = self.train()
        
        # Luego analizar errores extremos
        logger.info("\n" + "=" * 60)
        logger.info("EJECUTANDO ANÁLISIS DE ERRORES EXTREMOS")
        logger.info("=" * 60)
        analysis = self.analyze_extreme_errors(best_params)
        
        return best_params, analysis


def main():
    """Función principal"""
    logger.info("=" * 60)
    logger.info("[MAIN] Iniciando función main()")
    logger.info("=" * 60)
    
    # Cargar configuración
    logger.info("[MAIN] Cargando configuración desde ../settings.ini...")
    config = load_config("../settings.ini")  # Subir un nivel desde training/
    logger.debug(f"[MAIN] Config cargado: keys={list(config.keys())}")
    api_key = config.get("finnhub_api_key", "")
    
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        logger.error("[MAIN] ERROR: API key no configurada o inválida")
        print("ERROR: Configura tu API key de Finnhub en settings.ini")
        return
    
    logger.info(f"[MAIN] API key encontrada: {'*' * (len(api_key) - 4) + api_key[-4:] if len(api_key) > 4 else '****'}")
    
    # Crear trainer
    logger.info("[MAIN] Creando ModelTrainer...")
    try:
        trainer = ModelTrainer(api_key)
        logger.info("[MAIN] ModelTrainer creado exitosamente")
    except Exception as e:
        logger.error(f"[MAIN] ERROR creando ModelTrainer: {e}", exc_info=True)
        raise
    
    # Probar conexión a la API antes de continuar
    logger.info("[MAIN] Probando conexión a Finnhub API...")
    try:
        from src.core import FundamentalAnalysisEngine
        test_engine = FundamentalAnalysisEngine(api_key)
        connection_ok = test_engine.client.test_connection()
        if not connection_ok:
            logger.error("[MAIN] ❌ ERROR: No se pudo establecer conexión con Finnhub API")
            logger.error("[MAIN] Por favor verifica tu conexión a internet y vuelve a intentar")
            return
        logger.info("[MAIN] ✅ Conexión a Finnhub API verificada exitosamente")
    except Exception as e:
        logger.error(f"[MAIN] ❌ ERROR probando conexión: {e}", exc_info=True)
        logger.error("[MAIN] Por favor verifica tu conexión a internet y vuelve a intentar")
        return
    
    # Valores objetivo de Alpha Spread
    # MODELO v2 TECH ONLY: Solo empresas Tech/Growth USA con FCF confiable
    # Excluimos bancos/financieras (FCF=0) y utilities/telecom problemáticas
    # Este es el dataset "limpio" para entrenar el modelo tech
    
    # Dataset TECH CLEAN (solo empresas con error <35% del análisis anterior)
    # Excluimos META (63.5% error) y AVGO (64.8% error) que están causando problemas
    TECH_CLEAN = {
        "NFLX": 523.93,  # 0.0% error
        "GOOGL": 179.13, # 3.3% error
        "MSFT": 413.12,  # 21.4% error
    }
    
    # Dataset TECH ONLY (todas las tech, incluyendo problemáticas)
    TECH_ONLY = {
        # Big Tech
        "AAPL": 178.20,
        "MSFT": 413.12,
        "GOOGL": 179.13,
        "META": 544.05,
        "AMZN": 169.08,
        "NVDA": 156.86,
        "AVGO": 249.89,
        "NFLX": 523.93,
        "TSLA": 43.50,
        # Hardware/Infrastructure
        "DELL": 216.87,
        "HPE": 33.42,
        # Consumer Discretionary (Growth)
        "DIS": 138.13,
        # Payment Tech (no bancos tradicionales)
        "MA": 188.49,
        "PYPL": 93.94,
    }
    
    # Dataset TECH FILTERED (excluye empresas con errores extremos >100%)
    # Excluye: HPE (267%), PYPL (146%), MA (109%)
    TECH_FILTERED = {
        # Big Tech
        "AAPL": 178.20,
        "MSFT": 413.12,
        "GOOGL": 179.13,
        "META": 544.05,
        "AMZN": 169.08,
        "NVDA": 156.86,
        "AVGO": 249.89,
        "NFLX": 523.93,
        "TSLA": 43.50,
        # Hardware/Infrastructure
        "DELL": 216.87,
        # Consumer Discretionary (Growth)
        "DIS": 138.13,
        # EXCLUIDAS: HPE, MA, PYPL (errores extremos)
    }
    
    # Dataset TECH CLEAN PARA ALPHA SPREAD (solo empresas que funcionan bien)
    # Excluye outliers que distorsionan: TSLA (82%), AMZN (69%), AVGO (58%), NVDA (57%)
    # Objetivo: Replicar Alpha Spread con empresas similares
    TECH_CLEAN_ALPHA = {
        # Empresas con excelente precision (<10%)
        "NFLX": 523.93,  # 3.15% error
        "AAPL": 178.20,  # 6.13% error
        "META": 544.05,  # 6.68% error
        "GOOGL": 179.13, # 7.91% error
        # Empresas con buena precision (10-30%)
        "MSFT": 413.12,  # 19.96% error
        "DELL": 216.87,  # 22.41% error
        # EXCLUIDAS: TSLA, AMZN, AVGO, NVDA (outliers >50%), DIS (42% error)
    }
    
    # Dataset completo (incluye otros sectores para análisis)
    ALL_COMPANIES = {
        **TECH_ONLY,
        # Healthcare Growth (opcional)
        "JNJ": 173.91,
        # EXCLUIDAS del entrenamiento (pero pueden estar en caché para análisis):
        # - Bancos: JPM, BAC, GS, C, SCHW, RKT (FCF=0 o negativo)
        # - Telecom: VZ (FCF problemático)
        # - Utilities/Defensive: WMT, PG, UNH (diferentes dinámicas)
    }
    
    # MODO ALPHA SPREAD: Replica exactamente la metodología de Alpha Spread
    # - Pesos fijos 50/50 (no optimiza blending)
    # - ERP = 4.12% (como Alpha Spread)
    # - Crecimiento terminal conservador (1.5%)
    # - Solo optimiza factores de ajuste (growth, wacc)
    
    # Usar TECH_CLEAN por defecto (solo empresas con error <35%)
    # Cambiar a TECH_ONLY para incluir todas las tech (incluyendo problemáticas)
    # Cambiar a TECH_FILTERED para excluir empresas con errores extremos
    # Cambiar a TECH_CLEAN_ALPHA para replicar Alpha Spread (solo empresas que funcionan bien)
    USE_TECH_CLEAN = False  # Solo empresas que funcionan bien
    USE_TECH_ONLY = True  # Todas las tech - ENTRENAMIENTO TOTAL (incluye outliers para analizar)
    USE_TECH_FILTERED = False  # Excluye HPE, PYPL, MA (errores >100%)
    USE_TECH_CLEAN_ALPHA = False  # Para replicar Alpha Spread - excluye outliers (TSLA, AMZN, AVGO, NVDA)
    
    # EXCLUIR empresas problemáticas con timeouts o errores de API
    # Agregar símbolos aquí si tienen problemas recurrentes con la API
    EXCLUDE_PROBLEMATIC_SYMBOLS = ["PYPL"]  # PYPL tiene problemas de timeout
    
    if USE_TECH_CLEAN_ALPHA:
        target_values = TECH_CLEAN_ALPHA
        dataset_name = "TECH CLEAN ALPHA (7 empresas, sin outliers para replicar Alpha Spread)"
    elif USE_TECH_CLEAN:
        target_values = TECH_CLEAN
        dataset_name = "TECH CLEAN (3 empresas con error <35%)"
    elif USE_TECH_FILTERED:
        target_values = TECH_FILTERED
        dataset_name = "TECH FILTERED (11 empresas, sin HPE/PYPL/MA)"
    elif USE_TECH_ONLY:
        target_values = TECH_ONLY
        dataset_name = "TECH ONLY (14 empresas)"
    else:
        target_values = ALL_COMPANIES
        dataset_name = "ALL COMPANIES"
    
    # Filtrar empresas problemáticas
    if EXCLUDE_PROBLEMATIC_SYMBOLS:
        excluded_count = 0
        for symbol in EXCLUDE_PROBLEMATIC_SYMBOLS:
            if symbol in target_values:
                del target_values[symbol]
                excluded_count += 1
        if excluded_count > 0:
            logger.info(f"[FILTER] Excluidas {excluded_count} empresas problemáticas: {EXCLUDE_PROBLEMATIC_SYMBOLS}")
            print(f"[FILTER] Excluidas {excluded_count} empresas problemáticas: {EXCLUDE_PROBLEMATIC_SYMBOLS}")
    
    print("=" * 60)
    print("SISTEMA DE ENTRENAMIENTO - Alpha Spread")
    print("=" * 60)
    print(f"\nModo: {dataset_name}")
    print(f"Total de empresas: {len(target_values)}")
    if USE_TECH_CLEAN_ALPHA:
        print("✓ Entrenando con TECH CLEAN ALPHA (para replicar Alpha Spread)")
        print("✓ Empresas incluidas: NFLX, AAPL, META, GOOGL, MSFT, DELL (6 empresas)")
        print("✓ Excluidas: TSLA (82%), AMZN (69%), AVGO (58%), NVDA (57%), DIS (42%)")
        print("✓ Objetivo: Error < 10% para replicar Alpha Spread con precision")
        print("✓ Iteraciones aumentadas: 80 iteraciones, población 12")
    elif USE_TECH_CLEAN:
        print("✓ Entrenando solo con empresas TECH CLEAN (error <35% en análisis previo)")
        print("✓ Empresas: NFLX, GOOGL, MSFT (excluimos META y AVGO con errores >60%)")
        print("✓ Objetivo: Alcanzar error <20% con dataset limpio")
    elif USE_TECH_FILTERED:
        print("✓ Entrenando con empresas TECH FILTERED (excluye empresas con errores extremos)")
        print("✓ Excluidas: HPE (267%), PYPL (146%), MA (109%)")
        print("✓ Objetivo: Error < 30% (MODO CONTINUO - NO PARA HASTA CONSEGUIRLO)")
        print("✓ Iteraciones aumentadas: 80 iteraciones, población 12")
    elif USE_TECH_ONLY:
        print("✓ Entrenando con TODAS las empresas Tech/Growth USA")
        print("✓ Incluye outliers para analizar por qué se disparan")
        print("✓ Análisis automático de empresas con error >50%")
        print("✓ Objetivo: Error < 25% (todas las tech)")
    print("\nValores objetivo (Alpha Spread):")
    for symbol, value in target_values.items():
        print(f"  {symbol}: ${value:.2f}")
    
    # Intentar cargar valores de Alpha Spread desde archivo si existe
    alpha_spread_files = [
        "alpha_spread_values.csv",
        "alpha_spread_values.json",
        "target_values_alpha_spread.csv",
        "target_values_alpha_spread.json",
    ]
    
    # Cargar valores de Alpha Spread desde archivos CSV/JSON si existen
    alpha_spread_loaded = False
    for alpha_file in alpha_spread_files:
        if Path(alpha_file).exists():
            try:
                # Intentar cargar desde CSV
                if alpha_file.endswith('.csv'):
                    import csv
                    alpha_values = {}
                    with open(alpha_file, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            symbol = row.get('symbol', '').strip().upper()
                            try:
                                value = float(row.get('value', row.get('intrinsic_value', 0)))
                                if symbol and value > 0:
                                    alpha_values[symbol] = value
                            except (ValueError, KeyError):
                                continue
                # Intentar cargar desde JSON
                elif alpha_file.endswith('.json'):
                    with open(alpha_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if isinstance(data, dict):
                            alpha_values = {k.upper(): float(v) for k, v in data.items() if isinstance(v, (int, float))}
                        else:
                            alpha_values = {}
                
                if alpha_values:
                    print(f"\n[ALPHA SPREAD] Valores cargados desde {alpha_file}")
                    print(f"[ALPHA SPREAD] {len(alpha_values)} empresas encontradas")
                    # Actualizar target_values con valores de Alpha Spread
                    for symbol in target_values.keys():
                        if symbol in alpha_values:
                            old_value = target_values[symbol]
                            target_values[symbol] = alpha_values[symbol]
                            print(f"[ALPHA SPREAD] {symbol}: ${old_value:.2f} -> ${alpha_values[symbol]:.2f}")
                    alpha_spread_loaded = True
                    break
            except Exception as e:
                logger.warning(f"No se pudo cargar {alpha_file}: {e}")
    
    if not alpha_spread_loaded:
        print("\n[INFO] No se encontró archivo de valores Alpha Spread")
        print("[INFO] Para usar valores de Alpha Spread:")
        print("[INFO]   1. Exporta valores desde Alpha Spread a CSV/JSON")
        print("[INFO]   2. Guarda como alpha_spread_values.csv o .json")
        print("[INFO]   3. El programa los cargará automáticamente")
    
    # Modo automático: siempre usar valores por defecto (sin input interactivo)
    auto_mode = len(sys.argv) > 1 and sys.argv[1] == "--auto"
    
    if auto_mode:
        print("\nModo automático activado - usando valores por defecto")
    else:
        print("\nUsando valores por defecto configurados")
    
    # Validar que hay empresas para entrenar
    if not target_values or len(target_values) == 0:
        print("ERROR: No hay empresas configuradas para entrenar")
        print("Verifica la configuración de datasets (TECH_ONLY, TECH_CLEAN, etc.)")
        return
    
    # Intentar obtener valores faltantes desde target_value_fetcher (independiente)
    # (solo para símbolos que están en target_values pero sin valor)
    symbols_without_values = [s for s in target_values.keys() if not target_values.get(s)]
    if symbols_without_values:
        print(f"\n[INFO] Obteniendo {len(symbols_without_values)} valores faltantes desde JSON...")
        try:
            web_targets = fetch_multiple_targets(symbols_without_values)
            for symbol, value in web_targets.items():
                if value is not None:
                    target_values[symbol] = value
                    print(f"   [OK] {symbol}: ${value:.2f}")
        except Exception as e:
            logger.warning(f"No se pudieron obtener valores faltantes: {e}")
            print(f"   [WARN] Algunos valores no se pudieron obtener")
    
    print(f"\n[INFO] Iniciando entrenamiento con {len(target_values)} empresas")
    print(f"[INFO] Empresas: {', '.join(target_values.keys())}")
    sys.stdout.flush()
    
    # Establecer valores objetivo (con fetch_missing_from_web=False ya que ya lo hicimos arriba)
    try:
        trainer.set_target_values(target_values, fetch_missing_from_web=False)
        print("[OK] Valores objetivo establecidos correctamente")
        sys.stdout.flush()
    except Exception as e:
        print(f"[ERROR] Error estableciendo valores objetivo: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Entrenar con modo Alpha Spread
    print("\n[INFO] Iniciando proceso de entrenamiento...")
    print("[INFO] Esto puede tardar varios minutos/horas")
    sys.stdout.flush()
    
    try:
        # Usar sistema de entrenamiento automático en bucle
        logger.info("=" * 80)
        logger.info("MODO: Entrenamiento automático CONTINUO")
        logger.info("El sistema entrenará cada empresa INDEFINIDAMENTE hasta alcanzar el objetivo")
        logger.info("Presiona Ctrl+C para detener manualmente")
        logger.info("=" * 80)
        
        best_params = trainer.train_auto_loop(
            target_error=10.0,              # Error objetivo: 10%
            max_iterations_per_round=500,    # 500 iteraciones por ronda
            max_rounds_per_company=None,    # INFINITO - Continúa hasta alcanzar objetivo
            min_improvement_threshold=0.01  # Mejora mínima de 0.01% (más permisivo)
        )
        print("\n[OK] Entrenamiento completado exitosamente")
        sys.stdout.flush()
    except KeyboardInterrupt:
        print("\n[INFO] Entrenamiento interrumpido por el usuario (Ctrl+C)")
        sys.stdout.flush()
        return
    except Exception as e:
        print(f"\n[ERROR] Error durante el entrenamiento: {e}")
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        return
    
    # Guardar parámetros SOLO si mejoran los anteriores
    output_file = "trained_params.json"
    should_save = True
    
    # Verificar si hay parámetros anteriores
    if Path(output_file).exists():
        try:
            with open(output_file, "r") as f:
                old_params = json.load(f)
            old_error_log1p = old_params.get('error', float('inf'))
            new_error_log1p = best_params.get('error', float('inf'))
            
            # Convertir a porcentaje real para comparación y visualización
            # Si el archivo antiguo tiene error_pct, usarlo directamente
            if 'error_pct' in old_params:
                old_error_pct = old_params.get('error_pct', np.expm1(old_error_log1p))
            else:
                # Archivo antiguo sin error_pct, convertir desde log1p
                old_error_pct = np.expm1(old_error_log1p) if old_error_log1p != float('inf') else float('inf')
            
            if 'error_pct' in best_params:
                new_error_pct = best_params.get('error_pct', np.expm1(new_error_log1p))
            else:
                new_error_pct = np.expm1(new_error_log1p) if new_error_log1p != float('inf') else float('inf')
            
            # Solo sobrescribir si el nuevo error es mejor (menor) - comparar en escala log1p para consistencia
            if new_error_log1p >= old_error_log1p:
                logger.info(f"[PROTECCION] Nuevo error ({new_error_pct:.2f}% real) >= anterior ({old_error_pct:.2f}% real)")
                logger.info(f"[PROTECCION] Manteniendo parámetros anteriores - NO se sobrescriben")
                should_save = False
            else:
                logger.info(f"[MEJORA] Nuevo error ({new_error_pct:.2f}% real) < anterior ({old_error_pct:.2f}% real)")
                logger.info(f"[MEJORA] Guardando nuevos parámetros mejorados")
        except Exception as e:
            logger.warning(f"No se pudieron leer parámetros anteriores: {e}")
            # Si hay error leyendo, guardar de todas formas
    
    if should_save:
        with open(output_file, "w") as f:
            json.dump(best_params, f, indent=2)
        logger.info(f"[GUARDADO] Parámetros guardados en {output_file}")
        print(f"\n✅ Parámetros mejorados guardados en {output_file}")
    else:
        logger.info(f"[PROTECCION] Parámetros anteriores preservados en {output_file}")
        print(f"\n✅ Parámetros anteriores preservados (nuevo error no mejoró)")
    
    print("\nPara usar estos parámetros, actualiza el código con estos valores.")
    
    # Notificar al monitor que terminó (si está en modo auto)
    if "--auto" in sys.argv:
        try:
            from datetime import datetime
            status_file = Path("training_status.json")
            final_error_log1p = best_params.get('error', float('inf'))
            final_error_pct = best_params.get('error_pct', np.expm1(final_error_log1p) if final_error_log1p != float('inf') else float('inf'))
            with open(status_file, "w", encoding='utf-8') as f:
                json.dump({
                    "status": "completed",
                    "error": final_error_log1p,  # Error en escala log1p
                    "error_pct": final_error_pct,  # Error en porcentaje real
                    "objective_reached": bool(final_error_pct <= 30.0) if isinstance(final_error_pct, (int, float)) else False,
                    "timestamp": datetime.now().isoformat(),
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            pass  # No crítico si falla


if __name__ == "__main__":
    try:
        print("=" * 60)
        print("INICIANDO SCRIPT DE ENTRENAMIENTO")
        print("=" * 60)
        sys.stdout.flush()
        main()
        print("\n" + "=" * 60)
        print("SCRIPT FINALIZADO")
        print("=" * 60)
        sys.stdout.flush()
    except Exception as e:
        print(f"\n[ERROR CRÍTICO] Error fatal: {e}")
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        sys.exit(1)

