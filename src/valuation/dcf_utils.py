"""
Utilidades para cálculo DCF optimizado
PUNTO ÚNICO DE VERDAD para cálculo DCF
Evita duplicación de cálculos y creación innecesaria de engines
Todos los módulos (entrenamiento, producción) deben usar esta función
"""
from typing import Dict, Tuple, Optional
from .dcf_calculator import DCFCalculator, DCFResult
from ..utils import get_logger
from ..config import (
    RISK_FREE_RATE,
    ALPHASPREAD_ERP,
    DEFAULT_TAX_RATE,
    PROJECTION_YEARS,
    get_terminal_growth_for_sector,
    validate_tax_rate,
    MIN_COST_OF_DEBT,
    MAX_COST_OF_DEBT,
    MAX_DEBT_TO_EQUITY,
    MIN_BETA,
    MAX_BETA,
    MIN_GROWTH_RATE,
    MAX_GROWTH_RATE,
)

logger = get_logger("dcf_utils")


def compute_company_dcf(
    financial_data: Dict,
    growth_rates: Dict,
    company_params: Optional[Dict] = None,
    market_cap: Optional[float] = None,
    total_debt: Optional[float] = None,
    wacc_adjustment_factor: float = 1.0,
    use_alpha_spread_erp: bool = True,
    sector: Optional[str] = None
) -> Tuple[float, Dict]:
    """
    PUNTO ÚNICO DE VERDAD para cálculo DCF
    Calcula DCF para una empresa específica usando configuración centralizada
    
    Args:
        financial_data: Datos financieros de la empresa (debe incluir: free_cash_flow, shares_outstanding, beta, debt, shareholder_equity, interest_expense)
        growth_rates: Tasas de crecimiento históricas (debe incluir: fcf_growth)
        company_params: Parámetros específicos de la empresa (de CompanySpecificParams)
                       Si None, usa valores por defecto
        market_cap: Market Cap en millones (opcional, se obtiene de financial_data si no se proporciona)
        total_debt: Total Debt en millones (opcional, se obtiene de financial_data si no se proporciona)
        wacc_adjustment_factor: Factor de ajuste WACC (default: 1.0 = sin ajuste)
        use_alpha_spread_erp: Si True, usa ERP 4.12% (Alpha Spread), si False usa 5.8% (default)
        sector: Sector de la empresa (opcional, se obtiene de financial_data si no se proporciona)
    
    Returns:
        Tuple (dcf_value_per_share, debug_info)
        debug_info contiene: wacc_base, wacc_adjusted, growth_base, growth_adjusted, dcf_result
    """
    symbol = financial_data.get("symbol", "UNKNOWN")
    logger.debug(f"[DCF] {symbol} - Iniciando cálculo DCF...")
    
    # Obtener valores de financial_data si no se proporcionan
    if market_cap is None:
        market_cap = financial_data.get("market_cap", 0)
    if total_debt is None:
        total_debt = financial_data.get("debt", 0)
    if sector is None:
        sector = financial_data.get("sector", "Unknown")
    
    # Obtener parámetros específicos o usar defaults
    logger.debug(f"[DCF] {symbol} - Obteniendo parámetros de crecimiento...")
    if company_params:
        terminal_growth = company_params.get('terminal_growth_rate', get_terminal_growth_for_sector(sector))
        growth_adjustment = company_params.get('growth_adjustment_factor', 1.0)
    else:
        terminal_growth = get_terminal_growth_for_sector(sector)
        growth_adjustment = 1.0
    logger.debug(f"[DCF] {symbol} - Terminal growth: {terminal_growth:.2f}%, Growth adjustment: {growth_adjustment:.3f}")
    
    # growth_adjustment ya está definido arriba, se usa más abajo
    
    # Validar y obtener beta
    beta = financial_data.get("beta", 1.0)
    if beta < MIN_BETA or beta > MAX_BETA:
        beta = 1.0
    
    # Calcular debt_to_equity
    shareholder_equity = financial_data.get("shareholder_equity", 1)
    debt_to_equity = total_debt / max(shareholder_equity, 1)
    debt_to_equity = min(debt_to_equity, MAX_DEBT_TO_EQUITY)
    
    # Calcular cost_of_debt
    interest_expense = financial_data.get("interest_expense", 0)
    cost_of_debt = (interest_expense / max(total_debt, 1)) * 100 if total_debt > 0 else MIN_COST_OF_DEBT
    cost_of_debt = max(MIN_COST_OF_DEBT, min(cost_of_debt, MAX_COST_OF_DEBT))
    
    # Seleccionar ERP según configuración
    erp = ALPHASPREAD_ERP if use_alpha_spread_erp else 5.8
    
    # Crear DCFCalculator usando configuración centralizada
    dcf_calc = DCFCalculator(
        projection_years=PROJECTION_YEARS,
        terminal_growth_rate=terminal_growth,
        risk_free_rate=RISK_FREE_RATE,
        market_risk_premium=erp,
        beta=beta,
        debt_to_equity=debt_to_equity,
        cost_of_debt=cost_of_debt,
        tax_rate=DEFAULT_TAX_RATE,  # Se valida internamente en DCFCalculator
    )
    
    # Calcular WACC base usando Market Cap y Total Debt (método Alpha Spread)
    logger.debug(f"[DCF] {symbol} - Calculando WACC...")
    wacc_base = dcf_calc.calculate_wacc(market_cap=market_cap, total_debt=total_debt)
    wacc_adjusted = wacc_base * wacc_adjustment_factor
    logger.debug(f"[DCF] {symbol} - WACC base: {wacc_base:.2f}%, WACC ajustado: {wacc_adjusted:.2f}% (factor: {wacc_adjustment_factor:.3f})")
    
    # Aplicar factor de ajuste al crecimiento (growth_adjustment ya está definido arriba)
    logger.debug(f"[DCF] {symbol} - Aplicando ajuste de crecimiento...")
    base_fcf_growth = growth_rates.get("fcf_growth", 5.0)
    adjusted_fcf_growth = base_fcf_growth * growth_adjustment
    logger.debug(f"[DCF] {symbol} - FCF growth base: {base_fcf_growth:.2f}%, FCF growth ajustado: {adjusted_fcf_growth:.2f}%")
    
    # Validar growth rate dentro de límites
    adjusted_fcf_growth = max(MIN_GROWTH_RATE, min(adjusted_fcf_growth, MAX_GROWTH_RATE))
    
    # Calcular DCF con crecimiento ajustado
    logger.debug(f"[DCF] {symbol} - Calculando flujos de caja proyectados...")
    dcf_result = dcf_calc.calculate_dcf(
        current_fcf=financial_data["free_cash_flow"],
        growth_rate=adjusted_fcf_growth,
        shares_outstanding=financial_data["shares_outstanding"],
        scenario="base",
        market_cap=market_cap,
        total_debt=total_debt
    )
    logger.debug(f"[DCF] {symbol} - DCF calculado: ${dcf_result.fair_value_per_share:.2f} por acción")
    
    # Recalcular DCF con WACC ajustado si es necesario
    if wacc_adjustment_factor != 1.0 and dcf_result.total_dcf_value > 0:
        # Re-descontar flujos proyectados con WACC ajustado
        discounted_cf_adjusted = []
        for year, cf in enumerate(dcf_result.projected_cash_flows, start=1):
            pv = cf / ((1 + wacc_adjusted) ** year)
            discounted_cf_adjusted.append(pv)
        
        # Recalcular valor terminal con WACC ajustado
        final_fcf = dcf_result.projected_cash_flows[-1]
        terminal_value_adjusted = dcf_calc.calculate_terminal_value(final_fcf, wacc_adjusted)
        pv_terminal_adjusted = terminal_value_adjusted / ((1 + wacc_adjusted) ** PROJECTION_YEARS)
        
        # Valor total DCF ajustado
        total_dcf_adjusted = sum(discounted_cf_adjusted) + pv_terminal_adjusted
        dcf_value_adjusted = total_dcf_adjusted / financial_data["shares_outstanding"] if financial_data["shares_outstanding"] > 0 else 0
    else:
        dcf_value_adjusted = dcf_result.fair_value_per_share
    
    # Información de debug
    debug_info = {
        'wacc_base': wacc_base,
        'wacc_adjusted': wacc_adjusted,
        'growth_base': base_fcf_growth,
        'growth_adjusted': adjusted_fcf_growth,
        'dcf_result': dcf_result
    }
    
    return dcf_value_adjusted, debug_info

