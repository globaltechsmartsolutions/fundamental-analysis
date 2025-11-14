# Análisis: Parámetros Razonables para Replicar Alpha Spread

## 🎯 Objetivo

Identificar qué parámetros entrenar y cómo validar que sean **financieramente razonables**, no solo valores que ajusten para obtener el resultado esperado.

---

## 📊 Metodología Alpha Spread

Alpha Spread combina dos métodos de valoración:

1. **DCF (Discounted Cash Flow)** - Valoración absoluta basada en flujos de caja futuros
2. **Comparables** - Valoración relativa basada en múltiplos del sector

**Valor Final = (DCF × 50%) + (Comparables × 50%)**

---

## 🔍 Parámetros que DEBEN ser FIJOS (No entrenar)

Estos parámetros tienen valores estándar en la industria y Alpha Spread los usa consistentemente:

### 1. Parámetros Macroeconómicos Globales
- **Risk-Free Rate (Rf)**: 4.5% (bonos del Tesoro USA a 10 años, 2024)
- **Equity Risk Premium (ERP)**: 4.12% (valor que Alpha Spread usa públicamente)
- **Tax Rate**: 21% (tasa corporativa estándar USA)

**Razón**: Son valores de mercado reales, no deben ajustarse para ajustar resultados.

### 2. Parámetros de Proyección
- **Projection Years**: 10 años (estándar en DCF)
- **Terminal Growth Rate**: Por sector (Tech=2.5%, Utilities=1.5%, etc.)

**Razón**: Valores conservadores estándar. Alpha Spread usa estos valores consistentemente.

### 3. Pesos del Blend
- **DCF Weight**: 50%
- **Comparables Weight**: 50%

**Razón**: Alpha Spread usa promedio simple 50/50. Cambiar esto sería cambiar la metodología fundamental.

---

## ✅ Parámetros que PUEDEN entrenarse (Con validación)

### 1. Growth Adjustment Factor

**Qué es**: Factor que multiplica el crecimiento FCF histórico proyectado.

**Rango actual**: [0.5, 1.5]

**Validación razonable**:
- **< 0.7**: Muy conservador, solo para empresas con crecimiento extremadamente inestable
- **0.7 - 0.9**: Conservador, para empresas con crecimiento alto pero volátil (>15%)
- **0.9 - 1.1**: Normal, para empresas con crecimiento estable (3-15%)
- **1.1 - 1.3**: Optimista, solo si hay fundamentos sólidos (márgenes altos, FCF estable)
- **> 1.3**: Irrazonable, crecimiento insostenible

**Validación por empresa**:
```python
# Debe correlacionar con:
- Estabilidad del FCF histórico (CV < 0.3 → factor más alto)
- Márgenes EBITDA altos (>20%) → factor más alto
- Crecimiento histórico razonable (5-15%) → factor ~1.0
- Crecimiento extremo (>20%) → factor más bajo (0.7-0.9)
```

### 2. WACC Adjustment Factor

**Qué es**: Factor que multiplica el WACC calculado.

**Rango actual**: [0.7, 1.3]

**Validación razonable**:
- **< 0.85**: Muy optimista, solo para empresas con riesgo muy bajo (beta < 0.5, deuda mínima)
- **0.85 - 0.95**: Optimista, para empresas con bajo riesgo (beta < 1.0, deuda baja)
- **0.95 - 1.05**: Normal, para empresas con riesgo estándar (beta ~1.0, deuda moderada)
- **1.05 - 1.15**: Conservador, para empresas con alto riesgo (beta > 1.5, deuda alta)
- **> 1.15**: Muy conservador, solo para empresas muy volátiles (beta > 2.0)

**Validación por empresa**:
```python
# Debe correlacionar con:
- Beta bajo (< 0.8) → factor más bajo (0.9-1.0)
- Beta alto (> 1.5) → factor más alto (1.05-1.15)
- Deuda alta (D/E > 0.5) → factor más alto
- Deuda baja (D/E < 0.2) → factor más bajo
```

---

## 🚨 Validaciones CRÍTICAS que DEBEN implementarse

