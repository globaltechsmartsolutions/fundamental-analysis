"""
Calculadora de Comparables - Método secundario de Alpha Spread
Compara múltiplos con empresas similares del sector
"""
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class ComparableResult:
    """Resultado del cálculo por comparables"""
    fair_value_per_share: float
    pe_based_value: Optional[float]
    pb_based_value: Optional[float]
    ps_based_value: Optional[float]
    ev_ebitda_based_value: Optional[float]
    sector_pe: Optional[float]
    sector_pb: Optional[float]
    sector_ps: Optional[float]
    sector_ev_ebitda: Optional[float]


class ComparablesCalculator:
    """
    Calculadora de valoración por comparables estilo Alpha Spread
    
    Usa múltiplos:
    - P/E (Price/Earnings)
    - P/B (Price/Book)
    - P/S (Price/Sales)
    - EV/EBITDA
    
    Compara con promedio del sector y calcula valor justo
    """
    
    def __init__(self):
        pass
    
    def calculate_fair_value_from_multiple(
        self,
        current_value: float,
        sector_multiple: float,
        company_multiple: float
    ) -> float:
        """
        Calcula valor justo basado en múltiplo
        
        Si el sector tiene P/E = 20 y la empresa tiene P/E = 15,
        entonces está infravalorada
        
        Fair Value = Current Price * (Sector Multiple / Company Multiple)
        """
        if company_multiple <= 0:
            return 0.0
        
        # Si el múltiplo de la empresa es menor que el del sector, está barata
        fair_value = current_value * (sector_multiple / company_multiple)
        return fair_value
    
    def calculate_from_pe(
        self,
        current_price: float,
        eps: float,
        sector_pe: float
    ) -> Optional[float]:
        """Calcula valor justo basado en P/E"""
        if eps <= 0 or sector_pe <= 0:
            return None
        
        company_pe = current_price / eps
        fair_value = self.calculate_fair_value_from_multiple(
            current_price, sector_pe, company_pe
        )
        return fair_value
    
    def calculate_from_pb(
        self,
        current_price: float,
        book_value_per_share: float,
        sector_pb: float
    ) -> Optional[float]:
        """Calcula valor justo basado en P/B"""
        if book_value_per_share <= 0 or sector_pb <= 0:
            return None
        
        company_pb = current_price / book_value_per_share
        fair_value = self.calculate_fair_value_from_multiple(
            current_price, sector_pb, company_pb
        )
        return fair_value
    
    def calculate_from_ps(
        self,
        current_price: float,
        revenue_per_share: float,
        sector_ps: float
    ) -> Optional[float]:
        """Calcula valor justo basado en P/S"""
        if revenue_per_share <= 0 or sector_ps <= 0:
            return None
        
        company_ps = current_price / revenue_per_share
        fair_value = self.calculate_fair_value_from_multiple(
            current_price, sector_ps, company_ps
        )
        return fair_value
    
    def calculate_from_ev_ebitda(
        self,
        market_cap: float,
        ebitda: float,
        sector_ev_ebitda: float,
        debt: float = 0.0,
        cash: float = 0.0,
        shares_outstanding: float = None
    ) -> Optional[float]:
        """
        Calcula valor justo basado en EV/EBITDA usando EV REAL
        
        MEJORA: Ahora calcula EV real = Market Cap + Debt - Cash
        en lugar de asumir EV ≈ Market Cap
        
        Args:
            market_cap: Capitalización de mercado (millones)
            ebitda: EBITDA (millones)
            sector_ev_ebitda: Múltiplo EV/EBITDA del sector
            debt: Deuda total (millones) - opcional, default 0
            cash: Efectivo y equivalentes (millones) - opcional, default 0
            shares_outstanding: Número de acciones en circulación (millones) - opcional
        
        Returns:
            Fair value por acción basado en EV/EBITDA o None si no se puede calcular
        """
        if ebitda <= 0 or sector_ev_ebitda <= 0:
            return None
        
        # MEJORA: Calcular EV real = Market Cap + Debt - Cash
        enterprise_value = market_cap + debt - cash
        
        # Validar EV razonable
        if enterprise_value <= 0:
            # Si EV es negativo o cero, usar market_cap como fallback conservador
            enterprise_value = market_cap
            if enterprise_value <= 0:
                return None
        
        # Calcular múltiplo actual de la empresa
        company_ev_ebitda = enterprise_value / ebitda if ebitda > 0 else 0
        
        if company_ev_ebitda <= 0:
            return None
        
        # Fair value basado en múltiplo EV/EBITDA del sector
        # Si el sector tiene EV/EBITDA = 15 y la empresa tiene EV/EBITDA = 12,
        # entonces está infravalorada
        # Fair EV = EBITDA * sector_ev_ebitda
        fair_ev = ebitda * sector_ev_ebitda
        
        # Convertir EV a Market Cap: Market Cap = EV - Debt + Cash
        fair_market_cap = fair_ev - debt + cash
        
        # Si tenemos shares_outstanding, convertir a precio por acción
        if shares_outstanding and shares_outstanding > 0:
            return fair_market_cap / shares_outstanding
        
        # Si no tenemos shares, retornar market cap (el llamador deberá convertir)
        return fair_market_cap
    
    def get_sector_averages(
        self,
        peers_data: List[Dict],
        current_price: float,
        eps: float,
        book_value_per_share: float,
        revenue_per_share: float
    ) -> Dict[str, float]:
        """
        Calcula promedios del sector desde datos de peers
        
        En producción, esto debería obtener datos reales de peers
        Por ahora retorna valores estimados basados en la empresa actual
        """
        # Valores por defecto (en producción obtendrías de peers reales)
        # Estos son estimaciones conservadoras
        sector_pe = (current_price / eps) * 1.2 if eps > 0 else None  # Sector 20% más caro
        sector_pb = (current_price / book_value_per_share) * 1.15 if book_value_per_share > 0 else None
        sector_ps = (current_price / revenue_per_share) * 1.1 if revenue_per_share > 0 else None
        sector_ev_ebitda = None  # Requiere cálculo más complejo
        
        return {
            "pe": sector_pe,
            "pb": sector_pb,
            "ps": sector_ps,
            "ev_ebitda": sector_ev_ebitda
        }
    
    def calculate_comparables(
        self,
        current_price: float,
        eps: float,
        book_value_per_share: float,
        revenue_per_share: float,
        market_cap: float,
        ebitda: float,
        sector_averages: Dict[str, float],
        debt: float = 0.0,
        cash: float = 0.0,
        shares_outstanding: float = None
    ) -> ComparableResult:
        """
        Calcula valoración por comparables usando todos los múltiplos
        
        Retorna promedio ponderado de los valores calculados
        
        Args:
            debt: Deuda total (millones) - opcional, para cálculo EV real
            cash: Efectivo y equivalentes (millones) - opcional, para cálculo EV real
        """
        # Calcular valor justo desde cada múltiplo
        pe_value = self.calculate_from_pe(
            current_price, eps, sector_averages.get("pe", 0)
        ) if sector_averages.get("pe") else None
        
        pb_value = self.calculate_from_pb(
            current_price, book_value_per_share, sector_averages.get("pb", 0)
        ) if sector_averages.get("pb") else None
        
        ps_value = self.calculate_from_ps(
            current_price, revenue_per_share, sector_averages.get("ps", 0)
        ) if sector_averages.get("ps") else None
        
        # MEJORA: Pasar debt, cash y shares_outstanding para cálculo EV real
        ev_ebitda_value = self.calculate_from_ev_ebitda(
            market_cap, ebitda, sector_averages.get("ev_ebitda", 0),
            debt=debt, cash=cash, shares_outstanding=shares_outstanding
        ) if sector_averages.get("ev_ebitda") else None
        
        # Calcular promedio de valores
        # Alpha Spread promedia todos los múltiplos, pero podemos usar pesos ligeros para dar más peso a P/E
        # que suele ser más confiable para tech stocks
        values = []
        weights = []
        
        if pe_value:
            values.append(pe_value)
            weights.append(0.40)  # P/E tiene más peso (más confiable)
        if pb_value:
            values.append(pb_value)
            weights.append(0.20)
        if ps_value:
            values.append(ps_value)
            weights.append(0.25)
        if ev_ebitda_value:
            # ev_ebitda_value ya es precio por acción si se pasó shares_outstanding
            # Si no, es market cap y necesitamos convertir
            if shares_outstanding and shares_outstanding > 0:
                # Ya es precio por acción
                ev_value_per_share = ev_ebitda_value
            else:
                # Convertir market cap a precio por acción
                ev_value_per_share = ev_ebitda_value * (current_price / market_cap) if market_cap > 0 else None
            
            if ev_value_per_share and ev_value_per_share > 0:
                values.append(ev_value_per_share)
                weights.append(0.15)
        
        # Promedio ponderado (ligeramente) para acercarse mejor a Alpha Spread
        if len(values) > 0:
            # Normalizar pesos
            total_weight = sum(weights)
            if total_weight > 0:
                weights = [w / total_weight for w in weights]
                fair_value = sum(v * w for v, w in zip(values, weights))
            else:
                # Si no hay pesos, promedio simple
                fair_value = sum(values) / len(values)
        else:
            # Fallback: usar precio actual si no hay datos
            fair_value = current_price
        
        return ComparableResult(
            fair_value_per_share=fair_value,
            pe_based_value=pe_value,
            pb_based_value=pb_value,
            ps_based_value=ps_value,
            ev_ebitda_based_value=ev_ebitda_value,
            sector_pe=sector_averages.get("pe"),
            sector_pb=sector_averages.get("pb"),
            sector_ps=sector_averages.get("ps"),
            sector_ev_ebitda=sector_averages.get("ev_ebitda")
        )

