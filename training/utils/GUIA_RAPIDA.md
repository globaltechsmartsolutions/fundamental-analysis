# Guía Rápida - Sistema de Entrenamiento

## 🚀 Inicio Rápido

### 1. Ejecutar Entrenamiento

```bash
cd fundamental-analysis\training
train_model.bat
```

O con Python:
```bash
python train_model.py --auto
```

### 2. Analizar Resultados

```bash
python analisis_resultados.py
```

### 3. Verificar Errores

```bash
python verificar_resultados.py
```

---

## ⚙️ Configuración Rápida

### Cambiar Dataset

Editar `train_model.py` líneas 1309-1310:

```python
USE_TECH_CLEAN = False  # 3 empresas (rápido)
USE_TECH_ONLY = True    # 14 empresas (recomendado)
```

### Ajustar Iteraciones

Editar `train_model.py` líneas 833-842:

```python
maxiter = 40   # Número de iteraciones
popsize = 8    # Tamaño de población
```

---

## 📊 Interpretación Rápida

### Errores

- **< 10%**: ✅ Excelente
- **10-20%**: ✅ Bueno
- **20-30%**: ⚠️ Moderado
- **> 30%**: ❌ Alto (revisar)

### Archivos Importantes

- `trained_params.json`: Parámetros optimizados
- `training_results_iter_*.json`: Resultados detallados
- `training_checkpoint.json`: Progreso durante entrenamiento

---

## 🔧 Troubleshooting Rápido

### Entrenamiento se detiene
- ✅ Timeouts implementados (esperar máximo 5 min)
- Verificar logs en `var/logs/`

### Errores muy altos
- Ejecutar más iteraciones (mínimo 20)
- Excluir empresas problemáticas

### FCF = $0
- Verificar logs `[DEBUG_FCF_MSFT]`
- Revisar `data_extractor.py`

---

## 📚 Documentación Completa

Ver `README_ENTRENAMIENTO.md` para documentación detallada.

---

**Versión**: 1.0 | **Última actualización**: Noviembre 2025

