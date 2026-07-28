# -*- coding: utf-8 -*-
"""
Export CSV d'un modele GSA, via gsa_bridge.GsaModel.

Deux familles de fichiers, dans un dossier de sortie :
  - tables du modele (une par entite) : Nodes, Elements, Sections, Materials,
    Load Cases, Beam Loads, etc. ;
  - tables de resultats facon GSA, CONSOLIDEES : un seul fichier par type de
    resultat (« Beam and Spring Forces and Moments », « Beam Stresses »,
    « Beam Derived Stresses », « ... Displacements », « Nodal Displacements »,
    « Reactions »), tous les cas empiles avec une colonne `case`. Les cas de
    charge peuvent etre tres nombreux : on ne les separe donc PAS en fichiers
    distincts.

Les resultats sont ecrits en flux (ligne a ligne) pour ne pas charger des
centaines de milliers de lignes en memoire.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

# Tables du modele : (nom de fichier, methode de GsaModel)
MODEL_TABLES = [
    ("Nodes", "nodes"),
    ("Elements", "elements"),
    ("Members", "members"),
    ("Sections", "sections"),
    ("Materials", "materials"),
    ("Load Cases", "load_cases"),
    ("Beam Loads", "beam_loads"),
    ("Gravity Loads", "gravity_loads"),
    ("Analysis Tasks", "analysis_tasks"),
    ("Analysis Cases", "analysis_cases"),
    ("Combinations", "combination_cases"),
]

# Tables de resultats (noms des tables de sortie GSA) :
#   (nom de fichier, methode, colonnes, filtre_nan)
RESULT_TABLES = [
    ("Beam and Spring Forces and Moments", "beam_forces",
     ["case", "element", "pos", "Fx", "Fy", "Fz", "Mxx", "Myy", "Mzz"], False),
    # Contraintes 1D (Element1dStress), unites Pa : axiale A, cisaillements
    # Sy/Sz, flexion By fibres +z/-z, Bz fibres +y/-y, combinees C1/C2.
    ("Beam Stresses", "beam_stresses",
     ["case", "element", "pos", "A", "Sy", "Sz",
      "By_pz", "By_nz", "Bz_py", "Bz_ny", "C1", "C2"], False),
    # Contraintes derivees (Element1dDerivedStress), Pa : cisaillements
    # elastiques SEy/SEz, torsion St, von Mises VM.
    ("Beam Derived Stresses", "beam_derived_stresses",
     ["case", "element", "pos", "SEy", "SEz", "St", "VM"], False),
    ("Beam and Spring Displacements", "beam_displacements",
     ["case", "element", "pos", "Ux", "Uy", "Uz", "Rxx", "Ryy", "Rzz"], False),
    ("Nodal Displacements", "node_displacements",
     ["case", "node", "Ux", "Uy", "Uz", "Rxx", "Ryy", "Rzz"], False),
    ("Reactions", "node_reactions",
     ["case", "node", "Fx", "Fy", "Fz", "Mxx", "Myy", "Mzz"], True),
]


def _write_table(path: Path, rows: list[dict]) -> int:
    if not rows:
        return 0
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow({k: _flatten(v) for k, v in r.items()})
    return len(rows)


def _flatten(v):
    """Rend une valeur ecrivable en CSV (une liste -> chaine '1 2')."""
    if isinstance(v, (list, tuple)):
        return " ".join(str(x) for x in v)
    return v


def _all_nan(row: dict) -> bool:
    vals = [v for k, v in row.items() if k not in ("case", "node", "element", "pos")]
    return all(isinstance(v, float) and math.isnan(v) for v in vals)


def export_model_tables(model, out_dir: Path, log=print) -> None:
    """Ecrit une CSV par table du modele (entites)."""
    for nom, methode in MODEL_TABLES:
        rows = getattr(model, methode)()
        n = _write_table(out_dir / f"{nom}.csv", rows)
        if n:
            log(f"  {nom}.csv : {n} ligne(s)")
        else:
            log(f"  {nom} : vide (non ecrit)")


def _cases_avec_resultats(model) -> list[str]:
    """Liste ordonnee des cas ayant des resultats : 'A1', 'A2', ..., 'C1', ..."""
    dispo = model.result_cases()
    return [f"A{i}" for i in sorted(dispo["A"])] + [f"C{i}" for i in sorted(dispo["C"])]


def export_results(model, out_dir: Path, positions: int = 2,
                   cases: list[str] | None = None, log=print) -> None:
    """Ecrit les tables de resultats consolidees (tous cas dans un seul fichier)."""
    if cases is None:
        cases = _cases_avec_resultats(model)
    log(f"  {len(cases)} cas a exporter (positions/element = {positions})")

    for nom, methode_nom, colonnes, filtre_nan in RESULT_TABLES:
        methode = getattr(model, methode_nom)
        est_beam = methode_nom.startswith("beam_")
        path = out_dir / f"{nom}.csv"
        total, ignores = 0, []
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=colonnes)
            w.writeheader()
            for case in cases:
                try:
                    rows = methode(case, positions) if est_beam else methode(case)
                except Exception:
                    ignores.append(case)
                    continue
                for r in rows:
                    if filtre_nan and _all_nan(r):
                        continue  # noeud sans reaction (pas un appui) : ignore, comme GSA
                    w.writerow({"case": case, **r})
                    total += 1
        msg = f"  {nom}.csv : {total} ligne(s)"
        if ignores:
            msg += f" ({len(ignores)} cas sans ce resultat, ignores)"
        log(msg)


def export_all(model, out_dir: Path, positions: int = 2,
               cases: list[str] | None = None, log=print) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    log("Tables du modele :")
    export_model_tables(model, out_dir, log)
    log("Tables de resultats (consolidees, facon GSA) :")
    export_results(model, out_dir, positions=positions, cases=cases, log=log)
