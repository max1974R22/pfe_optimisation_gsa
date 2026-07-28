# -*- coding: utf-8 -*-
"""
Balayage du parametre « ratio_hauteur_depart » (point de depart de l'algo
escalade : h0 = L_barre / ratio, cf. algo_opti/escalade.py) sur le treillis
Pratt, famille RHS. Les AUTRES parametres restent aux valeurs par defaut
ci-dessous (memes defauts que config/dimensionnement.json).

Parametres par defaut des AUTRES etudes (non balayes ici) :
    hauteur_max_m         = 0.5    (cf. A1_hauteur_max.py)
    epaisseur_max_mm      = 10.0   (cf. A2_epaisseur_max.py)
    ratio_largeur_depart  = 3.0    (cf. A4_ratio_largeur_depart.py)

Stabilite EC3 desactivee (etude ELU/ELS pure, rapide, reproductible).

Lancement (calcul CSV + trace PNG en une fois) :
    venv/Scripts/python.exe comparaison_modele/A3_ratio_hauteur_depart.py
"""
from __future__ import annotations

import _commun as c

NOM = "A3_ratio_hauteur_depart"
CLE = "ratio_hauteur_depart"
AXE = "Ratio hauteur de depart  (L / ratio)"
VALEURS = [10.0, 15.0, 20.0, 25.0, 30.0, 40.0]


def main() -> None:
    print(f"=== {NOM} : {AXE} (famille {c.FAMILLE}, autres parametres au defaut : "
          f"hauteur_max_m={c.DEFAUTS['hauteur_max_m']:g}, "
          f"epaisseur_max_mm={c.DEFAUTS['epaisseur_max_mm']:g}, "
          f"ratio_largeur_depart={c.DEFAUTS['ratio_largeur_depart']:g}) ===")
    lignes = []
    for v in VALEURS:
        r = c.run(c.FAMILLES_PRATT, f"{CLE}={v}", **{CLE: v})
        lignes.append({CLE: v, **r})
    c.ecrire_csv(f"{NOM}.csv", CLE, lignes)
    c.tracer_balayage(f"{NOM}.csv", f"{NOM}.png", CLE, AXE)


if __name__ == "__main__":
    main()
