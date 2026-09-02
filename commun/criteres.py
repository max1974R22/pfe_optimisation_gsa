# -*- coding: utf-8 -*-
"""Les QUATRE criteres ELU compares par appv2, barre par barre.

appv2 ne cherche plus « la » permutation dimensionnante d'un seul critere (ce
que fait l'onglet Performances v2 d'`app_old/`, cf. `commun/dimensionnant.py`) mais
la permutation dimensionnante de CHACUN de quatre criteres, pour que la page
puisse changer d'avis sans recalculer : l'utilisateur coche/decoche torsion,
cisaillement et von Mises, et le critere retenu (celui de taux maximal parmi
ceux coches) est recalcule instantanement cote page.

    combine        max(|C1|, |C2|) / fy       contrainte normale combinee
                                              A = N/aire, B = |Myy|/Wy + |Mzz|/Wz,
                                              C1/C2 = A +- B (cf.
                                              `dimensionnant.contraintes_c1_c2`) ;
                                              Wy/Wz = module PLASTIQUE en classe
                                              1 et 2, ELASTIQUE en classe 3
                                              (EC3 §5.5, cf. `_classe_combine`
                                              ci-dessous) ; classe 4 REJETEE
                                              (indisponible, comme un profil non
                                              reconnu — pas de modules efficaces
                                              EN 1993-1-5 implementes ici)
    torsion        (|Mxx|/Wt) / (fy/racine3)  EC3 6.2.7, depuis les EFFORTS
    cisaillement   max(|Fy|/Avy, |Fz|/Avz)    EC3 6.2.6, depuis les EFFORTS ;
                   / (fy/racine3)             UN critere, deux axes — la ligne
                                              dit lequel gouverne
    von_mises      VM_gsa / fy                contrainte equivalente de von
                                              Mises LUE DANS GSA
                                              (`Element1dDerivedStress`), pas
                                              reconstruite depuis le torseur

POURQUOI von Mises vient de GSA et les trois autres des efforts. Les criteres
de section EC3 (combine, torsion, cisaillement) sont des taux d'effort sur
resistance : ils se calculent exactement depuis le torseur et les
caracteristiques de section (cf. `ec3.resistances`, seule implementation). La
contrainte equivalente de von Mises, elle, est une contrainte EN UN POINT de la
section : elle depend de la fibre consideree et du cisaillement de flexion, que
le torseur seul ne localise pas. GSA la calcule sur la geometrie reelle de la
section — on la lit donc telle quelle (`VonMisesStress`), ce qui la rend
directement comparable au von Mises affiche dans GSA.

Consequence a garder en tete : von Mises (elastique, cote GSA) et le critere
combine (module plastique) ne partagent pas la meme base. Sur un profil creux
circulaire le facteur de forme Wpl/Wel vaut ~1,3 : le von Mises de GSA peut
depasser le taux combine de ~30 % en flexion pure, sans qu'aucun cisaillement
n'intervienne. Ce n'est pas une incoherence de calcul, c'est la difference
entre une resistance de SECTION (plastification complete admise) et une
contrainte en un POINT.

CE QUE CE MODULE NE FAIT PAS : aucune verification de STABILITE (flambement
6.3.1, deversement 6.3.2) — comme `ec3.py`, il s'arrete a la resistance de
SECTION. Ce n'est pas un manque du projet : la stabilite EC3 §6.3 existe, mais
ailleurs, et sous DEUX formes qui donnent le meme resultat a coefficients
egaux (verifie a 0,0000 % sur 51 barres et 3 modeles, cf.
`tests/scripts/comparaison_stabilite_excel_python.py`) —

    commun/stabilite_ec3/              en Python pur : c'est ce qu'appv2 utilise
                                       depuis le 01/09/2026. Calcule en plus les
                                       coefficients C1/C2 du moment critique de
                                       deversement et la classe de section
    commun/excel_bridge/stabilite.py   le classeur Predim pilote par COM ; plus
                                       branche dans l'app, mais toujours l'oracle
                                       du test de comparaison

L'onglet Performances d'appv2 affiche donc bien une colonne « Taux stabilite »
a cote des quatre criteres de ce module ; les deux familles de criteres restent
independantes (l'une porte sur la SECTION, l'autre sur l'ELEMENT).
"""
from __future__ import annotations

