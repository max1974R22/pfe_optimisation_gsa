# -*- coding: utf-8 -*-
"""Calcul de la contrainte combinee C1/C2 depuis les efforts (N, Myy, Mzz) —
SEUL fichier ou cette formule (A = N/aire, B = |Myy|/Wpl_y + |Mzz|/Wpl_z,
C1 = A+B, C2 = A-B) est implementee, sous ses DEUX formes d'entree :

  - `contraintes_c1_c2`/`permutation_dimensionnante` : tableau NON reduit
    (permutation x position), pour trouver laquelle dimensionne reellement
    une barre — onglet Performances v2 (cf. section suivante) ;
  - `contrainte_combinee`/`amplitude_c1_c2` : lignes DEJA reduites (une valeur
    de N/Myy/Mzz par ligne — typiquement `beam_forces` max/min de
    `bridge._table_1d`), pour l'onglet Performances v1
    (`app_old/server.py::_perf_ligne`) et l'optimisation globale
    (`commun/algo_opti/_commun.py::evaluer_etat`).

Module de flexion : PLASTIQUE partout (Wpl_y/Wpl_z — `Zpy_m3`/`Zpz_m3` cote
sections GSA, `Wpl_y_m3`/`Wpl_z_m3` cote catalogue). L'ancienne variante au
module ELASTIQUE (`dimensionner.contrainte_combinee`) a ete supprimee : sur la
barre 2169 du gymnase, elle sous-estimait l'amplitude de flexion d'environ
23 % par rapport au module plastique (facteur de forme Wpl/Wel d'un CHS) —
plus de raison de garder deux formules pour la meme grandeur.

POURQUOI `contraintes_c1_c2`/`permutation_dimensionnante` EXISTENT EN PLUS DE
`contrainte_combinee`. Sur une combinaison enveloppe, `bridge._table_1d`
replie les permutations en deux lignes par position : le max signe de CHAQUE
composante, et le min. Le N, le Myy et le Mzz d'une meme ligne peuvent alors
venir de permutations DIFFERENTES — et `contrainte_combinee` les additionne
quand meme, alors qu'aucun chargement ne les produit ensemble.

Cette reduction N'EST PAS UNE BORNE, ni haute ni basse :

  - elle SURESTIME quand elle cumule des composantes issues de permutations
    differentes (un N maximal avec un moment qui ne l'accompagne jamais) ;
  - elle SOUS-ESTIME parce que B = |Myy|/Wy + |Mzz|/Wz prend une valeur
    ABSOLUE : la ligne « max » associe le N maximal au Myy maximal SIGNE,
    et rate le Myy de signe oppose — souvent bien plus grand en amplitude —
    qui accompagne reellement ce N.

Constate sur la Canopee (60 barres, fy 235 MPa) : reduction superieure a la
realite sur 14 barres, INFERIEURE sur 28, egale sur 18. Exemple de
sous-estimation, barre 168 (RHS 300x200x10) : la reduction voit a mi-portee
(N = +1082 kN, Myy = +3,98 kNm) et (N = -3,3 kN, Myy = -30,73 kNm), d'ou
125,3 MPa ; la permutation 275 porte en realite N = +1082 kN ET
Myy = -30,73 kNm simultanement, soit 158,5 MPa — 26,5 % de plus.

`contraintes_c1_c2` garde donc les permutations separees, et
`permutation_dimensionnante` cherche, parmi tous les couples (permutation,
position), celui qui maximise l'amplitude de C1/C2. Les efforts rapportes
coexistent donc physiquement : c'est une contrainte que la structure subit
vraiment, dans les deux sens. Deux sorties, calculees dans la MEME passe sur
le meme tableau d'efforts :
  - `permutation_dimensionnante` : la ligne « une barre » (perm gouvernante,
    position, torseur, C1/C2, taux ELU) ;
  - `taux_ec3_par_permutation`   : les 7 taux EC3 de chaque permutation, qui
    alimentent la carte barres x permutations.

Les resistances viennent de `ec3.resistances`.
"""
from __future__ import annotations

import math

import numpy as np

from dimensionner import taux_elu_fy
from ec3 import INDEX_COMPOSANTE, NOMS_CRITERES

# ordre des 6 colonnes des tableaux d'efforts (cf. gsa_bridge.permutations)
I_FX, I_MYY, I_MZZ = 0, 4, 5


