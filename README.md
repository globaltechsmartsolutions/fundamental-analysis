# Fundamental Analysis Engine

Motor de análisis fundamental estilo Alpha Spread que combina métodos DCF (Discounted Cash Flow) y Comparables para calcular el valor intrínseco de acciones.

## 📋 Flujo Principal

El sistema sigue este flujo completo para analizar empresas:

### Paso 1: Filtrar por Surprise EPS Positivo
- Obtiene datos de earnings de Finnhub API
- Filtra empresas con surprise EPS positivo (mejor resultado que lo esperado)
- Solo analiza empresas con potencial alcista

### Paso 2: Extraer Datos Financieros
- **Precio actual**: Cotización en tiempo real
- **Free Cash Flow (FCF)**: Flujo de caja libre (millones)
- **Shares Outstanding**: Acciones en circulación (millones)
- **EPS**: Earnings per Share
- **Market Cap**: Capitalización de mercado (millones)
- **Revenue, Net Income, EBITDA**: Ingresos, beneficios, EBITDA
- **Debt, Cash**: Deuda total y efectivo (millones)
- **Beta, Sector**: Beta real y sector de la empresa

### Paso 3: Calcular Valoración

#### 3.1 Método DCF (Discounted Cash Flow)
- Proyecta FCF a 10 años con crecimiento decreciente
- Calcula WACC (Weighted Average Cost of Capital) usando:
  - Beta real de la empresa
  - Cost of debt real (interest_expense / total_debt)
  - Debt-to-equity real (total_debt / shareholder_equity)
- Calcula valor terminal usando Gordon Growth Model
- Descuenta flujos y valor terminal al presente
- Genera 3 escenarios: pesimista, base, optimista

#### 3.2 Método Comparables
- Calcula múltiplos del sector usando **peers reales**:
  - **P/E** (Price/Earnings): Compara con promedio de peers
  - **P/B** (Price/Book): Compara valor contable
  - **P/S** (Price/Sales): Compara ingresos
  - **EV/EBITDA**: Usa **EV real** = Market Cap + Debt - Cash
- Obtiene promedios del sector iterando sobre hasta 10 peers
- Calcula valor justo basado en múltiplos del sector

#### 3.3 Valoración Combinada (Blended)
- **Promedio simple 50/50**: (DCF × 50%) + (Comparables × 50%)
- Estilo Alpha Spread: "To enhance accuracy, we average the results from these two methods"

### Paso 4: Decisión de Compra
- **Criterio**: Surprise EPS > 0 Y infravaloración > 25%
- Calcula porcentaje de infravaloración: `((Fair Value - Current Price) / Current Price) × 100`
- Determina status: undervalued, fair, overvalued

### Paso 5: Publicar a NATS (Opcional)
- Publica resultados a NATS para consumo del bot de trading
- Subject: `fundamental.valuation.{SYMBOL}`
- Payload incluye: symbol, buy, intrinsic_value, current_price, valuation_percentage

### Paso 6: Guardar Resultados
- Guarda resultados en JSON
- Ordena por oportunidad (mayor infravaloración primero)

## 🚀 Características Principales

### Validación de Inputs
- ✅ Validación de precio válido (>0, <100000)
- ✅ Validación de shares_outstanding con fallback a market_cap
- ✅ Validación de EPS razonable (-100 a 1000)
- ✅ Validación de growth_rate (-10% a 20%)

### Caché Inteligente
- ✅ `@lru_cache` en `get_company_profile` (maxsize=128)
- ✅ Evita llamadas API repetidas
- ✅ Reduce uso de API y mejora rendimiento

### Cálculo de Múltiplos Reales
- ✅ Calcula múltiplos **reales** de hasta 10 peers del sector
- ✅ Promedia P/E, P/B, P/S, EV/EBITDA de peers
- ✅ Validación de múltiplos razonables
- ✅ Fallback inteligente si no hay suficientes peers

### Cálculo EV Real
- ✅ **EV = Market Cap + Debt - Cash** (no simplificado)
- ✅ Usado en cálculo EV/EBITDA para mayor precisión
- ✅ Convierte EV a Market Cap: `Market Cap = EV - Debt + Cash`