import numpy as np

from dimensionnant import contraintes_c1_c2
from dimensionner import DimensionnementError
from ec3 import RACINE3

from commun.stabilite_ec3._commun import Torseur
from commun.stabilite_ec3.classe_section import classe_section
from commun.stabilite_ec3.section_catalogue import (
    SectionInconnue, profil_predim, section_catalogue)

# ordre des 6 colonnes du torseur (cf. gsa_bridge.permutations.COMPOSANTES)
I_FX, I_FY, I_FZ, I_MXX, I_MYY, I_MZZ = 0, 1, 2, 3, 4, 5
# ordre des 4 colonnes des contraintes derivees (cf. COMPOSANTES_DERIVEES)
I_SEY, I_SEZ, I_ST, I_VM = 0, 1, 2, 3

# les 4 criteres, dans l'ordre d'affichage. `combine` est TOUJOURS actif (c'est
# la reference) ; les trois autres sont des cases a cocher de la page.
CRITERES = ("combine", "torsion", "cisaillement", "von_mises")
LIBELLES = {"combine": "combiné", "torsion": "torsion",
            "cisaillement": "cisaillement", "von_mises": "von Mises"}
# critere qui ne peut pas etre decoche : sans lui il n'y a plus de reference
CRITERE_BASE = "combine"


def _classe_combine(sect: dict, N_N: float, My_Nm: float, Mz_Nm: float) -> int | None:
    """Classe EC3 §5.5 (Tableau 5.2) de `sect` sous le torseur (N, My, Mz, en
    SI — N, N.m) d'UNE case (permutation, position) precise.

    None si la classe est indeterminable : profil non transposable vers une
    designation catalogue (`profil_predim`, meme repli que la stabilite pour
    un profil 'STD ...' saisi a la main — cf. son docstring), designation
    absente du catalogue de sa famille, ou geometrie degeneree. Le critere
    `combine` traite ce None exactement comme une classe 4 : rejete plutot que
    calcule avec une hypothese non verifiee sur le module de flexion.

    Reutilise le catalogue de `commun/stabilite_ec3` (meme geometrie que la
    stabilite, cf. `commun/stabilite_ec3/section_catalogue.py`) UNIQUEMENT pour
    la geometrie (h/b/tw/tf/r/Iy/Iz) necessaire a la classification — les
    modules Wpl/Wel effectivement utilises dans le critere restent ceux lus
    dans GSA (`sect["Zpy_m3"]` etc.), pas ceux du catalogue, pour ne pas
    introduire une deuxieme source de la meme grandeur."""
    fy_Pa = sect.get("fy_Pa")
    if not fy_Pa:
        return None
    try:
        feuille, nom, _ = profil_predim(sect.get("profil", ""))
        section, _, _ = section_catalogue(feuille, nom)
        torseur = Torseur(N_Ed_kN=N_N / 1000.0, My_Ed_kNm=My_Nm / 1000.0,
                          Mz_Ed_kNm=Mz_Nm / 1000.0)
        return classe_section(section, torseur, fy_Pa / 1e6)["classe"]
    except (DimensionnementError, SectionInconnue):
        return None
    except Exception:                                             # noqa: BLE001
        # geometrie catalogue degeneree (division par une cote nulle...) :
        # meme traitement qu'une classe indeterminable, pas un plantage de la
        # page — coherent avec `commun/stabilite_ec3/session.py::verifier_barre`,
        # qui degrade de la meme facon toute erreur inattendue.
        return None


