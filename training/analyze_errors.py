"""Script para analizar errores en los logs de entrenamiento"""
import re
from pathlib import Path
from collections import defaultdict

log_file = Path("../var/logs/fundamental_analysis.log")

if not log_file.exists():
    print(f"Log file no encontrado: {log_file}")
    exit(1)

# Patrón para extraer: symbol, eval_num, growth, wacc, error
pattern = r'\[(\w+)\].*Eval #(\d+): growth=([\d.]+), wacc=([\d.]+).*error=([\d.]+)%'

errors_by_symbol = defaultdict(list)
unique_errors = defaultdict(set)

print("Analizando logs...")
with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        match = re.search(pattern, line)
        if match:
            symbol, eval_num, growth, wacc, error = match.groups()
            growth = float(growth)
            wacc = float(wacc)
            error = float(error)
            
            errors_by_symbol[symbol].append({
                'eval': int(eval_num),
                'growth': growth,
                'wacc': wacc,
                'error': error
            })
            unique_errors[symbol].add(error)

print("\n" + "="*80)
print("RESUMEN DE ERRORES POR EMPRESA")
print("="*80)

for symbol in sorted(errors_by_symbol.keys()):
    errors = errors_by_symbol[symbol]
    unique = sorted(unique_errors[symbol])
    
    print(f"\n{symbol}:")
    print(f"  Total evaluaciones: {len(errors)}")
    print(f"  Errores únicos encontrados: {len(unique)}")
    print(f"  Rango de errores: {min(unique):.2f}% - {max(unique):.2f}%")
    print(f"  Mejor error: {min(unique):.2f}%")
    print(f"  Peor error: {max(unique):.2f}%")
    
    # Mostrar los 10 mejores errores
    sorted_errors = sorted(errors, key=lambda x: x['error'])
    print(f"\n  Top 10 mejores errores:")
    for i, err in enumerate(sorted_errors[:10], 1):
        print(f"    {i}. growth={err['growth']:.3f}, wacc={err['wacc']:.3f} → error={err['error']:.2f}%")
    
    # Verificar si hay muchos errores iguales
    error_counts = defaultdict(int)
    for err in errors:
        error_counts[err['error']] += 1
    
    most_common_error = max(error_counts.items(), key=lambda x: x[1])
    if most_common_error[1] > len(errors) * 0.5:
        print(f"\n  ⚠️ ADVERTENCIA: {most_common_error[1]} de {len(errors)} evaluaciones ({most_common_error[1]/len(errors)*100:.1f}%) dieron el mismo error: {most_common_error[0]:.2f}%")
    
    # Mostrar distribución de errores
    print(f"\n  Distribución de errores:")
    for err_val in sorted(unique)[:10]:
        count = error_counts[err_val]
        pct = count / len(errors) * 100
        print(f"    {err_val:.2f}%: {count} veces ({pct:.1f}%)")

print("\n" + "="*80)
print("ANÁLISIS COMPLETO")
print("="*80)

