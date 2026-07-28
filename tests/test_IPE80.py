# -*- coding: utf-8 -*-
"""
Trace pas-a-pas du calcul manuel pour l'IPE80 : affiche chaque etape
(poids propre, charges elementaires, fleches par origine, combinaisons),
avec les formules et les valeurs substituees.

Reutilise les constantes et formules de scripts/calcul_manuel.py pour rester
strictement coherent avec le CSV produit par celui-ci.

Usage :
    venv\\Scripts\\python.exe tests\\test_IPE80.py
    venv\\Scripts\\python.exe tests\\test_IPE80.py IPE200   # autre section
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from calcul_manuel import (L, E, RHO, G, P_VARIABLE, CAS,
                           moment_max, tranchant_max, fleche_max,
                           lire_catalogue, RESULT_GSA)

SECTION = sys.argv[1].upper() if len(sys.argv) > 1 else "IPE80"


def titre(txt: str) -> None:
    print(f"\n=== {txt} " + "=" * max(0, 60 - len(txt)))


def main() -> None:
    sec = lire_catalogue().get(SECTION)
    if sec is None:
        sys.exit(f"Section {SECTION} absente de catalogues/IPE-AM.csv")
    aire = float(sec["aire_m2"])
    inertie = float(sec["Iyy_m4"])

    titre(f"1. Donnees — {SECTION}")
    print(f"  portee            L   = {L} m")
    print(f"  module d'Young    E   = {E:.3g} Pa  ({E / 1e9:.0f} GPa)")
    print(f"  masse volumique   rho = {RHO} kg/m3")
    print(f"  pesanteur         g   = {G} m/s2")
    print(f"  aire              A   = {aire} m2       (catalogue IPE-AM)")
    print(f"  inertie axe fort  Iyy = {inertie} m4    (catalogue IPE-AM)")

    titre("2. Charges lineaires")
    pp = RHO * aire * G
    print(f"  poids propre    pp = rho.A.g = {RHO} x {aire} x {G}")
    print(f"                     = {pp:.3f} N/m")
    print(f"  charge variable q  = {P_VARIABLE} N/m   (donnee)")

    titre("3. Effets des charges ELEMENTAIRES (superposition)")
    print("  formules (poutre bi-appuyee, charge repartie p) :")
    print("    My(p) = p.L^2/8    Vz(p) = p.L/2    f(p) = 5.p.L^4/(384.E.Iyy)")
    effets = {}
    for nom_charge, p in (("poids propre pp", pp), ("variable q", P_VARIABLE)):
        my, vz, f = moment_max(p, L), tranchant_max(p, L), fleche_max(p, L, E, inertie)
        effets[nom_charge] = (my, vz, f)
        print(f"\n  - {nom_charge} (p = {p:.3f} N/m) :")
        print(f"      My = {p:.3f} x {L}^2 / 8              = {my:8.1f} N.m")
        print(f"      Vz = {p:.3f} x {L} / 2                = {vz:8.1f} N")
        print(f"      f  = 5 x {p:.3f} x {L}^4 / (384 x {E:.3g} x {inertie})")
        print(f"         = {f:.6f} m  soit {f * 1000:.3f} mm")

    (my_pp, vz_pp, f_pp), (my_q, vz_q, f_q) = effets.values()

    titre("4. Combinaisons (structure lineaire : on superpose)")
    resultats = {}
    for cas, (c_pp, c_q) in CAS.items():
        nom = "ELU" if cas == "C1" else "ELS"
        p = c_pp * pp + c_q * P_VARIABLE
        my, vz, f = moment_max(p, L), tranchant_max(p, L), fleche_max(p, L, E, inertie)
        resultats[nom] = (my, vz, f)
        print(f"\n  {nom} ({cas}) : p = {c_pp} x pp + {c_q} x q "
              f"= {c_pp} x {pp:.3f} + {c_q} x {P_VARIABLE} = {p:.3f} N/m")
        print(f"      My = {my:8.1f} N.m    (= {c_pp} x {my_pp:.1f} + {c_q} x {my_q:.1f})")
        print(f"      Vz = {vz:8.1f} N      (= {c_pp} x {vz_pp:.1f} + {c_q} x {vz_q:.1f})")
        print(f"      f  = {f * 1000:8.3f} mm    "
              f"(= {c_pp} x {f_pp * 1000:.3f} + {c_q} x {f_q * 1000:.3f} mm)")
        print(f"      part de la fleche due a pp : {c_pp * f_pp / f:.1%} ; "
              f"due a q : {c_q * f_q / f:.1%}")

    titre("5. Controle vs GSA (result/sections/_Comparaison.csv)")
    ref_path = RESULT_GSA / "_Comparaison.csv"
    if not ref_path.exists():
        print("  (pas de CSV GSA : lancer scripts/etude_sections.py puis comparer_sections.py)")
        return
    with ref_path.open(encoding="utf-8-sig") as fcsv:
        ref = {r["section"]: r for r in csv.DictReader(fcsv)}
    r = ref.get(SECTION)
    if r is None:
        print(f"  ({SECTION} absent du CSV GSA)")
        return
    for nom, cas in (("ELU", "C1"), ("ELS", "C2")):
        my, vz, f = resultats[nom]
        for grandeur, manuel, col, fac in (
                ("My", my, f"{cas}_My_max_Nm", 1), ("Vz", vz, f"{cas}_Vz_max_N", 1),
                ("f ", f * 1000, f"{cas}_Uz_max_m", 1000)):
            gsa = abs(float(r[col])) * fac
            print(f"  {nom} {grandeur} : manuel {manuel:10.3f}  |  GSA {gsa:10.3f}"
                  f"  |  ecart {(manuel - gsa) / gsa:+.3%}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
