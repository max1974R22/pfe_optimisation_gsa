# -*- coding: utf-8 -*-
"""Taux d'utilisation EC3 par barre acier, sur les 668 permutations de l'ELU.

Lit le GRAND tableau `canopee_elu_permutations.csv` (et non la synthese, qui ne
garde que des valeurs absolues : la distinction compression / traction exige le
SIGNE) et produit une ligne par barre avec 7 taux d'utilisation, chacun
accompagne de l'effort, de la permutation et de la position qui le gouvernent.

Criteres — EC3-1-1 section 6.2, RESISTANCE DE SECTION uniquement :
  compression     6.2.4  |N|/(A fy/gM0)                 N < 0
  traction        6.2.3   N /(A fy/gM0)                 N > 0
  flexion_yy      6.2.5  |Myy|/(Wy fy/gM0)
  flexion_zz      6.2.5  |Mzz|/(Wz fy/gM0)
  torsion         6.2.7  (|T|/Wt)/(fy/racine(3)/gM0)
  cisaillement_y  6.2.6  |Fy|/(Avy (fy/racine(3))/gM0)
  cisaillement_z  6.2.6  |Fz|/(Avz (fy/racine(3))/gM0)

CE QUE CE SCRIPT NE FAIT PAS — a lire avant d'exploiter les taux :
  - AUCUN flambement (6.3.1), deversement (6.3.2) ni flambement par torsion :
    ce sont des verifications d'ELEMENT, qui exigent des longueurs de flambement
    absentes du modele. Le taux de compression est donc une borne INFERIEURE du
    taux reel. Pour la stabilite, le projet passe par le classeur Predim
    (excel_bridge/).
  - AUCUNE interaction entre efforts (6.2.1(7), 6.2.9 M+N, 6.2.10 M+V...) :
    les 7 taux sont independants, chacun sur SA permutation gouvernante, qui
    n'est en general pas la meme. Leur maximum n'est pas un taux d'ensemble.
  - AUCUNE classification de section (6.2 tableau 5.2) : le moment resistant
    est pris ELASTIQUE (Wel) par defaut, ce qui est valable et conservatif
    pour toutes les classes 1 a 3. `--plastique` bascule sur Wpl (a ne faire
    que si les sections sont de classe 1 ou 2).
  - fy est la valeur NOMINALE de la nuance (S355 -> 355 MPa), sans reduction
    pour les fortes epaisseurs (EN 1993-1-1 tableau 3.1).

Le module de torsion Wt vient de GSA (`Section.Properties().C`) ; l'aire de
cisaillement Av n'est PAS exposee par GSA et suit les formules de l'EC3
(cf. `caracteristiques` plus bas).

Usage :
    venv\\Scripts\\python.exe tests\\canopee_elu_ec3.py
    venv\\Scripts\\python.exe tests\\canopee_elu_ec3.py --plastique --gamma-m0 1.0
"""
from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _elu_commun import MODELE_DEFAUT, RESULTATS, Chrono
from gsa_bridge.bridge import GsaModel

RACINE3 = math.sqrt(3.0)

# 7 criteres : (nom, composante du torseur qui le pilote)
CRITERES = (("compression", "Fx"), ("traction", "Fx"),
            ("flexion_yy", "Myy"), ("flexion_zz", "Mzz"),
            ("torsion", "Mxx"),
            ("cisaillement_y", "Fy"), ("cisaillement_z", "Fz"))
COMPOSANTES = ("Fx", "Fy", "Fz", "Mxx", "Myy", "Mzz")


