"""
Sistema de Parámetros Específicos por Empresa (como Alpha Spread)
Cada empresa tiene sus propios parámetros calculados dinámicamente
"""
import json
from typing import Dict, Optional, Tuple
from pathlib import Path
from ..utils import get_logger
import numpy as np
from ..config import get_terminal_growth_for_sector

logger = get_logger("company_specific_params")


class CompanySpecificParams:
    """
    Calcula parámetros específicos por empresa basados en sus características financieras
    Replica el enfoque de Alpha Spread: cada empresa tiene su propio modelo
    """
    
    def __init__(self, symbol: str, financial_data: Dict, growth_rates: Dict, 
                 historical_data: Optional[Dict] = None):
        """
        Args:
            symbol: Símbolo de la empresa
            financial_data: Datos financieros actuales
            growth_rates: Tasas de crecimiento históricas
            historical_data: Datos históricos adicionales (opcional)
        """
        self.symbol = symbol
        self.financial_data = financial_data
        self.growth_rates = growth_rates
        self.historical_data = historical_data or {}
        
        # Características calculadas
        self.sector = financial_data.get("sector", "Unknown")
        self.beta = financial_data.get("beta", 1.0)
        self.fcf = financial_data.get("free_cash_flow", 0)
        self.revenue = financial_data.get("revenue", 0)
        self.ebitda = financial_data.get("ebitda", 0)
        self.debt = financial_data.get("debt", 0)
        self.market_cap = financial_data.get("market_cap", 0)
        self.ebit_margin = financial_data.get("ebit_margin", 0)
        self.ebitda_margin = financial_data.get("ebitda_margin", 0)
    
    def calculate_fcf_stability_score(self) -> float:
        """
        Calcula estabilidad del FCF (0-1)
        Empresas con FCF estable → mayor confianza en DCF
        Empresas con FCF volátil → menor confianza en DCF
        """
        if self.fcf <= 0:
            return 0.0
        
        # Si tenemos datos históricos, calcular volatilidad
        if self.historical_data and "fcf_history" in self.historical_data:
            fcf_history = self.historical_data["fcf_history"]
            if len(fcf_history) >= 3:
                # Calcular coeficiente de variación
                mean_fcf = np.mean(fcf_history)
                std_fcf = np.std(fcf_history)
                if mean_fcf > 0:
                    cv = std_fcf / mean_fcf
                    # Score: 1.0 = muy estable, 0.0 = muy volátil
                    stability = max(0.0, min(1.0, 1.0 - cv))
                    return stability
        
        # Fallback: usar margen EBITDA como proxy de estabilidad
        if self.ebitda_margin > 0:
            # Empresas con márgenes altos tienden a tener FCF más estable
            margin_score = min(1.0, self.ebitda_margin / 30.0)  # 30% = máximo razonable
            return margin_score * 0.7  # Penalizar un poco sin datos históricos
        
        return 0.5  # Neutral si no hay datos
    
    def calculate_growth_adjustment(self) -> float:
        """
        Calcula factor de ajuste de crecimiento específico por empresa
        Basado en:
        - Crecimiento histórico
        - Estabilidad del crecimiento
        - Tendencias del sector
        """
        base_growth = self.growth_rates.get("fcf_growth", 5.0)
        
        # Ajustar según estabilidad
        stability = self.calculate_fcf_stability_score()
        
        # Empresas con crecimiento muy alto pero inestable → reducir
        if base_growth > 20.0:
            # Penalizar crecimiento extremo
            adjustment = 0.7 + (stability * 0.2)  # Entre 0.7-0.9
        elif base_growth > 15.0:
            adjustment = 0.8 + (stability * 0.15)  # Entre 0.8-0.95
        elif base_growth > 10.0:
            adjustment = 0.85 + (stability * 0.1)  # Entre 0.85-0.95
        elif base_growth < 0:
            # Crecimiento negativo → usar mínimo conservador
            adjustment = 0.5
        else:
            # Crecimiento razonable (3-10%)
            adjustment = 0.9 + (stability * 0.1)  # Entre 0.9-1.0
        
        return adjustment
    
    def calculate_wacc_adjustment(self) -> float:
        """
        Calcula factor de ajuste de WACC específico por empresa
        Basado en:
        - Beta (volatilidad)
        - Estructura de capital
        - Riesgo del sector
        """
        # Ajustar según beta
        beta_adj = 1.0
        if self.beta > 2.0:
            # Beta muy alto → aumentar WACC (más riesgo)
            beta_adj = 1.1 + (self.beta - 2.0) * 0.05  # +5% por cada punto de beta > 2
        elif self.beta < 0.5:
            # Beta muy bajo → reducir WACC (menos riesgo)
            beta_adj = 0.95 - (0.5 - self.beta) * 0.1  # -10% por cada punto de beta < 0.5
        
        # Ajustar según deuda
        debt_adj = 1.0
        if self.market_cap > 0:
            debt_ratio = self.debt / self.market_cap
            if debt_ratio > 0.5:
                # Deuda excesiva → aumentar WACC
                debt_adj = 1.05 + (debt_ratio - 0.5) * 0.1
            elif debt_ratio < 0.1:
                # Poca deuda → reducir WACC ligeramente
                debt_adj = 0.98
        
        # Combinar ajustes
        wacc_adjustment = (beta_adj + debt_adj) / 2.0
        
        # Limitar rango razonable
        return max(0.8, min(1.2, wacc_adjustment))
    
    def calculate_dcf_weight(self) -> float:
        """
        Calcula peso del DCF específico por empresa
        Empresas con FCF estable → más peso DCF
        Empresas con FCF volátil o negativo → menos peso DCF
        """
        stability = self.calculate_fcf_stability_score()
        
        # Base: 50% (como Alpha Spread)
        base_weight = 0.5
        
        # Ajustar según estabilidad
        if stability > 0.7:
            # FCF muy estable → más peso DCF
            dcf_weight = base_weight + (stability - 0.7) * 0.3  # Hasta 0.59
        elif stability < 0.3:
            # FCF muy volátil → menos peso DCF
            dcf_weight = base_weight - (0.3 - stability) * 0.3  # Hasta 0.41
        else:
            # Estabilidad media → mantener 50%
            dcf_weight = base_weight
        
        # Asegurar rango razonable
        return max(0.3, min(0.7, dcf_weight))
    
    def calculate_comparables_weight(self) -> float:
        """
        Calcula peso de Comparables específico por empresa
        Complemento de DCF weight (deben sumar 1.0)
        """
        dcf_weight = self.calculate_dcf_weight()
        return 1.0 - dcf_weight
    
    def calculate_terminal_growth(self) -> float:
        """
        Calcula terminal growth específico por sector y empresa
        Usa configuración centralizada de settings_valoration
        """
        return get_terminal_growth_for_sector(self.sector)
    
    def get_all_params(self) -> Dict:
        """
        Retorna todos los parámetros específicos por empresa
        """
        dcf_weight = self.calculate_dcf_weight()
        comparables_weight = self.calculate_comparables_weight()
        growth_adjustment = self.calculate_growth_adjustment()
        wacc_adjustment = self.calculate_wacc_adjustment()
        terminal_growth = self.calculate_terminal_growth()
        
        return {
            "symbol": self.symbol,
            "sector": self.sector,
            "dcf_weight": round(dcf_weight, 4),
            "comparables_weight": round(comparables_weight, 4),
            "growth_adjustment_factor": round(growth_adjustment, 4),
            "wacc_adjustment_factor": round(wacc_adjustment, 4),
            "terminal_growth_rate": round(terminal_growth, 2),
            "fcf_stability_score": round(self.calculate_fcf_stability_score(), 4),
            "beta": round(self.beta, 2),
            "debt_ratio": round(self.debt / self.market_cap if self.market_cap > 0 else 0, 4),
            "note": "Parámetros específicos calculados dinámicamente (como Alpha Spread)"
        }
    
    def save_model(self, output_dir: Path = Path("models")):
        """
        Guarda el modelo específico de la empresa en un archivo JSON
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        model_file = output_dir / f"{self.symbol.lower()}_model.json"
        
        params = self.get_all_params()
        
        with open(model_file, 'w', encoding='utf-8') as f:
            json.dump(params, f, indent=2, default=str)
        
        logger.info(f"[SAVE] Modelo guardado para {self.symbol}: {model_file}")
        return model_file
    
    @staticmethod
    def load_model(symbol: str, models_dir: Path = Path("models")) -> Optional[Dict]:
        """
        Carga el modelo específico de una empresa desde archivo JSON
        """
        model_file = models_dir / f"{symbol.lower()}_model.json"
        
        if not model_file.exists():
            return None
        
        try:
            with open(model_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"No se pudo cargar modelo para {symbol}: {e}")
            return None

