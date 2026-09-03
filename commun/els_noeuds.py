# -*- coding: utf-8 -*-
"""Criteres ELS lus dans le MODELE, par le NOM des noeuds.

Remplace l'ancien critere de fleche du projet (|Uz| d'une barre <= L /
denominateur, une portee unique pour tout le modele) : celui-ci ne disait rien
d'un ouvrage reel, ou l'exigence de service porte sur des points precis
(rive de facade, appui de vitrage, faitiere...) et pas sur la barre la plus
flechie de la structure.

Desormais, c'est le modele qui porte les criteres : ils sont declares en
NOMMANT des noeuds dans GSA, et l'utilisateur ne renseigne que la direction
comparee et la limite en millimetres.

TROIS FAMILLES DE CRITERES
---------------------------
`ELS_glob_X`  — deplacement GLOBAL. Tous les noeuds portant ce nom (X = un
    indice libre, un chiffre en general : plusieurs criteres globaux
    differents peuvent coexister) doivent avoir un deplacement inferieur a la
    limite, dans la direction choisie. Exemple : « tous les noeuds
    ELS_glob_3 se deplacent de moins de 6 mm suivant z ».

`ELS_3pts_X`  — deplacement RELATIF A LA CORDE, sur TROIS noeuds portant le
    meme nom. Ce qui est compare a la limite n'est pas le deplacement absolu
    du point du milieu mais sa distance a sa projection sur la droite formee
    par les deux points d'extremite — la « fleche relative » : un porte-a-faux
    entier qui descend de 30 mm sans se deformer ne consomme rien de ce
    critere, alors qu'un ventre de 6 mm entre deux appuis eux-memes descendus
    de 30 mm le consomme entierement.

    Le milieu et les extremites sont identifies par la GEOMETRIE, pas par
    l'ordre de numerotation : les deux noeuds les plus eloignes l'un de
    l'autre sont les extremites, le troisieme est le milieu.

    La distance est mesuree DANS LA DIRECTION CHOISIE, a l'abscisse que le
    milieu occupe sur la corde NON DEFORMEE (t = projection orthogonale de C
    sur AB, dans [0, 1]) :

        ecart = u_d(C) - [ (1 - t) x u_d(A) + t x u_d(B) ]

    Prendre t sur la geometrie non deformee est le choix classique et le seul
    bien pose : en 3D, la projection d'un point sur une droite PARALLELEMENT a
    un axe est surdeterminee des que le point sort du plan (deux equations,
    une inconnue). Pour trois noeuds regulierement espaces, t = 0,5 et l'ecart
    redonne la fleche relative usuelle u_C - (u_A + u_B) / 2.

`ELS_drift_X` — deplacement RELATIF entre DEUX noeuds portant le meme nom :
    le drift inter-etage (« inner storey displacement »). Ce qui est compare
    a la limite n'est pas le deplacement absolu d'un plancher mais l'ECART
    entre les deplacements des deux planchers consecutifs, dans la direction
    choisie (typiquement horizontale, x ou y) :

        ecart = u_d(haut) - u_d(bas)

    Le HAUT et le BAS sont identifies par la cote z (le plus grand z est le
    haut) — PAS par l'ordre de numerotation des noeuds, meme parti pris que
    pour le milieu/les extremites d'un critere 3pts. La hauteur d'etage
    correspondante (|z_haut - z_bas|, en m) est calculee et exposee
    (`hauteur_etage_m`) a titre indicatif — le critere reste compare a
    `limite_mm` comme les deux autres familles (PAS un ratio h/xxx calcule
    automatiquement) : c'est a l'utilisateur d'y reporter la valeur en mm
    voulue (ex. hauteur d'etage / 300).

    Deux planchers qui se deplacent EXACTEMENT PAREIL (translation
    d'ensemble, aucun « racking » de l'etage) ne consomment rien de ce
    critere, contrairement a `ELS_glob_X` qui, applique separement a chacun,
    peut deja etre depasse alors que l'etage ne se deforme pas — c'est
    justement ce qu'un critere de drift ajoute par rapport a un deplacement
    absolu (cf. la discussion qui a precede ce module : un grand deplacement
    cumule en tete de structure peut masquer, ou a l'inverse un etage souple
    concentrer, une deformation relative dangereuse qu'un critere global ne
    voit pas).

TOUTES LES PERMUTATIONS
-----------------------
Les deplacements sont lus par PERMUTATION
(`deplacements_noeuds_par_permutation`), jamais sur l'enveloppe repliee
max/min de `GsaModel.node_displacements` : pour un critere 3 points, l'ecart
n'a de sens que si les trois deplacements viennent de la MEME
sous-combinaison — le max de u_C et le min de u_A peuvent venir de
combinaisons qui ne se produisent jamais ensemble. Meme parti pris que pour
l'ELU (cf. commun/gsa_bridge/permutations.py).

UTILISATION
-----------
    criteres = criteres_du_modele(m)                 # decouverte par les noms
    criteres = appliquer_reglages(criteres, reglages)  # direction + limite (page/config)
    resultats = evaluer(m._result("C48"), criteres, libelles)
"""
from __future__ import annotations

