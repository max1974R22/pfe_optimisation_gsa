# -*- coding: utf-8 -*-
"""Chrono minimal sur la Canopee : table Element1dStress de l'ENVELOPPE ELU,
pour UNE SEULE barre (et non "all").

Script autonome, sans mise en forme : il ouvre le modele (sur une copie de
travail, jamais l'original), relance l'analyse, appelle Element1dStress sur la
combinaison ENVELOPPE ELU pour un seul element, parcourt toutes les
permutations et ecrit la table brute en CSV. A la fin, il affiche le temps de
chaque etape.

Usage :
    venv\\Scripts\\python.exe tests\\test_canopee.py
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
COPIE = ROOT / "gsa_bridge" / "runtime" / "test_canopee.gwb"
RESULTATS = ROOT / "tests" / "resultats"
SORTIE = RESULTATS / "test_canopee_stress.csv"
POSITIONS = 3
ELEMENT = 1   # id de la barre a extraire (au lieu de "all")

RESULTATS.mkdir(parents=True, exist_ok=True)

chrono: dict[str, float] = {}


def top(nom: str, t0: float) -> None:
    chrono[nom] = time.perf_counter() - t0
    print(f"  {nom} : {chrono[nom]:.2f} s")


# 1. connexion : runtime .NET + copie de travail + ouverture du modele
t0 = time.perf_counter()
dotnet_runtime.ensure()
from GsaAPI import Model

COPIE.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(MODELE, COPIE)
m = Model(str(COPIE))
top("1. connexion (runtime + copie + ouverture)", t0)

# combinaison ENVELOPPE ELU, trouvee par son nom
combos = m.CombinationCases()
cid = next(k for k in combos.Keys
           if "ENVELOPPE" in combos[k].Name.upper()
           and "ELU" in combos[k].Name.upper())
print(f"  combinaison C{cid} = {combos[cid].Name}")

# 2. recalcul : toutes les taches d'analyse
t0 = time.perf_counter()
for tid in m.AnalysisTasks().Keys:
    m.Analyse(tid)
top("2. recalcul (Analyse de toutes les taches)", t0)

# 3. appel .NET Element1dStress : c'est ici que GSA recombine les permutations
t0 = time.perf_counter()
data = m.CombinationCaseResults()[cid].Element1dStress(str(ELEMENT), POSITIONS, None)
top(f"3. appel Element1dStress (GSA recombine, element {ELEMENT})", t0)

# 4. parcours Python de toutes les permutations (interop .NET -> Python)
t0 = time.perf_counter()
rows = []
n_perms = 0
for eid in data.Keys:
    coll = data[eid]
    perms = [coll] if coll.Count and hasattr(coll[0], "AxialStressA") else list(coll)
    n_perms = max(n_perms, len(perms))
    for ip, perm in enumerate(perms):
        for i, v in enumerate(perm):
            rows.append((eid, ip + 1, i,
                         v.AxialStressA, v.ShearStressSy, v.ShearStressSz,
                         v.BendingStressByPositiveZ, v.BendingStressByNegativeZ,
                         v.BendingStressBzPositiveY, v.BendingStressBzNegativeY,
                         v.CombinedStressC1, v.CombinedStressC2))
top("4. parcours des permutations (interop)", t0)
print(f"  {n_perms} permutation(s) max par element, {len(rows)} lignes")

# 5. ecriture CSV brute
t0 = time.perf_counter()
with SORTIE.open("w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["element", "permutation", "position",
                "A", "Sy", "Sz", "By_pz", "By_nz", "Bz_py", "Bz_ny", "C1", "C2"])
    w.writerows(rows)
top("5. ecriture CSV", t0)

m.Close()

print(f"\n{len(rows)} lignes -> {SORTIE.name}")
print(f"TOTAL : {sum(chrono.values()):.2f} s")
for nom, duree in chrono.items():
    print(f"  {nom:45s} {duree:8.2f} s  ({duree / sum(chrono.values()):.0%})")