# --------------------------------------------------------------------------
#  Caracteristiques de section : ce que GSA donne, et ce qu'il ne donne pas.
#
#  DONNE (Section.Properties(), expose par gsa_bridge) : A, Iyy/Izz, J, les
#  modules de flexion elastiques Zy/Zz et plastiques Zpy/Zpz, et le MODULE DE
#  TORSION `C` (tau_t = Mt / C). Verifie sur les 22 sections acier de la
#  Canopee : C egale a 0.5% pres la reconstruction de Bredt (2 Am t) pour les
#  RHS et J/(d/2) pour les CHS et les ronds pleins, le residu n'etant que
#  l'arrondi des cotes catalogue. On prend donc `C` tel quel.
#
#  NE DONNE PAS : l'aire de cisaillement Av de l'EC3 6.2.6. GSA expose Kyy/Kzz,
#  qui sont les facteurs de cisaillement de TIMOSHENKO (aire reduite de
#  DEFORMATION, pour la fleche) — une autre grandeur : rond plein K = 6/7 =
#  0.857 contre Av/A = 0.75, tube mince K = 0.500 contre Av/A = 2/pi = 0.637,
#  RHS 200x120x10 K = 0.573 contre Av,z/A = h/(b+h) = 0.625. Av est donc
#  calcule selon les formules de l'EC3, a partir des cotes lues dans la chaine
#  de profil. `--av gsa` bascule sur K x A si l'on veut malgre tout la valeur
#  GSA (ce n'est alors plus la verification de l'EC3).
# --------------------------------------------------------------------------
def geometrie(profil: str) -> dict | None:
    """{forme, h, b, t, d} en metres, ou None si le profil n'est pas reconnu.

    'STD RHS 200 120 10 10'      -> tube rectangulaire h x b, paroi t
    'STD C 40'                   -> rond PLEIN de diametre d
    'CAT EN-CHS CHS610x20.0 ...' -> tube circulaire d x t
    """
    p = (profil or "").strip()

    m = re.match(r"STD\s+RHS\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", p, re.I)
    if m:
        h, b, t1, t2 = (float(x) / 1000.0 for x in m.groups())
        return {"forme": "RHS", "h": h, "b": b, "t": min(t1, t2), "d": None}

    m = re.search(r"CHS\s*([\d.]+)\s*x\s*([\d.]+)", p, re.I)
    if m:
        d, t = (float(x) / 1000.0 for x in m.groups())
        return {"forme": "CHS", "h": d, "b": d, "t": t, "d": d}

    m = re.match(r"STD\s+C\s+([\d.]+)\s*$", p, re.I)
    if m:
        d = float(m.group(1)) / 1000.0
        return {"forme": "ROND", "h": d, "b": d, "t": None, "d": d}

    return None


def caracteristiques(sect: dict, source_av: str = "ec3") -> dict:
    """Complete une section GSA avec Avy, Avz et Wt.

    Wt vient TOUJOURS de GSA (`C_m3`). Avy/Avz suivent l'EC3 6.2.6(3) par
    defaut (cotes lues dans le profil), ou K x A si `source_av == "gsa"`.

    `ecart_aire` compare l'aire recalculee depuis le profil a celle de GSA :
    garde-fou sur la lecture de la chaine de profil.
    """
    A = sect["aire_m2"]
    out = {"forme": None, "Avy": None, "Avz": None,
           "Wt": sect.get("C_m3"), "ecart_aire": None}

    if source_av == "gsa":
        out["forme"] = (geometrie(sect["profil"]) or {}).get("forme") or "?"
        out["Avy"] = (sect.get("Kyy") or 0) * A or None
        out["Avz"] = (sect.get("Kzz") or 0) * A or None
        return out

    g = geometrie(sect["profil"])
    if not g:
        return out
    out["forme"] = g["forme"]

    if g["forme"] == "RHS":
        h, b, t = g["h"], g["b"], g["t"]
        # EC3 6.2.6(3), profil creux lamine d'epaisseur uniforme
        out["Avz"] = A * h / (b + h)          # effort // hauteur (local z)
        out["Avy"] = A * b / (b + h)          # effort // largeur (local y)
        out["ecart_aire"] = abs(2 * t * (h + b - 2 * t) - A) / A if A else None

    elif g["forme"] == "CHS":
        d, t = g["d"], g["t"]
        out["Avz"] = out["Avy"] = 2.0 * A / math.pi     # EC3 6.2.6(3)
        out["ecart_aire"] = abs(math.pi * (d - t) * t - A) / A if A else None

    elif g["forme"] == "ROND":
        d = g["d"]
        # section pleine : tau_max = 4V/(3A) -> aire de cisaillement 0.75 A
        # (l'EC3 ne tabule pas le rond plein ; valeur issue de l'elasticite)
        out["Avz"] = out["Avy"] = 0.75 * A
        out["ecart_aire"] = abs(math.pi * d * d / 4.0 - A) / A if A else None

    return out


