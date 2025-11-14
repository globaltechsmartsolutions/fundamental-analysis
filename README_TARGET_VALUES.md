# Configuración de Valores Objetivo

El módulo `target_value_fetcher.py` carga valores objetivo desde archivos JSON.

## Uso Básico

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

**Opción B: Especificar en código**
```python
from src.target_value_fetcher import load_target_values_from_json
from pathlib import Path

values = load_target_values_from_json(Path("mi_archivo.json"))
```

### Formato del JSON:
```json
{
  "comment": "Valores objetivo",
  "target_values": {
    "AAPL": 178.20,
    "MSFT": 413.12,
    "GOOGL": 179.13
  }
}
```

## Ejemplos de Uso

### Ejemplo 1: Usar JSON específico
```powershell
$env:TARGET_VALUES_JSON = "target_values_2024.json"
python training/train_model.py
```

### Ejemplo 2: Cargar valores programáticamente
```python
from src.target_value_fetcher import load_target_values_from_json

values = load_target_values_from_json()
print(f"Cargados {len(values)} valores")
```

## Archivos JSON Comunes

- `target_values_example.json` - Valores por defecto
- Puedes crear tus propios archivos JSON con cualquier nombre

## Funciones Disponibles

- `load_target_values_from_json(json_path=None)` - Carga valores desde JSON
- `fetch_target_from_web(symbol)` - Función de compatibilidad (carga desde JSON)
- `fetch_multiple_targets(symbols)` - Función de compatibilidad (carga desde JSON)
- `save_target_values_to_json(target_values, json_path=None)` - Guarda valores en JSON
