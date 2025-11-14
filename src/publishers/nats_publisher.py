"""
Publisher NATS para resultados de análisis fundamental
"""
from typing import Dict, Any, Optional
import orjson

try:
    from nats.aio.client import Client as NATS
    NATS_AVAILABLE = True
except ImportError:
    NATS_AVAILABLE = False
    NATS = None


class FundamentalAnalysisPublisher:
    """
    Publica resultados de análisis fundamental a NATS
    
    Formato simplificado para el bot:
    - buy: true/false (si debe comprar)
    - intrinsic_value: valor intrínseco calculado
    - current_price: precio actual
    - valuation_percentage: % de infravaloración/sobrevaloración
    """
    
    def __init__(self, nc, subject_prefix: str = "fundamental"):
        """
        Args:
            nc: Cliente NATS conectado
            subject_prefix: Prefijo para subjects (default: "fundamental")
        """
        if not NATS_AVAILABLE:
            raise ImportError("nats-py no está instalado. Instala con: pip install nats-py")
        self.nc = nc
        self.subject_prefix = subject_prefix.rstrip(".")
    
    async def publish_valuation(
        self,
        symbol: str,
        buy: bool,
        intrinsic_value: float,
        current_price: float,
        valuation_percentage: float,
        **extra_data: Dict[str, Any]
    ):
        """
        Publica resultado de valoración
        
        Args:
            symbol: Símbolo de la acción
            buy: True si debe comprar, False si no
            intrinsic_value: Valor intrínseco calculado
            current_price: Precio actual de mercado
            valuation_percentage: % de infravaloración (positivo) o sobrevaloración (negativo)
            **extra_data: Datos adicionales opcionales
        """
        payload = {
            "symbol": symbol,
            "buy": buy,
            "intrinsic_value": round(intrinsic_value, 2),
            "current_price": round(current_price, 2),
            "valuation_percentage": round(valuation_percentage, 2),
            **extra_data
        }
        
        subject = f"{self.subject_prefix}.valuation.{symbol}"
        message = orjson.dumps(payload)
        
        await self.nc.publish(subject, message)
        
        return subject, payload
    
    async def publish_analysis_result(
        self,
        symbol: str,
        buy: bool,
        intrinsic_value: float,
        current_price: float,
        valuation_percentage: float,
        surprise_eps: float = None,
        status: str = None,
        dcf_base: float = None,
        comparables_value: float = None
    ):
        """
        Publica resultado completo de análisis con datos adicionales
        
        Args:
            symbol: Símbolo de la acción
            buy: True si debe comprar
            intrinsic_value: Valor intrínseco (blended)
            current_price: Precio actual
            valuation_percentage: % de valoración
            surprise_eps: Surprise EPS si está disponible
            status: Status de valoración (undervalued, overvalued, etc.)
            dcf_base: Valor DCF base
            comparables_value: Valor por comparables
        """
        payload = {
            "symbol": symbol,
            "buy": buy,
            "intrinsic_value": round(intrinsic_value, 2),
            "current_price": round(current_price, 2),
            "valuation_percentage": round(valuation_percentage, 2),
        }
        
        # Agregar datos adicionales si están disponibles
        if surprise_eps is not None:
            payload["surprise_eps"] = round(surprise_eps, 4)
        if status:
            payload["status"] = status
        if dcf_base is not None:
            payload["dcf_base"] = round(dcf_base, 2)
        if comparables_value is not None:
            payload["comparables_value"] = round(comparables_value, 2)
        
        subject = f"{self.subject_prefix}.analysis.{symbol}"
        message = orjson.dumps(payload)
        
        await self.nc.publish(subject, message)
        
        return subject, payload

