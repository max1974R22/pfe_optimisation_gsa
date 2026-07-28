# -*- coding: utf-8 -*-
"""
Calcul MANUEL de la poutre ISO : les memes grandeurs que l'etude GSA
(scripts/etude_sections.py), mais par les formules classiques de la poutre
isostatique sur deux appuis sous charge repartie p :

    moment max (mi-travee)      My = p.L^2 / 8
    tranchant max (appui)       Vz = p.L / 2
    fleche max (mi-travee)      f  = 5.p.L^4 / (384.E.I)      (Euler-Bernoulli)

Chargement : poids propre pp (calcule par section : rho.A.g) + charge
VARIABLE lineaire q = 50 N/m. Deux combinaisons calculees :

    ELU = 1.35 pp + 1.5 q        (colonnes C1_*, comme la combo C1 du modele)
    ELS = pp + q                 (colonnes C2_*)

Recree le format de result/sections/_Comparaison.csv (memes sections, memes
conventions de signe que GSA : charge vers -Z, donc valeurs negatives ; Vz lu
a l'appui gauche) -> result/calcul_manuel/. Si le CSV GSA existe, imprime
aussi l'ecart max par grandeur (attendu : ~0 % sur My et Vz ; 0,1 a 0,9 % sur
la fleche, GSA ajoutant la deformation d'effort tranchant — poutre de
Timoshenko — que neglige Euler-Bernoulli).

Les proprietes de section (aire, Iyy) viennent de catalogues/IPE-AM.csv ;
les constantes du modele sont reprises des exports (Materials, Gravity Loads).

Usage :
    venv\\Scripts\\python.exe scripts\\calcul_manuel.py
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOGUE = ROOT / "catalogues" / "IPE-AM.csv"
RESULT_GSA = ROOT / "result" / "sections"   # pour la liste des sections + controle
SORTIE = ROOT / "result" / "calcul_manuel" / "_Comparaison.csv"

# --- constantes du modele Poutre ISO (cf. exports result/sections/<sec>/) ---
L = 10.0            # portee (m) : noeuds a x = -5 et +5
E = 205e9           # module d'Young du S235 du modele (Pa)
RHO = 7800.0        # masse volumique acier (kg/m3)
G = 9.81        # pesanteur (m/s2) ; charge gravite facteur -1 en Z
P_VARIABLE = 50.0   # charge variable q : UDL (N/m)

# combinaisons : nom de colonne -> (coef. poids propre, coef. charge variable)
CAS = {
    "C1": (1.35, 1.5),          # ELU = 1.35 pp + 1.5 q
    "C2": (1.0, 1.0),           # ELS = pp + q
}


# ----------------------------------------------------------------- formules
def moment_max(p: float, longueur: float) -> float:
    """Moment flechissant max a mi-travee : p.L^2/8 (N.m)."""
    return p * longueur ** 2 / 8


def tranchant_max(p: float, longueur: float) -> float:
    """Effort tranchant max a l'appui : p.L/2 (N)."""
    return p * longueur / 2


def fleche_max(p: float, longueur: float, module: float, inertie: float) -> float:
    """Fleche max a mi-travee (Euler-Bernoulli) : 5.p.L^4/(384.E.I) (m)."""
    return 5 * p * longueur ** 4 / (384 * module * inertie)


# ------------------------------------------------------------------- outils
def lire_catalogue() -> dict[str, dict]:
    with CATALOGUE.open(encoding="utf-8-sig") as f:
        return {r["nom"]: r for r in csv.DictReader(f)}


def cle_tri(nom: str):
    m = re.search(r"(\d+)", nom)
    return (0, int(m.group(1))) if m else (1, nom)


def sections_testees() -> list[str]:
    """Les memes sections que l'etude GSA (sous-dossiers de result/sections/)."""
    if RESULT_GSA.is_dir():
        noms = [d.name for d in RESULT_GSA.iterdir()
                if d.is_dir() and (d / "Sections.csv").exists()]
        if noms:
            return sorted(noms, key=cle_tri)
    sys.exit(f"Aucune section trouvee dans {RESULT_GSA} "
             "(lancer d'abord scripts/etude_sections.py)")


def comparer_au_gsa(lignes: list[dict]) -> None:
    """Ecart relatif max, par grandeur, avec result/sections/_Comparaison.csv."""
    ref_path = RESULT_GSA / "_Comparaison.csv"
    if not ref_path.exists():
        return
    with ref_path.open(encoding="utf-8-sig") as f:
        ref = {r["section"]: r for r in csv.DictReader(f)}
    ecarts: dict[str, float] = {}
    for ligne in lignes:
        r = ref.get(ligne["section"])
        if not r:
            continue
        for col, v in ligne.items():
            if "_max_" not in col or col not in r:
                continue
            v_gsa = float(r[col])
            if v_gsa == 0:
                continue
            grandeur = col.split("_")[1]           # Uz / My / Vz
            ecart = abs((float(v) - v_gsa) / v_gsa)
            ecarts[grandeur] = max(ecarts.get(grandeur, 0.0), ecart)
    print("Ecart max vs GSA :", ", ".join(
        f"{g} {e * 100:.3f} %" for g, e in sorted(ecarts.items())))


# --------------------------------------------------------------------- main
def main() -> None:
    catalogue = lire_catalogue()
    lignes = []
    for nom in sections_testees():
        sec = catalogue.get(nom)
        if sec is None:
            sys.exit(f"Section {nom} absente du catalogue {CATALOGUE.name}")
        aire = float(sec["aire_m2"])
        inertie = float(sec["Iyy_m4"])
        p_poids = RHO * aire * G                   # poids propre (N/m)

        ligne: dict = {"section": nom}
        for cas, (c_poids, c_var) in CAS.items():
            p = c_poids * p_poids + c_var * P_VARIABLE
            # signes : charge vers -Z -> fleche, moment et tranchant (appui
            # gauche) negatifs dans la convention de l'export GSA
            ligne[f"{cas}_Uz_max_m"] = round(-fleche_max(p, L, E, inertie), 6)
            ligne[f"{cas}_Uz_x_m"] = L / 2
            ligne[f"{cas}_My_max_Nm"] = round(-moment_max(p, L), 1)
            ligne[f"{cas}_My_x_m"] = L / 2
            ligne[f"{cas}_Vz_max_N"] = round(-tranchant_max(p, L), 1)
            ligne[f"{cas}_Vz_x_m"] = 0.0
        lignes.append(ligne)

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    with SORTIE.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(lignes[0].keys()))
        w.writeheader()
        w.writerows(lignes)
    print(f"{SORTIE.name} : {len(lignes)} section(s), {len(CAS)} cas -> {SORTIE}")
    comparer_au_gsa(lignes)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
