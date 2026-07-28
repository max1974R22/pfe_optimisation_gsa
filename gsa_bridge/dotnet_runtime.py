"""
Chargement du runtime .NET pour GsaAPI.dll (pythonnet).

Deux pieges, tous deux constates pendant le build :
  - GsaAPI.dll cible .NET Framework 4.8 : il faut forcer `load("netfx")`
    AVANT le premier `import clr`, sinon pythonnet peut demarrer CoreCLR et
    le moteur natif de GSA plante en AccessViolation au premier Analyse ;
  - les dependances natives du moteur doivent etre resolubles : le dossier
    d'installation de GSA est ajoute au chemin de recherche des DLL.

`ensure()` est idempotent et doit etre appele avant tout usage de GsaAPI.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

GSA_DIR = Path(r"C:\Program Files\Oasys\GSA 10.2")

_loaded = False


def ensure() -> None:
    global _loaded
    if _loaded:
        return
    if not GSA_DIR.exists():
        raise RuntimeError(f"Installation GSA introuvable : {GSA_DIR}")

    from pythonnet import load

    try:
        load("netfx")
    except RuntimeError:
        # runtime deja charge (autre module) : on continue, clr tranchera
        pass

    os.add_dll_directory(str(GSA_DIR))
    os.environ["PATH"] = str(GSA_DIR) + os.pathsep + os.environ.get("PATH", "")
    sys.path.append(str(GSA_DIR))

    import clr

    clr.AddReference("GsaAPI")
    _loaded = True
