"""Script para analizar errores de META específicamente"""
import re
from pathlib import Path
from collections import defaultdict

log_file = Path("../var/logs/fundamental_analysis.log")

if not log_file.exists():
    print(f"Log file no encontrado: {log_file}")
    exit(1)

pattern = r'\[META\].*Eval #(\d+): growth=([\d.]+), wacc=([\d.]+).*error=([\d.]+)%'

errors = []
error_counts = defaultdict(int)

print("Analizando META en logs...")
with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        match = re.search(pattern, line)
        if match:
            eval_num, growth, wacc, error = match.groups()
            growth = float(growth)
            wacc = float(wacc)
            error = float(error)
            
            errors.append({
                'eval': int(eval_num),
                'growth': growth,
                'wacc': wacc,
                'error': error
            })
            error_counts[error] += 1

if not errors:
    print("No se encontraron evaluaciones de META en los logs")
    exit(0)

unique_errors = sorted(set(e['error'] for e in errors))
sorted_errors = sorted(errors, key=lambda x: x['error'])

print(f"\n{'='*80}")
print(f"META: {len(errors)} evaluaciones encontradas")
print(f"{'='*80}")
print(f"Errores únicos: {len(unique_errors)}")
print(f"Rango: {min(unique_errors):.2f}% - {max(unique_errors):.2f}%")
print(f"Mejor error: {min(unique_errors):.2f}%")
print(f"Peor error: {max(unique_errors):.2f}%")

print(f"\nTop 20 mejores errores:")
for i, err in enumerate(sorted_errors[:20], 1):
    print(f"  {i:2d}. growth={err['growth']:6.3f}, wacc={err['wacc']:5.3f} → error={err['error']:6.2f}%")

print(f"\nDistribución de errores (top 20 más comunes):")
sorted_counts = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)
for error_val, count in sorted_counts[:20]:
    pct = count / len(errors) * 100
    print(f"  {error_val:6.2f}%: {count:5d} veces ({pct:5.1f}%)")

most_common = max(error_counts.items(), key=lambda x: x[1])
if most_common[1] > len(errors) * 0.3:
    print(f"\n⚠️ ADVERTENCIA: {most_common[1]} de {len(errors)} evaluaciones ({most_common[1]/len(errors)*100:.1f}%) dieron el mismo error: {most_common[0]:.2f}%")
    print(f"   Esto sugiere que muchas combinaciones diferentes están dando el mismo resultado.")

