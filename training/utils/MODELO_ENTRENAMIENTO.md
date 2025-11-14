# Modelo de Entrenamiento - Documentación Completa

## 📋 Resumen Ejecutivo

El sistema de entrenamiento optimiza parámetros del modelo de valoración para replicar los valores de Alpha Spread. Utiliza una estrategia híbrida: **entrenamiento individual para empresas críticas** y **entrenamiento global para el resto**.

---

## 🎯 Objetivo

Minimizar el error entre nuestros valores calculados y los valores objetivo de Alpha Spread, categorizando empresas según su error y aplicando estrategias diferenciadas.

---

## 🏗️ Arquitectura del Entrenamiento

### Flujo Principal

```
┌─────────────────────────────────────────────────────────┐
│ PASO 0: Preparar Datos                                 │
│ - Cargar caché desde disco                              │
│ - Precargar datos financieros faltantes                 │
└─────────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────────┐
│ PASO 1: Identificar Empresas Críticas                  │
│ - Evaluar todas las empresas con parámetros iniciales   │
│ - Categorizar: BUENAS (<10%), INTERMEDIAS (10-30%),     │
│   CRÍTICAS (>=30%)                                       │
└─────────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────────┐
│ PASO 2: Entrenamiento Individual (Solo Críticas)        │
│ Para cada empresa crítica:                              │
│   ├─ Intento 1: 500 iteraciones → ¿Error < 10%?        │
│   ├─ Intento 2: 1000 iteraciones → ¿Error < 10%?       │
│   └─ Intento 3: 1500 iteraciones → ¿Error < 10%?       │
│   Guardar modelo en models/{symbol}_model.json          │
└─────────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────────┐
│ PASO 3: Entrenamiento Global (Resto de Empresas)     │
│ - Optimizar parámetros globales con pesos diferenciados │
│ - Críticas: 60%, Intermedias: 30%, Buenas: 10%         │
└─────────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────────┐
│ PASO 4: Análisis de Errores Extremos                    │
│ - Identificar causas de errores altos                   │
│ - Diagnosticar problemas por empresa                    │
└─────────────────────────────────────────────────────────┘
```

---

## 📊 Categorización de Empresas

### Sistema de 3 Niveles

| Categoría | Error | Peso en Optimización | Acción |
|----------|-------|---------------------|--------|
| **BUENAS** | < 10% | 10% | Mantener (evitar empeorarlas) |
| **INTERMEDIAS** | 10% - 30% | 30% | Mejorar |
| **CRÍTICAS** | >= 30% | 60% | Entrenamiento individual prioritario |

### Lógica de Pesos

```python
# Si hay empresas de todas las categorías:
combined_error = 0.6 * error_críticas + 0.3 * error_intermedias + 0.1 * error_buenas

# Si solo hay críticas:
combined_error = error_críticas (100% peso)

# Si solo hay buenas:
combined_error = error_buenas (100% peso)
```

---

## 🔧 Parámetros que se Optimizan

### Modo Alpha Spread (Actual)

**Parámetros FIJOS:**
- `dcf_weight`: 0.5 (50%)
- `comparables_weight`: 0.5 (50%)
- `projection_years`: 10
- `terminal_growth_rate`: Por sector (Tech=2.5%, Utilities=1.5%, etc.)
- `market_risk_premium`: 4.12% (como Alpha Spread)
- `risk_free_rate`: 4.5%

**Parámetros OPTIMIZADOS:**
- `growth_adjustment_factor`: [0.5, 1.5] - Factor que multiplica el crecimiento FCF histórico
- `wacc_adjustment_factor`: [0.7, 1.3] - Factor que multiplica el WACC calculado

### Validación de Parámetros

Los parámetros entrenados se validan antes de guardar:
- `growth_adjustment_factor`: Debe estar entre [0.3, 2.0] y no ser 0
- `wacc_adjustment_factor`: Debe estar entre [0.5, 1.5] y no ser 0

Si son inválidos → Se descartan y se reintenta automáticamente.

---

## 🎓 Entrenamiento Individual (Empresas Críticas)

### Proceso por Empresa

