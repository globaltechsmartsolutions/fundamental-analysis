"""
Config - Configuración y estrategias por sector
"""
from typing import Dict, Optional
from .settings_valoration import (
    RISK_FREE_RATE,
    ALPHASPREAD_ERP,
    DEFAULT_TAX_RATE,
    PROJECTION_YEARS,
    DEFAULT_DCF_WEIGHT,
    DEFAULT_COMPARABLES_WEIGHT,
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
# Importación diferida para evitar circular imports
# from .sector_strategies import get_strategy_for_sector

__all__ = [
    'RISK_FREE_RATE',
    'ALPHASPREAD_ERP',
    'DEFAULT_TAX_RATE',
    'PROJECTION_YEARS',
    'DEFAULT_DCF_WEIGHT',
    'DEFAULT_COMPARABLES_WEIGHT',
    'get_terminal_growth_for_sector',
    'validate_tax_rate',
    'MIN_COST_OF_DEBT',
    'MAX_COST_OF_DEBT',
    'MAX_DEBT_TO_EQUITY',
    'MIN_BETA',
    'MAX_BETA',
    'MIN_GROWTH_RATE',
    'MAX_GROWTH_RATE',
    # 'get_strategy_for_sector',  # Importación diferida
]

def get_strategy_for_sector(sector: str, financial_data: Dict, growth_rates: Dict, company_params: Optional[Dict] = None):
    """Importación diferida para evitar circular imports"""
    from typing import Dict, Optional
    from .sector_strategies import get_strategy_for_sector as _get_strategy
    return _get_strategy(sector, financial_data, growth_rates, company_params)