def fy_des_materiaux(m) -> dict[int, float]:
    """{id materiau acier: fy en Pa}, deduit du NOM de la nuance ('S355')."""
    fy = {}
    for mat in m.materials():
        if mat["type"] != "acier":
            continue
        n = re.search(r"S\s*(\d{3})", mat["nom"] or "")
        if n:
            fy[mat["id"]] = float(n.group(1)) * 1e6
    return fy


def charger_sections(modele: Path, fy_mpa: float | None = None,
                     source_av: str = "ec3") -> dict[int, dict]:
    """{id section: caracteristiques} pour les sections ACIER du modele.

    Aucune analyse GSA : seules les tables Sections / Materials sont lues.
    Chaque entree porte, en plus des champs du pont, `forme`, `Avy`, `Avz`,
    `Wt`, `ecart_aire` et `fy_Pa`.
    """
    m = GsaModel(modele)
    try:
        fy_mat = fy_des_materiaux(m)
        sections = {}
        for s in m.sections():
            if s["materiau"] != "STEEL":
                continue
            car = caracteristiques(s, source_av)
            fy = fy_mpa * 1e6 if fy_mpa else fy_mat.get(s["materiau_grade"])
            sections[s["section"]] = {**s, **car, "fy_Pa": fy}
        return sections
    finally:
        m.close()


def resistances(sect: dict, gamma_m0: float = 1.0,
                plastique: bool = False) -> dict[str, float | None]:
    """Resistances de section EC3 6.2, par critere (None si non calculable).

    Point unique de definition des resistances : `canopee_elu_ec3.py` comme
    `canopee_elu_matrice.py` passent par ici, pour qu'aucune formule ne puisse
    diverger entre le tableau de taux et la matrice coloree.
    """
    fy = sect.get("fy_Pa")
    if not fy:
        return {nom: None for nom, _ in CRITERES}
    fyd = fy / gamma_m0                  # limite en contrainte normale
    tyd = fy / RACINE3 / gamma_m0        # limite en cisaillement (von Mises)
    Wy = sect["Zpy_m3"] if plastique else sect["Zy_m3"]
    Wz = sect["Zpz_m3"] if plastique else sect["Zz_m3"]

    def produit(module, limite):
        return module * limite if module else None

    A = sect["aire_m2"]
    return {
        "compression": produit(A, fyd),          # 6.2.4 (section seule)
        "traction": produit(A, fyd),             # 6.2.3
        "flexion_yy": produit(Wy, fyd),          # 6.2.5
        "flexion_zz": produit(Wz, fyd),          # 6.2.5
        "torsion": produit(sect.get("Wt"), tyd),  # 6.2.7
        "cisaillement_y": produit(sect.get("Avy"), tyd),   # 6.2.6
        "cisaillement_z": produit(sect.get("Avz"), tyd),   # 6.2.6
    }


# --------------------------------------------------------------------------
#  Lecture du grand tableau
# --------------------------------------------------------------------------
def colonnes_par_composante(entete: list[str]) -> dict[str, list[tuple[int, str]]]:
    """{composante: [(index de colonne, libelle de permutation)]}."""
    idx: dict[str, list[tuple[int, str]]] = {c: [] for c in COMPOSANTES}
    for i, nom in enumerate(entete):
        if not nom.startswith("perm"):
            continue
        tete, _, comp = nom.rpartition("_")
        if comp in idx:
            idx[comp].append((i, tete))
    return idx