import math
import re

import numpy as np

from commun.gsa_bridge.permutations import deplacements_noeuds_par_permutation

# nom de noeud -> critere. X est un indice libre (un chiffre en pratique, mais
# rien n'interdit 'facade' ou '2b') : il distingue plusieurs criteres de la
# meme famille. Insensible a la casse — GSA n'impose rien sur la casse des noms
# de noeuds, et un modele reel melange 'ELS_glob_1' et 'els_glob_1'.
MOTIF = re.compile(r"^\s*ELS_(glob|3pts|drift)_(\S+?)\s*$", re.IGNORECASE)

TYPES = ("glob", "3pts", "drift")

# direction comparee : axe GLOBAL du modele (les deplacements nodaux sont lus
# sans axe de sortie, donc dans le repere global). Valeur -> indice de colonne
# dans les tableaux (Ux, Uy, Uz) de `deplacements_noeuds_par_permutation`.
DIRECTIONS = {"x": 0, "y": 1, "z": 2}

# limite par defaut d'un critere que l'utilisateur n'a pas encore reglé
LIMITE_DEFAUT_MM = 20.0
DIRECTION_DEFAUT = "z"


class ElsError(ValueError):
    """Critere ELS declare dans le modele mais inexploitable (nombre de noeuds
    incorrect, geometrie degeneree...)."""


# --------------------------------------------------------------- decouverte
def _milieu_et_extremites(pts: list[tuple[int, tuple[float, float, float]]]
                          ) -> tuple[int, list[int], float]:
    """(noeud du milieu, [noeuds d'extremite], t) pour un critere 3 points.

    Les EXTREMITES sont les deux noeuds les plus eloignes l'un de l'autre ; le
    troisieme est le milieu. `t` est l'abscisse relative du milieu sur la corde
    non deformee (projection orthogonale, bornee a [0, 1] pour rester une
    interpolation meme si le point sort du segment).
    """
    paires = [(math.dist(a[1], b[1]), i, j)
              for i, a in enumerate(pts) for j, b in enumerate(pts) if i < j]
    d_max, i, j = max(paires)
    if d_max <= 0:
        raise ElsError("les trois noeuds sont confondus : corde indeterminee")
    k = ({0, 1, 2} - {i, j}).pop()
    A, B, C = np.array(pts[i][1]), np.array(pts[j][1]), np.array(pts[k][1])
    ab = B - A
    t = float(np.dot(C - A, ab) / np.dot(ab, ab))
    return pts[k][0], [pts[i][0], pts[j][0]], min(max(t, 0.0), 1.0)


def _haut_bas(pts: list[tuple[int, tuple[float, float, float]]]
             ) -> tuple[int, int, float]:
    """(noeud du haut, noeud du bas, hauteur d'etage en m) pour un critere
    drift — le HAUT est le noeud de plus grande cote z (meme axe vertical que
    la direction par defaut de ELS_glob), le BAS l'autre. Leve `ElsError` si
    les deux noeuds sont a la meme cote z (hauteur d'etage nulle,
    indeterminee)."""
    (id1, p1), (id2, p2) = pts[0], pts[1]
    h = p1[2] - p2[2]
    if abs(h) <= 0:
        raise ElsError("les deux noeuds sont a la meme cote z : hauteur d'etage nulle")
    return (id1, id2, h) if h > 0 else (id2, id1, -h)