### 1. Validación de Growth Adjustment Factor

```python
def validate_growth_adjustment(growth_adj: float, company_data: Dict) -> bool:
    """
    Valida que growth_adjustment_factor sea razonable para esta empresa
    
    Criterios:
    1. Debe correlacionar con estabilidad del FCF
    2. Debe correlacionar con crecimiento histórico
    3. No puede ser extremo sin justificación
    """
    fcf_growth = company_data.get('fcf_growth', 0)
    fcf_stability = company_data.get('fcf_stability_score', 0.5)
    ebitda_margin = company_data.get('ebitda_margin', 0)
    
    # Criterio 1: Crecimiento extremo requiere factor más bajo
    if fcf_growth > 25.0 and growth_adj > 1.0:
        return False  # Crecimiento insostenible no puede tener factor > 1.0
    
    # Criterio 2: Estabilidad baja requiere factor más bajo
    if fcf_stability < 0.3 and growth_adj > 1.0:
        return False  # FCF inestable no puede tener factor optimista
    
    # Criterio 3: Márgenes bajos requieren factor más bajo
    if ebitda_margin < 10.0 and growth_adj > 1.1:
        return False  # Márgenes bajos no justifican factor optimista
    
    # Criterio 4: Factor muy bajo requiere justificación
    if growth_adj < 0.6:
        # Solo válido si crecimiento negativo o muy inestable
        if fcf_growth >= 0 and fcf_stability > 0.4:
            return False
    
    return True
```

### 2. Validación de WACC Adjustment Factor

```python
def validate_wacc_adjustment(wacc_adj: float, company_data: Dict) -> bool:
    """
    Valida que wacc_adjustment_factor sea razonable para esta empresa
    
    Criterios:
    1. Debe correlacionar con beta
    2. Debe correlacionar con estructura de capital
    3. No puede ser extremo sin justificación
    """
    beta = company_data.get('beta', 1.0)
    debt_to_equity = company_data.get('debt_to_equity', 0.3)
    debt_ratio = company_data.get('debt_ratio', 0.0)
    
    # Criterio 1: Beta bajo requiere factor más bajo
    if beta < 0.7 and wacc_adj > 1.05:
        return False  # Beta bajo no justifica WACC alto
    
    # Criterio 2: Beta alto requiere factor más alto
    if beta > 1.8 and wacc_adj < 0.95:
        return False  # Beta alto requiere WACC más alto
    
    # Criterio 3: Deuda alta requiere factor más alto
    if debt_ratio > 0.4 and wacc_adj < 1.0:
        return False  # Deuda alta aumenta riesgo
    
    # Criterio 4: Factor muy bajo requiere beta muy bajo
    if wacc_adj < 0.85:
        if beta > 0.6 or debt_ratio > 0.2:
            return False
    
    # Criterio 5: Factor muy alto requiere beta muy alto o deuda muy alta
    if wacc_adj > 1.2:
        if beta < 1.5 and debt_ratio < 0.3:
            return False
    
    return True
```

---

## 📈 Estrategia de Entrenamiento Mejorada

### Fase 1: Entrenamiento Global (Parámetros Base)

1. **Entrenar growth_adjustment_factor global** con rango [0.8, 1.2]
   - Más conservador que el actual
   - Aplicar a todas las empresas inicialmente

2. **Entrenar wacc_adjustment_factor global** con rango [0.9, 1.1]
   - Más conservador que el actual
   - Aplicar a todas las empresas inicialmente

3. **Validar que los parámetros globales sean razonables**:
   - Deben estar cerca de 1.0 (ajuste mínimo)
   - Si están muy lejos de 1.0, revisar datos de entrada

### Fase 2: Entrenamiento Individual (Solo si es necesario)

**Solo entrenar individualmente si**:
- Error > 30% después del entrenamiento global
- Los parámetros globales no funcionan para esta empresa específica
- Hay características únicas que justifican ajuste individual

**Validaciones adicionales para entrenamiento individual**:
1. Los parámetros individuales deben estar **cerca de los globales** (±0.2)
2. Si difieren mucho, debe haber justificación financiera clara
3. Rechazar parámetros que sean "disparatados" aunque reduzcan el error