1. **Identificación**: Empresa con error >= 30%
2. **Objetivo**: Reducir error a < 10%
3. **Método**: `differential_evolution` optimizando solo 2 parámetros:
   - `growth_adjustment_factor`
   - `wacc_adjustment_factor`
4. **Reintentos**: Hasta 3 intentos con iteraciones crecientes:
   - Intento 1: 500 iteraciones
   - Intento 2: 1000 iteraciones
   - Intento 3: 1500 iteraciones
5. **Parada temprana**: Si alcanza error < 10%, se detiene inmediatamente
6. **Guardado**: Modelo guardado en `models/{symbol}_model.json` usando formato `CompanySpecificParams`

### Formato del Modelo Guardado

```json
{
  "symbol": "TSLA",
  "sector": "Consumer Cyclical",
  "dcf_weight": 0.5,
  "comparables_weight": 0.5,
  "growth_adjustment_factor": 0.85,  // ← Entrenado
  "wacc_adjustment_factor": 1.12,     // ← Entrenado
  "terminal_growth_rate": 2.0,
  "fcf_stability_score": 0.65,
  "beta": 2.1,
  "debt_ratio": 0.15,
  "error": 0.095,           // Error en escala log1p
  "error_pct": 9.5,         // Error en porcentaje real
  "trained": true,
  "training_note": "Modelo entrenado individualmente hasta alcanzar error < 10.0%"
}
```

---

## 🌐 Entrenamiento Global

### Para Empresas No-Críticas

- **Algoritmo**: `differential_evolution`
- **Iteraciones**: 300-500 según número de empresas
- **Población**: 12-20 individuos
- **Objetivo**: Error combinado < 5-15% (según número de empresas)
- **Parada temprana**: Si alcanza objetivo, se detiene automáticamente

### Función Objetivo

```python
def objective(params):
    # Evalúa TODAS las empresas con estos parámetros
    # Retorna error combinado con pesos diferenciados:
    # - Críticas: 60% peso
    # - Intermedias: 30% peso  
    # - Buenas: 10% peso
    return combined_error
```

---

## 📈 Métrica de Error

### Escala log1p

Los errores se trabajan en escala `log1p` para:
- Suavizar errores extremos (evita que un outlier domine)
- Mantener sensibilidad a mejoras pequeñas
- Permitir optimización más estable

**Conversión:**
```python
error_log1p = np.log1p(error_pct)      # Porcentaje → log1p
error_pct = np.expm1(error_log1p)      # log1p → Porcentaje
```

### Cálculo del Error

```python
# Por empresa:
error_pct = abs((valor_calculado - valor_objetivo) / valor_objetivo) * 100

# Error combinado (con pesos):
combined_error = 0.6 * error_críticas + 0.3 * error_intermedias + 0.1 * error_buenas
```

---

## 🔍 Evaluación de Empresas

### `_evaluate_single_company()`

Para cada empresa:

1. **Carga datos del caché** (evita peticiones repetidas)
2. **Valida FCF**: Si FCF <= 0, excluye del entrenamiento
3. **Calcula DCF**:
   - Usa datos reales: beta, debt, equity, cost_of_debt
   - Aplica `growth_adjustment_factor` al crecimiento FCF
   - Aplica `wacc_adjustment_factor` al WACC
4. **Calcula Comparables**:
   - Usa promedios del sector
   - Compara múltiplos (P/E, P/B, P/S, EV/EBITDA)
5. **Blended Value**:
   - `valor = (DCF × dcf_weight) + (Comparables × comparables_weight)`
6. **Error**:
   - `error = abs((valor - objetivo) / objetivo) * 100`

---

## 💾 Sistema de Caché

### Datos Cacheados

- **Datos financieros**: `financial_data_cache`
- **Tasas de crecimiento**: `growth_rates_cache`
- **Promedios del sector**: `sector_averages_cache`
- **Peers**: `peers_cache`

### Persistencia

- Guardado en: `training_cache.json`
- Se carga automáticamente al inicio
- Se actualiza cuando se obtienen nuevos datos

---

## 🎯 Objetivos de Error

### Por Número de Empresas

| Empresas | Objetivo Global | Iteraciones Máx | Población |
|----------|----------------|-----------------|-----------|
| <= 7 | 5% | 300 | 12 |
| 8-11 | 10% | 400 | 15 |
| >= 15 | 15% | 500 | 20 |

