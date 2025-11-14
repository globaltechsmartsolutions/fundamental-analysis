"""
Extractor de datos financieros desde Finnhub
Convierte datos de API a formato necesario para cálculos
"""
from typing import Dict, Optional
from functools import lru_cache
import threading
from .finnhub_client import FinnhubClient
from ..utils import get_logger

logger = get_logger("data_extractor")


class FinancialDataExtractor:
    """Extrae y procesa datos financieros para valoración"""
    
    def __init__(self, finnhub_client: FinnhubClient):
        self.client = finnhub_client
    
    def extract_basic_financials(self, symbol: str, raw_financials: Dict = None) -> Optional[Dict]:
        """
        Extrae datos financieros básicos necesarios para valoración
        
        Args:
            symbol: Símbolo de la empresa
            raw_financials: Datos financieros raw ya obtenidos (opcional, evita peticiones duplicadas)
        
        Retorna:
        {
            'revenue': float,
            'net_income': float,
            'eps': float,
            'free_cash_flow': float,
            'debt': float,
            'cash': float,
            'shares_outstanding': float,
            'book_value': float,
            'ebitda': float,
            'market_cap': float,
            'current_price': float
        }
        """
        try:
            # Optimización: obtener precio primero (más rápido) con timeout
            logger.debug(f"[{symbol}] Obteniendo precio actual...")
            current_price = None
            price_container = {'data': None, 'error': None}
            
            def fetch_price():
                try:
                    price_container['data'] = self.client.get_current_price(symbol)
                except Exception as e:
                    price_container['error'] = e
            
            price_thread = threading.Thread(target=fetch_price, daemon=True)
            price_thread.start()
            price_thread.join(timeout=10)
            logger.debug(f"[{symbol}] Precio obtenido: {price_container['data'] is not None}")
            
            if price_thread.is_alive():
                logger.warning(f"[{symbol}] Timeout obteniendo precio después de 10s")
                return None
            
            if price_container['error']:
                logger.warning(f"[{symbol}] Error obteniendo precio: {price_container['error']}")
                return None
            
            current_price = price_container['data']
            if not current_price or current_price <= 0:
                logger.warning(f"[{symbol}] No se pudo obtener precio actual o precio inválido: {current_price}")
                return None
            
            # VALIDACIÓN: Precio debe ser razonable
            if current_price > 100000:  # Precio muy alto (probable error)
                logger.warning(f"[{symbol}] Precio sospechosamente alto: ${current_price:.2f}, validando...")
                # Podría ser un split o error, pero continuamos con warning
            
            # Reutilizar datos raw si ya los tenemos (optimización)
            if raw_financials is None:
                # Obtener datos financieros consolidados (hace múltiples llamadas internas) con timeout
                logger.info(f"[{symbol}] Obteniendo datos financieros consolidados (puede tardar)...")
                financials = None
                financials_container = {'data': None, 'error': None}
                
                def fetch_financials():
                    try:
                        logger.debug(f"[{symbol}] Iniciando llamadas API para datos financieros...")
                        financials_container['data'] = self.client.get_company_basic_financials(symbol)
                        logger.debug(f"[{symbol}] Datos financieros obtenidos exitosamente")
                    except Exception as e:
                        logger.error(f"[{symbol}] Error en fetch_financials: {e}")
                        financials_container['error'] = e
                
                financials_thread = threading.Thread(target=fetch_financials, daemon=True)
                financials_thread.start()
                logger.debug(f"[{symbol}] Esperando datos financieros (timeout: 30s)...")
                financials_thread.join(timeout=30)  # 30s para múltiples llamadas API
                logger.debug(f"[{symbol}] Thread de datos financieros terminado: alive={financials_thread.is_alive()}")
                
                if financials_thread.is_alive():
                    logger.warning(f"[{symbol}] Timeout obteniendo datos financieros después de 30s")
                    return None
                
                if financials_container['error']:
                    logger.warning(f"[{symbol}] Error obteniendo datos financieros: {financials_container['error']}")
                    return None
                
                financials = financials_container['data']
            else:
                financials = raw_financials
            
            if not financials:
                logger.warning(f"[{symbol}] No se obtuvieron datos financieros")
                return None
            
            # Extraer datos del income statement más reciente
            income_statement = financials.get("income_statement", {})
            income_data = income_statement.get("data", [])
            if not income_data:
                logger.warning(f"[{symbol}] No hay datos de income statement. Estructura recibida: {list(financials.keys())}")
                return None
            
            # Ordenar por fecha (más reciente primero) - usar endDate o year
            income_data.sort(key=lambda x: (x.get("year", 0), x.get("quarter", 0)), reverse=True)
            latest_income_entry = income_data[0]
            latest_income_report = latest_income_entry.get("report", {})
            latest_income_items = latest_income_report.get("ic", []) if isinstance(latest_income_report, dict) else []
            
            # Extraer datos del balance sheet
            balance_data = financials.get("balance_sheet", {}).get("data", [])
            balance_data.sort(key=lambda x: (x.get("year", 0), x.get("quarter", 0)), reverse=True)
            latest_balance_entry = balance_data[0] if balance_data else {}
            latest_balance_report = latest_balance_entry.get("report", {})
            latest_balance_items = latest_balance_report.get("bs", []) if isinstance(latest_balance_report, dict) else []
            
            # Extraer datos del cash flow
            cf_data = financials.get("cash_flow", {}).get("data", [])
            cf_data.sort(key=lambda x: (x.get("year", 0), x.get("quarter", 0)), reverse=True)
            latest_cf_entry = cf_data[0] if cf_data else {}
            latest_cf_report = latest_cf_entry.get("report", {})
            latest_cf_items = latest_cf_report.get("cf", []) if isinstance(latest_cf_report, dict) else []
            
            # Precio ya obtenido arriba con timeout, reutilizamos el valor
            
            # Obtener perfil para shares outstanding
            profile = financials.get("profile", {})
            shares_outstanding = profile.get("shareOutstanding", 0)
            
            # IMPORTANTE: Finnhub devuelve shares outstanding en millones
            # Si viene en unidades, convertir a millones
            if shares_outstanding > 0 and shares_outstanding < 1:
                # Probablemente está en billones, convertir a millones
                shares_outstanding = shares_outstanding * 1000
            elif shares_outstanding > 1000000:
                # Probablemente está en unidades, convertir a millones
                shares_outstanding = shares_outstanding / 1000000
            
            # Si no está en el perfil, calcular desde market cap
            if shares_outstanding == 0 or shares_outstanding < 0.1:
                market_cap = profile.get("marketCapitalization", 0)
                # Market cap también está en millones
                if market_cap > 0 and current_price > 0:
                    shares_outstanding = market_cap / current_price  # Ya está en millones
                    print(f"DEBUG {symbol}: Calculado shares desde market cap: {shares_outstanding:.2f}M")
            
            # Debug removido - ya no necesario
            
            # IMPORTANTE: Los datos financieros de Finnhub están en UNIDADES ABSOLUTAS
            # Pero shares_outstanding está en MILLONES
            # Necesitamos convertir los valores financieros a MILLONES
            
            # Extraer valores del income statement usando conceptos GAAP
            revenue = 0
            net_income = 0
            ebit = 0
            depreciation = 0
            
            for item in latest_income_items:
                concept = item.get("concept", "")
                value = item.get("value", 0)
                
                if "RevenueFromContractWithCustomerExcludingAssessedTax" in concept or "Revenues" in concept:
                    revenue = value
                elif "NetIncomeLoss" in concept:
                    net_income = value
                elif "OperatingIncomeLoss" in concept or "IncomeLossFromContinuingOperationsBeforeIncomeTaxes" in concept:
                    ebit = value
                elif "DepreciationDepletionAndAmortization" in concept:
                    depreciation = value
            
            # Convertir a millones (dividir por 1,000,000)
            revenue_millions = revenue / 1_000_000 if revenue > 0 else 0
            net_income_millions = net_income / 1_000_000 if net_income > 0 else 0
            
            # VALIDACIÓN: Shares outstanding debe ser válido
            if shares_outstanding <= 0:
                logger.warning(f"[{symbol}] Shares outstanding inválido: {shares_outstanding}, intentando calcular desde market cap...")
                # Intentar calcular desde market cap si está disponible
                market_cap = profile.get("marketCapitalization", 0)
                if market_cap > 0 and current_price > 0:
                    shares_outstanding = market_cap / current_price
                    logger.info(f"[{symbol}] Shares calculados desde market cap: {shares_outstanding:.2f}M")
                else:
                    logger.error(f"[{symbol}] No se puede calcular shares: market_cap={market_cap}, price={current_price}")
                    return None
            
            # Calcular EPS (net income en millones / shares en millones = dólares por acción)
            eps = net_income_millions / shares_outstanding if shares_outstanding > 0 else 0
            
            # VALIDACIÓN: EPS debe ser razonable
            if eps < -100 or eps > 1000:  # EPS extremo (probable error)
                logger.warning(f"[{symbol}] EPS sospechosamente extremo: ${eps:.2f}, revisando datos...")
            
            # Free Cash Flow - buscar en report.cf usando conceptos GAAP
            free_cash_flow = 0
            operating_cf = 0
            capex = 0
            
            # Buscar dentro de latest_cf_items
            for item in latest_cf_items:
                concept = item.get("concept", "")
                value = item.get("value", 0)
                
                if "NetCashProvidedByUsedInOperatingActivities" in concept:
                    operating_cf = value
                elif "PaymentsToAcquirePropertyPlantAndEquipment" in concept or "CapitalExpenditures" in concept:
                    capex = abs(value)  # CapEx es negativo, tomar valor absoluto
                elif "FreeCashFlow" in concept:
                    # Si Finnhub ya proporciona FCF directamente, usarlo
                    free_cash_flow = value
            
            # Calcular FCF: Operating Cash Flow - CapEx
            # IMPORTANTE: Para empresas financieras, operating_cf puede ser negativo o no estar disponible
            # En ese caso, usar Net Income como proxy si está disponible
            if free_cash_flow == 0:
                if operating_cf != 0:
                    # Calcular FCF normalmente (puede ser negativo para empresas financieras)
                    free_cash_flow = operating_cf - capex
                elif net_income > 0:
                    # Fallback: usar Net Income como proxy para empresas financieras
                    # Las empresas financieras a menudo tienen FCF cercano a Net Income
                    logger.warning(f"[{symbol}] Operating CF no disponible, usando Net Income como proxy para FCF")
                    free_cash_flow = net_income * 0.9  # 90% de Net Income como estimación conservadora
                else:
                    logger.warning(f"[{symbol}] No se pudo calcular FCF: Operating CF={operating_cf}, Net Income={net_income}")
                    free_cash_flow = 0
            
            # Convertir FCF a millones (mantener negativo si es negativo)
            if free_cash_flow != 0:
                free_cash_flow_millions = free_cash_flow / 1_000_000
            else:
                free_cash_flow_millions = 0
            
            # Extraer valores del balance sheet usando conceptos GAAP
            total_debt = 0
            cash = 0
            book_value = 0
            
            for item in latest_balance_items:
                concept = item.get("concept", "")
                value = item.get("value", 0)
                
                if "CashAndCashEquivalentsAtCarryingValue" in concept:
                    cash = value
                elif "LongTermDebt" in concept or "Debt" in concept:
                    # Sumar deuda a corto y largo plazo
                    if "Current" in concept:
                        total_debt += value
                    elif "Noncurrent" in concept or "Noncurrent" not in concept:
                        total_debt += value
                elif "StockholdersEquity" in concept or "Equity" in concept:
                    book_value = value
            
            # Convertir a millones
            total_debt_millions = total_debt / 1_000_000 if total_debt > 0 else 0
            cash_millions = cash / 1_000_000 if cash > 0 else 0
            book_value_millions = book_value / 1_000_000 if book_value > 0 else 0
            book_value_per_share = book_value_millions / shares_outstanding if shares_outstanding > 0 else 0
            
            # EBITDA - calcular desde ebit + depreciation (ya extraídos arriba)
            ebitda = ebit + depreciation if ebit > 0 or depreciation > 0 else 0
            
            # Convertir EBITDA a millones
            ebitda_millions = ebitda / 1_000_000 if ebitda > 0 else 0
            
            # Convertir EBIT a millones (para márgenes operativos)
            ebit_millions = ebit / 1_000_000 if ebit > 0 else 0
            
            # Calcular márgenes operativos (como Alpha Spread)
            # Estos son ratios de rentabilidad distintos al "Margin of Safety" (margin de valoración)
            # 
            # MARGIN DE VALORACIÓN (Margin of Safety):
            #   - Se calcula en valuation_engine.calculate_undervaluation_percentage()
            #   - Formula: ((Intrinsic Value - Current Price) / Current Price) * 100
            #   - Es el "% Undervalued by X%" que muestra Alpha Spread
            #
            # MARGINS OPERATIVOS (Operating Margins):
            #   - Son ratios de rentabilidad: beneficio / ventas
            #   - Alpha Spread muestra: Gross, Operating, Net, FCF margins
            ebit_margin = (ebit_millions / revenue_millions * 100) if revenue_millions > 0 else 0
            ebitda_margin = (ebitda_millions / revenue_millions * 100) if revenue_millions > 0 else 0
            net_margin = (net_income_millions / revenue_millions * 100) if revenue_millions > 0 else 0
            fcf_margin = (free_cash_flow_millions / revenue_millions * 100) if revenue_millions > 0 else 0
            
            # Market cap (ya está en millones según el perfil)
            market_cap = profile.get("marketCapitalization", 0)
            if market_cap == 0:
                market_cap = current_price * shares_outstanding
            
            # Revenue per share (revenue en millones / shares en millones = dólares por acción)
            revenue_per_share = revenue_millions / shares_outstanding if shares_outstanding > 0 else 0
            
            # Extraer interest expense del income statement para calcular cost_of_debt real
            interest_expense = 0
            for item in latest_income_items:
                concept = item.get("concept", "")
                value = item.get("value", 0)
                if "InterestExpense" in concept or "InterestAndDebtExpense" in concept:
                    interest_expense = value
            interest_expense_millions = interest_expense / 1_000_000 if interest_expense > 0 else 0
            
            # Extraer shareholder equity del balance sheet para calcular debt_to_equity real
            shareholder_equity = 0
            for item in latest_balance_items:
                concept = item.get("concept", "")
                value = item.get("value", 0)
                if "StockholdersEquity" in concept or "Equity" in concept:
                    shareholder_equity = value
            shareholder_equity_millions = shareholder_equity / 1_000_000 if shareholder_equity > 0 else 0
            
            # Obtener beta real de métricas financieras
            beta = 1.0  # Default
            sector = "Unknown"  # Default
            
            try:
                metrics = raw_financials.get("metrics", {})
                if isinstance(metrics, dict):
                    metric_data = metrics.get("metric", {})
                    if isinstance(metric_data, dict):
                        beta_value = metric_data.get("beta", None)
                        if beta_value is not None and isinstance(beta_value, (int, float)):
                            beta = float(beta_value)
                            # Validar beta razonable (rango extendido para incluir empresas volátiles)
                            # Rango [0.3 - 5.0] permite betas extremos pero válidos (tech volátiles, emergentes)
                            if beta < 0.3 or beta > 5.0:
                                beta = 1.0
            except Exception as e:
                logger.debug(f"[{symbol}] No se pudo obtener beta de métricas: {e}")
            
            # Obtener sector del perfil
            try:
                profile = raw_financials.get("profile", {})
                if isinstance(profile, dict):
                    sector_value = profile.get("finnhubIndustry", "") or profile.get("industry", "")
                    if sector_value:
                        sector = sector_value
            except Exception as e:
                logger.debug(f"[{symbol}] No se pudo obtener sector del perfil: {e}")
            
            return {
                "revenue": revenue_millions,  # En millones
                "net_income": net_income_millions,  # En millones
                "eps": eps,  # Dólares por acción
                "free_cash_flow": free_cash_flow_millions,  # En millones
                "debt": total_debt_millions,  # En millones
                "cash": cash_millions,  # En millones
                "shares_outstanding": shares_outstanding,  # En millones
                "book_value": book_value_millions,  # En millones
                "book_value_per_share": book_value_per_share,  # Dólares por acción
                "ebitda": ebitda_millions,  # En millones
                "ebit": ebit_millions,  # En millones (para márgenes operativos)
                "ebit_margin": ebit_margin,  # % (EBIT / Revenue) - Operating Margin
                "ebitda_margin": ebitda_margin,  # % (EBITDA / Revenue) - EBITDA Margin
                "net_margin": net_margin,  # % (Net Income / Revenue) - Net Margin
                "fcf_margin": fcf_margin,  # % (FCF / Revenue) - FCF Margin
                "market_cap": market_cap,  # En millones
                "current_price": current_price,  # Dólares por acción
                "revenue_per_share": revenue_per_share,  # Dólares por acción
                "interest_expense": interest_expense_millions,  # En millones (para cost_of_debt)
                "shareholder_equity": shareholder_equity_millions,  # En millones (para debt_to_equity)
                "beta": beta,  # Beta real de la empresa (obtenido de Finnhub metrics)
                "sector": sector  # Sector de la empresa
            }
        
        except Exception as e:
            logger.error(f"[{symbol}] Error extrayendo datos: {e}", exc_info=True)
            return None
    
    def get_sector_averages(self, symbol: str, financial_data: Dict) -> Dict[str, float]:
        """
        Obtiene promedios del sector calculando múltiplos REALES de peers
        
        MEJORA: Ahora calcula promedios reales iterando sobre peers en lugar de usar valores fijos.
        Si no hay suficientes peers o fallan las llamadas, usa fallback a estimaciones.
        
        Según Alpha Spread, el algoritmo considera:
        1. Valores históricos del múltiplo
        2. Perspectivas de crecimiento (empresas con alto crecimiento = múltiplos más altos)
        3. Valores del múltiplo de la industria (REALES de peers)
        """
        try:
            # Obtener lista de peers con timeout para evitar bloqueos
            logger.info(f"[{symbol}] Obteniendo lista de peers de la API...")
            timeout_seconds = 10  # Timeout corto para evitar bloqueos largos
            
            peers = None
            peers_container = {'data': None, 'error': None}
            
            def fetch_peers():
                try:
                    peers_container['data'] = self.client.get_peers(symbol)
                except Exception as e:
                    peers_container['error'] = e
            
            peers_thread = threading.Thread(target=fetch_peers, daemon=True)
            peers_thread.start()
            peers_thread.join(timeout=timeout_seconds)
            
            if peers_thread.is_alive():
                logger.warning(f"[{symbol}] Timeout obteniendo peers después de {timeout_seconds}s, usando fallback")
                raise ValueError(f"Timeout obteniendo peers para {symbol}")
            
            if peers_container['error']:
                logger.warning(f"[{symbol}] Error obteniendo peers: {peers_container['error']}")
                raise ValueError(f"Error obteniendo peers para {symbol}: {peers_container['error']}")
            
            peers = peers_container['data']
            
            # Validar que peers es una lista válida
            if not isinstance(peers, list):
                logger.warning(f"[{symbol}] Respuesta de peers no es una lista: {type(peers)}")
                raise ValueError(f"Respuesta de peers inválida para {symbol}")
            
            if not peers or len(peers) == 0:
                logger.error(f"[{symbol}] No se obtuvieron peers de la API")
                raise ValueError(f"No se pudieron obtener peers para {symbol}")
            
            logger.info(f"[{symbol}] ✅ Obtenidos {len(peers)} peers de la API, procesando hasta 5...")
            
            current_price = financial_data.get("current_price", 0)
            eps = financial_data.get("eps", 0)
            book_value_per_share = financial_data.get("book_value_per_share", 0)
            revenue_per_share = financial_data.get("revenue_per_share", 0)
            
            current_pe = current_price / eps if eps > 0 else None
            current_pb = current_price / book_value_per_share if book_value_per_share > 0 else None
            current_ps = current_price / revenue_per_share if revenue_per_share > 0 else None
            
            # MEJORA: Calcular múltiplos REALES de peers
            peer_pes = []
            peer_pbs = []
            peer_pss = []
            peer_ev_ebitdas = []
            
            # Limitar a máximo 3 peers para balancear precisión vs coste de API
            # Con caché implementado, esto reduce de 31 a 19 llamadas API por empresa
            peers_to_process = peers[:3] if isinstance(peers, list) and len(peers) > 0 else []
            logger.info(f"[{symbol}] Procesando {len(peers_to_process)} peers (limitado a 3 para optimizar coste de API)")
            
            logger.info(f"[{symbol}] Calculando múltiplos de {len(peers_to_process)} peers...")
            
            for idx, peer_symbol in enumerate(peers_to_process, 1):
                try:
                    logger.info(f"[{symbol}] Procesando peer {idx}/{len(peers_to_process)}: {peer_symbol}")
                    # Usar timeout con threading para evitar bloqueos en llamadas API
                    timeout_seconds = 10  # Timeout por peer (10 segundos)
                    
                    # Obtener precio del peer con timeout
                    logger.debug(f"[{symbol}] Obteniendo precio de peer {peer_symbol}...")
                    peer_price = None
                    price_container = {'data': None, 'error': None}
                    
                    def fetch_price():
                        try:
                            price_container['data'] = self.client.get_current_price(peer_symbol)
                        except Exception as e:
                            price_container['error'] = e
                    
                    price_thread = threading.Thread(target=fetch_price, daemon=True)
                    price_thread.start()
                    price_thread.join(timeout=timeout_seconds)
                    
                    if price_thread.is_alive():
                        logger.warning(f"[{symbol}] Timeout obteniendo precio de peer {peer_symbol} después de {timeout_seconds}s")
                        continue
                    
                    if price_container['error']:
                        logger.warning(f"[{symbol}] Error obteniendo precio de peer {peer_symbol}: {price_container['error']}")
                        continue
                    
                    peer_price = price_container['data']
                    if not peer_price or peer_price <= 0:
                        logger.debug(f"[{symbol}] Precio inválido para peer {peer_symbol}: {peer_price}")
                        continue
                    
                    logger.debug(f"[{symbol}] Precio de peer {peer_symbol} obtenido: ${peer_price:.2f}")
                    
                    # Obtener métricas financieras básicas del peer con timeout
                    # IMPORTANTE: get_company_basic_financials hace 5 llamadas API secuenciales
                    # (income statement, balance sheet, cash flow, metrics, profile)
                    # Cada una puede tardar hasta 10s, más rate limiting entre llamadas
                    # Necesitamos timeout más largo: 5 llamadas x 10s + rate limiting = ~60s
                    logger.debug(f"[{symbol}] Obteniendo datos financieros de peer {peer_symbol}...")
                    peer_financials = None
                    financials_container = {'data': None, 'error': None}
                    
                    def fetch_financials():
                        try:
                            financials_container['data'] = self.client.get_company_basic_financials(peer_symbol)
                        except Exception as e:
                            financials_container['error'] = e
                    
                    financials_thread = threading.Thread(target=fetch_financials, daemon=True)
                    financials_thread.start()
                    # Timeout más largo para múltiples llamadas API: 60 segundos
                    financials_timeout = 60
                    financials_thread.join(timeout=financials_timeout)
                    
                    if financials_thread.is_alive():
                        logger.warning(f"[{symbol}] Timeout obteniendo datos financieros de peer {peer_symbol} después de {financials_timeout}s")
                        continue
                    
                    if financials_container['error']:
                        logger.warning(f"[{symbol}] Error obteniendo datos financieros de peer {peer_symbol}: {financials_container['error']}")
                        continue
                    
                    peer_financials = financials_container['data']
                    if not peer_financials:
                        logger.debug(f"[{symbol}] No se obtuvieron datos financieros para peer {peer_symbol}")
                        continue
                    
                    logger.debug(f"[{symbol}] Datos financieros de peer {peer_symbol} obtenidos exitosamente")
                    
                    # Extraer datos básicos del peer (esto es rápido, no necesita timeout)
                    logger.debug(f"[{symbol}] Extrayendo datos básicos de peer {peer_symbol}...")
                    peer_data = self.extract_basic_financials(peer_symbol, raw_financials=peer_financials)
                    if not peer_data:
                        logger.debug(f"[{symbol}] No se pudieron extraer datos básicos de peer {peer_symbol}")
                        continue
                    
                    logger.debug(f"[{symbol}] Datos básicos de peer {peer_symbol} extraídos exitosamente")
                    peer_eps = peer_data.get("eps", 0)
                    peer_bvps = peer_data.get("book_value_per_share", 0)
                    peer_rps = peer_data.get("revenue_per_share", 0)
                    peer_market_cap = peer_data.get("market_cap", 0)
                    peer_debt = peer_data.get("debt", 0)
                    peer_cash = peer_data.get("cash", 0)
                    peer_ebitda = peer_data.get("ebitda", 0)
                    
                    # Calcular múltiplos del peer
                    if peer_eps > 0:
                        peer_pe = peer_price / peer_eps
                        if 5 < peer_pe < 200:  # Validar P/E razonable
                            peer_pes.append(peer_pe)
                            logger.debug(f"[{symbol}] Peer {peer_symbol} P/E: {peer_pe:.2f}")
                    
                    if peer_bvps > 0:
                        peer_pb = peer_price / peer_bvps
                        if 0.5 < peer_pb < 50:  # Validar P/B razonable
                            peer_pbs.append(peer_pb)
                            logger.debug(f"[{symbol}] Peer {peer_symbol} P/B: {peer_pb:.2f}")
                    
                    if peer_rps > 0:
                        peer_ps = peer_price / peer_rps
                        if 0.5 < peer_ps < 100:  # Validar P/S razonable
                            peer_pss.append(peer_ps)
                            logger.debug(f"[{symbol}] Peer {peer_symbol} P/S: {peer_ps:.2f}")
                    
                    # Calcular EV/EBITDA del peer
                    if peer_ebitda > 0:
                        # EV = Market Cap + Debt - Cash
                        peer_ev = peer_market_cap + peer_debt - peer_cash
                        peer_ev_ebitda = peer_ev / peer_ebitda if peer_ebitda > 0 else None
                        if peer_ev_ebitda and 2 < peer_ev_ebitda < 50:  # Validar EV/EBITDA razonable
                            peer_ev_ebitdas.append(peer_ev_ebitda)
                            logger.debug(f"[{symbol}] Peer {peer_symbol} EV/EBITDA: {peer_ev_ebitda:.2f}")
                    
                    logger.info(f"[{symbol}] ✅ Peer {peer_symbol} procesado exitosamente")
                
                except Exception as e:
                    logger.warning(f"[{symbol}] Error obteniendo datos de peer {peer_symbol}: {e}", exc_info=True)
                    continue  # Continuar con siguiente peer
            
            logger.info(f"[{symbol}] Procesamiento de peers completado. Múltiplos obtenidos: P/E={len(peer_pes)}, P/B={len(peer_pbs)}, P/S={len(peer_pss)}, EV/EBITDA={len(peer_ev_ebitdas)}")
            
            # Calcular promedios de peers (si tenemos suficientes datos)
            sector_pe_estimate = None
            sector_pb_estimate = None
            sector_ps_estimate = None
            sector_ev_ebitda_estimate = None
            
            if len(peer_pes) >= 3:  # Mínimo 3 peers para calcular promedio
                sector_pe_estimate = sum(peer_pes) / len(peer_pes)
                logger.debug(f"[{symbol}] P/E sector promedio (de {len(peer_pes)} peers): {sector_pe_estimate:.2f}")
            elif len(peer_pes) > 0:
                # Si hay menos de 3, usar promedio pero con menos confianza
                sector_pe_estimate = sum(peer_pes) / len(peer_pes)
                logger.debug(f"[{symbol}] P/E sector promedio (solo {len(peer_pes)} peers, baja confianza): {sector_pe_estimate:.2f}")
            
            if len(peer_pbs) >= 3:
                sector_pb_estimate = sum(peer_pbs) / len(peer_pbs)
                logger.debug(f"[{symbol}] P/B sector promedio (de {len(peer_pbs)} peers): {sector_pb_estimate:.2f}")
            elif len(peer_pbs) > 0:
                sector_pb_estimate = sum(peer_pbs) / len(peer_pbs)
            
            if len(peer_pss) >= 3:
                sector_ps_estimate = sum(peer_pss) / len(peer_pss)
                logger.debug(f"[{symbol}] P/S sector promedio (de {len(peer_pss)} peers): {sector_ps_estimate:.2f}")
            elif len(peer_pss) > 0:
                sector_ps_estimate = sum(peer_pss) / len(peer_pss)
            
            if len(peer_ev_ebitdas) >= 3:
                sector_ev_ebitda_estimate = sum(peer_ev_ebitdas) / len(peer_ev_ebitdas)
                logger.debug(f"[{symbol}] EV/EBITDA sector promedio (de {len(peer_ev_ebitdas)} peers): {sector_ev_ebitda_estimate:.2f}")
            elif len(peer_ev_ebitdas) > 0:
                sector_ev_ebitda_estimate = sum(peer_ev_ebitdas) / len(peer_ev_ebitdas)
            
            # FALLBACK: Si no hay suficientes peers, usar estimaciones basadas en crecimiento
            if sector_pe_estimate is None:
                logger.debug(f"[{symbol}] No hay suficientes peers para P/E, usando estimación basada en crecimiento")
                growth_rates = self.client.get_historical_growth_rates(symbol)
                earnings_growth = growth_rates.get("earnings_growth", 0)
                if earnings_growth < 3.0:
                    earnings_growth = 6.0
                
                # Estimar P/E basado en crecimiento y P/E actual
                if current_pe:
                    sector_pe_estimate = current_pe * (1.0 + (earnings_growth / 100.0) * 0.15)
                    sector_pe_estimate = max(20.0, min(sector_pe_estimate, 40.0))
                else:
                    sector_pe_estimate = 30.0  # Default conservador
            
            if sector_pb_estimate is None:
                sector_pb_estimate = current_pb * 1.1 if current_pb else 9.5
                sector_pb_estimate = max(5.0, min(sector_pb_estimate, 15.0))
            
            if sector_ps_estimate is None:
                growth_rates = self.client.get_historical_growth_rates(symbol)
                revenue_growth = growth_rates.get("revenue_growth", 0)
                if revenue_growth < 3.0:
                    revenue_growth = 6.0
                
                if current_ps:
                    sector_ps_estimate = current_ps * (1.0 + (revenue_growth / 100.0) * 0.10)
                    sector_ps_estimate = max(3.0, min(sector_ps_estimate, 12.0))
                else:
                    sector_ps_estimate = 7.0  # Default
            
            if sector_ev_ebitda_estimate is None:
                sector_ev_ebitda_estimate = 14.0  # Default conservador para tech
            
            return {
                "pe": sector_pe_estimate,
                "pb": sector_pb_estimate if sector_pb_estimate else None,
                "ps": sector_ps_estimate if sector_ps_estimate else None,
                "ev_ebitda": sector_ev_ebitda_estimate
            }
        
        except Exception as e:
            logger.error(f"[{symbol}] ERROR crítico obteniendo promedios del sector: {e}")
            logger.error(f"[{symbol}] Traceback completo:", exc_info=True)
            # Solo usar fallback si es absolutamente necesario (error crítico)
            logger.warning(f"[{symbol}] Usando valores estimados como último recurso debido a error crítico")
            return self._get_default_sector_averages(symbol, financial_data)
    
    def _get_default_sector_averages(self, symbol: str, financial_data: Dict) -> Dict[str, float]:
        """
        Retorna valores por defecto para promedios del sector cuando no se pueden obtener peers
        """
        current_price = financial_data.get("current_price", 0)
        eps = financial_data.get("eps", 0)
        book_value_per_share = financial_data.get("book_value_per_share", 0)
        revenue_per_share = financial_data.get("revenue_per_share", 0)
        
        current_pe = current_price / eps if eps > 0 else None
        current_pb = current_price / book_value_per_share if book_value_per_share > 0 else None
        current_ps = current_price / revenue_per_share if revenue_per_share > 0 else None
        
        logger.info(f"[{symbol}] Usando valores por defecto para promedios del sector")
        
        return {
            "pe": current_pe * 1.05 if current_pe else 30.0,
            "pb": current_pb * 1.1 if current_pb else None,
            "ps": current_ps * 1.05 if current_ps else None,
            "ev_ebitda": 14.0
        }