---

## 🎯 Criterios de Aceptación de Parámetros Entrenados

### Criterio 1: Razonabilidad Financiera
- ✅ Growth adjustment debe correlacionar con estabilidad y crecimiento histórico
- ✅ WACC adjustment debe correlacionar con beta y estructura de capital
- ❌ Rechazar parámetros que no tengan sentido financiero

### Criterio 2: Consistencia
- ✅ Parámetros similares para empresas similares (mismo sector, mismo perfil de riesgo)
- ❌ Rechazar parámetros que sean muy diferentes sin justificación

### Criterio 3: Estabilidad
- ✅ Parámetros deben ser estables entre entrenamientos (no cambiar drásticamente)
- ❌ Rechazar parámetros que cambien mucho entre ejecuciones

### Criterio 4: Generalización
- ✅ Parámetros globales deben funcionar razonablemente bien para la mayoría
- ❌ Rechazar parámetros que solo funcionen para empresas específicas (overfitting)

---

## 🔧 Implementación Recomendada

### 1. Agregar Validaciones Financieras

```python
def validate_trained_params(params: Dict, company_data: Dict) -> Tuple[bool, List[str]]:
    """
    Valida que los parámetros entrenados sean financieramente razonables
    
    Returns:
        (is_valid, reasons)
    """
    reasons = []
    
    # Validar growth_adjustment_factor
    if not validate_growth_adjustment(params['growth_adjustment_factor'], company_data):
        reasons.append("growth_adjustment_factor no es razonable para esta empresa")
    
    # Validar wacc_adjustment_factor
    if not validate_wacc_adjustment(params['wacc_adjustment_factor'], company_data):
        reasons.append("wacc_adjustment_factor no es razonable para esta empresa")
    
    # Validar consistencia con empresas similares
    # TODO: Comparar con parámetros de empresas similares
    
    is_valid = len(reasons) == 0
    return is_valid, reasons
```

### 2. Entrenamiento en Dos Fases

**Fase 1: Global**
- Entrenar parámetros globales con validaciones estrictas
- Aplicar a todas las empresas
- Si error promedio < 15%, usar estos parámetros

**Fase 2: Individual (Solo si necesario)**
- Solo para empresas con error > 30% después de Fase 1
- Validar que parámetros individuales sean razonables
- Rechazar si no pasan validaciones financieras

### 3. Penalización por Parámetros Extremos

```python
def objective_with_penalty(params, company_data):
    """
    Función objetivo que penaliza parámetros extremos
    """
    error = calculate_error(params)
    
    # Penalización por growth_adjustment extremo
    growth_penalty = 0
    if params['growth_adjustment_factor'] < 0.7 or params['growth_adjustment_factor'] > 1.3:
        growth_penalty = abs(params['growth_adjustment_factor'] - 1.0) * 10
    
    # Penalización por wacc_adjustment extremo
    wacc_penalty = 0
    if params['wacc_adjustment_factor'] < 0.85 or params['wacc_adjustment_factor'] > 1.15:
        wacc_penalty = abs(params['wacc_adjustment_factor'] - 1.0) * 10
    
    return error + growth_penalty + wacc_penalty
```

---

## 📝 Conclusión

**Parámetros a entrenar**:
1. ✅ `growth_adjustment_factor` - Con validaciones financieras estrictas
2. ✅ `wacc_adjustment_factor` - Con validaciones financieras estrictas

**Parámetros NO entrenar**:
1. ❌ Parámetros macroeconómicos (Rf, ERP, Tax Rate)
2. ❌ Terminal growth rate (ya está por sector)
3. ❌ Pesos del blend (50/50 es metodología Alpha Spread)
4. ❌ Projection years (10 años es estándar)

**Validaciones críticas**:
1. ✅ Parámetros deben correlacionar con características financieras
2. ✅ Parámetros similares para empresas similares
3. ✅ Rechazar parámetros extremos sin justificación
4. ✅ Penalizar parámetros que solo funcionen para casos específicos

