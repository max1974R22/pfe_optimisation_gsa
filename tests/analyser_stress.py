# -*- coding: utf-8 -*-
"""Max et min de chaque colonne de contrainte, toutes permutations confondues,
depuis tests/resultats/test_canopee_stress.csv (sortie de test_canopee.py).

Usage :
    venv\\Scripts\\python.exe tests\\analyser_stress.py
"""
import csv
import math
from pathlib import Path

CSV_ENTREE = Path(__file__).resolve().parent / "resultats" / "test_canopee_stress.csv"
COLONNES = ["A", "Sy", "Sz", "By_pz", "By_nz", "Bz_py", "Bz_ny", "C1", "C2"]

with CSV_ENTREE.open(encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

for col in COLONNES:
    vals = [(float(r[col]), r["permutation"]) for r in rows
            if not math.isnan(float(r[col]))]
    if not vals:
        print(f"{col}: aucune valeur")
        continue
    vmax, pmax = max(vals)
    vmin, pmin = min(vals)
    print(f"{col}: max = {vmax:.1f} (perm {pmax})  min = {vmin:.1f} (perm {pmin})")
