#!/usr/bin/env python
"""
Script de ejecución rápida para análisis fundamental
"""
import sys
from pathlib import Path

# Agregar raíz del proyecto al path para imports absolutos
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.core.main import main

if __name__ == "__main__":
    main()

