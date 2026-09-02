# -*- coding: utf-8 -*-
"""Script de demo/verification standalone pour commun/stabilite_ec3 : verifie
les 4 taux de stabilite EC3 (flambement §6.3.1, deversement §6.3.2,
flechie+comprimee [6.61]/[6.62]) sur UNE section et UN torseur types, en
faisant varier la FORME DU DIAGRAMME DE MOMENT selon yy (My) et selon zz
(Mz) independamment -- aucun Excel, aucun GSA, juste le module pur Python.

Section : IPE400/S235, geometrie et courbes de flambement (Tableau 6.2)
reprises telles quelles du classeur Predim (verifie sur le modele
10_story_frame.gwb, barre 11) -- cf. memoire [[stabilite-ec3-appv2]].

Usage :
    venv\\Scripts\\python.exe commun\\stabilite_ec3\\test_stabilite.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from commun.stabilite_ec3._commun import CaracteristiquesSection, ParametresBarre, Torseur  # noqa: E402
from commun.stabilite_ec3.verification import verifier_stabilite  # noqa: E402

# ---------------------------------------------------------------- section
# IPE400, S235 (Tableau 6.2 : h/b=400/180=2.22>1.2, tf=13,5<=40mm -> y-y="a", z-z="b")
SECTION = CaracteristiquesSection(
    nom="IPE400",
    h=400.0, b=180.0, tw=8.6, tf=13.5, A=8446.36,
    Iy=231_300_000.0, Iz=13_180_000.0,
    Wyel=1_160_000.0, Wypl=1_307_000.0, Wzel=146_000.0, Wzpl=229_000.0,
    iy=166.0, iz=39.5, It=513_000.0, Iw=492_214_513_750.0,
    courbe_flambement_y="a", courbe_flambement_z="b", est_section_I_H=True,
)

# ------------------------------------------------------------- parametres
# portee/longueurs de flambement-deversement 6 m, appuye-appuye, aucun
# facteur avance saisi a la main (k=kw=1) -- classe 1 (confirme sur IPE400,
# S235, comme sur le modele reel)
PARAMETRES = ParametresBarre(
    fy=235.0, E=210_000.0, G=80_769.0, gamma_M0=1.0, gamma_M1=1.0,
    Lcr_y_m=6.0, Lcr_z_m=6.0, L_deversement_m=6.0,
    k=1.0, kw=1.0,
    classe_section=1,
    repartition_charge="uniforme",
    # sensible_torsion : defaut True (tableau B.2), meme reglage que le
    # classeur Predim (Excel: P36="oui", jamais decoche par appv2)
)

N_ED_KN = -600.0   # compression moderee (~30 % de la resistance plastique
                    # en compression pure de la section) : fait vivre
                    # flambement ET interaction flexion+compression

# ----------------------------------------------------- formes de diagramme
# (nom, debut, milieu, fin) en kNm, meme convention que le classeur
# (Calcul!D31:D33 pour My, D35:D37 pour Mz) : moment le long de la barre,
# signe reel -- PAS un couple (M, psi*M) d'extremites seules.
FORMES_YY = [
    ("uniforme (charge repartie)",           30.0, 120.0,  30.0),
    ("moments d'extremite (portique)",       100.0,   0.0, -100.0),
    ("porte-a-faux / triangulaire",            0.0,  45.0,   90.0),
]
FORMES_ZZ = [
    ("nulle (flexion plane seule)",            0.0,   0.0,    0.0),
    ("uniforme, faible amplitude",             5.0,  18.0,    5.0),
    ("extremites, signe oppose",              15.0,   0.0,  -15.0),
]


def main() -> None:
    print(f"Section {SECTION.nom} (h/b={SECTION.h/SECTION.b:.2f}, courbes "
          f"{SECTION.courbe_flambement_y}/{SECTION.courbe_flambement_z}) -- "
          f"fy={PARAMETRES.fy:.0f} MPa, classe {PARAMETRES.classe_section}, "
          f"L={PARAMETRES.Lcr_y_m:.1f} m, N_Ed={N_ED_KN:.0f} kN\n")

    for nom_yy, my0, my1, my2 in FORMES_YY:
        for nom_zz, mz0, mz1, mz2 in FORMES_ZZ:
            torseur = Torseur(
                N_Ed_kN=N_ED_KN,
                My_Ed_kNm=max(abs(my0), abs(my1), abs(my2)),
                Mz_Ed_kNm=max(abs(mz0), abs(mz1), abs(mz2)),
                My_debut_kNm=my0, My_milieu_kNm=my1, My_fin_kNm=my2,
                Mz_debut_kNm=mz0, Mz_milieu_kNm=mz1, Mz_fin_kNm=mz2,
            )
            resultat = verifier_stabilite(SECTION, PARAMETRES, torseur)

            print(f"yy : {nom_yy}")
            print(f"  My = {my0:6.1f} / {my1:6.1f} / {my2:6.1f} kNm  (debut/milieu/fin)")
            print(f"zz : {nom_zz}")
            print(f"  Mz = {mz0:6.1f} / {mz1:6.1f} / {mz2:6.1f} kNm  (debut/milieu/fin)")
            for cas, taux in resultat["taux"].items():
                marque = " <-- dimensionnant" if cas == resultat["cas"] else ""
                print(f"    {cas:24s} {taux:6.3f}{marque}")
            verdict = "OK" if resultat["taux_stabilite"] <= 1.0 else "KO"
            print(f"  taux retenu = {resultat['taux_stabilite']:.3f}  ({verdict})\n")


if __name__ == "__main__":
    main()