def taux_par_permutation(efforts: np.ndarray, derivees: np.ndarray | None,
                         sect: dict) -> dict[str, np.ndarray | None]:
    """{critere: tableau (permutation, position) de taux} — None si incalculable.

    `efforts` : (permutation, position, 6) de
    `permutations.efforts_par_permutation`, unites SI.
    `derivees` : (permutation, position, 4) de
    `permutations.contraintes_derivees_par_permutation`, en Pa — None si non
    extraites (le critere von Mises est alors indisponible).
    `sect` : une entree de `ec3.sections_acier` (aire_m2, Zpy_m3/Zpz_m3, Wt,
    Avy, Avz, fy_Pa).

    Une case = UNE permutation a UNE position : les composantes qui y sont
    combinees coexistent physiquement (c'est tout l'objet de la lecture non
    reduite, cf. `commun/dimensionnant.py`). Le cisaillement expose en plus ses
    deux axes separement, sous les cles `cisaillement_y`/`cisaillement_z`, pour
    que la ligne puisse dire lequel gouverne.
    """
    fy = sect.get("fy_Pa")
    aire, wpl_y, wpl_z = sect.get("aire_m2"), sect.get("Zpy_m3"), sect.get("Zpz_m3")
    out: dict[str, np.ndarray | None] = {c: None for c in CRITERES}
    out["cisaillement_y"] = out["cisaillement_z"] = None
    if not fy or efforts.size == 0:
        return out
    e = np.nan_to_num(efforts)
    tyd = fy / RACINE3                     # limite de cisaillement (von Mises)

    if aire and wpl_y and wpl_z:
        # 1ere passe, TOUJOURS avec Wpl (le cas le plus courant, classe 1/2) :
        # sert a localiser la case (permutation, position) gouvernante, dont
        # le torseur decide de la classe EC3 §5.5 — la classification depend
        # de N/My/Mz, donc de LA case, pas de la section seule (cf.
        # `_classe_combine`).
        c1, c2 = contraintes_c1_c2(efforts, aire, wpl_y, wpl_z)
        ip, ipos, _ = _argmax_2d(np.maximum(c1, -c2))
        classe = _classe_combine(sect, float(e[ip, ipos, I_FX]),
                                 float(e[ip, ipos, I_MYY]), float(e[ip, ipos, I_MZZ]))
        if classe == 3:
            # W elastique, PAS plastique — grille entierement recalculee (la
            # case gouvernante peut changer : Wel ne remet pas a l'echelle A
            # et B dans les memes proportions que Wpl, cf. la formule de
            # `contraintes_c1_c2`)
            wel_y, wel_z = sect.get("Zy_m3"), sect.get("Zz_m3")
            if wel_y and wel_z:
                c1, c2 = contraintes_c1_c2(efforts, aire, wel_y, wel_z)
            else:
                classe = None                  # Wel absent : indisponible
        if classe not in (None, 4):
            # classe 1 ou 2 (Wpl, 1ere passe inchangee) ou 3 (Wel, recalculee) —
            # une classe 4, ou indeterminable (None), REJETTE le critere pour
            # l'instant (pas de modules efficaces EN 1993-1-5 ici) : `out`
            # reste a None, comme tout critere incalculable
            out["combine"] = np.maximum(c1, -c2) / fy      # = max(|C1|,|C2|)/fy
            # C1 (max signe) / C2 (min signe), conservees pour determiner, dans
            # critere_dimensionnant, si c'est la fibre tendue (C1) ou comprimee
            # (C2) qui gouverne a la case retenue — cf. "signe"
            out["combine_c1"], out["combine_c2"] = c1, c2

    wt = sect.get("Wt")
    if wt:
        out["torsion"] = np.abs(e[:, :, I_MXX]) / wt / tyd

    for cle, i_comp, cle_av in (("cisaillement_y", I_FY, "Avy"),
                                ("cisaillement_z", I_FZ, "Avz")):
        av = sect.get(cle_av)
        if av:
            out[cle] = np.abs(e[:, :, i_comp]) / av / tyd
    axes = [out["cisaillement_y"], out["cisaillement_z"]]
    axes = [a for a in axes if a is not None]
    if axes:
        out["cisaillement"] = axes[0] if len(axes) == 1 else np.maximum(*axes)

    if derivees is not None and derivees.shape[:2] == efforts.shape[:2]:
        out["von_mises"] = np.abs(np.nan_to_num(derivees[:, :, I_VM])) / fy

    return out


