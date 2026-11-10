"""Lanceur utilisé par PyInstaller (point d'entrée de l'exécutable)."""
import sys

from tcfmaster.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