def extremes(ligne: list[str], colonnes: list[tuple[int, str]]) -> tuple:
    """(max signe, libelle) et (min signe, libelle) sur toutes les permutations."""
    vmax = vmin = None
    lmax = lmin = ""
    for i, lib in colonnes:
        s = ligne[i]
        if not s:
            continue
        v = float(s)
        if vmax is None or v > vmax:
            vmax, lmax = v, lib
        if vmin is None or v < vmin:
            vmin, lmin = v, lib
    return (vmax or 0.0, lmax), (vmin or 0.0, lmin)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modele", default=str(MODELE_DEFAUT), help="fichier .gwb")
    ap.add_argument("--entree", default=str(RESULTATS / "canopee_elu_permutations.csv"))
    ap.add_argument("--sortie", default=str(RESULTATS / "canopee_elu_ec3.csv"))
    ap.add_argument("--gamma-m0", type=float, default=1.0,
                    help="coefficient partiel gamma_M0 (defaut 1.0)")
    ap.add_argument("--fy-mpa", type=float, default=None,
                    help="force fy pour TOUTES les sections (defaut : nuance du modele)")
    ap.add_argument("--plastique", action="store_true",
                    help="moment resistant plastique Wpl (defaut : elastique Wel)")
    ap.add_argument("--av", choices=("ec3", "gsa"), default="ec3",
                    help="aire de cisaillement : formules EC3 6.2.6 (defaut) ou "
                         "K x A de GSA (facteur de Timoshenko, hors EC3)")
    ap.add_argument("--separateur", default=",", help="separateur de colonnes (defaut ',')")
    args = ap.parse_args()

    entree = Path(args.entree)
    if not entree.exists():
        print(f"erreur : {entree} est introuvable "
              "(lancer d'abord canopee_elu_permutations.py)")
        return 1

    chrono = Chrono()
    print("Taux d'utilisation EC3 (resistance de section, EN 1993-1-1 6.2)")
    print("=" * 70)

    # --- proprietes de section, depuis le modele -------------------------
    # aucune analyse GSA ici : les efforts viennent du CSV, on n'a besoin que
    # des tables Sections / Materials
    sections = charger_sections(Path(args.modele), args.fy_mpa, args.av)
    chrono.top(f"lecture des {len(sections)} sections acier")

    nuances = sorted({s["fy_Pa"] for s in sections.values() if s["fy_Pa"]})
    print(f"  fy : {', '.join(f'{f / 1e6:.0f} MPa' for f in nuances)}"
          + ("  (force par --fy-mpa)" if args.fy_mpa else "  (nuances du modele)"))
    print(f"  moment resistant : {'PLASTIQUE (Wpl)' if args.plastique else 'ELASTIQUE (Wel)'}"
          f"   gamma_M0 = {args.gamma_m0}")
    print(f"  module de torsion Wt : GSA (Section.Properties().C)")
    print("  aire de cisaillement Av : " + ("formules EC3 6.2.6" if args.av == "ec3"
          else "K x A de GSA (Timoshenko — HORS EC3)"))

    inconnues = [s for s in sections.values() if s["forme"] is None]
    if inconnues:
        print(f"  ! {len(inconnues)} sections au profil non reconnu "
              "(cisaillement non calcule) :")
        for s in inconnues[:5]:
            print(f"      section {s['section']} : {s['profil']!r}")
    suspectes = [s for s in sections.values()
                 if s["ecart_aire"] is not None and s["ecart_aire"] > 0.05]
    if suspectes:
        print(f"  ! {len(suspectes)} sections dont l'aire recalculee s'ecarte "
              ">5% de celle de GSA :")
        for s in suspectes[:5]:
            print(f"      section {s['section']} : {s['profil']!r} "
                  f"ecart {s['ecart_aire']:.1%}")

    # --- balayage du grand tableau ---------------------------------------
    with entree.open(encoding="utf-8-sig", newline="") as f:
        tete = f.readline()
        sep = ";" if tete.count(";") > tete.count(",") else ","
        f.seek(0)
        lecteur = csv.reader(f, delimiter=sep)
        entete = next(lecteur)
        col = {n: i for i, n in enumerate(entete)}
        idx = colonnes_par_composante(entete)
        nb_perm = len(idx["Fx"])
        print(f"  {entree.name} : {nb_perm} permutations x {len(COMPOSANTES)} composantes")

        # {element: {composante: (max, lib, pos) / (min, lib, pos)}}
        agr: dict[int, dict] = {}
        info: dict[int, dict] = {}
        for ligne in lecteur:
            eid = int(ligne[col["element"]])
            pos = float(ligne[col["pos_pct"]])
            if eid not in agr:
                agr[eid] = {c: {"max": (0.0, "", 0.0), "min": (0.0, "", 0.0)}
                            for c in COMPOSANTES}
                info[eid] = {k: ligne[col[k]] for k in
                             ("type", "section", "nom_section", "profil", "longueur_m")}
            a = agr[eid]
            for c in COMPOSANTES:
                (vx, lx), (vn, ln) = extremes(ligne, idx[c])
                if vx > a[c]["max"][0]:
                    a[c]["max"] = (vx, lx, pos)
                if vn < a[c]["min"][0]:
                    a[c]["min"] = (vn, ln, pos)
    chrono.top(f"balayage de {len(agr)} barres x {nb_perm} permutations")

    # --- taux --------------------------------------------------------------
    def pire(a, c):
        """Extreme de plus grande amplitude d'une composante : (valeur, lib, pos)."""
        return max(a[c]["max"], a[c]["min"], key=lambda t: abs(t[0]))

    lignes = []
    sans_fy = 0
    for eid in sorted(agr):
        a, i = agr[eid], info[eid]
        s = sections.get(int(i["section"]))
        if not s or not s["fy_Pa"]:
            sans_fy += 1
            continue
        R = resistances(s, args.gamma_m0, args.plastique)

        def taux(valeur, resistance):
            if not resistance or resistance <= 0:
                return None
            return abs(valeur) / resistance

        # compression = extreme NEGATIF de Fx ; traction = extreme POSITIF
        n_comp, l_comp, p_comp = a["Fx"]["min"]
        n_trac, l_trac, p_trac = a["Fx"]["max"]
        m_yy = pire(a, "Myy")
        m_zz = pire(a, "Mzz")
        t_tor = pire(a, "Mxx")
        v_y = pire(a, "Fy")
        v_z = pire(a, "Fz")

        valeurs = {
            "compression": (min(n_comp, 0.0), l_comp, p_comp,
                            taux(min(n_comp, 0.0), R["compression"])),
            "traction": (max(n_trac, 0.0), l_trac, p_trac,
                         taux(max(n_trac, 0.0), R["traction"])),
            "flexion_yy": (*m_yy, taux(m_yy[0], R["flexion_yy"])),
            "flexion_zz": (*m_zz, taux(m_zz[0], R["flexion_zz"])),
            "torsion": (*t_tor, taux(t_tor[0], R["torsion"])),
            "cisaillement_y": (*v_y, taux(v_y[0], R["cisaillement_y"])),
            "cisaillement_z": (*v_z, taux(v_z[0], R["cisaillement_z"])),
        }

        row = {"element": eid, **i, "forme": s["forme"],
               "fy_MPa": round(s["fy_Pa"] / 1e6), "aire_m2": s["aire_m2"]}
        for nom, _ in CRITERES:
            v, lib, pos, t = valeurs[nom]
            row[f"taux_{nom}"] = "" if t is None else f"{t:.4f}"
            row[f"{nom}_valeur"] = f"{v:.6g}"
            row[f"{nom}_perm"] = lib
            row[f"{nom}_pos_pct"] = pos
        connus = {n: valeurs[n][3] for n, _ in CRITERES if valeurs[n][3] is not None}
        if connus:
            pirecrit = max(connus, key=connus.get)
            row["taux_max"] = f"{connus[pirecrit]:.4f}"
            row["critere_max"] = pirecrit
        else:
            row["taux_max"] = ""
            row["critere_max"] = ""
        lignes.append(row)

    if sans_fy:
        print(f"  ! {sans_fy} barres ecartees (nuance d'acier non identifiee)")

    # --- ecriture ----------------------------------------------------------
    entete_out = ["element", "type", "section", "nom_section", "profil", "forme",
                  "longueur_m", "aire_m2", "fy_MPa"]
    for nom, _ in CRITERES:
        entete_out += [f"taux_{nom}", f"{nom}_valeur", f"{nom}_perm", f"{nom}_pos_pct"]
    entete_out += ["taux_max", "critere_max"]

    sortie = Path(args.sortie)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    with sortie.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=entete_out, delimiter=args.separateur)
        w.writeheader()
        w.writerows(lignes)
    chrono.top(f"calcul des taux + ecriture ({len(lignes)} barres)")

    # --- apercu ------------------------------------------------------------
    print("-" * 70)
    print(f"  -> {sortie}  ({len(lignes)} barres x {len(entete_out)} colonnes)")
    par_critere: dict[str, int] = {}
    for r in lignes:
        if r["critere_max"]:
            par_critere[r["critere_max"]] = par_critere.get(r["critere_max"], 0) + 1
    print("  critere le plus sollicitant, par nombre de barres :")
    for c, n in sorted(par_critere.items(), key=lambda x: -x[1]):
        print(f"      {c:<16} {n:>4} barres")
    depasse = [r for r in lignes if r["taux_max"] and float(r["taux_max"]) > 1.0]
    print(f"  barres dont un taux de section depasse 1.0 : {len(depasse)}")
    print("=" * 70)
    print(chrono.resume())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