def criteres_du_modele(m) -> list[dict]:
    """Criteres ELS declares dans le modele, deduits des NOMS de ses noeuds.

    Un critere par nom rencontre, trie par type puis par indice. Chacun porte
    ses noeuds, la direction et la limite PAR DEFAUT (a remplacer par les
    reglages de l'utilisateur, cf. `appliquer_reglages`), et — pour un critere
    mal declare — un champ `probleme` explicatif plutot qu'une exception : un
    modele dont UN critere est bancal doit rester calculable sur les autres.
    """
    par_nom: dict[str, list] = {}
    for n in m.nodes():
        mo = MOTIF.match(str(n.get("nom") or ""))
        if mo is None:
            continue
        cle = f"ELS_{mo.group(1).lower()}_{mo.group(2)}"
        par_nom.setdefault(cle, []).append(
            (n["node"], (n["x"], n["y"], n["z"]), mo.group(1).lower(), mo.group(2)))

    criteres = []
    for nom, trouves in par_nom.items():
        type_, indice = trouves[0][2], trouves[0][3]
        noeuds = sorted(t[0] for t in trouves)
        c = {"nom": nom, "type": type_, "indice": indice, "noeuds": noeuds,
             "direction": DIRECTION_DEFAUT, "limite_mm": LIMITE_DEFAUT_MM,
             "actif": True, "probleme": None}
        if type_ == "3pts":
            if len(noeuds) != 3:
                c["probleme"] = (
                    f"Le nom {nom!r} est porté par {len(noeuds)} nœud(s) : un "
                    "critère 3 points en demande exactement 3 (deux extrémités "
                    "et un milieu).")
            else:
                try:
                    milieu, extremites, t = _milieu_et_extremites(
                        [(t_[0], t_[1]) for t_ in trouves])
                    c.update(milieu=milieu, extremites=extremites, t=round(t, 4))
                except ElsError as e:
                    c["probleme"] = f"{nom} : {e}"
        elif type_ == "drift":
            if len(noeuds) != 2:
                c["probleme"] = (
                    f"Le nom {nom!r} est porté par {len(noeuds)} nœud(s) : un "
                    "critère de drift inter-étage en demande exactement 2 "
                    "(les deux planchers consécutifs).")
            else:
                try:
                    haut, bas, h_m = _haut_bas([(t_[0], t_[1]) for t_ in trouves])
                    c.update(haut=haut, bas=bas, hauteur_etage_m=round(h_m, 4))
                except ElsError as e:
                    c["probleme"] = f"{nom} : {e}"
        criteres.append(c)
    criteres.sort(key=lambda c: (c["type"], _cle_indice(c["indice"])))
    return criteres


def _cle_indice(indice: str):
    """Tri naturel des indices : ELS_glob_2 avant ELS_glob_10, les indices non
    numeriques apres, par ordre alphabetique."""
    return (0, int(indice), "") if indice.isdigit() else (1, 0, indice.lower())


def reglages_config(cfg: dict) -> tuple[dict, dict]:
    """(reglages par critere, defauts) depuis cfg["critere_els"] de
    config/dimensionnement.json — pour les entrees SANS interface (CLI
    `commun/dimensionner.py`, algorithmes de `commun/algo_opti/`). L'interface
    web, elle, regle direction et limite a la main et n'y passe pas.

    Un fichier de configuration sans bloc `critere_els` (ou vide) laisse tous
    les criteres aux valeurs par defaut du module : le modele reste
    verifiable des qu'il porte des noeuds nommes, sans configuration prealable.
    """
    bloc = cfg.get("critere_els") or {}
    return (bloc.get("criteres") or {}), (bloc.get("defauts") or {})


