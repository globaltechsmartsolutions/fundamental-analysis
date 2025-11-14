"""
Calculadora DCF (Discounted Cash Flow) - Método principal de Alpha Spread
Proyecta flujos de caja futuros y los descuenta al valor presente usando WACC
"""
from typing import Dict, Optional
from dataclasses import dataclass
from ..utils import get_logger

logger = get_logger("dcf_calculator")


@dataclass
class DCFResult:
    """Resultado del cálculo DCF"""
    fair_value_per_share: float
    total_dcf_value: float
    terminal_value: float
    projected_cash_flows: list
    wacc: float
    scenario: str  # 'pessimistic', 'base', 'optimistic'


class DCFCalculator:
    """
    Calculadora DCF estilo Alpha Spread
    
    Pasos:
    1. Proyecta FCF para los próximos 5-10 años
    2. Descuenta cada flujo usando WACC
    3. Calcula valor terminal (después del año 10)
    4. Suma todo y divide entre número de acciones
    """
    
    def __init__(
        self,
        projection_years: int = 10,
        terminal_growth_rate: float = 2.5,  # Tasa de crecimiento perpetuo (%) - ajustado para acercarse a Alpha Spread
        risk_free_rate: float = 4.5,  # Tasa libre de riesgo (%) - ajustado para 2024
        market_risk_premium: float = 4.12,  # Prima de riesgo de mercado (%) - Alpha Spread usa 4.12%
        beta: float = 1.0,  # Beta de la empresa (1.0 para tech grandes, más conservador)
        debt_to_equity: float = 0.3,  # Ratio deuda/patrimonio - más conservador
        cost_of_debt: float = 5.0,  # Costo de la deuda (%) - más conservador
        tax_rate: float = 21.0  # Tasa de impuestos (%) - IMPORTANTE: se convierte a fracción internamente
    ):
        """
        Args:
            tax_rate: Tasa de impuestos en porcentaje (ej: 21.0 = 21%)
                     Se convierte internamente a fracción (0.21) para cálculos
        """
        self.projection_years = projection_years
        self.terminal_growth_rate = terminal_growth_rate / 100.0
        self.risk_free_rate = risk_free_rate / 100.0
        self.market_risk_premium = market_risk_premium / 100.0
        self.beta = beta
        self.debt_to_equity = debt_to_equity
        self.cost_of_debt = cost_of_debt / 100.0
        # BUG FIX: tax_rate debe ser fracción (0.21), no porcentaje (21.0)
        # Si viene como porcentaje, convertir a fracción
        if tax_rate > 1.0:
            self.tax_rate = tax_rate / 100.0  # Convertir de porcentaje a fracción
        else:
            self.tax_rate = tax_rate  # Ya viene como fracción
    
    def calculate_wacc(self, market_cap: float = None, total_debt: float = None) -> float:
        """
        Calcula WACC (Weighted Average Cost of Capital) como Alpha Spread
        
        WACC = (E/(D+E) * Re) + (D/(D+E) * Rd * (1 - Tc))
        
        Donde:
        - E = Market Cap (valor de mercado del patrimonio)
        - D = Total Debt (deuda total)
        - Re = Costo del patrimonio (CAPM) = Rf + β * ERP
        - Rd = Costo de la deuda (Interest Expense / Total Debt)
        - Tc = Tasa de impuestos
        
        Args:
            market_cap: Market Cap en millones (opcional, si se proporciona usa método Alpha Spread)
            total_debt: Total Debt en millones (opcional, si se proporciona usa método Alpha Spread)
        """
        # Costo del patrimonio usando CAPM (como Alpha Spread)
        # Re = Rf + β * ERP
        cost_of_equity = self.risk_free_rate + self.beta * self.market_risk_premium
        
        # Calcular pesos según método Alpha Spread o método tradicional
        if market_cap is not None and total_debt is not None and market_cap > 0:
            # MÉTODO ALPHA SPREAD: Usar Market Cap y Total Debt directamente
            # E = Market Cap, D = Total Debt, V = E + D
            total_value = market_cap + total_debt
            if total_value > 0:
                equity_weight = market_cap / total_value  # E/(D+E)
                debt_weight = total_debt / total_value    # D/(D+E)
            else:
                # Fallback si total_value = 0
                equity_weight = 1.0
                debt_weight = 0.0
        else:
            # MÉTODO TRADICIONAL: Usar debt_to_equity ratio (fallback)
            # Si D/E = 0.3, entonces D = 0.3, E = 1.0, V = 1.3
            equity_weight = 1.0 / (1.0 + self.debt_to_equity)
            debt_weight = self.debt_to_equity / (1.0 + self.debt_to_equity)
        
        # Costo de deuda después de impuestos
        cost_of_debt_after_tax = self.cost_of_debt * (1 - self.tax_rate)
        
        # WACC (como Alpha Spread)
        wacc = (equity_weight * cost_of_equity) + (debt_weight * cost_of_debt_after_tax)
        
        return wacc
    
    def project_cash_flows(
        self,
        current_fcf: float,
        growth_rate: float,
        scenario: str = "base"
    ) -> list:
        """
        Proyecta flujos de caja libres futuros
        
        Args:
            current_fcf: FCF actual (último año)
            growth_rate: Tasa de crecimiento anual (%)
            scenario: 'pessimistic', 'base', 'optimistic'
        
        Returns:
            Lista de FCF proyectados por año
        """
        # VALIDACIÓN: Growth rate debe ser razonable
        if growth_rate > 20.0:
            logger.warning(f"Growth rate muy alto ({growth_rate:.2f}%), limitando a 20% para realismo")
            growth_rate = 20.0
        elif growth_rate < -10.0:
            logger.warning(f"Growth rate muy negativo ({growth_rate:.2f}%), limitando a -10%")
            growth_rate = -10.0
        # Si FCF es 0 o negativo, NO inventar valores mágicos
        # En entrenamiento, estas empresas se excluyen (ver train_model.py)
        # En inferencia normal, retornar 0 o usar método alternativo
        if current_fcf <= 0:
            if current_fcf == 0:
                # FCF = 0: No inventar valores. En entrenamiento se excluye.
                # En inferencia, retornar 0 para que el sistema use solo Comparables
                logger.warning(f"FCF es 0. En entrenamiento esta empresa se excluye. En inferencia, DCF retornará 0.")
                current_fcf = 0.0  # No inventar, dejar en 0
            else:
                # FCF negativo: usar valor absoluto pero con crecimiento muy conservador
                logger.warning(f"FCF negativo ({current_fcf:.2f}M), usando valor absoluto con crecimiento conservador")
                current_fcf = abs(current_fcf) * 0.5  # Reducir a la mitad para ser conservador
        
        # Ajustar crecimiento según escenario
        # Para tech stocks grandes, los escenarios son menos extremos
        scenario_multipliers = {
            "pessimistic": 0.75,  # 75% del crecimiento base (menos pesimista)
            "base": 1.0,
            "optimistic": 1.4   # 140% del crecimiento base (más realista)
        }
        
        multiplier = scenario_multipliers.get(scenario, 1.0)
        adjusted_growth = (growth_rate / 100.0) * multiplier
        
        # Proyectar FCF con crecimiento decreciente (típico en DCF)
        # Los primeros años crecen más rápido, luego se estabiliza
        projected = []
        current = current_fcf
        
        for year in range(1, self.projection_years + 1):
            # Crecimiento decreciente: más conservador para acercarse a Alpha Spread
            # Alpha Spread parece usar proyecciones más conservadoras
            if year <= 3:
                year_growth = adjusted_growth  # Mantener crecimiento completo primeros 3 años
            elif year <= 6:
                year_growth = adjusted_growth * 0.75  # Reducir a 75% años 4-6
            elif year <= 8:
                year_growth = adjusted_growth * 0.6  # Reducir a 60% años 7-8
            else:
                year_growth = adjusted_growth * 0.5  # Reducir a 50% últimos años
            
            current = current * (1 + year_growth)
            projected.append(current)
        
        return projected
    
    def calculate_terminal_value(self, final_fcf: float, wacc: float) -> float:
        """
        Calcula valor terminal usando modelo de crecimiento perpetuo (como Alpha Spread)
        
        Terminal Value = FCF_último_año * (1 + g) / (WACC - g)
        
        Donde:
        - FCF_último_año = Último FCF proyectado
        - g = Tasa de crecimiento perpetuo (conservador: 1.5-2.5%)
        - WACC = Costo de capital promedio ponderado
        
        Alpha Spread usa valores conservadores:
        - Tech → 2.5%
        - Utilities → 1.5%
        - Healthcare/Industrials → 2.0%
        - Default → 2.0%
        """
        # Si FCF es 0 o negativo, el valor terminal es 0
        # Esto es correcto: empresas con FCF=0 no deberían usar DCF
        if final_fcf <= 0:
            return 0.0
        
        # Validar que WACC > g (requisito del modelo)
        if wacc <= self.terminal_growth_rate:
            # Si WACC <= g, el modelo no es válido
            # Alpha Spread usaría un múltiplo conservador en este caso
            logger.warning(f"WACC ({wacc:.2%}) <= Terminal Growth ({self.terminal_growth_rate:.2%}) - usando múltiplo conservador")
            terminal_value = final_fcf * 15.0  # Múltiplo conservador (fallback)
        else:
            # Fórmula clásica de Alpha Spread
            terminal_value = final_fcf * (1 + self.terminal_growth_rate) / (wacc - self.terminal_growth_rate)
        
        return terminal_value
    
    def calculate_dcf(
        self,
        current_fcf: float,
        growth_rate: float,
        shares_outstanding: float,
        scenario: str = "base",
        market_cap: float = None,
        total_debt: float = None
    ) -> DCFResult:
        """
        Calcula valor intrínseco usando DCF
        
        Args:
            current_fcf: Flujo de caja libre actual (en millones)
            growth_rate: Tasa de crecimiento esperada (% anual)
            shares_outstanding: Número de acciones en circulación (en millones)
            scenario: 'pessimistic', 'base', 'optimistic'
            market_cap: Market Cap en millones (opcional, para cálculo WACC Alpha Spread)
            total_debt: Total Debt en millones (opcional, para cálculo WACC Alpha Spread)
        
        Returns:
            DCFResult con valor por acción y detalles
        """
        # Calcular WACC (con Market Cap y Total Debt si se proporcionan - método Alpha Spread)
        wacc = self.calculate_wacc(market_cap=market_cap, total_debt=total_debt)
        
        # Proyectar flujos de caja
        projected_cf = self.project_cash_flows(current_fcf, growth_rate, scenario)
        
        # Descontar cada flujo al valor presente
        discounted_cf = []
        for year, cf in enumerate(projected_cf, start=1):
            pv = cf / ((1 + wacc) ** year)
            discounted_cf.append(pv)
        
        # Sumar todos los flujos descontados
        pv_of_cash_flows = sum(discounted_cf)
        
        # Calcular valor terminal
        final_fcf = projected_cf[-1]
        terminal_value = self.calculate_terminal_value(final_fcf, wacc)
        
        # Descontar valor terminal al presente
        pv_terminal = terminal_value / ((1 + wacc) ** self.projection_years)
        
        # Valor total de la empresa
        total_dcf_value = pv_of_cash_flows + pv_terminal
        
        # Debug: verificar valores
        # print(f"DEBUG DCF: FCF={current_fcf}, Shares={shares_outstanding}, Total DCF={total_dcf_value}")
        
        # Valor por acción
        # IMPORTANTE: Si shares_outstanding está en millones, total_dcf_value también debe estar en millones
        fair_value_per_share = total_dcf_value / shares_outstanding if shares_outstanding > 0 else 0
        
        # Debug
        # print(f"DEBUG DCF: Fair value per share = {fair_value_per_share}")
        
        return DCFResult(
            fair_value_per_share=fair_value_per_share,
            total_dcf_value=total_dcf_value,
            terminal_value=pv_terminal,
            projected_cash_flows=projected_cf,
            wacc=wacc,
            scenario=scenario
        )
    
    def calculate_all_scenarios(
        self,
        current_fcf: float,
        growth_rate: float,
        shares_outstanding: float
    ) -> Dict[str, DCFResult]:
        """Calcula DCF para los tres escenarios"""
        scenarios = {}
        for scenario in ["pessimistic", "base", "optimistic"]:
            scenarios[scenario] = self.calculate_dcf(
                current_fcf, growth_rate, shares_outstanding, scenario
            )
        return scenarios

