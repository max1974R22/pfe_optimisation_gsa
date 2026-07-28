# -*- coding: utf-8 -*-
"""
Balayage du parametre « epaisseur_max_mm » (plafond d'epaisseur de paroi admis
par l'algo escalade, cf. algo_opti/escalade.py) sur le treillis Pratt, famille
RHS. Les AUTRES parametres restent aux valeurs par defaut ci-dessous (memes
defauts que config/dimensionnement.json).

Parametres par defaut des AUTRES etudes (non balayes ici) :
    hauteur_max_m         = 0.5    (cf. A1_hauteur_max.py)
    ratio_hauteur_depart   = 20.0   (cf. A3_ratio_hauteur_depart.py)
    ratio_largeur_depart   = 3.0    (cf. A4_ratio_largeur_depart.py)

Stabilite EC3 desactivee (etude ELU/ELS pure, rapide, reproductible).

Lancement (calcul CSV + trace PNG en une fois) :
    venv/Scripts/python.exe comparaison_modele/A2_epaisseur_max.py
"""
from __future__ import annotations

import _commun as c

NOM = "A2_epaisseur_max"
CLE = "epaisseur_max_mm"
AXE = "Epaisseur de paroi max (mm)"
VALEURS = [4.0, 5.0, 6.3, 8.0, 10.0, 12.5, 16.0]


def main() -> None:
    print(f"=== {NOM} : {AXE} (famille {c.FAMILLE}, autres parametres au defaut : "
          f"hauteur_max_m={c.DEFAUTS['hauteur_max_m']:g}, "
          f"ratio_hauteur_depart={c.DEFAUTS['ratio_hauteur_depart']:g}, "
          f"ratio_largeur_depart={c.DEFAUTS['ratio_largeur_depart']:g}) ===")
    lignes = []
    for v in VALEURS:
        r = c.run(c.FAMILLES_PRATT, f"{CLE}={v}", **{CLE: v})
        lignes.append({CLE: v, **r})
    c.ecrire_csv(f"{NOM}.csv", CLE, lignes)
    c.tracer_balayage(f"{NOM}.csv", f"{NOM}.png", CLE, AXE)


if __name__ == "__main__":
    main()
