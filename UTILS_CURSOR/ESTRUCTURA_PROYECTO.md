# Estructura del Proyecto - Fundamental Analysis

## 📁 Organización Modular

```
fundamental-analysis/
├── src/                          # Código fuente modularizado
│   ├── core/                     # Componentes principales
│   │   ├── main.py               # FundamentalAnalysisEngine
│   │   ├── valuation_engine.py   # ValuationEngine
│   │   └── buy_decision.py       # BuyDecisionEngine
│   │
│   ├── valuation/                # Módulos de valoración
│   │   ├── dcf_calculator.py     # DCFCalculator
│   │   ├── dcf_utils.py          # compute_company_dcf
│   │   ├── comparables_calculator.py
│   │   └── company_specific_params.py
│   │
│   ├── data/                      # Extracción y gestión de datos
│   │   ├── finnhub_client.py
│   │   ├── data_extractor.py
│   │   ├── cache_manager.py
│   │   └── target_value_fetcher.py
│   │
│   ├── config/                    # Configuración
│   │   ├── settings_valoration.py
│   │   └── sector_strategies.py
│   │
│   ├── utils/                     # Utilidades
│   │   └── logs.py
│   │
│   ├── publishers/                # Publicación de resultados
│   │   └── nats_publisher.py
│   │
│   └── ui/                        # Interfaz de usuario
│       ├── main_window.py
│       └── widgets.py
│
├── training/                      # Sistema de entrenamiento
│   ├── train_model.py            # Script principal
│   ├── trained_params.json       # Parámetros entrenados
│   ├── utils/                    # Documentación de uso
│   │   ├── MODELO_ENTRENAMIENTO.md
│   │   └── GUIA_RAPIDA.md
│   └── analysis/                 # Análisis técnicos
│       └── ANALISIS_PARAMETROS_RAZONABLES.md
│
├── UTILS_CURSOR/                  # Documentación y análisis histórico
│   ├── MODEL_ANALYSIS.md
│   ├── PEERS_COST_ANALYSIS.md
│   ├── CACHE_ANALYSIS.md
│   ├── README_SCRAPING.md
│   └── README_TARGET_VALUES.md
│
├── models/                        # Modelos entrenados por empresa
│   └── {symbol}_model.json
│
├── var/                           # Datos variables
│   ├── cache/                     # Caché de datos financieros
│   └── logs/                      # Logs del sistema
│
└── README.md                      # Documentación principal
```

## 🎯 Imports

### Desde la raíz del proyecto:
```python
from src.core.main import FundamentalAnalysisEngine
from src.valuation import compute_company_dcf
from src.data import FinnhubClient
```

### Desde training/:
```python
from src.core import FundamentalAnalysisEngine
from src.valuation import CompanySpecificParams
from src.utils import setup_logging
```

## 📚 Documentación

- **README.md** - Documentación principal del proyecto
- **training/utils/** - Guías de entrenamiento
- **training/analysis/** - Análisis técnicos de parámetros
- **UTILS_CURSOR/** - Documentación histórica y análisis