### Paralelización
- ✅ Procesamiento paralelo con `asyncio.gather`
- ✅ Analiza múltiples empresas simultáneamente
- ✅ Manejo robusto de excepciones por empresa

### Rate Limiting Adaptativo
- ✅ Ajusta intervalo basado en respuestas 429
- ✅ Reduce gradualmente si no hay errores
- ✅ Previene bans de API

## 📁 Estructura del Proyecto

```
fundamental-analysis/
├── src/
│   └── fundamental_analysis/
│       ├── finnhub_client.py      # Cliente API con rate limiting adaptativo
│       ├── data_extractor.py      # Extracción y validación de datos
│       ├── dcf_calculator.py      # Cálculo DCF con WACC real
│       ├── comparables_calculator.py  # Cálculo comparables con EV real
│       ├── valuation_engine.py    # Motor principal de valoración
│       ├── buy_decision.py         # Lógica de decisión de compra
│       ├── nats_publisher.py      # Publicación a NATS
│       ├── logs.py                 # Configuración de logging
│       └── main.py                 # Motor principal con paralelización
├── training/
│   ├── train_model.py             # Entrenamiento del modelo
│   ├── monitor_training.py         # Monitor de proceso
│   └── show_results.py            # Visualización de resultados
└── README.md                       # Este archivo
```

## 🔧 Configuración

### Requisitos
- Python 3.8+
- API Key de Finnhub (configurar en `settings.ini`)
- Opcional: NATS server para publicación

### Instalación
```bash
pip install -r requirements.txt
```

### Configuración API
Editar `settings.ini`:
```ini
[finnhub]
api_key = tu_api_key_aqui
```

## 📊 Ejemplo de Uso

```python
from src.fundamental_analysis.main import FundamentalAnalysisEngine

# Crear motor
engine = FundamentalAnalysisEngine()

# Analizar empresas
symbols = ["AAPL", "MSFT", "GOOGL"]
results = await engine.analyze_companies_async(symbols)

# Resultados incluyen:
# - symbol: Símbolo de la acción
# - buy: True/False (decisión de compra)
# - intrinsic_value: Valor intrínseco calculado
# - current_price: Precio actual
# - valuation_percentage: % de infravaloración
# - dcf_base, dcf_pessimistic, dcf_optimistic: Valores DCF
# - comparables_value: Valor por comparables
```

## 🎯 Metodología Alpha Spread

El sistema replica la metodología de Alpha Spread:

1. **DCF**: Método absoluto basado en flujos de caja proyectados
2. **Comparables**: Método relativo comparando con peers del sector
3. **Blended Value**: Promedio simple 50/50 de ambos métodos
4. **Decision**: Surprise EPS positivo + infravaloración > 25%

## 📈 Mejoras Implementadas

### Críticas
- ✅ Validación de inputs críticos
- ✅ Caché para datos repetidos
- ✅ `get_sector_averages` con peers reales
- ✅ Logging mejorado

### Prioridad Media
- ✅ Paralelización en `main.py` con `asyncio.gather`
- ✅ Cálculo EV real en comparables
- ✅ Documentación del flujo principal

## 🔍 Logging

El sistema genera logs detallados en:
- `var/logs/fundamental_analysis.log`: Log completo
- `var/logs/fundamental_analysis_errors.log`: Solo errores
- Rotación automática con compresión ZIP

## 📝 Notas

- Todos los valores financieros están en **millones** excepto precios y ratios
- El sistema usa datos **reales** de la empresa (beta, cost_of_debt, debt_to_equity)
- Los múltiplos del sector se calculan de **peers reales**, no valores fijos
- El cálculo EV usa **EV real** = Market Cap + Debt - Cash

## 🤝 Contribuciones

Las mejoras futuras pueden incluir:
- Train/test split para validación
- Optuna para optimización de hiperparámetros
- Modelos ML como baseline
- Interpretabilidad (LIME, SHAP)
