"""
Motor Principal de Análisis Fundamental
Filtra empresas con surprise EPS positivo y calcula valoración estilo Alpha Spread
Publica resultados a NATS para consumo del bot
"""
import json
import sys
import asyncio
from typing import List, Dict, Optional
from pathlib import Path
import configparser
import datetime

from ..data import FinnhubClient, FinancialDataExtractor, CacheManager
from .valuation_engine import ValuationEngine, ValuationResult
from .buy_decision import BuyDecisionEngine
from ..utils import setup_logging, get_logger
from ..publishers import FundamentalAnalysisPublisher
from ..valuation import CompanySpecificParams
from ..config import (
    get_strategy_for_sector,
    RISK_FREE_RATE,
    ALPHASPREAD_ERP,
    DEFAULT_TAX_RATE,
    PROJECTION_YEARS,
    DEFAULT_DCF_WEIGHT,
    DEFAULT_COMPARABLES_WEIGHT,
    get_terminal_growth_for_sector,
)

try:
    from nats.aio.client import Client as NATS
    NATS_AVAILABLE = True
except ImportError:
    NATS_AVAILABLE = False


class FundamentalAnalysisEngine:
    """Motor principal de análisis fundamental"""
    
    # Variable de clase para controlar que el mensaje de caché solo se muestre una vez
    _cache_init_logged = False
    
    def __init__(
        self,
        api_key: str,
        nats_client: Optional[NATS] = None,
        nats_subject_prefix: str = "fundamental",
        undervaluation_threshold: float = 25.0,
        logger=None,
        trained_params_path: Optional[str] = None,
        **kwargs
    ):
        """
        Args:
            api_key: API key de Finnhub
            nats_client: Cliente NATS (opcional)
            nats_subject_prefix: Prefijo para subjects NATS
            undervaluation_threshold: Umbral mínimo de infravaloración para comprar (%)
            logger: Logger (opcional, se crea uno si no se proporciona)
            trained_params_path: Ruta al archivo trained_params.json (opcional)
        """
        self.logger = logger or get_logger("engine")
        self.logger.debug(f"[ENGINE_INIT] Iniciando FundamentalAnalysisEngine...")
        
        # Inicializar CacheManager para todos los tipos de datos
        project_root = Path(__file__).parent.parent
        cache_dir = project_root / "var" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.logger.debug(f"[ENGINE_INIT] Cache directory: {cache_dir}")
        self.cache_manager = CacheManager(cache_dir)
        
        # Mostrar estadísticas del caché al iniciar (solo una vez para evitar ruido)
        if not FundamentalAnalysisEngine._cache_init_logged:
            cache_stats = self.cache_manager.get_stats()
            self.logger.info(f"Caché inicializado: {cache_stats}")
            FundamentalAnalysisEngine._cache_init_logged = True
        else:
            self.logger.debug(f"[ENGINE_INIT] Cache ya inicializado previamente, omitiendo mensaje")
        
        # Crear cliente Finnhub con CacheManager
        self.logger.debug(f"[ENGINE_INIT] Creando FinnhubClient con API key: {'*' * (len(api_key) - 4) + api_key[-4:] if len(api_key) > 4 else '****'}")
        self.client = FinnhubClient(api_key, cache_manager=self.cache_manager)
        self.logger.debug(f"[ENGINE_INIT] FinnhubClient creado exitosamente")
        self.extractor = FinancialDataExtractor(self.client)
        self.logger.debug(f"[ENGINE_INIT] FinancialDataExtractor creado exitosamente")
        
        # Cargar parámetros entrenados si están disponibles
        self.logger.debug(f"[ENGINE_INIT] Cargando parámetros entrenados desde: {trained_params_path}")
        self.trained_params = self._load_trained_params(trained_params_path)
        if self.trained_params:
            self.logger.info(f"Parametros entrenados cargados: growth_adj={self.trained_params.get('growth_adjustment_factor', 1.0):.3f}, "
                       f"wacc_adj={self.trained_params.get('wacc_adjustment_factor', 1.0):.3f}")
        else:
            self.logger.debug(f"[ENGINE_INIT] No se encontraron parámetros entrenados")
        
        # Valuation Engine - acepta parámetros DCF a través de kwargs
        # Extraer parámetros DCF de kwargs si existen
        dcf_kwargs = {
            'projection_years': kwargs.pop('projection_years', 10),
            'terminal_growth_rate': kwargs.pop('terminal_growth_rate', 2.5),
            'risk_free_rate': kwargs.pop('risk_free_rate', 4.5),
            'market_risk_premium': kwargs.pop('market_risk_premium', 5.8),
            'beta': kwargs.pop('beta', 1.0),
            'debt_to_equity': kwargs.pop('debt_to_equity', 0.3),
            'cost_of_debt': kwargs.pop('cost_of_debt', 5.0),
            'tax_rate': kwargs.pop('tax_rate', 21.0),
        }
        dcf_weight = kwargs.pop('dcf_weight', 0.5)
        comparables_weight = kwargs.pop('comparables_weight', 0.5)
        
        self.logger.debug(f"[ENGINE_INIT] Creando ValuationEngine con parámetros: "
                         f"dcf_weight={dcf_weight}, comparables_weight={comparables_weight}, "
                         f"projection_years={dcf_kwargs['projection_years']}, "
                         f"terminal_growth={dcf_kwargs['terminal_growth_rate']}, "
                         f"risk_free_rate={dcf_kwargs['risk_free_rate']}, "
                         f"market_risk_premium={dcf_kwargs['market_risk_premium']}")
        self.valuation_engine = ValuationEngine(
            dcf_weight=dcf_weight,
            comparables_weight=comparables_weight,
            **dcf_kwargs
        )
        self.logger.debug(f"[ENGINE_INIT] ValuationEngine creado exitosamente")
        self.buy_decision = BuyDecisionEngine(undervaluation_threshold)
        self.logger.debug(f"[ENGINE_INIT] BuyDecisionEngine creado con threshold={undervaluation_threshold}")
        self.logger.debug(f"[ENGINE_INIT] FundamentalAnalysisEngine inicializado completamente")
        
        # Inicializar NATS publisher si hay cliente NATS
        self.nats_client = nats_client
        self.nats_publisher = None
        if nats_client:
            self.nats_publisher = FundamentalAnalysisPublisher(nats_client, nats_subject_prefix)
    
    def _load_trained_params(self, trained_params_path: Optional[str] = None) -> Optional[Dict]:
        """
        Carga parámetros entrenados desde trained_params.json
        
        Returns:
            Dict con parámetros entrenados o None si no se encuentra
        """
        if trained_params_path is None:
            # Buscar en el directorio de training
            training_dir = Path(__file__).parent.parent / "training"
            trained_params_path = training_dir / "trained_params.json"
        
        trained_params_path = Path(trained_params_path)
        
        if not trained_params_path.exists():
            self.logger.debug(f"No se encontró archivo de parámetros entrenados: {trained_params_path}")
            return None
        
        try:
            with open(trained_params_path, 'r', encoding='utf-8') as f:
                params = json.load(f)
            
            # Validar que tiene los campos necesarios
            if 'growth_adjustment_factor' in params and 'wacc_adjustment_factor' in params:
                return params
            else:
                self.logger.warning(f"Archivo trained_params.json no tiene los campos necesarios")
                return None
        except Exception as e:
            self.logger.warning(f"Error cargando parámetros entrenados: {e}")
            return None
    
    
    def filter_companies_with_positive_surprise(self, symbols: List[str]) -> List[Dict]:
        """
        Filtra empresas con surprise EPS positivo
        
        Returns:
            Lista de dicts con symbol y surprise_eps
        """
        filtered = []
        
        self.logger.info(f"Analizando {len(symbols)} empresas para filtrar surprise EPS positivo")
        
        for i, symbol in enumerate(symbols, 1):
            try:
                self.logger.info(f"[{i}/{len(symbols)}] Verificando {symbol}...")
                
                # Verificar caché primero usando CacheManager
                earning = self.cache_manager.get('earnings', symbol)
                
                # Si no hay en caché o está expirado, obtener de la API
                if earning is None:
                    self.logger.info(f"[{symbol}] Obteniendo earnings de la API...")
                    earning = self.client.get_earnings_with_surprise(symbol)
                    self.logger.info(f"[{symbol}] Earnings obtenidos: {earning is not None}")
                    # Guardar en caché inmediatamente después de obtener
                    self.cache_manager.set('earnings', symbol, earning, save_immediately=True)
                
                if earning:
                    surprise = earning.get("surprise", 0)
                    actual_eps = earning.get("actual", 0)
                    estimate_eps = earning.get("estimate", 0)
                    
                    filtered.append({
                        "symbol": symbol,
                        "surprise_eps": surprise,
                        "actual_eps": actual_eps,
                        "estimate_eps": estimate_eps,
                        "period": earning.get("period", ""),
                        "year": earning.get("year", 0)
                    })
                    self.logger.info(f"{symbol}: Surprise EPS +{surprise:.2f} (Actual: {actual_eps:.2f}, Estimate: {estimate_eps:.2f})")
                else:
                    # Guardar también cuando no hay surprise (para evitar llamadas repetidas)
                    # Solo si no está ya en caché
                    if self.cache_manager.get('earnings', symbol) is None:
                        self.cache_manager.set('earnings', symbol, None, save_immediately=True)
                    self.logger.debug(f"{symbol}: Sin surprise EPS positivo")
            
            except Exception as e:
                self.logger.warning(f"Error verificando {symbol}: {e}", exc_info=True)
                continue
        
        # El caché se guarda automáticamente por CacheManager cuando se actualiza
        
        self.logger.info(f"Encontradas {len(filtered)} empresas con surprise EPS positivo de {len(symbols)} analizadas")
        return filtered
    
    def calculate_valuation_for_symbol(
        self,
        symbol: str,
        surprise_eps: Optional[float] = None
    ) -> Optional[ValuationResult]:
        """
        Calcula valoración completa para un símbolo
        """
        try:
            self.logger.info(f"Calculando valoración para {symbol}...")
            
            # Extraer datos financieros
            self.logger.info(f"[{symbol}] Extrayendo datos financieros básicos...")
            financial_data = self.extractor.extract_basic_financials(symbol)
            self.logger.info(f"[{symbol}] Datos financieros extraídos: {financial_data is not None}")
            if not financial_data:
                self.logger.warning(f"No se pudieron obtener datos financieros para {symbol}")
                return None
            
            self.logger.info(f"{symbol} - Datos extraídos:")
            self.logger.info(f"  Precio: ${financial_data['current_price']:.2f}")
            self.logger.info(f"  FCF: ${financial_data['free_cash_flow']:.2f} (¿millones?)")
            self.logger.info(f"  Shares Outstanding: {financial_data['shares_outstanding']:.2f} (¿millones?)")
            self.logger.info(f"  EPS: ${financial_data['eps']:.2f}")
            self.logger.info(f"  Market Cap: ${financial_data['market_cap']:.2f} (¿millones?)")
            self.logger.info(f"  Revenue: ${financial_data['revenue']:.2f} (¿millones?)")
            self.logger.info(f"  Net Income: ${financial_data['net_income']:.2f} (¿millones?)")
            
            # Obtener tasas de crecimiento históricas
            growth_rates = self.client.get_historical_growth_rates(symbol)
            
            # NUEVO ENFOQUE: Usar estrategia por sector + modelos específicos por empresa
            sector = financial_data.get("sector", "Unknown")
            
            # 1. PRIORIDAD: Intentar cargar modelo específico entrenado por empresa (si existe)
            # Estos modelos tienen parámetros optimizados específicamente para esta empresa
            models_dir = Path("models")
            company_model = CompanySpecificParams.load_model(symbol, models_dir)
            
            if company_model and 'growth_adjustment_factor' in company_model and 'wacc_adjustment_factor' in company_model:
                # Usar modelo específico entrenado (tiene máxima prioridad)
                self.logger.info(f"{symbol} - ✅ Usando modelo específico entrenado (prioridad máxima)")
                company_params = company_model.copy()
                # Asegurar que tiene todos los campos necesarios
                if 'dcf_weight' not in company_params:
                    company_params['dcf_weight'] = company_model.get('dcf_weight', 0.5)
                if 'comparables_weight' not in company_params:
                    company_params['comparables_weight'] = company_model.get('comparables_weight', 0.5)
                
                self.logger.info(f"{symbol} - Parámetros específicos entrenados:")
                self.logger.info(f"  • Growth Adjustment: {company_params['growth_adjustment_factor']:.3f}")
                self.logger.info(f"  • WACC Adjustment: {company_params['wacc_adjustment_factor']:.3f}")
                self.logger.info(f"  • Pesos: DCF={company_params.get('dcf_weight', 0.5):.1%}, Comp={company_params.get('comparables_weight', 0.5):.1%}")
                if 'error' in company_model:
                    self.logger.info(f"  • Error entrenamiento: {company_model['error']:.2f}%")
            else:
                # 2. FALLBACK: Calcular parámetros dinámicos específicos por empresa
                self.logger.debug(f"{symbol} - Calculando parámetros dinámicos específicos")
                company_params_obj = CompanySpecificParams(
                    symbol=symbol,
                    financial_data=financial_data,
                    growth_rates=growth_rates
                )
                company_params = company_params_obj.get_all_params()
                
                # 3. FALLBACK: Usar factores de ajuste globales entrenados si están disponibles
                # Solo si NO hay modelo específico entrenado
                if self.trained_params:
                    old_growth = company_params.get('growth_adjustment_factor', 1.0)
                    old_wacc = company_params.get('wacc_adjustment_factor', 1.0)
                    
                    company_params['growth_adjustment_factor'] = self.trained_params.get('growth_adjustment_factor', 1.0)
                    company_params['wacc_adjustment_factor'] = self.trained_params.get('wacc_adjustment_factor', 1.0)
                    
                    # También usar los pesos entrenados si están disponibles
                    if 'dcf_weight' in self.trained_params:
                        company_params['dcf_weight'] = self.trained_params['dcf_weight']
                    if 'comparables_weight' in self.trained_params:
                        company_params['comparables_weight'] = self.trained_params['comparables_weight']
                    
                    self.logger.info(f"{symbol} - Aplicando parámetros globales entrenados:")
                    self.logger.info(f"  • Growth Adjustment: {old_growth:.3f} → {company_params['growth_adjustment_factor']:.3f}")
                    self.logger.info(f"  • WACC Adjustment: {old_wacc:.3f} → {company_params['wacc_adjustment_factor']:.3f}")
                    self.logger.info(f"  • Pesos: DCF={company_params.get('dcf_weight', 0.5):.1%}, Comp={company_params.get('comparables_weight', 0.5):.1%}")
                else:
                    self.logger.debug(f"{symbol} - Usando parámetros calculados dinámicamente (sin entrenamiento)")
            
            # 2. Obtener estrategia por sector
            try:
                self.logger.info(f"{symbol} - Obteniendo estrategia para sector: {sector}")
                strategy = get_strategy_for_sector(sector)
                self.logger.info(f"{symbol} - Estrategia obtenida: {strategy.__class__.__name__}")
            except Exception as e:
                self.logger.error(f"{symbol} - ERROR obteniendo estrategia: {e}", exc_info=True)
                raise
            
            # 3. Obtener promedios del sector
            self.logger.info(f"{symbol} - Obteniendo promedios del sector...")
            sector_averages = self.extractor.get_sector_averages(symbol, financial_data)
            self.logger.info(f"{symbol} - Promedios del sector obtenidos")
            
            # 4. Calcular valoración usando estrategia del sector
            self.logger.info(f"{symbol} - Iniciando cálculo de valoración (DCF + Comparables)...")
            dcf_value, comparables_value, strategy_debug = strategy.calculate_valuation(
                symbol=symbol,
                financial_data=financial_data,
                growth_rates=growth_rates,
                sector_averages=sector_averages,
                company_params=company_params
            )
            self.logger.info(f"{symbol} - Valoración calculada: DCF=${dcf_value:.2f}, Comparables=${comparables_value:.2f}")
            
            # 5. Blend con pesos específicos de la empresa
            dcf_weight = company_params.get('dcf_weight', DEFAULT_DCF_WEIGHT)
            comparables_weight = company_params.get('comparables_weight', DEFAULT_COMPARABLES_WEIGHT)
            
            # Para financieras con DCF=0, usar solo Comparables
            if dcf_value <= 0 and "financial" in sector.lower():
                dcf_weight = 0.0
                comparables_weight = 1.0
                self.logger.debug(f"{symbol} - Financiera con DCF=0, usando solo Comparables")
            
            blended_fair_value = (dcf_value * dcf_weight) + (comparables_value * comparables_weight)
            
            self.logger.debug(f"{symbol} - Tasa crecimiento FCF ajustada: {growth_rates.get('fcf_growth', 0):.2f}%")
            self.logger.debug(f"{symbol} - Pesos: DCF={dcf_weight:.1%}, Comparables={comparables_weight:.1%}")
            self.logger.debug(f"{symbol} - Valores: DCF=${dcf_value:.2f}, Comparables=${comparables_value:.2f}, Blended=${blended_fair_value:.2f}")
            
            # 6. Crear ValuationResult compatible con el formato esperado
            current_price = financial_data["current_price"]
            undervaluation_pct = ((blended_fair_value - current_price) / current_price) * 100 if current_price > 0 else 0.0
            
            # Determinar status
            if undervaluation_pct > 20:
                status = "undervalued"
            elif undervaluation_pct > 5:
                status = "slightly_undervalued"
            elif undervaluation_pct < -20:
                status = "overvalued"
            elif undervaluation_pct < -5:
                status = "slightly_overvalued"
            else:
                status = "fair"
            
            # Calcular ratios
            eps = financial_data.get("eps", 0)
            book_value_per_share = financial_data.get("book_value_per_share", 0)
            revenue_per_share = financial_data.get("revenue_per_share", 0)
            pe_ratio = current_price / eps if eps > 0 else None
            pb_ratio = current_price / book_value_per_share if book_value_per_share > 0 else None
            ps_ratio = current_price / revenue_per_share if revenue_per_share > 0 else None
            
            # Crear ValuationResult
            valuation = ValuationResult(
                symbol=symbol,
                current_price=current_price,
                blended_fair_value=blended_fair_value,
                undervaluation_percentage=undervaluation_pct,
                status=status,
                dcf_pessimistic=dcf_value * 0.9,  # Aproximación
                dcf_base=dcf_value,
                dcf_optimistic=dcf_value * 1.1,  # Aproximación
                comparables_value=comparables_value,
                surprise_eps=surprise_eps,
                pe_ratio=pe_ratio,
                pb_ratio=pb_ratio,
                ps_ratio=ps_ratio
            )
            
            self.logger.info(f"{symbol} - Valoración calculada: "
                            f"Precio=${valuation.current_price:.2f}, "
                            f"Valor Justo=${valuation.blended_fair_value:.2f}, "
                            f"Infravaloración={valuation.undervaluation_percentage:+.1f}%, "
                            f"Status={valuation.status}")
            
            return valuation
        
        except Exception as e:
            self.logger.error(f"Error calculando valoración para {symbol}: {e}", exc_info=True)
            return None
    
    async def analyze_companies_async(
        self,
        symbols: List[str],
        output_file: Optional[str] = None
    ) -> List[Dict]:
        """
        Analiza lista de empresas de forma asíncrona:
        1. Filtra por surprise EPS positivo
        2. Calcula valoración para cada una
        3. Determina decisión de compra
        4. Publica a NATS si está disponible
        5. Ordena por oportunidad (mayor infravaloración primero)
        
        Returns:
            Lista de dicts con resultados completos incluyendo decisión de compra
        """
        # Paso 1: Filtrar por surprise EPS positivo
        filtered_companies = self.filter_companies_with_positive_surprise(symbols)
        
        if not filtered_companies:
            self.logger.warning("No se encontraron empresas con surprise EPS positivo")
            return []
        
        # Paso 2: Calcular valoración y decisión de compra para cada una
        # MEJORA: Paralelizar procesamiento usando asyncio.gather
        self.logger.info(f"Calculando valoraciones estilo Alpha Spread para {len(filtered_companies)} empresas (paralelizado)...")
        
        async def process_company(company: Dict) -> Optional[Dict]:
            """Procesa una empresa individual y retorna resultado o None"""
            symbol = company["symbol"]
            surprise = company["surprise_eps"]
            
            try:
                valuation = self.calculate_valuation_for_symbol(symbol, surprise)
                
                if not valuation:
                    return None
                
                # Determinar decisión de compra
                buy_decision = self.buy_decision.should_buy(surprise, valuation)
                decision_details = self.buy_decision.get_decision_details(surprise, valuation)
                
                # Crear resultado completo
                result = {
                    "symbol": symbol,
                    "buy": buy_decision,
                    "intrinsic_value": round(valuation.blended_fair_value, 2),
                    "current_price": round(valuation.current_price, 2),
                    "valuation_percentage": round(valuation.undervaluation_percentage, 2),
                    "surprise_eps": surprise,
                    "status": valuation.status,
                    "dcf_base": round(valuation.dcf_base, 2),
                    "dcf_pessimistic": round(valuation.dcf_pessimistic, 2),
                    "dcf_optimistic": round(valuation.dcf_optimistic, 2),
                    "comparables_value": round(valuation.comparables_value, 2),
                    "decision_reason": decision_details["reason"],
                    "timestamp": datetime.datetime.now().isoformat()
                }
                
                # Log de decisión
                buy_emoji = "COMPRAR" if buy_decision else "NO COMPRAR"
                self.logger.info(
                    f"{buy_emoji} {symbol}: "
                    f"Precio=${result['current_price']:.2f}, "
                    f"Valor=${result['intrinsic_value']:.2f}, "
                    f"Valoración={result['valuation_percentage']:+.1f}%, "
                    f"Razón: {decision_details['reason']}"
                )
                
                # Publicar a NATS si está disponible
                if self.nats_publisher:
                    try:
                        subject, payload = await self.nats_publisher.publish_valuation(
                            symbol=symbol,
                            buy=buy_decision,
                            intrinsic_value=valuation.blended_fair_value,
                            current_price=valuation.current_price,
                            valuation_percentage=valuation.undervaluation_percentage
                        )
                        self.logger.debug(f"Publicado a NATS: {subject} - {json.dumps(payload)}")
                    except Exception as e:
                        self.logger.error(f"Error publicando {symbol} a NATS: {e}", exc_info=True)
                
                return result
            
            except Exception as e:
                self.logger.error(f"Error procesando {symbol}: {e}", exc_info=True)
                return None
        
        # Procesar todas las empresas en paralelo (máximo 5 concurrentes para evitar rate limits)
        # Usar asyncio.gather para paralelizar
        tasks = [process_company(company) for company in filtered_companies]
        results_raw = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filtrar resultados válidos y manejar excepciones
        results = []
        for i, result in enumerate(results_raw):
            if isinstance(result, Exception):
                symbol = filtered_companies[i]["symbol"]
                self.logger.error(f"Excepción procesando {symbol}: {result}", exc_info=True)
            elif result is not None:
                results.append(result)
        
        # Paso 3: Ordenar por oportunidad (mayor infravaloración primero)
        results.sort(key=lambda x: x["valuation_percentage"], reverse=True)
        
        # Paso 4: Guardar resultados si se especifica archivo
        if output_file:
            self.save_results(results, output_file)
        
        return results
    
    def analyze_companies(
        self,
        symbols: List[str],
        output_file: Optional[str] = None
    ) -> List[Dict]:
        """
        Versión síncrona que ejecuta analyze_companies_async
        """
        if self.nats_client:
            return asyncio.run(self.analyze_companies_async(symbols, output_file))
        else:
            # Sin NATS, ejecutar de forma síncrona sin publicación
            return asyncio.run(self.analyze_companies_async(symbols, output_file))
    
    def save_results(self, results: List[Dict], output_file: str):
        """Guarda resultados en archivo JSON"""
        output_data = {
            "timestamp": datetime.datetime.now().isoformat(),
            "total_companies": len(results),
            "buy_recommendations": sum(1 for r in results if r["buy"]),
            "results": results
        }
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        self.logger.info(f"Resultados guardados en: {output_file} ({len(results)} empresas)")


