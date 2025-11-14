"""
Data - Extracción y gestión de datos financieros
"""
from .finnhub_client import FinnhubClient
from .data_extractor import FinancialDataExtractor
from .cache_manager import CacheManager
# target_value_fetcher movido a src/target_value_fetcher.py
from ..target_value_fetcher import fetch_target_from_web, fetch_multiple_targets

__all__ = [
    'FinnhubClient',
    'FinancialDataExtractor',
    'CacheManager',
    'fetch_target_from_web',
    'fetch_multiple_targets',
]

