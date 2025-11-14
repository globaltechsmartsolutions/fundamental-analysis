# Análisis de Parámetros del Modelo DCF

## Cómo Funcionan los Parámetros

### 1. `growth_adjustment_factor`

**Efecto en el modelo:**
```python
adjusted_fcf_growth = base_fcf_growth * growth_adjustment_factor
```

**Relación con el valor DCF:**
- `growth_adjustment_factor > 1.0` → Aumenta crecimiento FCF → **Aumenta DCF** → Aumenta valor
- `growth_adjustment_factor < 1.0` → Reduce crecimiento FCF → **Reduce DCF** → Reduce valor
- `growth_adjustment_factor = 1.0` → Sin ajuste (usa crecimiento histórico)

**Rango típico:** 0.3 - 2.5

### 2. `wacc_adjustment_factor`

**Efecto en el modelo:**
```python
wacc_adjusted = wacc_base * wacc_adjustment_factor
```

**Relación con el valor DCF:**
- `wacc_adjustment_factor > 1.0` → Aumenta WACC → **Descuenta más** (reduce valor presente) → **Reduce DCF** → Reduce valor
- `wacc_adjustment_factor < 1.0` → Reduce WACC → **Descuenta menos** (aumenta valor presente) → **Aumenta DCF** → Aumenta valor
- `wacc_adjustment_factor = 1.0` → Sin ajuste (usa WACC calculado)

**Rango típico:** 0.4 - 1.8

## Interacción entre Parámetros

Los parámetros **NO son independientes**:

1. **Efecto combinado:**
   - `growth ↑` + `wacc ↓` → **Máximo aumento** de DCF
   - `growth ↓` + `wacc ↑` → **Máximo decremento** de DCF
   - `growth ↑` + `wacc ↑` → Efectos opuestos (depende de magnitudes)
   - `growth ↓` + `wacc ↓` → Efectos opuestos (depende de magnitudes)

2. **Espacio de búsqueda:**
   - El espacio de parámetros puede tener **múltiples mínimos locales**
   - La relación no es lineal - hay interacciones complejas
   - El óptimo puede estar en regiones no intuitivas

## Por Qué el Error Puede Aumentar

### Escenario 1: Mínimo Local
- El algoritmo encuentra un mínimo local (no global)
- Los parámetros están cerca de un mínimo pero no del óptimo real
- **Solución:** Explorar más el espacio, usar diferentes estrategias

### Escenario 2: Parámetros Muy Alejados
- Los parámetros están en el lado opuesto del óptimo
- Ejemplo: Si el óptimo es `growth=0.8, wacc=1.2`, pero encuentra `growth=2.0, wacc=0.5`
- **Solución:** Usar mejores parámetros como punto de partida, explorar alrededor

### Escenario 3: Estancamiento desde Iteración 1
- El algoritmo empieza desde un punto muy malo
- La población inicial no tiene diversidad suficiente
- **Solución:** Usar población inicial centrada en mejores parámetros encontrados

## Estrategias de Mejora

### ✅ Estrategia 1: Usar Mejores Parámetros como Punto de Partida
```python
# Si encontramos growth=1.2, wacc=0.9 con error 45%
# Usar estos como centro de población inicial
init_population = crear_poblacion_centrada_en(growth=1.2, wacc=0.9)
```

### ✅ Estrategia 2: Exploración Inteligente cuando Empeora
```python
# Si error aumenta de 45% a 60%
# NO invertir completamente (puede estar en el lado opuesto)
# En su lugar: explorar alrededor del mejor punto con diferentes estrategias
if error_aumento:
    # Explorar alrededor del mejor punto con diferentes mutaciones
    explorar_alrededor_de(mejores_parametros, radio=0.2)
```

### ✅ Estrategia 3: No Guardar Modelos que Empeoren
```python
# Solo guardar si mejora o mantiene el mejor error
if nuevo_error < mejor_error:
    guardar_modelo()
else:
    descartar_y_continuar()
```

### ✅ Estrategia 4: Búsqueda Adaptativa
```python
# Si está estancado desde iteración 1:
# - Cambiar estrategia (best1bin → rand1bin)
# - Aumentar mutación
# - Usar población inicial más diversa
# - Explorar diferentes regiones del espacio
```

## Recomendaciones Implementadas

1. ✅ **Población inicial centrada:** Usar mejores parámetros como centro
2. ✅ **Exploración adaptativa:** Si empeora, explorar alrededor del mejor punto
3. ✅ **No guardar modelos peores:** Solo mantener el mejor resultado
4. ✅ **Rotación de estrategias:** Cambiar estrategia cuando está estancado
5. ✅ **Iteraciones adaptativas:** Aumentar iteraciones cuando no mejora

## Nota sobre Inversión de Parámetros

**NO es recomendable invertir completamente** porque:
- El espacio puede tener múltiples mínimos
- La relación no es simétrica
- Puede estar en el lado opuesto pero no en el opuesto exacto

**Mejor enfoque:**
- Explorar alrededor del mejor punto encontrado
- Usar diferentes estrategias de optimización
- Aumentar diversidad de población cuando está estancado

