# -*- coding: utf-8 -*-
"""
Influence de l'ORDRE DE DEPART des familles sur l'algo escalade
(algo_opti/escalade.py) — mais SEULEMENT sur les familles qui en dependent.

En phase de croissance, l'escalade n'augmente QUE les familles KO au gabarit
de depart (les familles deja OK ne sont jamais escaladees) : seul l'ordre
RELATIF de ces familles-la change le resultat. On commence donc par evaluer la
CONFIG 0 (chaque famille au profil le plus fin) pour reperer les familles KO,
puis on ne permute QUE celles-ci (les OK restent en fin de liste, dans leur
ordre par defaut).

Le nombre de familles KO est petit (souvent <= 4, soit 4! = 24 ordres) :
- si k! <= N (nombre de permutations demande), on les teste TOUTES,
  exhaustivement (aucun tirage aleatoire, resultat complet) ;
- sinon on en tire N au hasard (reproductible, graine fixe).

Complement de B1_ordres_choisis.py (quelques ordres choisis a la main).

Parametres par defaut (fixes, non balayes ici — cf. A1..A4) :
    hauteur_max_m         = 0.5
    epaisseur_max_mm      = 10.0
    ratio_hauteur_depart  = 20.0
    ratio_largeur_depart  = 3.0

Stabilite EC3 desactivee (etude ELU/ELS pure, rapide, reproductible).

Lancement (N=100 par defaut, calcul CSV + trace PNG en une fois) :
    venv/Scripts/python.exe comparaison_modele/B2_ordres_aleatoires.py
    venv/Scripts/python.exe comparaison_modele/B2_ordres_aleatoires.py 300
"""
from __future__ import annotations

import csv as csv_mod
import itertools
import math
import random
import sys

import _commun as c
from algo_opti import escalade

NOM = "B2_ordres_aleatoires"
N_DEFAUT = 100
GRAINE = 42   # tirage reproductible d'un lancement a l'autre


def permutations_aleatoires(libelles: list[str], n: int,
                            graine: int = GRAINE) -> list[list[str]]:
    """n permutations DISTINCTES de `libelles`, tirage reproductible (borne au
    nombre total de permutations possibles pour ne jamais boucler sans fin)."""
    n = min(n, math.factorial(len(libelles)))
    rng = random.Random(graine)
    vues: set[tuple[str, ...]] = set()
    ordres = []
    while len(ordres) < n:
        perm = libelles[:]
        rng.shuffle(perm)
        t = tuple(perm)
        if t in vues:
            continue
        vues.add(t)
        ordres.append(perm)
    return ordres