def contraintes_c1_c2(efforts: np.ndarray, aire: float, wpl_y: float,
                      wpl_z: float) -> tuple[np.ndarray, np.ndarray]:
    """(C1, C2) en Pa pour chaque couple (permutation, position).

    Calcule les 4 combinaisons de signes possibles de flexion biaxiale :
    σ = N/aire ± My/Wpl_y ± Mz/Wpl_z, puis retient le MAX (C1) et le MIN (C2).
    Cela représente les deux états limites réels de la section (fibres extrêmes).

    `wpl_y`/`wpl_z` : modules de flexion PLASTIQUES (Wpl_y/Wpl_z — `Zpy_m3`/
    `Zpz_m3` cote sections GSA), pas elastiques.

    Chaque case combine des efforts d'une SEULE permutation à une SEULE
    position — c'est tout l'objet du module (cf. en-tête).

    `efforts` : tableau (permutation, position, 6). Les NaN sont traités comme
    nuls, comme dans les scripts d'étude.
    """
    e = np.nan_to_num(efforts)
    a = e[:, :, I_FX] / aire
    my_w = e[:, :, I_MYY] / wpl_y
    mz_w = e[:, :, I_MZZ] / wpl_z

    # 4 combinaisons de signes pour la flexion biaxiale
    flexion = np.array([
        my_w + mz_w,
        my_w - mz_w,
        -my_w + mz_w,
        -my_w - mz_w,
    ])  # shape (4, nperm, npos)

    max_flexion = np.max(flexion, axis=0)
    min_flexion = np.min(flexion, axis=0)

    return a + max_flexion, a + min_flexion


def permutation_dimensionnante(efforts: np.ndarray, aire: float, wpl_y: float,
                               wpl_z: float, fy_Pa: float | None) -> dict | None:
    """Couple (permutation, position) qui maximise l'amplitude de C1/C2.

    Renvoie {"perm", "position", "efforts", "C1_Pa", "C2_Pa", "sigma_Pa",
    "taux_ELU"} — `perm` et `position` sont des INDEX (0-based) dans le
    tableau, `efforts` les 6 composantes SI de cette case exacte. None si la
    section ne permet pas le calcul (aire ou module manquant).

    `wpl_y`/`wpl_z` : modules de flexion PLASTIQUES (cf. `contraintes_c1_c2`).

    L'amplitude retenue est max(C1, -C2), qui vaut exactement max(|C1|, |C2|)
    puisque C1 >= C2 toujours (C1 = max, C2 = min des 4 combinaisons).
    `taux_ELU` = sigma / fy via `dimensionner.taux_elu_fy` — SEULE
    implementation de ce taux, comme partout ailleurs dans l'application.
    """
    if not aire or not wpl_y or not wpl_z or efforts.size == 0:
        return None
    c1, c2 = contraintes_c1_c2(efforts, aire, wpl_y, wpl_z)
    amplitude = np.maximum(c1, -c2)
    plat = int(np.argmax(amplitude))
    ip, ipos = divmod(plat, amplitude.shape[1])
    sigma = float(amplitude[ip, ipos])
    return {
        "perm": ip,
        "position": ipos,
        "efforts": np.nan_to_num(efforts[ip, ipos]).tolist(),
        "C1_Pa": float(c1[ip, ipos]),
        "C2_Pa": float(c2[ip, ipos]),
        "sigma_Pa": sigma,
        "taux_ELU": taux_elu_fy(sigma, fy_Pa) if fy_Pa else None,
    }


def taux_ec3_par_permutation(efforts: np.ndarray,
                             resistances: dict[str, float | None]) -> np.ndarray:
    """Taux d'utilisation EC3 de chaque permutation : tableau (permutation, 7).

    Pour une permutation donnee, chaque composante est reduite a son amplitude
    MAXIMALE sur les positions de la barre, puis rapportee a la resistance de
    section correspondante. Les colonnes sont dans l'ordre de
    `ec3.NOMS_CRITERES` ; un critere sans resistance calculable (aire de
    cisaillement inconnue sur un profil non reconnu, nuance absente...) reste
    a 0.

    Fx alimente DEUX criteres opposes : le signe du Fx d'amplitude maximale
    tranche entre compression (< 0) et traction (>= 0) — c'est la meme regle
    que `tests/canopee_elu_matrice.py`, dont ce module reprend le calcul.
    """
    e = np.nan_to_num(efforts)
    nperm = e.shape[0]
    amplitudes = np.abs(e).max(axis=1)                    # (nperm, 6)

    # signe du Fx gouvernant, permutation par permutation
    i_fx = np.abs(e[:, :, I_FX]).argmax(axis=1)
    signe = np.sign(e[np.arange(nperm), i_fx, I_FX])

    taux = np.zeros((nperm, len(NOMS_CRITERES)), dtype=np.float32)
    for k, nom in enumerate(NOMS_CRITERES):
        r = resistances.get(nom)
        if not r or r <= 0:
            continue
        t = amplitudes[:, INDEX_COMPOSANTE[nom]] / r
        if nom == "compression":
            t = np.where(signe < 0, t, 0.0)
        elif nom == "traction":
            t = np.where(signe >= 0, t, 0.0)
        taux[:, k] = t
    return taux