def load_config(config_path: str = "settings.ini") -> Dict:
    """Carga configuración desde settings.ini"""
    config = configparser.ConfigParser()
    
    if not Path(config_path).exists():
        return {}
    
    config.read(config_path)
    
    return {
        "finnhub_api_key": config.get("FINNHUB", "api_key", fallback=""),
        "symbols": [
            s.strip() 
            for s in config.get("SYMBOLS", "list", fallback="").split(",")
            if s.strip()
        ],
        "output_file": config.get("OUTPUT", "file", fallback="valuation_results.json"),
        "nats_url": config.get("NATS", "url", fallback=""),
        "nats_subject_prefix": config.get("NATS", "subject_prefix", fallback="fundamental"),
        "undervaluation_threshold": config.getfloat("BUY_DECISION", "undervaluation_threshold", fallback=25.0),
        "log_level": config.get("LOGGING", "level", fallback="INFO"),
        "log_dir": config.get("LOGGING", "dir", fallback="var/logs")
    }


async def connect_nats(url: str) -> Optional[NATS]:
    """Conecta a NATS si está disponible"""
    if not NATS_AVAILABLE:
        return None
    
    try:
        nc = NATS()
        await nc.connect(url)
        return nc
    except Exception as e:
        logger = get_logger("nats")
        logger.warning(f"No se pudo conectar a NATS en {url}: {e}")
        return None


