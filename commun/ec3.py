# -*- coding: utf-8 -*-
"""Resistances de section EC3 (EN 1993-1-1 6.2) — SEULE implementation.

Module de calcul partage, au meme titre que `dimensionnant.contrainte_combinee`
pour les contraintes combinees C1/C2 : tout ce qui a besoin d'une resistance
EC3 passe par ici, pour qu'aucune formule ne puisse diverger d'un appelant a
l'autre.

  - `tests/scripts/canopee_elu_ec3.py`     tableau des 7 taux par barre ;
  - `tests/scripts/canopee_elu_matrice.py` carte barres x permutations ;
  - `tests/scripts/elu2_diagnostic_barre.py` diagnostic pas-a-pas sur une seule barre ;
  - `app_old/server.py`                onglet Performances v2 (meme carte, en ligne).

Criteres — RESISTANCE DE SECTION uniquement :
  compression     6.2.4  |N|/(A fy/gM0)                 N < 0
  traction        6.2.3   N /(A fy/gM0)                 N > 0
  flexion_yy      6.2.5  |Myy|/(Wy fy/gM0)
  flexion_zz      6.2.5  |Mzz|/(Wz fy/gM0)
  torsion         6.2.7  (|T|/Wt)/(fy/racine(3)/gM0)
  cisaillement_y  6.2.6  |Fy|/(Avy (fy/racine(3))/gM0)
  cisaillement_z  6.2.6  |Fz|/(Avz (fy/racine(3))/gM0)

CE QUE CE MODULE NE FAIT PAS — a lire avant d'exploiter les taux :
  - AUCUN flambement (6.3.1), deversement (6.3.2) ni flambement par torsion :
    ce sont des verifications d'ELEMENT, qui exigent des longueurs de flambement
    absentes du modele. Le taux de compression est donc une borne INFERIEURE du
    taux reel. Pour la stabilite, le projet a deux implementations equivalentes :
    `commun/stabilite_ec3/` (Python, ~2.10^4 fois plus rapide — c'est le moteur
    d'appv2 depuis le 01/09/2026) et le classeur Predim
    (`commun/excel_bridge/stabilite.py`, qui reste l'oracle du test) —
    cf. `tests/scripts/comparaison_stabilite_excel_python.py`.
  - AUCUNE interaction entre efforts (6.2.1(7), 6.2.9 M+N, 6.2.10 M+V...) :
    les 7 taux sont independants, chacun sur SA permutation gouvernante, qui
    n'est en general pas la meme. Leur maximum n'est pas un taux d'ensemble.
  - AUCUNE classification de section (tableau 5.2) : le moment resistant est
    pris ELASTIQUE (Wel) par defaut, valable et conservatif pour les classes
    1 a 3. `plastique=True` bascule sur Wpl (classes 1 et 2 seulement).
  - fy sans reduction pour les fortes epaisseurs (tableau 3.1).
"""
from __future__ import annotations

import math
import re
from pathlib import Path

RACINE3 = math.sqrt(3.0)

# 7 criteres : (nom, composante du torseur qui le pilote)
CRITERES = (("compression", "Fx"), ("traction", "Fx"),
            ("flexion_yy", "Myy"), ("flexion_zz", "Mzz"),
            ("torsion", "Mxx"),
            ("cisaillement_y", "Fy"), ("cisaillement_z", "Fz"))
COMPOSANTES = ("Fx", "Fy", "Fz", "Mxx", "Myy", "Mzz")
NOMS_CRITERES = [nom for nom, _ in CRITERES]

# index de la composante qui alimente chaque critere DANS `COMPOSANTES`
# (l'ordre des 6 colonnes du torseur, cf. gsa_bridge.permutations)
INDEX_COMPOSANTE = {nom: COMPOSANTES.index(comp) for nom, comp in CRITERES}

# teinte pleine (taux = 1) de chaque critere. Definie ICI et publiee a la page
# par l'API (cf. app_old/server.py) : la carte de l'onglet Performances v2 et les
# images de `tests/canopee_elu_matrice.py` gardent ainsi les memes couleurs.
COULEURS = {
    "compression": (0, 60, 255),        # bleu
    "traction": (230, 0, 0),            # rouge
    "flexion_yy": (245, 205, 0),        # jaune
    "flexion_zz": (145, 0, 200),        # violet
    "torsion": (0, 190, 200),           # cyan
    "cisaillement_y": (0, 150, 40),     # vert
    "cisaillement_z": (255, 130, 0),    # orange
}


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
#  de profil. `source_av="gsa"` bascule sur K x A si l'on veut malgre tout la
#  valeur GSA (ce n'est alors plus la verification de l'EC3).
# --------------------------------------------------------------------------
def _nombre(s: str) -> float:
    """'323,9' ou '323.9' -> 323.9. GSA saisi a la main (sections 'STD ...')
    utilise parfois la virgule decimale francaise ; le catalogue ('CAT ...')
    utilise toujours le point. Les deux se rencontrent dans le meme modele
    (ex. le gymnase, dont les 'STD CHS 323,9 5,4' etaient jusqu'ici illisibles)."""
    return float(s.replace(",", "."))