def _argmax_2d(t: np.ndarray) -> tuple[int, int, float]:
    """(permutation, position, valeur) du maximum d'un tableau (nperm, npos)."""
    plat = int(np.argmax(t))
    ip, ipos = divmod(plat, t.shape[1])
    return ip, ipos, float(t[ip, ipos])


def critere_dimensionnant(taux: dict[str, np.ndarray | None], critere: str,
                          efforts: np.ndarray,
                          derivees: np.ndarray | None) -> dict | None:
    """Case (permutation, position) qui maximise UN critere, et son contenu.

    Renvoie None si le critere n'est pas calculable sur cette barre (aire de
    cisaillement inconnue sur un profil non reconnu, module de torsion absent,
    contraintes derivees non lues...) — la page affichera « – » plutot qu'un
    zero trompeur.

    Le dict rendu porte l'index de permutation et de position (0-based, a
    etiqueter par l'appelant), le taux, le TORSEUR complet de cette case exacte
    (6 composantes SI, qui coexistent donc) et, quand ils s'appliquent, le
    detail propre au critere : contraintes C1/C2 pour `combine`, contrainte de
    torsion et de cisaillement elastique pour les autres, von Mises de GSA.
    Pour `cisaillement`, `axe` dit lequel de y/z gouverne CETTE case. Pour
    `combine`, `signe` dit si c'est la fibre tendue (C1, "traction") ou
    comprimee (C2, "compression") qui gouverne CETTE case.
    """
    t = taux.get(critere)
    if t is None:
        return None
    ip, ipos, valeur = _argmax_2d(t)
    d = {"critere": critere, "perm": ip, "position": ipos, "taux": valeur,
         "efforts": np.nan_to_num(efforts[ip, ipos]).tolist()}
    if derivees is not None and derivees.shape[:2] == efforts.shape[:2]:
        v = np.nan_to_num(derivees[ip, ipos])
        d["St_Pa"] = float(v[I_ST])
        d["SEy_Pa"] = float(v[I_SEY])
        d["SEz_Pa"] = float(v[I_SEZ])
        d["VM_Pa"] = float(v[I_VM])
    if critere == "combine":
        c1_arr, c2_arr = taux.get("combine_c1"), taux.get("combine_c2")
        if c1_arr is not None and c2_arr is not None:
            c1v, c2v = float(c1_arr[ip, ipos]), float(c2_arr[ip, ipos])
            d["signe"] = "traction" if c1v >= -c2v else "compression"
            d["C1_Pa"], d["C2_Pa"] = c1v, c2v
    if critere == "cisaillement":
        ty, tz = taux.get("cisaillement_y"), taux.get("cisaillement_z")
        vy = float(ty[ip, ipos]) if ty is not None else -1.0
        vz = float(tz[ip, ipos]) if tz is not None else -1.0
        d["axe"] = "y" if vy >= vz else "z"
    return d


def criteres_dimensionnants(efforts: np.ndarray, derivees: np.ndarray | None,
                            sect: dict) -> dict[str, dict | None]:
    """{critere: case dimensionnante} pour les 4 criteres, en UNE passe.

    C'est la fonction que l'extraction d'appv2 appelle par barre. Le maximum
    d'un ENSEMBLE de criteres se deduit ensuite de ces quatre resultats sans
    revenir aux tableaux : max sur les cases du max sur les criteres = max sur
    les criteres du max sur les cases. La page peut donc cocher/decocher les
    criteres sans aucun recalcul serveur.
    """
    taux = taux_par_permutation(efforts, derivees, sect)
    return {c: critere_dimensionnant(taux, c, efforts, derivees) for c in CRITERES}
