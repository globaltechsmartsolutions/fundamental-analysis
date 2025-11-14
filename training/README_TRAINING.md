# Guía de Entrenamiento de Modelos

Este directorio contiene scripts para entrenar modelos de valoración por empresa.

## Opciones de Entrenamiento

### 1. Entrenamiento Masivo (Todas las Empresas)

**Script:** `train_model.py`

Entrena todas las empresas en secuencia usando el sistema de bucle automático.

```bash
python train_model.py
```

**Ventajas:**
- ✅ Entrena todas las empresas automáticamente
- ✅ Comparte caché entre empresas (más eficiente)
- ✅ Un solo proceso, fácil de monitorear
- ✅ Sistema de bucle automático con detección de convergencia

**Desventajas:**
- ❌ Si una empresa falla, puede afectar a otras
- ❌ No se puede paralelizar fácilmente
- ❌ Más lento si solo necesitas entrenar una empresa

### 2. Entrenamiento Individual (Una Empresa)

**Script:** `train_single.py`

Entrena una sola empresa de forma aislada.

```bash
python train_single.py AAPL
python train_single.py AAPL 10.0 500  # Con parámetros personalizados
```

**Parámetros:**
- `SYMBOL`: Símbolo de la empresa (requerido)
- `target_error`: Error objetivo en % (default: 10.0)
- `max_iterations`: Máximo de iteraciones (default: 500)

**Ventajas:**
- ✅ Aislamiento: si falla, no afecta a otras
- ✅ Rápido para entrenar una empresa específica
- ✅ Fácil de depurar problemas específicos
- ✅ Puede ejecutarse en paralelo manualmente

**Desventajas:**
- ❌ Tiene que cargar caché cada vez (más lento si entrenas muchas)

### 3. Entrenamiento Paralelo (Múltiples Empresas)

**Script:** `train_parallel.bat` (Windows)

Ejecuta múltiples empresas en paralelo, cada una en su propia ventana.

```bash
train_parallel.bat AAPL MSFT GOOGL META
```

**Ventajas:**
- ✅ Paralelización real: múltiples empresas a la vez
- ✅ Aislamiento: cada empresa en su propio proceso
- ✅ Más rápido para entrenar muchas empresas
- ✅ Puedes ver el progreso de cada una individualmente

**Desventajas:**
- ❌ Cada proceso carga su propio caché (más uso de memoria)
- ❌ Más difícil de monitorear todas a la vez

## ¿Cuándo Usar Cada Opción?

### Usa `train_model.py` cuando:
- Quieres entrenar todas las empresas automáticamente
- Es la primera vez que entrenas
- Quieres un proceso centralizado y fácil de monitorear
- No necesitas paralelización

### Usa `train_single.py` cuando:
- Solo necesitas entrenar una empresa específica
- Estás depurando problemas con una empresa
- Quieres probar diferentes parámetros en una empresa
- Quieres ejecutar empresas en paralelo manualmente

### Usa `train_parallel.bat` cuando:
- Necesitas entrenar muchas empresas rápidamente
- Tienes recursos suficientes (CPU/memoria)
- Quieres ver el progreso de cada empresa individualmente
- No te importa el uso adicional de memoria

## Ejemplos de Uso

### Entrenar solo AAPL con objetivo de 5%:
```bash
python train_single.py AAPL 5.0
```

### Entrenar AAPL, MSFT y GOOGL en paralelo:
```bash
train_parallel.bat AAPL MSFT GOOGL
```

### Entrenar todas las empresas (modo masivo):
```bash
python train_model.py
```

## Recomendación

**Para uso normal:** Usa `train_model.py` - es más simple y eficiente.

**Para desarrollo/depuración:** Usa `train_single.py` - más fácil de trabajar con empresas individuales.

**Para velocidad máxima:** Usa `train_parallel.bat` - pero solo si tienes recursos suficientes y necesitas entrenar muchas empresas rápidamente.

