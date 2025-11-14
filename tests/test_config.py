#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, 'src')
from target_value_fetcher import USE_SCRAPING_ONLY, fetch_target_from_web, fetch_multiple_targets

print("=" * 60)
print("CONFIGURACION DE TARGET VALUE FETCHER")
print("=" * 60)
print(f"\nUSE_SCRAPING_ONLY por defecto: {USE_SCRAPING_ONLY}")
print("\nComportamiento:")
if USE_SCRAPING_ONLY:
    print("  - Usa SOLO scraping (valores actualizados desde Alpha Spread)")
else:
    print("  - Usa SOLO JSON (valores desde target_values_example.json)")

print("\n" + "=" * 60)
print("PRUEBA:")
print("=" * 60)

# Probar con configuración actual
print("\nProbando AAPL con configuración actual:")
val = fetch_target_from_web('AAPL', use_scraping_only=None)
print(f"  AAPL: ${val:.2f}" if val else "  AAPL: No disponible")

print("\nProbando múltiples símbolos desde JSON:")
vals = fetch_multiple_targets(['AAPL', 'MSFT', 'GOOGL'], use_scraping_only=False)
for symbol, value in vals.items():
    print(f"  {symbol}: ${value:.2f}" if value else f"  {symbol}: No disponible")

print("\n" + "=" * 60)
print("PARA CAMBIAR LA CONFIGURACION:")
print("=" * 60)
print("\nWindows PowerShell:")
print('  $env:USE_SCRAPING_ONLY = "true"   # Usar scraping')
print('  $env:USE_SCRAPING_ONLY = "false"  # Usar JSON (por defecto)')
print("\nLinux/Mac:")
print('  export USE_SCRAPING_ONLY=true   # Usar scraping')
print('  export USE_SCRAPING_ONLY=false  # Usar JSON (por defecto)')

