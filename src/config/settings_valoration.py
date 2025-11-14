"""
Configuración Centralizada de Parámetros de Valoración
Punto único de verdad para todos los parámetros del modelo
Evita desviaciones entre entrenamiento y producción
"""
from typing import Dict

# ============================================================================
# PARÁMETROS MACROECONÓMICOS GLOBALES
# ============================================================================

# Tasa libre de riesgo (Risk-Free Rate)
# Basada en bonos del Tesoro USA a 10 años (2024)
RISK_FREE_RATE = 4.5  # Porcentaje anual

# Prima de riesgo de mercado (Equity Risk Premium - ERP)
DEFAULT_ERP = 5.8  # ERP estándar (más conservador)
ALPHASPREAD_ERP = 4.12  # ERP que usa Alpha Spread públicamente

# Tasa de impuestos corporativa
DEFAULT_TAX_RATE = 21.0  # Porcentaje (se convierte a fracción internamente)

# Años de proyección explícita
PROJECTION_YEARS = 10

# ============================================================================
# TERMINAL GROWTH RATE POR SECTOR
# ============================================================================
# Alpha Spread usa valores conservadores por sector
# Tech → 2.5%, Utilities → 1.5%, Healthcare/Industrials → 2.0%

SECTOR_TERMINAL_GROWTH: Dict[str, float] = {
    # Technology
    "technology": 2.5,
    "tech": 2.5,
    "software": 2.5,
    "semiconductor": 2.5,
    
    # Healthcare
    "healthcare": 2.0,
    "pharmaceutical": 2.0,
    "biotechnology": 2.0,
    
    # Financial Services
    "financial services": 2.0,
    "financial": 2.0,
    "banking": 2.0,
    
    # Consumer & Retail
    "consumer cyclical": 2.0,
    "consumer discretionary": 2.0,
    "retail": 2.0,
    "consumer defensive": 1.8,
    "consumer staples": 1.8,
    
    # Industrials
    "industrials": 2.0,
    "industrial": 2.0,
    
    # Communication Services
    "communication services": 2.0,
    "telecommunications": 2.0,
    
    # Utilities (más conservador)
    "utilities": 1.5,
    "utility": 1.5,
    
    # Energy & Materials
    "energy": 1.8,
    "basic materials": 1.8,
    "materials": 1.8,
    
    # Real Estate
    "real estate": 1.8,
}

# Terminal growth por defecto (si no se encuentra el sector)
DEFAULT_TERMINAL_GROWTH = 2.0

# ============================================================================
# PARÁMETROS DE AJUSTE Y LÍMITES
# ============================================================================

# Límites para cost_of_debt
MIN_COST_OF_DEBT = 3.0  # Porcentaje mínimo
MAX_COST_OF_DEBT = 10.0  # Porcentaje máximo

# Límites para debt_to_equity
MAX_DEBT_TO_EQUITY = 2.0  # Ratio máximo razonable

# Límites para beta
MIN_BETA = 0.3  # Beta mínimo válido
MAX_BETA = 5.0  # Beta máximo válido

# Límites para growth rate
MIN_GROWTH_RATE = -10.0  # Porcentaje mínimo (permite decrecimiento)
MAX_GROWTH_RATE = 20.0  # Porcentaje máximo

# ============================================================================
# PARÁMETROS DE BLEND DCF + COMPARABLES
# ============================================================================

# Pesos por defecto (Alpha Spread usa promedio simple 50/50)
DEFAULT_DCF_WEIGHT = 0.5
DEFAULT_COMPARABLES_WEIGHT = 0.5

# Rango de pesos permitidos
MIN_DCF_WEIGHT = 0.3  # Mínimo peso DCF (30%)
MAX_DCF_WEIGHT = 0.7  # Máximo peso DCF (70%)

# ============================================================================
# PARÁMETROS DE ENTRENAMIENTO
# ============================================================================

# Error máximo por empresa (para evitar outliers extremos)
MAX_ERROR_PER_COMPANY = 400.0  # Porcentaje máximo

# Error objetivo por número de empresas
TARGET_ERROR_BY_COMPANIES = {
    7: 10.0,   # Dataset pequeño (TECH_CLEAN_ALPHA)
    11: 25.0,  # Dataset mediano (TECH_ONLY)
    15: 30.0,  # Dataset grande
}

# ============================================================================
# FUNCIONES UTILITARIAS
# ============================================================================

def get_terminal_growth_for_sector(sector: str) -> float:
    """
    Retorna terminal growth rate específico por sector
    
    Args:
        sector: Nombre del sector (case-insensitive)
    
    Returns:
        Terminal growth rate en porcentaje
    """
    sector_lower = sector.lower() if sector else ""
    
    # Buscar coincidencia exacta o parcial
    for key, value in SECTOR_TERMINAL_GROWTH.items():
        if key in sector_lower:
            return value
    
    # Default si no se encuentra
    return DEFAULT_TERMINAL_GROWTH


def get_target_error(num_companies: int) -> float:
    """
    Retorna error objetivo según número de empresas
    
    Args:
        num_companies: Número de empresas en el dataset
    
    Returns:
        Error objetivo en porcentaje
    """
    # Buscar el threshold más cercano
    thresholds = sorted(TARGET_ERROR_BY_COMPANIES.keys())
    
    for threshold in thresholds:
        if num_companies <= threshold:
            return TARGET_ERROR_BY_COMPANIES[threshold]
    
    # Si es mayor que el máximo, usar el máximo
    return TARGET_ERROR_BY_COMPANIES[max(thresholds)]


def validate_tax_rate(tax_rate: float) -> float:
    """
    Valida y normaliza tax_rate (acepta porcentaje o fracción)
    
    Args:
        tax_rate: Tasa de impuestos (puede venir como porcentaje o fracción)
    
    Returns:
        Tasa de impuestos como fracción (0.21 para 21%)
    """
    if tax_rate > 1.0:
        # Viene como porcentaje, convertir a fracción
        return tax_rate / 100.0
    else:
        # Ya viene como fracción
        return tax_rate

