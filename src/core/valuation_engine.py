"""
Motor de Valoración Principal - Combina DCF y Comparables
Estilo Alpha Spread: Promedio simple (50% DCF + 50% Comparables)
Según Alpha Spread: "To enhance accuracy, we average the results from these two methods"
"""
from typing import Dict, Optional
from dataclasses import dataclass, asdict
from ..valuation import DCFCalculator, DCFResult, ComparablesCalculator, ComparableResult


@dataclass
class ValuationResult:
    """Resultado completo de la valoración"""
    symbol: str
    current_price: float
    blended_fair_value: float  # Valor justo combinado (promedio simple: 50% DCF + 50% Comparables)
    undervaluation_percentage: float  # % de infravaloración/sobrevaloración
    status: str  # 'undervalued', 'fair', 'overvalued'
    
    # DCF Results (todos los escenarios)
    dcf_pessimistic: float
    dcf_base: float
    dcf_optimistic: float
    
    # Comparables Results
    comparables_value: float
    
    # Detalles adicionales
    surprise_eps: Optional[float]
    pe_ratio: Optional[float]
    pb_ratio: Optional[float]
    ps_ratio: Optional[float]
    
    def to_dict(self) -> Dict:
        """Convierte a diccionario para serialización"""
        return asdict(self)