### Objetivo Individual

- **Empresas críticas**: Error < 10% (entrenamiento individual)
- **Parada temprana**: Se detiene cuando alcanza objetivo

---

## 🚨 Análisis de Errores Extremos

### `analyze_extreme_errors()`

Analiza empresas con error >= 30% para identificar causas:

1. **Datos financieros problemáticos**:
   - FCF <= 0 o muy bajo/alto
   - Datos faltantes

2. **Crecimientos extremos**:
   - Crecimiento FCF > 50% (insostenible)
   - Crecimiento FCF < -20% (declive)

3. **Análisis por método**:
   - Calcula DCF y Comparables por separado
   - Identifica cuál método falla más

4. **Discrepancias**:
   - Gran diferencia entre DCF y Comparables (>50%)

5. **Problemas de datos**:
   - Datos de sector/peers insuficientes
   - Beta extremo

---

## 📁 Archivos Generados

### Modelos Individuales
- **Ubicación**: `models/{symbol}_model.json`
- **Formato**: Compatible con `CompanySpecificParams.load_model()`
- **Contenido**: Parámetros optimizados + metadatos de entrenamiento

### Parámetros Globales
- **Ubicación**: `trained_params.json`
- **Contenido**: Parámetros globales optimizados para todas las empresas

### Checkpoints
- **Ubicación**: `training_checkpoint.json`
- **Contenido**: Estado del entrenamiento (mejores parámetros hasta ahora)

### Análisis
- **Ubicación**: `training_results_iter_{N}.json`
- **Contenido**: Resultados detallados por empresa

---

## 🔄 Integración con main.py

### Carga de Modelos

```python
# En main.py, calculate_valuation_for_symbol():
models_dir = Path("models")
company_model = CompanySpecificParams.load_model(symbol, models_dir)

if company_model and 'trained' in company_model:
    # Usar modelo entrenado (prioridad máxima)
    company_params = company_model.copy()
    # growth_adjustment_factor y wacc_adjustment_factor ya están optimizados
```

### Prioridad de Parámetros

1. **Modelo individual entrenado** (`models/{symbol}_model.json`) - Máxima prioridad
2. **Parámetros globales entrenados** (`trained_params.json`) - Segunda prioridad
3. **Parámetros calculados dinámicamente** - Fallback

---

## ⚙️ Configuración Actual

### Modo Alpha Spread

- **Pesos**: 50/50 fijo (no se optimizan)
- **ERP**: 4.12% (como Alpha Spread)
- **Terminal Growth**: Por sector (conservador)
- **Parámetros optimizados**: Solo `growth_adjustment_factor` y `wacc_adjustment_factor`

### Timeouts

- **Evaluación individual**: 30 segundos por empresa
- **Evaluación completa**: 180 segundos máximo
- **API calls**: 30 segundos máximo, 2 reintentos

---

## 📝 Logging

### Niveles Reducidos

- **Progreso**: Cada 10 iteraciones
- **Detalles por empresa**: Cada 50 iteraciones o cuando está cerca del objetivo
- **Errores**: Siempre se muestran

### Información Clave

- Empresas críticas identificadas
- Progreso de entrenamiento individual
- Objetivos alcanzados
- Problemas identificados en análisis

---

## 🎯 Estrategia Actual

1. **Preparar datos** → Cargar caché y precargar faltantes
2. **Identificar críticas** → Evaluar todas y categorizar
3. **Entrenar críticas individualmente** → Hasta alcanzar < 10% o 3 intentos
4. **Entrenar resto globalmente** → Con pesos diferenciados
5. **Analizar errores extremos** → Diagnosticar causas

---

## 🔍 Puntos Clave

- ✅ **Entrenamiento individual** para empresas críticas (error >= 30%)
- ✅ **Validación de parámetros** antes de guardar (evita valores disparatados)
- ✅ **Reintentos automáticos** si parámetros son inválidos
- ✅ **Pesos diferenciados** según severidad del error
- ✅ **Parada temprana** cuando se alcanza objetivo
- ✅ **Análisis automático** de causas de errores extremos
- ✅ **Formato CompanySpecificParams** para compatibilidad con main.py