async def main_async():
    """Función principal asíncrona"""
    logger = setup_logging()
    logger.info("=" * 60)
    logger.info("Fundamental Analysis Engine - Alpha Spread Style")
    logger.info("=" * 60)
    
    # Cargar configuración
    config = load_config()
    
    api_key = config.get("finnhub_api_key")
    if not api_key:
        logger.error("FINNHUB_API_KEY no encontrado en settings.ini")
        sys.exit(1)
    
    symbols = config.get("symbols", [])
    if not symbols:
        logger.error("No se especificaron símbolos en settings.ini")
        sys.exit(1)
    
    output_file = config.get("output_file", "valuation_results.json")
    nats_url = config.get("nats_url", "")
    nats_subject_prefix = config.get("nats_subject_prefix", "fundamental")
    undervaluation_threshold = config.get("undervaluation_threshold", 25.0)
    
    # Conectar a NATS si está configurado
    nats_client = None
    if nats_url:
        logger.info(f"Conectando a NATS en {nats_url}...")
        nats_client = await connect_nats(nats_url)
        if nats_client:
            logger.info("Conectado a NATS")
        else:
            logger.warning("Continuando sin NATS")
    
    # Cargar parámetros entrenados si están disponibles
    training_dir = Path(__file__).parent.parent / "training"
    trained_params_path = training_dir / "trained_params.json"
    
    # Crear engine y analizar
    engine = FundamentalAnalysisEngine(
        api_key=api_key,
        nats_client=nats_client,
        nats_subject_prefix=nats_subject_prefix,
        undervaluation_threshold=undervaluation_threshold,
        logger=logger,
        trained_params_path=trained_params_path if trained_params_path.exists() else None
    )
    
    results = await engine.analyze_companies_async(symbols, output_file)
    
    # Mostrar resumen final
    logger.info("=" * 60)
    logger.info("RESUMEN FINAL")
    logger.info("=" * 60)
    
    if results:
        buy_recommendations = [r for r in results if r["buy"]]
        no_buy = [r for r in results if not r["buy"]]
        
        logger.info(f"\nRecomendaciones de COMPRA: {len(buy_recommendations)}")
        logger.info(f"NO COMPRAR: {len(no_buy)}")
        
        if buy_recommendations:
            logger.info(f"\nTop 5 Oportunidades de COMPRA:")
            for i, r in enumerate(buy_recommendations[:5], 1):
                logger.info(f"  {i}. {r['symbol']}: {r['valuation_percentage']:+.1f}% "
                          f"(${r['current_price']:.2f} → ${r['intrinsic_value']:.2f})")
    else:
        logger.warning("No se obtuvieron resultados")
    
    logger.info("=" * 60)
    
    # Cerrar NATS si está conectado
    if nats_client:
        await nats_client.close()


def main():
    """Función principal síncrona"""
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