def contrainte_combinee(rows: list[dict], aire, wpl_y, wpl_z) -> dict:
    """SEULE implementation de la contrainte combinee C1/C2 sur des lignes
    DEJA REDUITES — partagee par l'optimisation globale
    (commun/algo_opti/_commun.py::evaluer_etat) et l'onglet Performances v1
    (app_old/server.py::_perf_ligne) : les deux DOIVENT calculer exactement la
    meme chose, donc appellent cette fonction plutot que de reimplementer la
    formule chacun de leur cote. Meme formule que `contraintes_c1_c2`
    (cf. en-tete du module), mais une ligne = un (N, Myy, Mzz) au lieu d'un
    tableau (permutation, position) — typiquement le max/min signe de
    `beam_forces` sur une combinaison enveloppe, pas les permutations brutes.

    C1 (A+B, max signe) / C2 (A-B, min signe), calculees DIRECTEMENT depuis
    les efforts (Fx, Myy, Mzz de `beam_forces`/`member_forces`) plutot que
    les tables de contraintes GSA (beam_stresses/beam_derived_stresses —
    plusieurs appels couteux, cf. `dimensionner.dimensionner()` qui les
    utilise, elle, pour les AUTRES mesures — von Mises, cisaillements... —
    indisponibles depuis les seuls efforts).

    A = N/aire (contrainte axiale), B = |My|/Wpl_y + |Mz|/Wpl_z (flexion
    bi-axiale cumulee, cas le plus defavorable des fibres). C1 = A+B
    (traction/fibre tendue gouvernante), C2 = A-B (compression/fibre
    comprimee gouvernante) — memes conventions que la colonne C1/C2 des
    tables de contraintes GSA (au module elastique cote GSA : un ecart avec
    les C1/C2 natifs de GSA est donc attendu, cf. tests/scripts/
    elu2_diagnostic_barre.py::etape7_c1_c2_natifs_gsa).

    Calculee LIGNE PAR LIGNE (meme position/permutation pour N, My et Mz :
    combiner l'extreme de chaque composante prise separement — a des
    positions/permutations differentes — ne serait pas physique), puis
    reduite au max (C1) / min (C2) sur toutes les lignes fournies.

    `rows` : lignes beam_forces/member_forces (Fx, Myy, Mzz, "element"),
    deja filtrees a la cible voulue (une barre, une famille, une position...).
    `aire`/`wpl_y`/`wpl_z` : caracteristiques de LA section actuellement
    affectee a cette cible (aire_m2, Wpl_y/Zpy_m3, Wpl_z/Zpz_m3 — accepte
    aussi bien des floats (sections GSA) que des chaines (catalogue CSV)).

    Renvoie {"c1", "c2", "element_c1", "element_c2"} en PASCAL (Pa) — None
    si les lignes ou la section manquent. `element_c1`/`element_c2` designent
    la barre ou l'extreme se produit (utile pour une famille de plusieurs
    barres ; sans objet — mais sans danger — pour une seule barre)."""
    aire = float(aire) if aire else None
    wpl_y = float(wpl_y) if wpl_y else None
    wpl_z = float(wpl_z) if wpl_z else None
    if not rows or not aire or not wpl_y or not wpl_z:
        return {"c1": None, "c2": None, "element_c1": None, "element_c2": None}
    c1 = c2 = None
    elem_c1 = elem_c2 = None
    for r in rows:
        n, my, mz = r["Fx"], r["Myy"], r["Mzz"]
        if any(isinstance(v, float) and math.isnan(v) for v in (n, my, mz)):
            continue
        a = n / aire
        b = abs(my) / wpl_y + abs(mz) / wpl_z
        v1, v2 = a + b, a - b
        if c1 is None or v1 > c1:
            c1, elem_c1 = v1, r.get("element")
        if c2 is None or v2 < c2:
            c2, elem_c2 = v2, r.get("element")
    return {"c1": c1, "c2": c2, "element_c1": elem_c1, "element_c2": elem_c2}


def amplitude_c1_c2(cc: dict) -> tuple[float, int | None]:
    """Amplitude ELU gouvernante (max(|C1|, |C2|), en Pa) + la barre qui la
    porte, depuis le dict renvoye par `contrainte_combinee` — SEULE
    implementation de cette reduction, partagee pour la meme raison (cf.
    `contrainte_combinee`).

    Comme C1 >= C2 toujours (C1 - C2 = 2B >= 0), max(|C1|, |C2|) vaut
    exactement max(C1, -C2) : pas besoin de comparer les valeurs absolues des
    deux, juste le signe qui les separe. Renvoie (0.0, None) si aucune des
    deux valeurs n'est disponible (section/lignes manquantes)."""
    c1, c2 = cc.get("c1"), cc.get("c2")
    if c1 is None and c2 is None:
        return 0.0, None
    c1v, c2v = c1 or 0.0, c2 or 0.0
    if -c2v >= c1v:
        return -c2v, cc.get("element_c2")
    return c1v, cc.get("element_c1")
