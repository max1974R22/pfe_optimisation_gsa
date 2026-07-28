# -*- coding: utf-8 -*-
"""Matrice coloree barres x permutations ELU : ou et par quoi ca travaille.

Une IMAGE ou chaque pixel est un couple (barre, permutation de l'ENVELOPPE
ELU) : 657 lignes x 668 colonnes sur la Canopee.

  - la TEINTE dit QUEL critere EC3 est le plus sollicite dans cette case ;
  - l'INTENSITE dit COMBIEN : blanc a taux 0, teinte pleine a taux 1 ;
  - NOIR des qu'un taux depasse 1.

    compression      bleu        flexion_yy   jaune       torsion   cyan
    traction         rouge       flexion_zz   violet
    cisaillement_y   vert        cisaillement_z  orange

Le taux d'une case est le MAXIMUM des 7 taux EC3 de cette barre sous cette
seule permutation (efforts reduits sur les 5 positions de la barre). Les
resistances viennent de `canopee_elu_ec3.py` — un seul endroit definit les
formules EC3, la matrice et le tableau de taux ne peuvent pas diverger. Les
memes limites s'appliquent donc ici : resistance de SECTION uniquement (6.2),
sans flambement ni deversement, sans interaction entre efforts.

Deux images sont ecrites :
  - `canopee_elu_matrice.png`         : 1 pixel par case, sans decor
    (agrandissable a l'identique par `--echelle N`) ;
  - `canopee_elu_matrice_annotee.png` : la meme avec axes, separateurs entre
    les 38 combinaisons ELU et legende.

Usage :
    venv\\Scripts\\python.exe tests\\canopee_elu_matrice.py
    venv\\Scripts\\python.exe tests\\canopee_elu_matrice.py --tri taux --echelle 2
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _elu_commun import MODELE_DEFAUT, RESULTATS, Chrono
from canopee_elu_ec3 import CRITERES, charger_sections, resistances

# teinte pleine (taux = 1) de chaque critere, dans l'ordre de CRITERES
COULEURS = {
    "compression": (0, 60, 255),        # bleu
    "traction": (230, 0, 0),            # rouge
    "flexion_yy": (245, 205, 0),        # jaune
    "flexion_zz": (145, 0, 200),        # violet
    "torsion": (0, 190, 200),           # cyan
    "cisaillement_y": (0, 150, 40),     # vert
    "cisaillement_z": (255, 130, 0),    # orange
}
NOIR = (0, 0, 0)

# composante du torseur qui alimente chaque critere, dans l'ordre de CRITERES.
# L'ordre des colonnes du grand tableau est Fx, Fy, Fz, Mxx, Myy, Mzz.
COMPOSANTE_DE = {"compression": 0, "traction": 0, "flexion_yy": 4,
                 "flexion_zz": 5, "torsion": 3, "cisaillement_y": 1,
                 "cisaillement_z": 2}
NOMS = [nom for nom, _ in CRITERES]


def lire_matrice(entree: Path, chrono: Chrono) -> tuple:
    """Depouille le grand tableau.

    Renvoie (elements, infos, efforts, signe_Fx, libelles) avec
      efforts[i, p, c] = max |composante c| sur les 5 positions de la barre i
                         sous la permutation p ;
      signe_Fx[i, p]   = signe du Fx d'amplitude maximale (compression < 0).
    """
    with entree.open(encoding="utf-8-sig", newline="") as f:
        tete = f.readline()
        sep = ";" if tete.count(";") > tete.count(",") else ","
        f.seek(0)
        lecteur = csv.reader(f, delimiter=sep)
        entete = next(lecteur)
        col = {n: i for i, n in enumerate(entete)}
        # les colonnes de valeurs sont rangees permutation par permutation,
        # 6 composantes a la suite : un simple reshape(nperm, 6) suffit
        valeurs = [i for i, n in enumerate(entete) if n.startswith("perm")]
        i0, nperm = valeurs[0], len(valeurs) // 6

        def libelle(nom: str) -> str:
            """'perm038_C11p01_Myy' -> 'C11p01' ; 'perm038_Myy' -> 'perm038'."""
            tete = nom.rsplit("_", 1)[0]
            rang, _, reste = tete.partition("_")
            return reste or rang

        libelles = [libelle(entete[i0 + 6 * p]) for p in range(nperm)]

        elements: list[int] = []
        infos: list[dict] = []
        efforts: list[np.ndarray] = []
        signes: list[np.ndarray] = []
        acc = sgn = None
        for ligne in lecteur:
            eid = int(ligne[col["element"]])
            if not elements or eid != elements[-1]:
                elements.append(eid)
                infos.append({k: ligne[col[k]] for k in
                              ("type", "section", "nom_section", "profil",
                               "longueur_m")})
                acc = np.zeros((nperm, 6))
                sgn = np.ones(nperm)
                efforts.append(acc)
                signes.append(sgn)
            brut = [x if x else "nan" for x in ligne[i0:i0 + 6 * nperm]]
            v = np.array(brut, dtype=np.float64).reshape(nperm, 6)
            a = np.abs(np.nan_to_num(v))
            mieux = a[:, 0] > acc[:, 0]          # AVANT la mise a jour de acc
            sgn[mieux] = np.sign(np.nan_to_num(v[mieux, 0]))
            np.maximum(acc, a, out=acc)
    chrono.top(f"lecture de {len(elements)} barres x {nperm} permutations")
    return elements, infos, np.stack(efforts), np.stack(signes), libelles


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modele", default=str(MODELE_DEFAUT))
    ap.add_argument("--entree", default=str(RESULTATS / "canopee_elu_permutations.csv"))
    ap.add_argument("--sortie", default=str(RESULTATS / "canopee_elu_matrice.png"))
    ap.add_argument("--gamma-m0", type=float, default=1.0)
    ap.add_argument("--fy-mpa", type=float, default=None)
    ap.add_argument("--plastique", action="store_true")
    ap.add_argument("--av", choices=("ec3", "gsa"), default="ec3")
    ap.add_argument("--tri", choices=("element", "taux", "section"),
                    default="element",
                    help="ordre des lignes : id d'element (defaut), taux max "
                         "decroissant, ou regroupement par section")
    ap.add_argument("--echelle", type=int, default=1,
                    help="agrandissement entier de l'image brute (defaut 1)")
    args = ap.parse_args()

    entree = Path(args.entree)
    if not entree.exists():
        print(f"erreur : {entree} est introuvable "
              "(lancer d'abord canopee_elu_permutations.py)")
        return 1

    chrono = Chrono()
    print("Matrice barres x permutations ELU")
    print("=" * 70)

    sections = charger_sections(Path(args.modele), args.fy_mpa, args.av)
    chrono.top(f"lecture des {len(sections)} sections acier")

    elements, infos, efforts, signe, libelles = lire_matrice(entree, chrono)
    nb, nperm = efforts.shape[0], efforts.shape[1]

    # --- taux par case ----------------------------------------------------
    taux = np.zeros((nb, nperm, len(NOMS)))
    sans_resistance: set[str] = set()
    for i, info in enumerate(infos):
        s = sections.get(int(info["section"]))
        if not s:
            continue
        R = resistances(s, args.gamma_m0, args.plastique)
        for k, nom in enumerate(NOMS):
            r = R.get(nom)
            if not r:
                sans_resistance.add(nom)
                continue
            t = efforts[i, :, COMPOSANTE_DE[nom]] / r
            # Fx alimente compression ET traction : le signe tranche
            if nom == "compression":
                t = np.where(signe[i] < 0, t, 0.0)
            elif nom == "traction":
                t = np.where(signe[i] >= 0, t, 0.0)
            taux[i, :, k] = t

    gouvernant = taux.argmax(axis=2)
    tmax = taux.max(axis=2)
    chrono.top("calcul des taux EC3 case par case")

    # --- tri des lignes ---------------------------------------------------
    if args.tri == "taux":
        ordre = np.argsort(-tmax.max(axis=1), kind="stable")
    elif args.tri == "section":
        ordre = np.argsort([int(i["section"]) for i in infos], kind="stable")
    else:
        ordre = np.arange(nb)
    tmax, gouvernant = tmax[ordre], gouvernant[ordre]
    elements = [elements[i] for i in ordre]
    infos = [infos[i] for i in ordre]

    # --- coloriage --------------------------------------------------------
    # blanc a 0, teinte pleine a 1 : couleur = 255 - t (255 - teinte)
    palette = np.array([COULEURS[n] for n in NOMS], dtype=np.float64)
    teinte = palette[gouvernant]                      # (nb, nperm, 3)
    t = np.clip(tmax, 0.0, 1.0)[:, :, None]
    img = 255.0 - t * (255.0 - teinte)
    img[tmax > 1.0] = NOIR                            # depassement : noir
    img = img.astype(np.uint8)
    chrono.top("coloriage")

    # --- image brute, 1 pixel = 1 case ------------------------------------
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    sortie = Path(args.sortie)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    brute = img
    if args.echelle > 1:
        brute = np.repeat(np.repeat(img, args.echelle, axis=0), args.echelle, axis=1)
    plt.imsave(sortie, brute)

    # --- image annotee ----------------------------------------------------
    # bornes des 38 combinaisons ELU (C9..C46) dans les 668 permutations
    combi = [(re.match(r"(C\d+)", l) or re.match(r"(.*)", l)).group(1)
             for l in libelles]
    bornes, etiquettes = [], []
    for p, c in enumerate(combi):
        if p == 0 or c != combi[p - 1]:
            bornes.append(p)
            etiquettes.append(c)
    bornes.append(nperm)

    fig, ax = plt.subplots(figsize=(16, 9), dpi=140)
    ax.imshow(img, aspect="auto", interpolation="nearest", origin="upper")
    for b in bornes[1:-1]:
        ax.axvline(b - 0.5, color="0.55", lw=0.4)
    centres = [(bornes[i] + bornes[i + 1] - 1) / 2 for i in range(len(etiquettes))]
    # une combinaison a permutation UNIQUE ne fait qu'une colonne : etiqueter
    # les 38 se chevaucherait. On n'en garde qu'une tous les `ecart` colonnes,
    # et on annonce en clair celles qui sautent.
    ecart = max(1, nperm // 55)
    gardes, dernier = [], -1e9
    for i, c in enumerate(centres):
        if c - dernier >= ecart:
            gardes.append(i)
            dernier = c
    saute = [etiquettes[i] for i in range(len(etiquettes)) if i not in gardes]
    ax.set_xticks([centres[i] for i in gardes])
    ax.set_xticklabels([etiquettes[i] for i in gardes], rotation=90, fontsize=6)
    legende_x = (f"{nperm} permutations de l'ENVELOPPE ELU, "
                 f"groupees par combinaison (C9 a C46)")
    if saute:
        legende_x += (f"\nnon etiquetees, trop etroites (1 permutation) : "
                      f"{saute[0]} a {saute[-1]}")
    ax.set_xlabel(legende_x)
    ax.set_ylabel(f"{nb} barres acier"
                  + {"element": " (par id d'element)",
                     "taux": " (triees par taux max decroissant)",
                     "section": " (groupees par section)"}[args.tri])
    ax.set_title("Taux d'utilisation EC3 (resistance de section) "
                 "par barre et par permutation ELU\n"
                 "teinte = critere le plus sollicite, intensite = taux "
                 "(blanc 0 -> teinte pleine 1), noir = depassement")
    legende = [Patch(facecolor=np.array(COULEURS[n]) / 255, label=n) for n in NOMS]
    legende.append(Patch(facecolor="black", label="taux > 1"))
    ax.legend(handles=legende, loc="upper left", bbox_to_anchor=(1.01, 1.0),
              fontsize=8, frameon=False)
    fig.tight_layout()
    annotee = sortie.with_name(sortie.stem + "_annotee.png")
    fig.savefig(annotee, bbox_inches="tight")
    plt.close(fig)
    chrono.top("ecriture des images")

    # --- apercu ------------------------------------------------------------
    print("-" * 70)
    print(f"  -> {sortie}  ({brute.shape[1]} x {brute.shape[0]} px)")
    print(f"  -> {annotee}")
    if sans_resistance:
        print(f"  ! criteres sans resistance calculable (cases laissees a 0) : "
              f"{', '.join(sorted(sans_resistance))}")
    total = tmax.size
    print(f"  {total} cases  |  depassements (>1) : {int((tmax > 1).sum())} "
          f"({(tmax > 1).mean():.1%})  |  taux max : {tmax.max():.2f}")
    print("  repartition du critere gouvernant :")
    for k, nom in enumerate(NOMS):
        n = int((gouvernant == k).sum())
        if n:
            print(f"      {nom:<16} {n:>9} cases  ({n / total:>5.1%})")
    print("=" * 70)
    print(chrono.resume())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
