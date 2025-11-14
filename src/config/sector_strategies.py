"""
Estrategias de Valoración por Sector
Cada sector tiene su propia lógica de valoración (como Alpha Spread)
"""
from typing import Dict, Optional, Tuple
from ..utils import get_logger
# Importación diferida para evitar circular imports
def _get_compute_company_dcf():
    from ..valuation import compute_company_dcf
    return compute_company_dcf

def _get_comparables_calculator():
    from ..valuation import ComparablesCalculator
    return ComparablesCalculator

logger = get_logger("sector_strategies")


class ValuationStrategy:
    """Estrategia base de valoración"""
    
    def calculate_valuation(
        self,
        symbol: str,
        financial_data: Dict,
        growth_rates: Dict,
        sector_averages: Dict,
        company_params: Optional[Dict] = None
    ) -> Tuple[float, float, Dict]:
        """
        Calcula valoración para una empresa
        
        Returns:
            Tuple (dcf_value, comparables_value, debug_info)
        """
        raise NotImplementedError


class TechStrategy(ValuationStrategy):
    """
    Estrategia para empresas Tech
    Usa DCF estándar + Comparables con pesos equilibrados
    """
    
    def calculate_valuation(
        self,
        symbol: str,
        financial_data: Dict,
        growth_rates: Dict,
        sector_averages: Dict,
        company_params: Optional[Dict] = None
    ) -> Tuple[float, float, Dict]:
        """Estrategia estándar para Tech"""
        # Calcular DCF usando punto único de verdad
        # Obtener market_cap y total_debt para WACC Alpha Spread
        market_cap = financial_data.get("market_cap", 0)
        total_debt = financial_data.get("debt", 0)
        wacc_adjustment = company_params.get('wacc_adjustment_factor', 1.0) if company_params else 1.0
        
        compute_company_dcf = _get_compute_company_dcf()
        dcf_value, dcf_debug = compute_company_dcf(
            financial_data=financial_data,
            growth_rates=growth_rates,
            company_params=company_params,
            market_cap=market_cap,
            total_debt=total_debt,
            wacc_adjustment_factor=wacc_adjustment,
            use_alpha_spread_erp=True,
            sector=financial_data.get("sector", "Technology")
        )
        
        # Calcular Comparables directamente
        ComparablesCalculator = _get_comparables_calculator()
        comparables_calc = ComparablesCalculator()
        comparables_result = comparables_calc.calculate_comparables(
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
        
        comparables_value = comparables_result.fair_value_per_share
        
        debug_info = {
            'strategy': 'TechStrategy',
            'dcf_debug': dcf_debug,
            'comparables_value': comparables_value
        }
        
        return dcf_value, comparables_value, debug_info


class FinancialsStrategy(ValuationStrategy):
    """
    Estrategia para empresas Financieras (Bancos, Seguros, etc.)
    DCF no funciona bien con FCF contable de bancos
    Usa principalmente Comparables (P/E, P/B, P/Tangible Book)
    """
    
    def calculate_valuation(
        self,
        symbol: str,
        financial_data: Dict,
        growth_rates: Dict,
        sector_averages: Dict,
        company_params: Optional[Dict] = None
    ) -> Tuple[float, float, Dict]:
        """
        Para financieras: DCF con FCF ajustado o solo Comparables
        """
        fcf = financial_data.get("free_cash_flow", 0)
        
        # Si FCF es negativo o muy bajo, usar solo Comparables
        if fcf <= 0:
            logger.debug(f"[FinancialsStrategy] {symbol}: FCF={fcf:.2f}M <= 0, usando solo Comparables")
            dcf_value = 0.0  # No usar DCF
        else:
            # Intentar DCF pero con crecimiento más conservador
            # Para bancos, el FCF puede ser volátil, usar crecimiento más bajo
            adjusted_growth_rates = growth_rates.copy()
            if adjusted_growth_rates.get("fcf_growth", 0) > 10.0:
                adjusted_growth_rates["fcf_growth"] = min(adjusted_growth_rates["fcf_growth"] * 0.6, 8.0)
            
            # Obtener market_cap y total_debt para WACC Alpha Spread
            market_cap = financial_data.get("market_cap", 0)
            total_debt = financial_data.get("debt", 0)
            wacc_adjustment = company_params.get('wacc_adjustment_factor', 1.0) if company_params else 1.0
            
            compute_company_dcf = _get_compute_company_dcf()
        dcf_value, dcf_debug = compute_company_dcf(
                financial_data=financial_data,
                growth_rates=adjusted_growth_rates,
                company_params=company_params,
                market_cap=market_cap,
                total_debt=total_debt,
                wacc_adjustment_factor=wacc_adjustment,
                use_alpha_spread_erp=True,
                sector=financial_data.get("sector", "Financial")
            )
        
        # Comparables es más confiable para financieras
        ComparablesCalculator = _get_comparables_calculator()
        comparables_calc = ComparablesCalculator()
        comparables_result = comparables_calc.calculate_comparables(
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
        
        comparables_value = comparables_result.fair_value_per_share
        
        debug_info = {
            'strategy': 'FinancialsStrategy',
            'dcf_value': dcf_value,
            'dcf_debug': dcf_debug if fcf > 0 else None,
            'comparables_value': comparables_value,
            'note': 'Financials: DCF solo si FCF > 0, mayor peso en Comparables'
        }
        
        return dcf_value, comparables_value, debug_info


class UtilitiesStrategy(ValuationStrategy):
    """
    Estrategia para Utilities
    Crecimiento más conservador, terminal growth más bajo
    """
    
    def calculate_valuation(
        self,
        symbol: str,
        financial_data: Dict,
        growth_rates: Dict,
        sector_averages: Dict,
        company_params: Optional[Dict] = None
    ) -> Tuple[float, float, Dict]:
        """Estrategia conservadora para Utilities"""
        # Ajustar crecimiento más conservador
        adjusted_growth_rates = growth_rates.copy()
        if adjusted_growth_rates.get("fcf_growth", 0) > 5.0:
            adjusted_growth_rates["fcf_growth"] = min(adjusted_growth_rates["fcf_growth"] * 0.8, 4.0)
        
        # Obtener market_cap y total_debt para WACC Alpha Spread
        market_cap = financial_data.get("market_cap", 0)
        total_debt = financial_data.get("debt", 0)
        wacc_adjustment = company_params.get('wacc_adjustment_factor', 1.0) if company_params else 1.0
        
        compute_company_dcf = _get_compute_company_dcf()
        dcf_value, dcf_debug = compute_company_dcf(
            financial_data=financial_data,
            growth_rates=adjusted_growth_rates,
            company_params=company_params,
            market_cap=market_cap,
            total_debt=total_debt,
            wacc_adjustment_factor=wacc_adjustment,
            use_alpha_spread_erp=True,
            sector="Utilities"  # Forzar terminal growth bajo
        )
        
        ComparablesCalculator = _get_comparables_calculator()
        comparables_calc = ComparablesCalculator()
        comparables_result = comparables_calc.calculate_comparables(
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
        
        comparables_value = comparables_result.fair_value_per_share
        
        debug_info = {
            'strategy': 'UtilitiesStrategy',
            'dcf_debug': dcf_debug,
            'comparables_value': comparables_value
        }
        
        return dcf_value, comparables_value, debug_info


def get_strategy_for_sector(sector: str) -> ValuationStrategy:
    """
    Retorna la estrategia apropiada para un sector
    
    Args:
        sector: Nombre del sector
    
    Returns:
        ValuationStrategy apropiada
    """
    sector_lower = sector.lower() if sector else ""
    
    # Mapeo de sectores a estrategias
    if any(keyword in sector_lower for keyword in ["financial", "banking", "insurance"]):
        return FinancialsStrategy()
    elif any(keyword in sector_lower for keyword in ["utility", "utilities"]):
        return UtilitiesStrategy()
    else:
        # Default: TechStrategy (funciona para mayoría de sectores)
        return TechStrategy()

