"""
Lógica de decisión de compra basada en análisis fundamental
"""
from typing import Optional
from .valuation_engine import ValuationResult


class BuyDecisionEngine:
    """
    Determina si se debe comprar una acción basado en:
    - Surprise EPS positivo
    - Infravaloración > 25%
    """
    
    def __init__(self, undervaluation_threshold: float = 25.0):
        """
        Args:
            undervaluation_threshold: Umbral mínimo de infravaloración para comprar (%)
        """
        self.undervaluation_threshold = undervaluation_threshold
    
    def should_buy(
        self,
        surprise_eps: Optional[float],
        valuation_result: ValuationResult
    ) -> bool:
        """
        Determina si se debe comprar la acción
        
        Condiciones:
        1. Surprise EPS debe ser positivo (mayor que 0)
        2. Infravaloración debe ser mayor al umbral (default 25%)
        
        Args:
            surprise_eps: Surprise EPS (None si no disponible)
            valuation_result: Resultado de la valoración
        
        Returns:
            True si se debe comprar, False en caso contrario
        """
        # Condición 1: Surprise EPS positivo
        if surprise_eps is None or surprise_eps <= 0:
            return False
        
        # Condición 2: Infravaloración mayor al umbral
        if valuation_result.undervaluation_percentage < self.undervaluation_threshold:
            return False
        
        # Ambas condiciones cumplidas
        return True
    
    def get_decision_details(
        self,
        surprise_eps: Optional[float],
        valuation_result: ValuationResult
    ) -> dict:
        """
        Obtiene detalles de la decisión de compra
        
        Returns:
            Dict con:
            - buy: True/False
            - reason: Razón de la decisión
            - surprise_eps_ok: Si surprise EPS es positivo
            - undervaluation_ok: Si cumple umbral de infravaloración
        """
        surprise_ok = surprise_eps is not None and surprise_eps > 0
        undervaluation_ok = valuation_result.undervaluation_percentage >= self.undervaluation_threshold
        
        buy = surprise_ok and undervaluation_ok
        
        # Determinar razón
        if not surprise_ok:
            reason = f"Surprise EPS no positivo ({surprise_eps if surprise_eps else 'N/A'})"
        elif not undervaluation_ok:
            reason = f"Infravaloración insuficiente ({valuation_result.undervaluation_percentage:.1f}% < {self.undervaluation_threshold}%)"
        else:
            reason = f"Cumple condiciones: Surprise EPS +{surprise_eps:.2f}, Infravaloración {valuation_result.undervaluation_percentage:.1f}%"
        
        return {
            "buy": buy,
            "reason": reason,
            "surprise_eps_ok": surprise_ok,
            "undervaluation_ok": undervaluation_ok,
            "surprise_eps": surprise_eps,
            "undervaluation_percentage": valuation_result.undervaluation_percentage,
            "threshold": self.undervaluation_threshold
        }