class ValuationEngine:
    """
    Motor principal de valoración estilo Alpha Spread
    
    Combina:
    - 50% DCF (método absoluto)
    - 50% Comparables/Relative Valuation (método relativo)
    - Promedio simple según metodología Alpha Spread
    
    Calcula escenarios: pesimista, base, optimista
    """
    
    def __init__(
        self,
        dcf_weight: float = 0.50,  # Alpha Spread promedia ambos métodos (50/50)
        comparables_weight: float = 0.50,
        **dcf_kwargs
    ):
        """
        Args:
            dcf_weight: Peso del método DCF (default 50% - promedio simple)
            comparables_weight: Peso del método Comparables (default 50% - promedio simple)
            **dcf_kwargs: Parámetros para DCFCalculator
        """
        self.dcf_weight = dcf_weight
        self.comparables_weight = comparables_weight
        self.dcf_calculator = DCFCalculator(**dcf_kwargs)
        self.comparables_calculator = ComparablesCalculator()
    
    def calculate_blended_value(
        self,
        dcf_value: float,
        comparables_value: float
    ) -> float:
        """
        Calcula valor justo combinado (blended fair value)
        
        Según Alpha Spread: "To enhance accuracy, we average the results from these two methods"
        Blended Value = (DCF * 50%) + (Comparables * 50%) - promedio simple
        """
        blended = (dcf_value * self.dcf_weight) + (comparables_value * self.comparables_weight)
        return blended
    
    def calculate_undervaluation_percentage(
        self,
        fair_value: float,
        current_price: float
    ) -> float:
        """
        Calcula Margin of Safety / porcentaje de infravaloración/sobrevaloración
        
        Este es el "margin actual" de valoración (Margin of Safety), equivalente al
        "% Undervalued by X%" que muestra Alpha Spread.
        
        Formula (como Alpha Spread):
        MOS % = ((Intrinsic Value - Current Price) / Current Price) * 100
        
        Donde:
        - Intrinsic Value = Blend DCF + Comparables (Base Case)
        - Current Price = Precio actual de mercado
        
        Positivo = infravalorada (barata) - Margin of Safety positivo
        Negativo = sobrevalorada (cara) - Margin of Safety negativo
        
        NOTA: Este NO es lo mismo que los "margins operativos" (Operating Margin,
        Net Margin, FCF Margin), que son ratios de rentabilidad (beneficio/ventas).
        """
        if current_price <= 0:
            return 0.0
        
        percentage = ((fair_value - current_price) / current_price) * 100
        return percentage
    
    def determine_status(self, undervaluation_pct: float) -> str:
        """
        Determina status basado en porcentaje de infravaloración
        
        - > 20%: Undervalued (muy barata)
        - 5% a 20%: Slightly Undervalued
        - -5% a 5%: Fair Value
        - -20% a -5%: Slightly Overvalued
        - < -20%: Overvalued (muy cara)
        """
        if undervaluation_pct > 20:
            return "undervalued"
        elif undervaluation_pct > 5:
            return "slightly_undervalued"
        elif undervaluation_pct < -20:
            return "overvalued"
        elif undervaluation_pct < -5:
            return "slightly_overvalued"
        else:
            return "fair"
    
    def calculate_valuation(
        self,
        symbol: str,
        current_price: float,
        current_fcf: float,
        fcf_growth_rate: float,
        shares_outstanding: float,
        eps: float,
        book_value_per_share: float,
        revenue_per_share: float,
        market_cap: float,
        ebitda: float,
        sector_averages: Dict[str, float],
        surprise_eps: Optional[float] = None,
        debt: float = 0.0,
        cash: float = 0.0
    ) -> ValuationResult:
        """
        Calcula valoración completa para una empresa
        
        Args:
            symbol: Símbolo de la acción
            current_price: Precio actual
            current_fcf: Flujo de caja libre actual (millones)
            fcf_growth_rate: Tasa de crecimiento de FCF (% anual)
            shares_outstanding: Acciones en circulación (millones)
            eps: Earnings per share
            book_value_per_share: Valor contable por acción
            revenue_per_share: Ingresos por acción
            market_cap: Capitalización de mercado (millones)
            ebitda: EBITDA (millones)
            sector_averages: Promedios del sector (PE, PB, PS, EV/EBITDA)
            surprise_eps: Surprise EPS si está disponible
        
        Returns:
            ValuationResult completo
        """
        # Calcular DCF para todos los escenarios
        dcf_scenarios = self.dcf_calculator.calculate_all_scenarios(
            current_fcf, fcf_growth_rate, shares_outstanding
        )
        
        dcf_base_value = dcf_scenarios["base"].fair_value_per_share
        dcf_pessimistic_value = dcf_scenarios["pessimistic"].fair_value_per_share
        dcf_optimistic_value = dcf_scenarios["optimistic"].fair_value_per_share
        
        # Debug: mostrar valores DCF
        import logging
        logger = logging.getLogger("fundamental_analysis.valuation")
        # Obtener detalles del DCF base para logging
        dcf_base_details = dcf_scenarios["base"]
        
        logger.info(f"DEBUG {symbol} - Valores DCF:")
        logger.info(f"  Pesimista: ${dcf_pessimistic_value:.2f}")
        logger.info(f"  Base: ${dcf_base_value:.2f}")
        logger.info(f"  Optimista: ${dcf_optimistic_value:.2f}")
        logger.info(f"  Inputs: FCF=${current_fcf:.2f}M, Shares={shares_outstanding:.2f}M, Growth={fcf_growth_rate:.2f}%")
        logger.info(f"  WACC: {dcf_base_details.wacc*100:.2f}%")
        logger.info(f"  Total DCF Value: ${dcf_base_details.total_dcf_value:.2f}M")
        logger.info(f"  Terminal Value PV: ${dcf_base_details.terminal_value:.2f}M")
        logger.info(f"  FCF Year 1: ${dcf_base_details.projected_cash_flows[0]:.2f}M")
        logger.info(f"  FCF Year 10: ${dcf_base_details.projected_cash_flows[-1]:.2f}M")
        
        # Calcular Comparables
        # MEJORA: Pasar debt, cash y shares_outstanding para cálculo EV real
        comparables_result = self.comparables_calculator.calculate_comparables(
            current_price=current_price,
            eps=eps,
            book_value_per_share=book_value_per_share,
            revenue_per_share=revenue_per_share,
            market_cap=market_cap,
            ebitda=ebitda,
            sector_averages=sector_averages,
            debt=debt,
            cash=cash,
            shares_outstanding=shares_outstanding
        )
        
        logger.info(f"DEBUG {symbol} - Comparables:")
        logger.info(f"  Fair Value: ${comparables_result.fair_value_per_share:.2f}")
        pe_based_str = f"${comparables_result.pe_based_value:.2f}" if comparables_result.pe_based_value is not None else "N/A"
        pb_based_str = f"${comparables_result.pb_based_value:.2f}" if comparables_result.pb_based_value is not None else "N/A"
        ps_based_str = f"${comparables_result.ps_based_value:.2f}" if comparables_result.ps_based_value is not None else "N/A"
        sector_pe_str = f"{comparables_result.sector_pe:.2f}" if comparables_result.sector_pe else "N/A"
        company_pe_str = f"${current_price/eps:.2f}" if eps > 0 else "N/A"
        logger.info(f"  P/E Based: {pe_based_str}")
        logger.info(f"  P/B Based: {pb_based_str}")
        logger.info(f"  P/S Based: {ps_based_str}")
        logger.info(f"  Sector P/E: {sector_pe_str}")
        logger.info(f"  Company P/E: {company_pe_str}")
        
        # Calcular valor combinado (blended)
        blended_fair_value = self.calculate_blended_value(
            dcf_base_value,
            comparables_result.fair_value_per_share
        )
        
        logger.info(f"DEBUG {symbol} - Blended: ${blended_fair_value:.2f} (DCF: ${dcf_base_value:.2f} x {self.dcf_weight*100:.0f}% + Comparables: ${comparables_result.fair_value_per_share:.2f} x {self.comparables_weight*100:.0f}%)")
        
        # Calcular porcentaje de infravaloración
        undervaluation_pct = self.calculate_undervaluation_percentage(
            blended_fair_value,
            current_price
        )
        
        # Determinar status
        status = self.determine_status(undervaluation_pct)
        
        # Calcular ratios
        pe_ratio = current_price / eps if eps > 0 else None
        pb_ratio = current_price / book_value_per_share if book_value_per_share > 0 else None
        ps_ratio = current_price / revenue_per_share if revenue_per_share > 0 else None
        
        return ValuationResult(
            symbol=symbol,
            current_price=current_price,
            blended_fair_value=blended_fair_value,
            undervaluation_percentage=undervaluation_pct,
            status=status,
            dcf_pessimistic=dcf_pessimistic_value,
            dcf_base=dcf_base_value,
            dcf_optimistic=dcf_optimistic_value,
            comparables_value=comparables_result.fair_value_per_share,
            surprise_eps=surprise_eps,
            pe_ratio=pe_ratio,
            pb_ratio=pb_ratio,
            ps_ratio=ps_ratio
        )