def geometrie(profil: str) -> dict | None:
    """{forme, h, b, t, d} en metres, ou None si le profil n'est pas reconnu.

    'STD RHS 200 120 10 10'          -> tube rectangulaire h x b, paroi t
    'STD CHS 323,9 5,4'              -> tube circulaire d x t (virgule ou point)
    'STD C 40'                       -> rond PLEIN de diametre d
    'CAT EN-CHS CHS610x20.0 ...'     -> tube circulaire d x t (forme catalogue)
    'CAT EN-RHS RHS200x100x5 ...'    -> tube rectangulaire (forme catalogue)
    'CAT EN-SHS SHS70x70x3 ...'      -> tube carre (forme catalogue)

    Les deux ecritures coexistent dans les modeles du projet : GSA stocke
    'STD RHS h b t t' / 'STD CHS d t' pour une section saisie a la main
    (virgule decimale possible) mais 'CAT EN-RHS RHS200x100x5' pour une
    section prise dans un catalogue (point toujours) — donc pour tout ce que
    produisent `catalogues/` et l'optimisation. Ne reconnaitre qu'une seule
    des deux ferait disparaitre silencieusement les criteres de cisaillement
    sur les modeles qui utilisent l'autre.

    Les profils en I (IPE, HE...), en U ouvert ('STD CH ...') et les
    cornieres ('STD A ...') ne sont PAS reconnus : leur aire de cisaillement
    EC3 depend d'une geometrie (rayon de raccordement, section ouverte) que
    la chaine de profil ne donne pas assez pour reconstruire simplement. Les
    criteres de cisaillement restent alors indisponibles (compression,
    traction, flexion, torsion restent calcules : ils ne dependent que de
    l'aire et des modules, deja fournis par GSA).
    """
    p = (profil or "").strip()

    m = re.match(r"STD\s+RHS\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)", p, re.I)
    if m:
        h, b, t1, t2 = (_nombre(x) / 1000.0 for x in m.groups())
        return {"forme": "RHS", "h": h, "b": b, "t": min(t1, t2), "d": None}

    # 'STD CHS d t' : saisie a la main, DEUX nombres (RHS en a quatre) — a
    # tester avant le motif catalogue ci-dessous, qui matcherait aussi 'CHS'
    m = re.match(r"STD\s+CHS\s+([\d.,]+)\s+([\d.,]+)\s*$", p, re.I)
    if m:
        d, t = (_nombre(x) / 1000.0 for x in m.groups())
        return {"forme": "CHS", "h": d, "b": d, "t": t, "d": d}

    m = re.search(r"CHS\s*([\d.]+)\s*x\s*([\d.]+)", p, re.I)
    if m:
        d, t = (float(x) / 1000.0 for x in m.groups())
        return {"forme": "CHS", "h": d, "b": d, "t": t, "d": d}

    # forme catalogue : RHS200x100x5, SHS70x70x3, RHS50x30x2.6
    m = re.search(r"(?:RHS|SHS)\s*([\d.]+)\s*x\s*([\d.]+)\s*x\s*([\d.]+)", p, re.I)
    if m:
        h, b, t = (float(x) / 1000.0 for x in m.groups())
        return {"forme": "RHS", "h": h, "b": b, "t": t, "d": None}

    m = re.match(r"STD\s+C\s+([\d.,]+)\s*$", p, re.I)
    if m:
        d = _nombre(m.group(1)) / 1000.0
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


def sections_acier(m, fy_Pa: float | None = None,
                   source_av: str = "gsa") -> dict[int, dict]:
    """{id section: caracteristiques} pour les sections ACIER d'un modele OUVERT.

    Aucune analyse GSA : seules les tables Sections / Materials sont lues.
    Chaque entree porte, en plus des champs du pont, `forme`, `Avy`, `Avz`,
    `Wt`, `ecart_aire` et `fy_Pa`.

    `fy_Pa` force une limite elastique UNIQUE pour toutes les sections (c'est
    ce que fait l'app, dont le critere de contrainte porte un fy unique
    editable — cf. config/dimensionnement.json) ; None lit la nuance du modele
    section par section (S355 -> 355 MPa), ce que font les scripts d'etude.

    `source_av` (defaut "gsa") : source des aires de cisaillement Avy/Avz.
    "gsa" = facteurs Timoshenko (Kyy, Kzz) × aire (recommande).
    "ec3" = recalcul depuis la geometrie du profil selon EC3 6.2.6(3).
    """
    fy_mat = fy_des_materiaux(m)
    sections = {}
    for s in m.sections():
        if s["materiau"] != "STEEL":
            continue
        car = caracteristiques(s, source_av)
        fy = fy_Pa if fy_Pa else fy_mat.get(s["materiau_grade"])
        sections[s["section"]] = {**s, **car, "fy_Pa": fy}
    return sections


def charger_sections(modele: Path, fy_mpa: float | None = None,
                     source_av: str = "gsa") -> dict[int, dict]:
    """`sections_acier` sur un modele a OUVRIR (scripts en ligne de commande).

    L'app, qui tient deja un modele ouvert, appelle `sections_acier`
    directement plutot que de rouvrir une copie de travail.
    """
    from commun.gsa_bridge.bridge import GsaModel

    m = GsaModel(modele)
    try:
        return sections_acier(m, fy_mpa * 1e6 if fy_mpa else None, source_av)
    finally:
        m.close()


def resistances(sect: dict, gamma_m0: float = 1.0,
                plastique: bool = False) -> dict[str, float | None]:
    """Resistances de section EC3 6.2, par critere (None si non calculable).

    Point unique de definition des resistances (cf. en-tete du module) : le
    tableau de taux, la carte coloree et l'onglet Performances v2 passent tous
    par ici.
    """
    fy = sect.get("fy_Pa")
    if not fy:
        return {nom: None for nom in NOMS_CRITERES}
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
