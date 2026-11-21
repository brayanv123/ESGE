"""Punto de entrada principal de la aplicación para Streamlit Cloud y ejecución local."""

from __future__ import annotations

from pathlib import Path
import sys

# Asegurar que la carpeta 'src' esté en el path de importación de Python
ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Importar la función principal del dashboard de mapas y proyectos
from esge.dash_mapas import main

if __name__ == "__main__":
    main()

