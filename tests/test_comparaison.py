# -*- coding: utf-8 -*-
"""Compare : 3 appels Element1dStress SEPARES (barre 1, puis 2, puis 3) contre
UN SEUL appel groupe ("1 2 3"), sur la combinaison ENVELOPPE ELU de la
Canopee. Le modele est ouvert et analyse UNE SEULE FOIS (hors chrono) pour que
la comparaison porte uniquement sur le cout de l'appel Element1dStress
lui-meme. Les CSV sont ecrits dans tests/resultats/.

Usage :
    venv\\Scripts\\python.exe tests\\test_comparaison.py
"""
import csv
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gsa_bridge import dotnet_runtime

MODELE = ROOT / "GSA_model" / "Canopée - Modèle de Vent.gwb"
COPIE = ROOT / "gsa_bridge" / "runtime" / "test_comparaison.gwb"
DOSSIER_TEST = ROOT / "tests" / "resultats"
POSITIONS = 3
BARRES = [1, 2, 3]

DOSSIER_TEST.mkdir(parents=True, exist_ok=True)


def ecrire_csv(chemin: Path, data) -> int:
    """Ecrit une table Element1dStress (dict eid -> permutations) en CSV brut,
    renvoie le nombre de lignes ecrites."""
    rows = []
    for eid in data.Keys:
        coll = data[eid]
        perms = [coll] if coll.Count and hasattr(coll[0], "AxialStressA") else list(coll)
        for ip, perm in enumerate(perms):
            for i, v in enumerate(perm):
                rows.append((eid, ip + 1, i,
                             v.AxialStressA, v.ShearStressSy, v.ShearStressSz,
                             v.BendingStressByPositiveZ, v.BendingStressByNegativeZ,
                             v.BendingStressBzPositiveY, v.BendingStressBzNegativeY,
                             v.CombinedStressC1, v.CombinedStressC2))
    with chemin.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["element", "permutation", "position",
                    "A", "Sy", "Sz", "By_pz", "By_nz", "Bz_py", "Bz_ny", "C1", "C2"])
        w.writerows(rows)
    return len(rows)


# --- ouverture + analyse, une seule fois, hors chrono comparatif
dotnet_runtime.ensure()
from GsaAPI import Model

shutil.copyfile(MODELE, COPIE)
m = Model(str(COPIE))
combos = m.CombinationCases()
cid = next(k for k in combos.Keys
           if "ENVELOPPE" in combos[k].Name.upper() and "ELU" in combos[k].Name.upper())
print(f"combinaison C{cid} = {combos[cid].Name}")
for tid in m.AnalysisTasks().Keys:
    m.Analyse(tid)
resultat = m.CombinationCaseResults()[cid]

# --- 3 appels separes (barre 1, puis 2, puis 3)
temps_separes = []
for b in BARRES:
    t0 = time.perf_counter()
    data = resultat.Element1dStress(str(b), POSITIONS, None)
    n = ecrire_csv(DOSSIER_TEST / f"stress_barre{b}.csv", data)
    dt = time.perf_counter() - t0
    temps_separes.append(dt)
    print(f"barre {b} seule : {dt:.3f} s ({n} lignes)")

total_separe = sum(temps_separes)
print(f"total des 3 appels separes : {total_separe:.3f} s")

# --- 1 appel groupe ("1 2 3")
t0 = time.perf_counter()
data = resultat.Element1dStress(" ".join(str(b) for b in BARRES), POSITIONS, None)
n = ecrire_csv(DOSSIER_TEST / "stress_barres_1_2_3.csv", data)
temps_groupe = time.perf_counter() - t0
print(f"appel groupe '1 2 3' : {temps_groupe:.3f} s ({n} lignes)")

m.Close()

print(f"\n3 appels separes : {total_separe:.3f} s")
print(f"1 appel groupe    : {temps_groupe:.3f} s")
print(f"ecart : {total_separe - temps_groupe:+.3f} s "
      f"({(total_separe / temps_groupe - 1):+.0%} par rapport au groupe)")
