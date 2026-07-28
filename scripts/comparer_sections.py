# -*- coding: utf-8 -*-
"""
Tableau comparatif des sections testees, a partir des CSV deja exportes par
scripts/etude_sections.py (aucun appel a GSA : pur post-traitement).

Produit result/sections/_Comparaison.csv : UNE LIGNE PAR SECTION, et pour
CHAQUE CAS de resultat trouve (A1, A2, C1, C2...), six colonnes :
    <cas>_Uz_max_m,  <cas>_Uz_x_m   : fleche max (signee) et sa position ;
    <cas>_My_max_Nm, <cas>_My_x_m   : moment max (signe) et sa position ;
    <cas>_Vz_max_N,  <cas>_Vz_x_m   : tranchant max (signe) et sa position.

« Max » = valeur de plus grande amplitude (on garde le signe). La position est
en metres depuis l'origine de l'element (longueur calculee depuis Nodes.csv) ;
si un modele avait plusieurs elements, elle s'ecrit "E<elem> @ <x> m".

Usage :
    venv\\Scripts\\python.exe scripts\\comparer_sections.py
"""
from __future__ import annotations

import csv
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "result" / "sections"
SORTIE = DATA / "_Comparaison.csv"

# (prefixe colonne, fichier source, colonne valeur)
QUANTITES = [
    ("Uz", "Beam and Spring Displacements.csv", "Uz"),
    ("My", "Beam and Spring Forces and Moments.csv", "Myy"),
    ("Vz", "Beam and Spring Forces and Moments.csv", "Fz"),
]


def lire_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def longueurs_elements(dossier: Path) -> dict[str, float]:
    """Longueur de chaque element, depuis Nodes.csv + Elements.csv."""
    noeuds = {r["node"]: (float(r["x"]), float(r["y"]), float(r["z"]))
              for r in lire_csv(dossier / "Nodes.csv")}
    longueurs = {}
    for e in lire_csv(dossier / "Elements.csv"):
        topo = e["topologie"].split()
        if len(topo) >= 2 and topo[0] in noeuds and topo[1] in noeuds:
            a, b = noeuds[topo[0]], noeuds[topo[1]]
            longueurs[e["element"]] = math.dist(a, b)
    return longueurs


def max_et_position(rows: list[dict], colonne: str,
                    longueurs: dict[str, float]) -> tuple[float | None, str]:
    """Valeur de plus grande amplitude d'une colonne et sa position sur la poutre."""
    meilleur = None
    for r in rows:
        v = float(r[colonne])
        if math.isnan(v):
            continue
        if meilleur is None or abs(v) > abs(meilleur[0]):
            meilleur = (v, r["element"], float(r["pos"]))
    if meilleur is None:
        return None, ""
    v, elem, pos = meilleur
    x = round(pos * longueurs.get(elem, float("nan")), 3)
    if len(longueurs) == 1:
        return v, x
    return v, f"E{elem} @ {x} m"


def cle_tri(nom: str):
    """IPE80 < IPE100 < ... : tri par la partie numerique, sinon alphabetique."""
    m = re.search(r"(\d+)", nom)
    return (0, int(m.group(1))) if m else (1, nom)


def main() -> None:
    dossiers = sorted(
        (d for d in DATA.iterdir()
         if d.is_dir() and (d / "Beam and Spring Forces and Moments.csv").exists()),
        key=lambda d: cle_tri(d.name))
    if not dossiers:
        sys.exit(f"Aucun dossier de section avec resultats dans {DATA}")

    lignes = []
    for dossier in dossiers:
        longueurs = longueurs_elements(dossier)
        sources = {f: lire_csv(dossier / f) for _, f, _ in QUANTITES}
        cas = sorted({r["case"] for rows in sources.values() for r in rows},
                     key=lambda c: (c[0], int(c[1:])))
        ligne: dict = {"section": dossier.name}
        for c in cas:
            for prefixe, fichier, colonne in QUANTITES:
                rows_cas = [r for r in sources[fichier] if r["case"] == c]
                v, x = max_et_position(rows_cas, colonne, longueurs)
                unite = {"Uz": "m", "My": "Nm", "Vz": "N"}[prefixe]
                ligne[f"{c}_{prefixe}_max_{unite}"] = (
                    None if v is None else round(v, 6 if prefixe == "Uz" else 1))
                ligne[f"{c}_{prefixe}_x_m"] = x
        lignes.append(ligne)

    with SORTIE.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(lignes[0].keys()))
        w.writeheader()
        w.writerows(lignes)
    print(f"{SORTIE.name} : {len(lignes)} section(s), "
          f"{(len(lignes[0]) - 1) // 6} cas -> {SORTIE}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
