# Análisis de Datos para Caché

## Datos que se obtienen de la API

### 1. **Earnings/Surprise EPS** ✅ YA EN CACHÉ
- **Frecuencia de cambio**: Trimestral (cuando se reportan earnings)
- **Caché actual**: 7 días
- **Impacto**: Alto (se usa para filtro inicial)
- **Estado**: ✅ Implementado

### 2. **Company Profile** (`get_company_profile`)
- **Frecuencia de cambio**: Muy baja (solo cambios corporativos)
- **Datos**: Nombre, sector, industria, descripción, website, logo
- **Caché recomendado**: 90 días
- **Impacto**: Medio (se usa para sector/industria)
- **Ahorro**: 1 llamada API por empresa

### 3. **Peers** (`get_peers`)
- **Frecuencia de cambio**: Baja (cambios en industria)
- **Datos**: Lista de símbolos de empresas similares
- **Caché recomendado**: 30 días
- **Impacto**: Alto (se usa para calcular promedios del sector)
- **Ahorro**: 1 llamada API por empresa + evita procesar peers repetidos

### 4. **Financial Statements** (`get_financials`)
- **Income Statement** (anual): Cambia 1 vez al año
- **Balance Sheet** (anual): Cambia 1 vez al año
- **Cash Flow** (anual): Cambia 1 vez al año
- **Caché recomendado**: 90 días (hasta nuevos reportes anuales)
- **Impacto**: Muy alto (5 llamadas API por empresa + 5 por cada peer)
- **Ahorro**: 5 llamadas API por empresa + 5 por cada peer procesado

### 5. **Financial Metrics** (`get_financial_metrics`)
- **Frecuencia de cambio**: Baja (cuando cambian estados financieros)
- **Datos**: Ratios, métricas calculadas
- **Caché recomendado**: 30 días
- **Impacto**: Medio (1 llamada API por empresa)
- **Ahorro**: 1 llamada API por empresa

### 6. **Current Price** (`get_current_price`)
- **Frecuencia de cambio**: Constante (cada segundo)
- **Caché recomendado**: NO cachear (o máximo 5 minutos)
- **Impacto**: Bajo (1 llamada rápida)
- **Estado**: ❌ No cachear

## Análisis de Impacto

### Por empresa principal:
- **Sin caché**: ~8 llamadas API
  - 1 earnings
  - 1 profile
  - 1 peers
  - 5 financial statements (income, balance, cash flow, metrics, profile)
  - 1 price (no cachear)

### Por peer (5 peers):
- **Sin caché**: ~6 llamadas API por peer = 30 llamadas totales
  - 1 price (no cachear)
  - 5 financial statements

### Total sin caché:
- **Empresa principal**: 8 llamadas
- **5 Peers**: 30 llamadas
- **Total**: 38 llamadas API por empresa analizada

### Con caché optimizado:
- **Empresa principal**: 2-3 llamadas (solo price + validar caché)
- **5 Peers**: 5 llamadas (solo prices, datos financieros en caché)
- **Total**: 7-8 llamadas API por empresa analizada

### Ahorro estimado:
- **~80% menos llamadas API** cuando el caché está poblado
- **Tiempo de procesamiento**: De ~2-3 minutos a ~30-60 segundos por empresa

## Estrategia de Caché Propuesta

### Estructura de archivos:
```
var/cache/
├── earnings_cache.json          (ya existe, 7 días)
├── profile_cache.json           (nuevo, 90 días)
├── peers_cache.json             (nuevo, 30 días)
├── financials_cache.json        (nuevo, 90 días)
└── metrics_cache.json           (nuevo, 30 días)
```

### Validación de caché:
- Verificar fecha de caché antes de usar
- Si está expirado, obtener de API y actualizar caché
- Si no existe, obtener de API y guardar en caché

### Invalidez automática:
- Si hay error 404 o datos vacíos, invalidar caché
- Si hay cambios significativos (ej: split de acciones), invalidar caché manualmente

