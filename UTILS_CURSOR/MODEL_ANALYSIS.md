# Análisis del Modelo de Entrenamiento vs Valores Objetivo

## Estado Actual del Modelo

### Parámetros Entrenados (`trained_params.json`)
```json
{
  "growth_adjustment_factor": 0.772,  // Reduce crecimiento en ~23%
  "wacc_adjustment_factor": 1.064,    // Aumenta WACC en ~6%
  "dcf_weight": 0.5,                  // Fijo 50%
  "comparables_weight": 0.5,          // Fijo 50%
  "error_pct": 43.7%                  // ⚠️ MUY ALTO
}
```

### Resultados del Entrenamiento (Iteración 80)

| Símbolo | Estimado | Objetivo | Error | DCF | Comparables |
|---------|----------|----------|-------|-----|-------------|
| META    | $660.56  | $544.05  | 21.4% | $458.81 | $862.31 ⚠️ |
| TSLA    | $56.21   | $43.50   | 29.2% | $11.33 | $101.08 ⚠️ |
| AVGO    | ?        | $249.89  | ?     | ?    | ?          |

## Problemas Identificados

### 1. **Modelo Demasiado Simplificado**
- **Problema**: Solo ajusta 2 parámetros globales para todas las empresas
- **Realidad**: Alpha Spread probablemente usa parámetros específicos por empresa
- **Evidencia**: Empresas con características muy diferentes (META vs TSLA) necesitan ajustes diferentes

### 2. **Comparables Está Sobrevalorando**
- **META**: Comparables = $862 vs Objetivo = $544 (58% más alto)
- **TSLA**: Comparables = $101 vs Objetivo = $43.5 (132% más alto)
- **Causa probable**: Promedios del sector incorrectos o pesos de múltiplos incorrectos

### 3. **DCF Está Subvalorando en Algunos Casos**
- **TSLA**: DCF = $11.33 vs Objetivo = $43.5 (74% más bajo)
- **Causa probable**: Crecimiento ajustado demasiado conservador (0.772 factor)

### 4. **Parámetros Específicos por Empresa No Se Usan**
- El código calcula `CompanySpecificParams` pero luego los sobrescribe con parámetros globales
- Esto elimina la capacidad de ajuste fino por empresa

## Análisis de Por Qué No Se Alcanzan los Valores Objetivo

### Limitaciones del Modelo Actual

1. **Factores Globales vs Específicos**
   - ✅ **Actual**: Un factor de crecimiento (0.772) para todas las empresas
   - ❌ **Necesario**: Factores específicos por empresa según características

2. **Pesos Fijos 50/50**
   - ✅ **Actual**: Siempre 50% DCF + 50% Comparables
   - ❌ **Necesario**: Pesos específicos según estabilidad FCF y sector

3. **Comparables No Optimizado**
   - ✅ **Actual**: Promedio ponderado fijo (40% P/E, 20% P/B, 25% P/S, 15% EV/EBITDA)
   - ❌ **Necesario**: Pesos específicos por sector/empresa

4. **Promedios del Sector Basados en Pocos Peers**
   - ✅ **Actual**: Solo 3 peers (reducido de 5)
   - ❌ **Problema**: Con solo 3 peers, los promedios pueden ser poco representativos

## Soluciones Propuestas

### Opción 1: Entrenar Parámetros Específicos por Empresa (RECOMENDADO)
**Ventajas**:
- Replica mejor el enfoque de Alpha Spread
- Permite ajuste fino por empresa
- Mejor precisión esperada

**Desventajas**:
- Más complejo de entrenar
- Requiere más datos de entrenamiento

**Implementación**:
- Entrenar `growth_adjustment_factor` y `wacc_adjustment_factor` por empresa
- Guardar en modelos específicos (`models/{symbol}_model.json`)
- Usar en producción en lugar de sobrescribir con globales

### Opción 2: Mejorar Comparables
**Problemas actuales**:
- Promedios del sector pueden ser incorrectos
- Pesos de múltiplos fijos pueden no ser óptimos
- EV/EBITDA puede estar mal calculado (ya corregido)

**Mejoras**:
- Validar promedios del sector con más peers
- Ajustar pesos de múltiplos según sector
- Mejorar fallbacks cuando no hay suficientes peers

### Opción 3: Entrenar Pesos del Blend
**Actual**: Pesos fijos 50/50
**Propuesta**: Entrenar pesos específicos por empresa según:
- Estabilidad FCF
- Sector
- Calidad de datos

### Opción 4: Combinación (MEJOR OPCIÓN)
1. Entrenar factores globales como baseline
2. Entrenar ajustes específicos por empresa
3. Mejorar cálculo de Comparables
4. Entrenar pesos del blend por empresa

## Recomendación Final

**NO, con el modelo actual NO se pueden alcanzar los valores objetivo** porque:

1. **Error demasiado alto (43.7%)**: Indica que el modelo no captura las diferencias entre empresas
2. **Parámetros globales insuficientes**: Empresas diferentes necesitan ajustes diferentes
3. **Comparables sobrevalorando**: Necesita mejor calibración
4. **DCF subvalorando en algunos casos**: Necesita ajustes específicos

**Para alcanzar los valores objetivo se necesita**:

1. ✅ Entrenar parámetros específicos por empresa (no solo globales)
2. ✅ Mejorar cálculo de Comparables (pesos y promedios del sector)
3. ✅ Entrenar pesos del blend por empresa
4. ✅ Validar y mejorar datos de entrada (peers, promedios del sector)

## Próximos Pasos Sugeridos

1. **Análisis detallado**: Comparar valores calculados vs objetivos empresa por empresa
2. **Identificar patrones**: ¿Qué empresas funcionan bien? ¿Cuáles se disparan?
3. **Entrenar modelo específico**: Crear modelo que entrena parámetros por empresa
4. **Validar Comparables**: Revisar cálculo de promedios del sector y pesos de múltiplos

