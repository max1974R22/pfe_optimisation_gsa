# -*- coding: utf-8 -*-
"""Synthèse par barre : pour chaque effort, trouve la permutation gouvernante.

À partir de `canopee_elu_permutations.csv` (une ligne par barre+position, 668×6 colonnes),
génère une feuille synthétique : une ligne par barre, 6 colonnes (Fx, Fy, Fz, Mxx, Myy, Mzz),
chacune montrant la permutation dimensionnante et sa position.

Usage :
    venv\\Scripts\\python.exe tests\\canopee_elu_synthese.py
    venv\\Scripts\\python.exe tests\\canopee_elu_synthese.py --entree resultats/canopee_elu_permutations.csv --sortie result.csv
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTATS = ROOT / "tests" / "resultats"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--entree", default=str(RESULTATS / "canopee_elu_permutations.csv"),
                    help="CSV d'entrée")
    ap.add_argument("--sortie", default=str(RESULTATS / "canopee_elu_synthese.csv"),
                    help="CSV de sortie")
    ap.add_argument("--separateur", default=",", help="séparateur (défaut ',' : standard)")
    args = ap.parse_args()

    entree = Path(args.entree)
    sortie = Path(args.sortie)
    if not entree.exists():
        print(f"erreur : {entree} n'existe pas")
        return 1

    print(f"Lecture {entree.name}...")
    with entree.open(encoding="utf-8-sig", newline="") as f:
        entete_ligne = f.readline()
        # auto-détecter le séparateur du fichier (virgule ou point-virgule)
        sep_fichier = ";" if entete_ligne.count(";") > entete_ligne.count(",") else ","
        f.seek(0)
        lecteur = csv.DictReader(f, delimiter=sep_fichier)
        en_tete = lecteur.fieldnames
        lignes = list(lecteur)

    if not lignes:
        print("  fichier vide")
        return 1

    print(f"  {len(lignes)} lignes, {len(en_tete)} colonnes")

    # colonnes d'identité et les 6 composantes
    colonnes_identite = ["element", "type", "section", "nom_section", "profil", "longueur_m"]
    composantes = ["Fx", "Fy", "Fz", "Mxx", "Myy", "Mzz"]

    # grouper par élément et créer pour chaque effort : (max_abs, permutation, position)
    par_element: dict[str, dict[str, dict]] = {}
    for ligne in lignes:
        eid = ligne["element"]
        if eid not in par_element:
            par_element[eid] = {col: ligne[col] for col in colonnes_identite}
            for comp in composantes:
                par_element[eid][comp] = {"max": 0.0, "perm": "", "pos": 0.0}

        pos = float(ligne["pos_pct"])

        # parcourir les 668 permutations pour chaque composante
        for comp in composantes:
            # colonnes de cette composante : perm001_..._Fx, perm002_..._Fx, etc.
            # ex. perm001_C9_Fx, perm002_C10p01_Fx, ...
            max_abs = par_element[eid][comp]["max"]
            for col in en_tete:
                if col.endswith(f"_{comp}"):
                    try:
                        val = float(ligne[col])
                    except (ValueError, KeyError):
                        continue
                    if abs(val) > max_abs:
                        max_abs = abs(val)
                        # extraire le libellé de permutation (perm001_C9 du col perm001_C9_Fx)
                        etiq = "_".join(col.split("_")[:-1])  # perm001_C9
                        par_element[eid][comp] = {"max": max_abs, "perm": etiq, "pos": pos}

    # écrire la synthèse : 1 ligne par élément
    print(f"Écriture {sortie.name}...")
    with sortie.open("w", encoding="utf-8-sig", newline="") as f:
        en_tete_synthese = colonnes_identite + [f"{c}_max" for c in composantes] + \
                          [f"{c}_perm" for c in composantes] + \
                          [f"{c}_pos" for c in composantes]
        writer = csv.DictWriter(f, fieldnames=en_tete_synthese, delimiter=args.separateur)
        writer.writeheader()

        for eid in sorted(par_element.keys(), key=lambda x: int(x)):
            e = par_element[eid]
            row = {col: e.get(col, "") for col in colonnes_identite}
            for c in composantes:
                row[f"{c}_max"] = e[c]["max"]
                row[f"{c}_perm"] = e[c]["perm"]
                row[f"{c}_pos"] = e[c]["pos"]
            writer.writerow(row)

    print(f"  -> {sortie} ({len(par_element)} barres)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
