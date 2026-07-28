# -*- coding: utf-8 -*-
"""
Influence de l'ORDRE DE DEPART des familles sur l'algo escalade
(algo_opti/escalade.py) : l'escalade traite les familles dans l'ordre de
`groupes`, la phase de croissance et la phase d'allegement en dependent donc
l'optimum local atteint change selon l'ordre. Sur ce treillis Pratt (8
familles => 8! = 40320 ordres possibles), on n'en teste ici que quelques uns,
CHOISIS A LA MAIN, en deplacant surtout les familles DIMENSIONNANTES
(Membrure haute, Diag ext) et la famille la plus LOURDE (Membrure basse, 6
barres) — voir B2_ordres_aleatoires.py pour un balayage systematique sur N
permutations aleatoires.

Parametres par defaut (fixes, non balayes ici — cf. A1..A4) :
    hauteur_max_m         = 0.5
    epaisseur_max_mm      = 10.0
    ratio_hauteur_depart  = 20.0
    ratio_largeur_depart  = 3.0

Stabilite EC3 desactivee (etude ELU/ELS pure, rapide, reproductible).

Lancement (calcul CSV + trace PNG en une fois) :
    venv/Scripts/python.exe comparaison_modele/B1_ordres_choisis.py
"""
from __future__ import annotations

import _commun as c

NOM = "B1_ordres_choisis"

ORDRES = {
    "1-naturel": [
        "Membrure haute", "Diag ext", "Diag int", "Diag mid",
        "Membrure basse", "Mont ext", "Mont int", "Mont mid"
    ],
    "2-dim_d_abord": [
        "Membrure haute", "Diag ext", "Diag int", "Diag mid",
        "Mont ext", "Mont int", "Mont mid", "Membrure basse"
    ],
    "3-lourd_d_abord": [
        "Membrure basse", "Membrure haute", "Diag ext", "Diag int",
        "Diag mid", "Mont ext", "Mont int", "Mont mid"
    ],
    "4-dim_puis_lourd": [
        "Membrure haute", "Diag ext", "Diag int", "Diag mid",
        "Mont ext", "Mont int", "Mont mid", "Membrure basse"
    ],
    "5-lourd_puis_dim": [
        "Membrure basse", "Membrure haute", "Diag ext", "Diag int",
        "Diag mid", "Mont ext", "Mont int", "Mont mid"
    ],
    "6-dim_en_dernier": [
        "Diag int", "Diag mid", "Mont ext", "Mont int", "Mont mid",
        "Membrure basse", "Membrure haute", "Diag ext"
    ],
    "7-lourd_en_dernier": [
        "Membrure haute", "Diag ext", "Diag int", "Diag mid",
        "Mont ext", "Mont int", "Mont mid", "Membrure basse"
    ],
    "8-inverse": [
        "Mont mid", "Mont int", "Mont ext", "Membrure basse",
        "Diag mid", "Diag int", "Diag ext", "Membrure haute"
    ],
}


def _ordonner(ordre_libelles: list[str]) -> list[dict]:
    par_nom = {g["libelle"]: g for g in c.FAMILLES_PRATT}
    return [par_nom[nom] for nom in ordre_libelles]


def main() -> None:
    print(f"=== {NOM} : influence de l'ordre de depart des familles "
          f"(famille {c.FAMILLE}, parametres fixes au defaut : "
          f"hauteur_max_m={c.DEFAUTS['hauteur_max_m']:g}, "
          f"epaisseur_max_mm={c.DEFAUTS['epaisseur_max_mm']:g}, "
          f"ratio_hauteur_depart={c.DEFAUTS['ratio_hauteur_depart']:g}, "
          f"ratio_largeur_depart={c.DEFAUTS['ratio_largeur_depart']:g}) ===")
    lignes = []
    for nom, ordre in ORDRES.items():
        groupes = _ordonner(ordre)
        r = c.run(groupes, nom)
        lignes.append({"ordre": nom, "sequence": " > ".join(ordre), **r})

    chemin = c.RESULT / f"{NOM}.csv"
    champs = ["ordre", "masse_totale_kg", "analyses", "converge", "taux_ELS",
              "familles_ok", "duree_s", "sequence", "sections"]
    import csv as csv_mod
    with chemin.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv_mod.DictWriter(f, fieldnames=champs)
        w.writeheader()
        for lg in lignes:
            w.writerow({k: lg[k] for k in champs})
    print(f"  -> {chemin.relative_to(c.ROOT)}")

    c.tracer_ordres(f"{NOM}.csv", f"{NOM}.png", col_libelle="ordre")


if __name__ == "__main__":
    main()