def appliquer_reglages(criteres: list[dict], reglages: dict | None,
                       defauts: dict | None = None) -> list[dict]:
    """Reporte sur les criteres decouverts les reglages de l'utilisateur —
    {"ELS_glob_3": {"direction": "z", "limite_mm": 6, "actif": true}, ...}.

    `defauts` (facultatif) s'applique a TOUS les criteres avant les reglages
    nommes, qui le surchargent — cf. `reglages_config`.

    Un critere absent des reglages garde ses valeurs par defaut : la page ne
    renvoie que ce qu'elle affiche, et un modele rechargé peut porter de
    nouveaux noeuds nommes. Les valeurs invalides (direction inconnue, limite
    nulle ou negative) sont ignorees plutot que de faire echouer le calcul —
    la limite d'un critere reste alors celle par defaut.
    """
    par_nom = {str(k).strip().upper(): v for k, v in (reglages or {}).items()}
    for c in criteres:
        for r in (defauts, par_nom.get(c["nom"].upper())):
            if not isinstance(r, dict):
                continue
            d = str(r.get("direction") or "").strip().lower()
            if d in DIRECTIONS:
                c["direction"] = d
            try:
                lim = float(r.get("limite_mm"))
                if lim > 0:
                    c["limite_mm"] = lim
            except (TypeError, ValueError):
                pass
            if "actif" in r:
                c["actif"] = bool(r["actif"])
    return criteres


def selecteur(criteres: list[dict]) -> str:
    """Selecteur GSA ("12 45 78") des noeuds de tous les criteres exploitables
    — une seule lecture de resultats pour tous les criteres a la fois."""
    ids = sorted({n for c in criteres if exploitable(c) for n in c["noeuds"]})
    return " ".join(str(i) for i in ids)


def exploitable(c: dict) -> bool:
    """Critere actif, bien declare et pourvu de noeuds."""
    return bool(c.get("actif") and not c.get("probleme") and c.get("noeuds"))


# ---------------------------------------------------------------- evaluation
def _libelle(libelles: list[str] | None, ip: int) -> str:
    if libelles and ip < len(libelles):
        return libelles[ip]
    return f"perm{ip + 1:03d}"


def _evaluer_glob(c: dict, dep: dict[int, np.ndarray],
                  libelles: list[str] | None) -> dict | None:
    """Plus grand |u_d| parmi TOUS les noeuds du critere et TOUTES les
    permutations : c'est le noeud et la sous-combinaison qui gouvernent."""
    i = DIRECTIONS[c["direction"]]
    pire = None
    for nid in c["noeuds"]:
        a = dep.get(nid)
        if a is None or a.size == 0:
            continue
        u = a[:, i]
        fini = np.isfinite(u)
        if not fini.any():
            continue
        ip = int(np.argmax(np.where(fini, np.abs(u), -1.0)))
        v = abs(float(u[ip]))
        if pire is None or v > pire[0]:
            pire = (v, nid, ip)
    if pire is None:
        return None
    v, nid, ip = pire
    return {"valeur_mm": v * 1000.0, "noeud": nid, "perm": ip,
            "libelle": _libelle(libelles, ip)}


def _evaluer_3pts(c: dict, dep: dict[int, np.ndarray],
                  libelles: list[str] | None) -> dict | None:
    """Plus grand |ecart a la corde| sur toutes les permutations.

    Les trois deplacements sont pris DANS LA MEME permutation (c'est tout
    l'objet de la lecture non reduite) et combines a l'abscisse t du milieu sur
    la corde non deformee, cf. l'en-tete du module.
    """
    i = DIRECTIONS[c["direction"]]
    a, b = (dep.get(n) for n in c["extremites"])
    cm = dep.get(c["milieu"])
    if a is None or b is None or cm is None:
        return None
    n = min(a.shape[0], b.shape[0], cm.shape[0])
    if n == 0:
        return None
    t = c["t"]
    ecart = cm[:n, i] - ((1.0 - t) * a[:n, i] + t * b[:n, i])
    fini = np.isfinite(ecart)
    if not fini.any():
        return None
    ip = int(np.argmax(np.where(fini, np.abs(ecart), -1.0)))
    return {"valeur_mm": abs(float(ecart[ip])) * 1000.0, "noeud": c["milieu"],
            "perm": ip, "libelle": _libelle(libelles, ip)}