def _ordonner(ordre_libelles: list[str]) -> list[dict]:
    par_nom = {g["libelle"]: g for g in c.FAMILLES_PRATT}
    return [par_nom[nom] for nom in ordre_libelles]


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else N_DEFAUT

    # CONFIG 0 : une analyse GSA au gabarit de depart pour reperer les familles
    # KO — seules celles-ci seront escaladees, donc seul leur ordre compte
    cfg0 = c.base_cfg(c.FAMILLES_PRATT)
    ko_indices = escalade.familles_ko_depart(c.MODELE, cfg0)
    ko_libelles = [c.FAMILLES_PRATT[i]["libelle"] for i in ko_indices]
    ok_libelles = [g["libelle"] for g in c.FAMILLES_PRATT
                   if g["libelle"] not in set(ko_libelles)]

    k = len(ko_libelles)
    total_perms = math.factorial(k)
    exhaustif = total_perms <= n
    if exhaustif:
        # k! <= N : on teste TOUTES les permutations des familles KO
        ordres_ko = [list(p) for p in itertools.permutations(ko_libelles)]
    else:
        # trop de permutations : echantillon aleatoire reproductible
        ordres_ko = permutations_aleatoires(ko_libelles, n)

    mode = (f"exhaustif ({total_perms} permutation(s))" if exhaustif
            else f"echantillon {len(ordres_ko)}/{total_perms}")
    print(f"=== {NOM} : ordre des familles KO au depart "
          f"(famille {c.FAMILLE}, parametres fixes au defaut : "
          f"hauteur_max_m={c.DEFAUTS['hauteur_max_m']:g}, "
          f"epaisseur_max_mm={c.DEFAUTS['epaisseur_max_mm']:g}, "
          f"ratio_hauteur_depart={c.DEFAUTS['ratio_hauteur_depart']:g}, "
          f"ratio_largeur_depart={c.DEFAUTS['ratio_largeur_depart']:g}) ===")
    print(f"  config 0 : {k} famille(s) KO permutee(s) [{', '.join(ko_libelles) or 'aucune'}] "
          f"-> {mode}")
    if ok_libelles:
        print(f"  familles OK (ordre fige en fin de liste) : {', '.join(ok_libelles)}")

    lignes = []
    for i, ordre_ko in enumerate(ordres_ko, start=1):
        # les familles OK, jamais escaladees, sont posees apres (ordre par defaut)
        ordre_complet = ordre_ko + ok_libelles
        groupes = _ordonner(ordre_complet)
        r = c.run(groupes, f"perm {i}/{len(ordres_ko)}")
        lignes.append({"permutation": i,
                       "sequence_ko": " > ".join(ordre_ko),
                       "sequence": " > ".join(ordre_complet), **r})

    chemin = c.RESULT / f"{NOM}.csv"
    champs = ["permutation", "masse_totale_kg", "analyses", "converge",
              "taux_ELS", "familles_ok", "duree_s", "sequence_ko", "sequence", "sections"]
    with chemin.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv_mod.DictWriter(f, fieldnames=champs)
        w.writeheader()
        for lg in lignes:
            w.writerow({k_: lg[k_] for k_ in champs})
    print(f"  -> {chemin.relative_to(c.ROOT)}")

    tracer_distribution(f"{NOM}.csv", f"{NOM}.png", ko_libelles, exhaustif, total_perms)


def tracer_distribution(nom_csv: str, nom_png: str, ko_libelles: list[str],
                        exhaustif: bool, total_perms: int) -> None:
    """Histogramme de la masse totale sur tous les ordres testes — ces ordres
    ne permutent QUE les familles KO au depart (cf. main), le seul facteur qui
    change reellement le resultat de l'escalade."""
    import matplotlib.pyplot as plt

    rows = c.lire_csv(nom_csv)
    masse = [float(r["masse_totale_kg"]) for r in rows]
    converge = [int(r["converge"]) for r in rows]
    n = len(rows)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(masse, bins=min(30, max(5, n // 3)), color="#c2185b", alpha=0.85,
           edgecolor="white")
    ax.axvline(min(masse), color="#2e7d32", linestyle=":", linewidth=2,
              label=f"meilleur : {min(masse):.1f} kg")
    ax.axvline(max(masse), color="#616161", linestyle=":", linewidth=2,
              label=f"pire : {max(masse):.1f} kg")
    ax.set_xlabel("Masse d'acier totale (kg)")
    ax.set_ylabel("Nombre d'ordres testes")
    n_non_conv = sum(1 for ok in converge if not ok)
    k = len(ko_libelles)
    mode = "exhaustif" if exhaustif else "echantillon aleatoire"
    titre = (f"Escalade / Pratt — masse sur {n} ordre(s) des {k} famille(s) "
             f"KO au depart ({mode}, {total_perms} possible(s))")
    if n_non_conv:
        titre += f" — {n_non_conv} non convergent(s)"
    ax.set_title(titre, fontsize=10)
    # familles KO permutees (le facteur etudie), annotees sur le graphe
    ax.text(0.02, 0.98, "Familles KO permutees :\n" + "\n".join(ko_libelles or ["aucune"]),
            transform=ax.transAxes, va="top", ha="left", fontsize=8, color="#444",
            bbox=dict(boxstyle="round", fc="white", ec="#ccc", alpha=0.8))
    ax.legend(fontsize=9, loc="upper right")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    sortie = c.RESULT / nom_png
    fig.savefig(sortie, dpi=120)
    plt.close(fig)
    print(f"  -> {sortie.name}")


if __name__ == "__main__":
    main()
