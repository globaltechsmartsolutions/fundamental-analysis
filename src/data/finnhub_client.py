"""
Cliente para obtener datos financieros de Finnhub API
"""
import time
import logging
from typing import Dict, List, Optional, Any
from functools import lru_cache
import requests
from datetime import datetime, timedelta
import threading

logger = logging.getLogger(__name__)


class FinnhubClient:
    """Cliente para interactuar con Finnhub API"""
    
    # Semáforo compartido para limitar peticiones concurrentes (5 a la vez)
    # Esto permite paralelizar sin exceder rate limits
    # Con 5 concurrentes y intervalo de 1s: 5 peticiones cada segundo = 300/min teórico
    # Pero limitamos a 60/min con el rate limiter, así que: 5 concurrentes cada 5s = 60/min ✅
    _api_semaphore = threading.Semaphore(5)  # Máximo 5 peticiones concurrentes
    _last_call_lock = threading.Lock()  # Lock para thread-safety del rate limiter
    _shared_last_call_time = 0  # Última llamada compartida entre threads
    _call_count = 0  # Contador de llamadas en la ventana de tiempo
    _window_start = 0  # Inicio de la ventana de 60 segundos
    
    def __init__(self, api_key: str, cache_manager=None):
        self.api_key = api_key
        self.base_url = "https://finnhub.io/api/v1"
        self.last_call_time = 0
        # Finnhub free tier: 60 calls/min según documentación
        # Estrategia: Permitir 5 concurrentes, pero limitar a 60 llamadas por minuto
        # Esto permite paralelización real sin esperas innecesarias
        self.max_calls_per_minute = 60
        self.adaptive_interval = 0.0  # Sin espera inicial (solo se activa si hay rate limits)
        self.cache_manager = cache_manager  # CacheManager opcional para cachear datos
    
    def _rate_limit(self):
        """Rate limiting adaptativo thread-safe usando token bucket"""
        # Adquirir semáforo para limitar concurrencia
        self._api_semaphore.acquire()
        try:
            current_time = time.time()
            with self._last_call_lock:
                # Reiniciar contador si pasó 1 minuto
                if current_time - self._window_start >= 60:
                    self._call_count = 0
                    self._window_start = current_time
                
                # Si ya hicimos 60 llamadas en este minuto, esperar hasta que pase el minuto
                if self._call_count >= self.max_calls_per_minute:
                    wait_time = 60 - (current_time - self._window_start)
                    if wait_time > 0:
                        logger.debug(f"Rate limit: {self._call_count}/60 llamadas usadas, esperando {wait_time:.1f}s...")
                        time.sleep(wait_time)
                        self._call_count = 0
                        self._window_start = time.time()
                
                # Incrementar contador ANTES de hacer la llamada
                self._call_count += 1
                
                # Solo esperar si hay rate limits previos (adaptive_interval > 0.5s)
                # Esto permite máxima velocidad cuando no hay problemas
                if self.adaptive_interval > 0.5:
                    elapsed = current_time - self._shared_last_call_time
                    if elapsed < self.adaptive_interval:
                        time.sleep(self.adaptive_interval - elapsed)
                
                self._shared_last_call_time = time.time()
        finally:
            # Liberar semáforo después de hacer la petición
            pass  # Se libera después de la petición en _get
    
    def _release_semaphore(self):
        """Libera el semáforo después de completar la petición"""
        self._api_semaphore.release()
    
    def _get(self, endpoint: str, params: Dict[str, Any] = None, retries: int = 5) -> Dict:
        """Realiza petición GET a la API con retry en caso de rate limit"""
        self._rate_limit()  # Adquiere semáforo y aplica rate limiting
        try:
            if params is None:
                params = {}
            params['token'] = self.api_key
            
            url = f"{self.base_url}/{endpoint}"
            
            for attempt in range(retries):
                try:
                    # Timeout separado: 5s para conectar, 15s para leer respuesta (total max 20s)
                    # Esto evita bloqueos en DNS o conexión inicial
                    response = requests.get(
                        url, 
                        params=params, 
                        timeout=(5, 15),  # (connect_timeout, read_timeout)
                        stream=False  # No usar streaming para evitar bloqueos adicionales
                    )
                    
                    # Si hay rate limit, esperar más tiempo y aumentar intervalo adaptativo
                    if response.status_code == 429:
                        wait_time = (attempt + 1) * 10  # 10, 20, 30, 40, 50 segundos
                        # Aumentar intervalo adaptativo para futuras llamadas
                        self.adaptive_interval = min(self.adaptive_interval * 1.5, 2.0)  # Máximo 2 segundos
                        # Resetear contador para dar más espacio
                        with self._last_call_lock:
                            self._call_count = 0
                            self._window_start = time.time()
                        logger.warning(f"Rate limit detectado en {endpoint}, esperando {wait_time}s...")
                        logger.info(f"Intervalo adaptativo aumentado a {self.adaptive_interval:.2f}s")
                        time.sleep(wait_time)
                        continue
                    else:
                        # Si no hay rate limit, reducir gradualmente el intervalo adaptativo
                        if self.adaptive_interval > 0.5:
                            self.adaptive_interval = max(self.adaptive_interval * 0.98, 0.5)  # Mínimo 0.5s
                    
                    # Si hay error 5xx (servidor), esperar más
                    if 500 <= response.status_code < 600:
                        wait_time = (attempt + 1) * 5
                        logger.warning(f"Error del servidor ({response.status_code}) en {endpoint}, esperando {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    
                    response.raise_for_status()
                    return response.json()
                except requests.exceptions.Timeout as e:
                    error_type = "Timeout"
                    if attempt == retries - 1:
                        logger.error(f"⏱️ TIMEOUT final en {endpoint} después de {retries} intentos: {str(e)}")
                        logger.error(f"   Verifica tu conexión a internet o VPN")
                        raise
                    wait_time = (attempt + 1) * 3  # 3, 6, 9, 12, 15 segundos
                    logger.warning(f"⏱️ Timeout en {endpoint} (intento {attempt+1}/{retries}), esperando {wait_time}s...")
                    time.sleep(wait_time)
                except requests.exceptions.ConnectionError as e:
                    error_type = "ConnectionError"
                    if attempt == retries - 1:
                        logger.error(f"🔌 ERROR DE CONEXIÓN final en {endpoint} después de {retries} intentos")
                        logger.error(f"   Error: {str(e)}")
                        logger.error(f"   Verifica:")
                        logger.error(f"   - Tu conexión a internet")
                        logger.error(f"   - Si usas VPN, verifica que esté funcionando")
                        logger.error(f"   - Firewall/proxy que pueda estar bloqueando conexiones")
                        raise
                    wait_time = (attempt + 1) * 3  # 3, 6, 9, 12, 15 segundos
                    logger.warning(f"🔌 Error de conexión en {endpoint} (intento {attempt+1}/{retries}), esperando {wait_time}s...")
                    logger.debug(f"   Detalle: {str(e)}")
                    time.sleep(wait_time)
                except requests.exceptions.RequestException as e:
                    error_type = type(e).__name__
                    if attempt == retries - 1:
                        logger.error(f"❌ Error final en {endpoint} después de {retries} intentos: {error_type}: {str(e)}")
                        raise
                    wait_time = (attempt + 1) * 3  # 3, 6, 9, 12, 15 segundos
                    logger.warning(f"⚠️ Error en {endpoint} ({error_type}, intento {attempt+1}/{retries}), esperando {wait_time}s...")
                    time.sleep(wait_time)
            
            raise Exception(f"Failed to get {endpoint} after {retries} attempts")
        finally:
            # Liberar semáforo después de completar la petición
            self._release_semaphore()
    
    def get_company_profile(self, symbol: str) -> Dict:
        """
        Obtiene perfil de la empresa
        Usa caché persistente si está disponible (profiles no cambian frecuentemente)
        """
        # Intentar obtener del caché primero
        if self.cache_manager:
            cached = self.cache_manager.get('profile', symbol)
            if cached is not None:
                logger.debug(f"[{symbol}] Perfil obtenido del caché")
                return cached
        
        # Si no está en caché, obtener de la API
        profile = self._get("stock/profile2", {"symbol": symbol})
        
        # Guardar en caché si está disponible
        if self.cache_manager and profile:
            self.cache_manager.set('profile', symbol, profile)
            logger.debug(f"[{symbol}] Perfil guardado en caché")
        
        return profile
    
    def get_quote(self, symbol: str) -> Dict:
        """Obtiene precio actual de la acción"""
        return self._get("quote", {"symbol": symbol})
    
    def get_financials(self, symbol: str, statement: str = "bs", freq: str = "annual") -> Dict:
        """
        Obtiene estados financieros
        statement: 'bs' (balance sheet), 'ic' (income statement), 'cf' (cash flow)
        freq: 'annual' o 'quarterly'
        Usa caché persistente si está disponible (estados financieros cambian poco)
        """
        # Crear clave única para el caché (símbolo + statement + freq)
        cache_key = f"{symbol}_{statement}_{freq}"
        
        # Intentar obtener del caché primero
        if self.cache_manager:
            cached = self.cache_manager.get('financials', cache_key)
            if cached is not None:
                logger.debug(f"[{symbol}] Estados financieros ({statement}, {freq}) obtenidos del caché")
                return cached
        
        # Si no está en caché, obtener de la API
        financials = self._get("stock/financials-reported", {
            "symbol": symbol,
            "statement": statement,
            "freq": freq
        })
        
        # Guardar en caché si está disponible
        if self.cache_manager and financials:
            self.cache_manager.set('financials', cache_key, financials)
            logger.debug(f"[{symbol}] Estados financieros ({statement}, {freq}) guardados en caché")
        
        return financials
    
    def get_earnings(self, symbol: str) -> Dict:
        """Obtiene datos de earnings (ganancias) incluyendo surprise"""
        return self._get("stock/earnings", {"symbol": symbol})
    
    def get_financial_metrics(self, symbol: str, metric: str = "all") -> Dict:
        """
        Obtiene métricas financieras
        metric: 'all', 'price', 'valuation', 'growth', 'profitability', etc.
        Usa caché persistente si está disponible (métricas cambian poco)
        """
        # Crear clave única para el caché (símbolo + metric)
        cache_key = f"{symbol}_{metric}"
        
        # Intentar obtener del caché primero
        if self.cache_manager:
            cached = self.cache_manager.get('metrics', cache_key)
            if cached is not None:
                logger.debug(f"[{symbol}] Métricas financieras ({metric}) obtenidas del caché")
                return cached
        
        # Si no está en caché, obtener de la API
        metrics = self._get("stock/metric", {
            "symbol": symbol,
            "metric": metric
        })
        
        # Guardar en caché si está disponible
        if self.cache_manager and metrics:
            self.cache_manager.set('metrics', cache_key, metrics)
            logger.debug(f"[{symbol}] Métricas financieras ({metric}) guardadas en caché")
        
        return metrics
    
    def get_peers(self, symbol: str) -> List[str]:
        """
        Obtiene lista de empresas similares (peers)
        Usa caché persistente si está disponible (peers cambian poco)
        """
        # Intentar obtener del caché primero
        if self.cache_manager:
            cached = self.cache_manager.get('peers', symbol)
            if cached is not None:
                logger.debug(f"[{symbol}] Peers obtenidos del caché: {len(cached)} empresas")
                return cached
        
        # Si no está en caché, obtener de la API
        peers = self._get("stock/peers", {"symbol": symbol})
        
        # Guardar en caché si está disponible
        if self.cache_manager and peers:
            self.cache_manager.set('peers', symbol, peers)
            logger.debug(f"[{symbol}] Peers guardados en caché: {len(peers)} empresas")
        
        return peers
    
    def get_company_basic_financials(self, symbol: str) -> Dict:
        """
        Obtiene datos financieros básicos consolidados
        Incluye: revenue, netIncome, freeCashFlow, debt, cash, sharesOutstanding
        """
        # Obtener income statement para revenue y net income
        logger.debug(f"    [{symbol}] Obteniendo income statement...")
        income_statement = self.get_financials(symbol, statement="ic", freq="annual")
        
        # Delay mínimo entre peticiones (el rate limiter ya maneja el intervalo principal)
        # Reducido de 1s a 0.5s ya que el rate limiter de 2.5s es suficiente
        
        # Obtener balance sheet para debt y cash
        logger.debug(f"    [{symbol}] Obteniendo balance sheet...")
        balance_sheet = self.get_financials(symbol, statement="bs", freq="annual")
        
        # Obtener cash flow para free cash flow
        logger.debug(f"    [{symbol}] Obteniendo cash flow...")
        cash_flow = self.get_financials(symbol, statement="cf", freq="annual")
        
        # Obtener métricas para shares outstanding y ratios
        logger.debug(f"    [{symbol}] Obteniendo métricas financieras...")
        metrics = self.get_financial_metrics(symbol)
        
        # Obtener perfil para número de acciones
        logger.debug(f"    [{symbol}] Obteniendo perfil de empresa...")
        profile = self.get_company_profile(symbol)
        
        return {
            "income_statement": income_statement,
            "balance_sheet": balance_sheet,
            "cash_flow": cash_flow,
            "metrics": metrics,
            "profile": profile
        }
    
    def get_earnings_with_surprise(self, symbol: str) -> Optional[Dict]:
        """
        Obtiene earnings más recientes y verifica surprise EPS positivo
        Retorna None si no hay surprise positivo o no hay datos
        """
        earnings_data = self.get_earnings(symbol)
        
        if not earnings_data or not isinstance(earnings_data, list) or len(earnings_data) == 0:
            return None
        
        # Buscar el earnings más reciente con surprise positivo
        for earning in earnings_data:
            surprise = earning.get("surprise")
            if surprise is not None and surprise > 0:
                return earning
        
        return None
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """Obtiene precio actual de la acción"""
        quote = self.get_quote(symbol)
        if quote and "c" in quote:
            return quote["c"]  # 'c' es el precio de cierre actual
        return None
    
    def test_connection(self) -> bool:
        """
        Prueba la conexión a la API de Finnhub
        Retorna True si la conexión es exitosa, False en caso contrario
        """
        try:
            logger.info("🔍 Probando conexión a Finnhub API...")
            # Hacer una petición simple (quote de AAPL que siempre existe)
            test_response = self._get("quote", {"symbol": "AAPL"})
            if test_response and "c" in test_response:
                logger.info("✅ Conexión exitosa a Finnhub API")
                return True
            else:
                logger.warning("⚠️ Conexión establecida pero respuesta inesperada")
                return False
        except requests.exceptions.Timeout:
            logger.error("⏱️ TIMEOUT: No se pudo conectar a Finnhub API (timeout)")
            logger.error("   Verifica tu conexión a internet")
            return False
        except requests.exceptions.ConnectionError as e:
            logger.error("🔌 ERROR DE CONEXIÓN: No se pudo conectar a Finnhub API")
            logger.error(f"   Error: {str(e)}")
            logger.error("   Verifica:")
            logger.error("   - Tu conexión a internet")
            logger.error("   - Si usas VPN, verifica que esté funcionando")
            logger.error("   - Firewall/proxy que pueda estar bloqueando conexiones")
            return False
        except Exception as e:
            logger.error(f"❌ Error inesperado probando conexión: {type(e).__name__}: {str(e)}")
            return False
    
    def get_historical_growth_rates(self, symbol: str, years: int = 5, financials: Dict = None) -> Dict[str, float]:
        """
        Calcula tasas de crecimiento históricas
        Retorna: revenue_growth, earnings_growth, fcf_growth
        
        Args:
            symbol: Símbolo de la empresa
            years: Años de datos históricos a usar
            financials: Datos financieros ya obtenidos (opcional, evita peticiones duplicadas)
        """
        # Reutilizar datos si ya los tenemos (optimización)
        if financials is None:
            financials = self.get_company_basic_financials(symbol)
        
        # Extraer datos históricos de income statement
        income_data = financials.get("income_statement", {}).get("data", [])
        
        if len(income_data) < 2:
            return {"revenue_growth": 0.0, "earnings_growth": 0.0, "fcf_growth": 0.0}
        
        # Ordenar por fecha (más reciente primero)
        income_data.sort(key=lambda x: x.get("period", ""), reverse=True)
        
        # Calcular crecimiento de revenue
        revenue_growth = 0.0
        if len(income_data) >= 2:
            rev_current = income_data[0].get("revenue", 0)
            rev_previous = income_data[1].get("revenue", 0)
            if rev_previous > 0:
                revenue_growth = ((rev_current - rev_previous) / rev_previous) * 100
        
        # Calcular crecimiento de earnings
        earnings_growth = 0.0
        if len(income_data) >= 2:
            net_current = income_data[0].get("netIncome", 0)
            net_previous = income_data[1].get("netIncome", 0)
            if net_previous > 0:
                earnings_growth = ((net_current - net_previous) / net_previous) * 100
        
        # Calcular crecimiento de FCF
        cf_data = financials.get("cash_flow", {}).get("data", [])
        cf_data.sort(key=lambda x: x.get("period", ""), reverse=True)
        
        fcf_growth = 0.0
        if len(cf_data) >= 2:
            fcf_current = cf_data[0].get("freeCashFlow", 0) if "freeCashFlow" in cf_data[0] else 0
            fcf_previous = cf_data[1].get("freeCashFlow", 0) if "freeCashFlow" in cf_data[1] else 0
            if fcf_previous > 0:
                fcf_growth = ((fcf_current - fcf_previous) / fcf_previous) * 100
        
        return {
            "revenue_growth": revenue_growth,
            "earnings_growth": earnings_growth,
            "fcf_growth": fcf_growth
        }