def _evaluer_drift(c: dict, dep: dict[int, np.ndarray],
                   libelles: list[str] | None) -> dict | None:
    """Plus grand |deplacement relatif haut - bas| sur toutes les
    permutations — le drift inter-etage, dans la direction choisie (une
    translation d'ensemble des deux planchers, meme grande, ne consomme rien
    du critere : seul l'ECART compte)."""
    i = DIRECTIONS[c["direction"]]
    haut, bas = dep.get(c["haut"]), dep.get(c["bas"])
    if haut is None or bas is None:
        return None
    n = min(haut.shape[0], bas.shape[0])
    if n == 0:
        return None
    ecart = haut[:n, i] - bas[:n, i]
    fini = np.isfinite(ecart)
    if not fini.any():
        return None
    ip = int(np.argmax(np.where(fini, np.abs(ecart), -1.0)))
    return {"valeur_mm": abs(float(ecart[ip])) * 1000.0, "noeud": c["haut"],
            "perm": ip, "libelle": _libelle(libelles, ip)}


def evaluer(resultat, criteres: list[dict],
            libelles: list[str] | None = None,
            coefficient: float = 1.0) -> list[dict]:
    """Verifie tous les criteres exploitables sous UNE combinaison ELS.

    `resultat` : CombinationCaseResult GSA (`GsaModel._result("C48")`).
    `libelles` : etiquettes des permutations de cette combinaison
    (`libelles_permutations`), pour nommer la sous-combinaison gouvernante —
    facultatif, on retombe sinon sur 'perm001'.
    `coefficient` : seuil de verdict (`ok`), comme pour l'ELU — 1.0 = pas de
    marge (le deplacement ne doit pas depasser la limite du noeud), 0.9 =
    dimensionner a 90 % de cette limite.

    Une ligne par critere DECLARE (y compris ceux qui sont inactifs ou mal
    declares : la page doit pouvoir les montrer et dire pourquoi ils ne
    comptent pas), avec `valeur_mm`, `taux`, `ok`, le noeud et la
    sous-combinaison gouvernants. `taux`/`ok` sont None quand le critere n'a
    pas de resultat exploitable — jamais un zero trompeur.
    """
    sel = selecteur(criteres)
    dep = deplacements_noeuds_par_permutation(resultat, sel) if sel else {}
    lignes = []
    for c in criteres:
        ligne = {"nom": c["nom"], "type": c["type"], "direction": c["direction"],
                 "limite_mm": c["limite_mm"], "noeuds": list(c["noeuds"]),
                 "actif": bool(c.get("actif")), "probleme": c.get("probleme"),
                 "valeur_mm": None, "taux": None, "ok": None,
                 "noeud": None, "perm": None, "libelle": None}
        if c["type"] == "3pts":
            ligne["milieu"] = c.get("milieu")
            ligne["extremites"] = c.get("extremites")
        elif c["type"] == "drift":
            ligne["haut"] = c.get("haut")
            ligne["bas"] = c.get("bas")
            ligne["hauteur_etage_m"] = c.get("hauteur_etage_m")
        if exploitable(c):
            if c["type"] == "3pts":
                d = _evaluer_3pts(c, dep, libelles)
            elif c["type"] == "drift":
                d = _evaluer_drift(c, dep, libelles)
            else:
                d = _evaluer_glob(c, dep, libelles)
            if d is None:
                ligne["probleme"] = ("aucun deplacement exploitable sur ces "
                                     "noeuds sous cette combinaison")
            else:
                lim = c["limite_mm"]
                ligne.update(valeur_mm=round(d["valeur_mm"], 3),
                             taux=round(d["valeur_mm"] / lim, 4) if lim else None,
                             noeud=d["noeud"], perm=d["perm"] + 1,
                             libelle=d["libelle"])
                ligne["ok"] = ligne["taux"] is not None and ligne["taux"] <= coefficient
        lignes.append(ligne)
    return lignes


def taux_max(lignes: list[dict]) -> tuple[float | None, dict | None]:
    """(taux ELS retenu, ligne gouvernante) = le MAX des taux verifiables.

    (None, None) si aucun critere n'est exploitable — un modele SANS noeud
    nomme ELS_* n'a aucune exigence de service a verifier, ce n'est pas un
    echec (meme parti pris que l'ancienne colonne de fleche quand aucune
    combinaison ELS n'etait choisie)."""
    verifiables = [l for l in lignes if l.get("taux") is not None]
    if not verifiables:
        return None, None
    gouv = max(verifiables, key=lambda l: l["taux"])
    return gouv["taux"], gouv
