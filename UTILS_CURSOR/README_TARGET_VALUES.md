# Configuración de Valores Objetivo

El módulo `target_value_fetcher.py` es completamente independiente y permite trabajar con valores objetivo de dos formas:

## 1. Usar JSON Manual (Por Defecto)

Por defecto, el módulo carga valores desde `target_values_example.json`.

### Cambiar el archivo JSON usado:

**Opción A: Variable de entorno**
```powershell
# Windows PowerShell
$env:TARGET_VALUES_JSON = "mi_archivo.json"
```

```bash
# Linux/Mac
export TARGET_VALUES_JSON="mi_archivo.json"
```

**Opción B: Editar el código**
Edita `src/target_value_fetcher.py` y cambia:
```python
DEFAULT_JSON_FILE = "mi_archivo.json"  # En lugar de 'target_values_example.json'
```

### Formato del JSON:
```json
{
  "comment": "Valores objetivo de Alpha Spread",
  "target_values": {
    "AAPL": 178.20,
    "MSFT": 413.12,
    "GOOGL": 179.13
  }
}
```

## 2. Usar Scraping (Valores Actualizados)

Para obtener valores desde Alpha Spread mediante scraping:

```powershell
# Windows PowerShell
$env:USE_SCRAPING_ONLY = "true"
```

```bash
# Linux/Mac
export USE_SCRAPING_ONLY=true
```

### Guardar valores scraped en JSON:

Si quieres guardar los valores obtenidos del scraping en un JSON:

```powershell
# Windows PowerShell
$env:USE_SCRAPING_ONLY = "true"
$env:SAVE_SCRAPED_TO_JSON = "true"
```

Esto guardará los valores en `target_values_scraped.json` (o el archivo especificado en `TARGET_VALUES_JSON`).

## Ejemplos de Uso

### Ejemplo 1: Solo Scraping y Guardado (SIN entrenar)
**Usa el script independiente `scrape_and_save.py`:**

```powershell
# Obtener valores desde scraping y guardarlos en JSON (NO entrena)
python scrape_and_save.py AAPL MSFT GOOGL META

# O usar lista por defecto (todos los símbolos)
python scrape_and_save.py
```

Esto:
- ✅ Obtiene valores desde Alpha Spread (scraping)
- ✅ Los guarda en `target_values_scraped.json`
- ❌ NO entrena el modelo

### Ejemplo 2: Usar JSON manual específico para entrenar
```powershell
$env:TARGET_VALUES_JSON = "target_values_2024.json"
$env:USE_SCRAPING_ONLY = "false"
python training/train_model.py
```

### Ejemplo 3: Usar JSON guardado desde scraping para entrenar
```powershell
# Primero obtener valores (si no los tienes)
python scrape_and_save.py AAPL MSFT GOOGL

# Luego entrenar usando ese JSON
$env:TARGET_VALUES_JSON = "target_values_scraped.json"
$env:USE_SCRAPING_ONLY = "false"
python training/train_model.py
```

## Archivos JSON Comunes

- `target_values_example.json` - Valores por defecto (manual)
- `target_values_scraped.json` - Valores obtenidos desde scraping (auto-generado)
- Puedes crear tus propios archivos JSON con cualquier nombre

## Ventajas

1. **Flexibilidad**: Puedes tener múltiples archivos JSON y cambiar entre ellos fácilmente
2. **Control**: Puedes editar manualmente los valores en JSON
3. **Actualización**: Puedes obtener valores actualizados desde scraping cuando quieras
4. **Persistencia**: Los valores scraped se pueden guardar para reutilizar

