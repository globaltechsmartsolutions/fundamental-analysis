# Resumen: Cómo Entrenamos Cada Empresa

## 🎯 Estrategia de Entrenamiento

### Proceso Completo

```
1. PREPARAR DATOS
   ↓
2. IDENTIFICAR EMPRESAS CRÍTICAS (error >= 30%)
   ↓
3. ENTRENAR CRÍTICAS INDIVIDUALMENTE
   ├─ Validar parámetros financieramente
   ├─ Hasta 3 intentos con más iteraciones
   └─ Guardar modelo si error < 10%
   ↓
4. ENTRENAR RESTO GLOBALMENTE
   └─ Con pesos diferenciados por categoría
   ↓
5. ANALIZAR ERRORES EXTREMOS
```

---

## 📊 Parámetros que Entrenamos

### ✅ SÍ entrenamos (con validación financiera):

1. **`growth_adjustment_factor`** [0.3, 2.0]
   - Factor que multiplica el crecimiento FCF histórico
   - **Validación**: Debe correlacionar con:
     - Estabilidad del FCF
     - Crecimiento histórico
     - Márgenes EBITDA

2. **`wacc_adjustment_factor`** [0.5, 1.5]
   - Factor que multiplica el WACC calculado
   - **Validación**: Debe correlacionar con:
     - Beta de la empresa
     - Estructura de capital (deuda)
     - Riesgo del sector

### ❌ NO entrenamos (valores fijos):

- Risk-Free Rate (4.5%)
- Equity Risk Premium (4.12%)
- Tax Rate (21%)
- Terminal Growth Rate (por sector)
- Projection Years (10)
- Pesos del blend (50/50)

---

## 🔍 Validaciones Financieras Implementadas

### Para `growth_adjustment_factor`:

✅ **Aceptado si**:
- Crecimiento razonable (5-15%) → factor ~0.9-1.1
- Crecimiento extremo (>25%) → factor más bajo (0.7-0.9)
- FCF estable (márgenes altos) → factor puede ser más alto
- Márgenes altos (>20%) → factor puede ser más alto

❌ **Rechazado si**:
- Crecimiento extremo (>25%) pero factor > 1.0
- FCF inestable pero factor optimista (>1.0)
- Márgenes bajos (<10%) pero factor muy optimista (>1.1)
- Factor muy bajo (<0.6) sin justificación

### Para `wacc_adjustment_factor`:

✅ **Aceptado si**:
- Beta bajo (<0.8) → factor más bajo (0.9-1.0)
- Beta alto (>1.5) → factor más alto (1.05-1.15)
- Deuda alta (D/E > 0.5) → factor más alto
- Deuda baja (D/E < 0.2) → factor más bajo

❌ **Rechazado si**:
- Beta bajo pero factor alto (>1.05)
- Beta alto pero factor bajo (<0.95)
- Deuda alta pero factor bajo (<1.0)
- Factor extremo sin justificación financiera

---

## 🎓 Entrenamiento Individual por Empresa

### Cuándo se entrena individualmente:

- **Solo empresas críticas**: Error >= 30% después de evaluación inicial
- **Objetivo**: Reducir error a < 10%
- **Método**: `differential_evolution` optimizando solo 2 parámetros

### Proceso:

1. **Intento 1**: 500 iteraciones
   - Si error < 10% → ✅ Guardar modelo
   - Si parámetros inválidos → ❌ Reintentar

2. **Intento 2**: 1000 iteraciones (si falló intento 1)
   - Si error < 10% → ✅ Guardar modelo
   - Si parámetros inválidos → ❌ Reintentar

3. **Intento 3**: 1500 iteraciones (si falló intento 2)
   - Último intento
   - Si falla → ⚠️ Continuar con entrenamiento global

### Validación en cada intento:

```python
# 1. Validación de rangos básicos
if growth_adj < 0.3 or growth_adj > 2.0:
    ❌ Rechazar

# 2. Validación financiera
if fcf_growth > 25% and growth_adj > 1.0:
    ❌ Rechazar (crecimiento extremo no puede tener factor optimista)

if beta < 0.7 and wacc_adj > 1.05:
    ❌ Rechazar (beta bajo no justifica WACC alto)

# ... más validaciones financieras
```

---

## 📈 Entrenamiento Global

### Para empresas no-críticas:

- **Algoritmo**: `differential_evolution`
- **Parámetros**: `growth_adjustment_factor` y `wacc_adjustment_factor` globales
- **Pesos diferenciados**:
  - Críticas: 60% peso
  - Intermedias: 30% peso
  - Buenas: 10% peso

---

## ✅ Criterios de Aceptación

### 1. Razonabilidad Financiera
- ✅ Parámetros deben tener sentido según características de la empresa
- ❌ Rechazar parámetros "disparatados" aunque reduzcan el error

### 2. Rangos Válidos
- ✅ `growth_adjustment_factor`: [0.3, 2.0]
- ✅ `wacc_adjustment_factor`: [0.5, 1.5]

### 3. Correlación con Datos
- ✅ Debe correlacionar con beta, deuda, crecimiento, márgenes
- ❌ No puede ser extremo sin justificación

---

## 🎯 Resultado Final

Cada empresa crítica tiene su propio modelo en `models/{symbol}_model.json` con:
- Parámetros entrenados y validados financieramente
- Error < 10% (objetivo alcanzado)
- Metadatos de entrenamiento

Las empresas no-críticas usan parámetros globales entrenados.

