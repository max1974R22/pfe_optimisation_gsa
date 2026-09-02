# -*- coding: utf-8 -*-
"""EN 1993-1-1 §5.5 — classe de section (Tableau 5.2), sans Excel.

Port de l'onglet `Calcul classe` du classeur Predim, lu formule par formule
(openpyxl). C'est la derniere chose que le classeur fournissait et que
`commun/stabilite_ec3` recevait en ENTREE (`ParametresBarre.classe_section`) :
sans elle, il n'y a pas de verification de stabilite autonome, puisque la
classe decide si les modules de flexion sont elastiques (classe 3) ou
plastiques (classes 1, 2 et — dans ce classeur — 4).

Correspondance avec le classeur (onglet `Calcul classe`) :

  sections en I/H (IPE, IPN, HE, HD, UB, UC)   lignes 12-59
      classe d'ame      D7 = IF(My partout nul ET N<0, MAX(colonne comprimee),
                                MAX(colonne flechie, colonne flechie+comprimee))
      classe de semelle D8 = MAX(colonne comprimee, colonne flechie+comprimee)
      classe            D9 = MAX(D7, D8)          -> Calcul!W3
  sections creuses rectangulaires (RHS, SHS)     lignes 74-123
      ame               D69, semelle D70, classe D71
  sections creuses circulaires (CHS)             lignes 127-138
      classe            D132 = d/t contre 50e^2, 70e^2, 90e^2

TROIS FIDELITES AU CLASSEUR qu'il faut connaitre avant de comparer a la norme :

  1. Le classeur prend le MAX de la colonne « paroi flechie » (qui s'applique
     TOUJOURS) et de la colonne « flechie et comprimee ». La seconde est celle
     qui decrit reellement l'etat de la paroi quand N != 0 ; prendre le max des
     deux est CONSERVATIF, pas litteral.
  2. La relaxation du §5.5.2(9) (epsilon* = sqrt(fy/gM0/|sigma_com,Ed|), qui
     peut faire remonter une paroi de classe 4 en classe 3) est CALCULEE par le
     classeur (lignes 28, 55, 90, 116) mais EXCLUE de ses MAX. On ne l'applique
     donc pas non plus.
  3. Les moments pris en compte sont le MAX des QUATRE valeurs saisies —
     diagramme a 3 points ET valeur du torseur (`MAX(ABS(D31),ABS(D32),
     ABS(P25),ABS(D33))`) —, alors que le taux de deversement, lui, n'utilise
     que les 3 points du diagramme (Q86). Ce n'est pas une incoherence du port :
     c'est ce que fait le classeur.

Convention de signe, celle du classeur : N > 0 = TRACTION, une contrainte de
COMPRESSION est NEGATIVE.
"""
from __future__ import annotations

import math

from ._commun import CaracteristiquesSection, Torseur

# libelles des classes, pour les messages
CLASSES = (1, 2, 3, 4)


def epsilon(fy: float) -> float:
    """epsilon = sqrt(235/fy), Tableau 5.2 (Excel : `Calcul classe`!D6/D68/D129).

    `fy` est la limite elastique NOMINALE de la nuance, celle que le classeur
    lit dans sa table de nuances — pas une valeur saisie a la main."""
    return math.sqrt(235.0 / fy)


# ==========================================================================
#  Tableau 5.2, feuille 1 — parois comprimees INTERNES (ames, et semelles des
#  sections creuses)
# ==========================================================================
def _classe_interne_flexion(c_sur_t: float, eps: float) -> int:
    """Paroi entierement flechie : 72e / 83e / 124e (Excel : C24/C25/C26)."""
    if c_sur_t <= 72 * eps:
        return 1
    if c_sur_t <= 83 * eps:
        return 2
    if c_sur_t <= 124 * eps:
        return 3
    return 4


def _classe_interne_compression(c_sur_t: float, eps: float) -> int:
    """Paroi entierement comprimee : 33e / 38e / 42e (Excel : E24/E25/E26)."""
    if c_sur_t <= 33 * eps:
        return 1
    if c_sur_t <= 38 * eps:
        return 2
    if c_sur_t <= 42 * eps:
        return 3
    return 4


def _limite_interne_flexion_compression(classe: int, eps: float,
                                        alpha: float, psi: float) -> float:
    """Limite c/t d'une paroi interne flechie ET comprimee (Excel : G24/G25/G26).

    classes 1 et 2 : parametrees par alpha (part comprimee de la paroi) ;
    classe 3 : parametree par psi (rapport des contraintes d'extremite).
    """
    if classe == 1:
        return 396 * eps / (13 * alpha - 1) if alpha > 0.5 else 36 * eps / alpha
    if classe == 2:
        return 456 * eps / (13 * alpha - 1) if alpha > 0.5 else 41.5 * eps / alpha
    if psi > -1:
        return 42 * eps / (0.67 + 0.33 * psi)
    return 62 * eps * (1 - psi) * math.sqrt(-psi)


def _classe_interne_flexion_compression(c_sur_t: float, eps: float,
                                        alpha: float, psi: float) -> int:
    for classe in (1, 2, 3):
        if c_sur_t <= _limite_interne_flexion_compression(classe, eps, alpha, psi):
            return classe
    return 4


# ==========================================================================
#  Tableau 5.2, feuille 2 — semelles en CONSOLE (sections en I/H seulement)
# ==========================================================================
def _classe_console_compression(c_sur_t: float, eps: float) -> int:
    """Semelle en console entierement comprimee : 9e / 10e / 14e
    (Excel : C51/C52/C53)."""
    if c_sur_t <= 9 * eps:
        return 1
    if c_sur_t <= 10 * eps:
        return 2
    if c_sur_t <= 14 * eps:
        return 3
    return 4


def _k_sigma(psi: float, sigma_racine: float, sigma_bout: float) -> float | None:
    """k_sigma d'une semelle en console, EN 1993-1-5 Tableau 4.2
    (Excel : `Calcul classe`!J46). None si psi sort du domaine tabule."""
    if sigma_racine > 0 and sigma_bout < 0 and abs(psi) > 1:
        return 1.7 - 5 * psi + 17.1 * psi ** 2
    if psi == 1:
        return 0.43
    if psi == 0:
        return 0.57
    if psi == -1:
        return 0.85
    if -1 <= psi <= 1:
        return 0.57 - 0.21 * psi + 0.07 * psi ** 2
    return None


def _classe_console_flexion_compression(c_sur_t: float, eps: float, alpha: float,
                                        k_sigma: float | None) -> int:
    """Semelle en console flechie et comprimee, EXTREMITE COMPRIMEE
    (Excel : E51/E52/E53). Le classeur ne traite pas le cas « extremite
    tendue » : sur un profil bi-symetrique il est toujours plus favorable
    (note G50 du classeur)."""
    if c_sur_t <= 9 * eps / alpha:
        return 1
    if c_sur_t <= 10 * eps / alpha:
        return 2
    if k_sigma is not None and c_sur_t <= 21 * eps * math.sqrt(k_sigma):
        return 3
    return 4


# ==========================================================================
#  alpha et psi, communs a toutes les parois
# ==========================================================================
def _alpha(sigma_comprime: float, sigma_oppose: float,
           moment_nul: bool = False) -> float:
    """Part comprimee de la paroi (Excel : G18/H80/H106).

    `sigma_comprime` : contrainte de la fibre la PLUS comprimee (la plus
    negative) ; `sigma_oppose` : celle de l'autre extremite. alpha vaut 1 quand
    la paroi est entierement comprimee (rien a interpoler) ou entierement
    tendue (cas degenere, sans effet : la colonne correspondante ne s'applique
    alors pas).
    """
    if moment_nul or sigma_oppose <= 0 or sigma_comprime > 0:
        return 1.0
    return sigma_comprime / (sigma_comprime - sigma_oppose)


def _psi(sigma_comprime: float, sigma_oppose: float) -> float:
    """Rapport des contraintes d'extremite (Excel : H20/I82/I108). 0 si la
    paroi n'est pas contrainte du tout (le classeur produirait #DIV/0!, sans
    consequence : les colonnes qui l'utilisent ne s'appliquent pas)."""
    if sigma_comprime == 0:
        return 0.0
    return sigma_oppose / sigma_comprime


def _max_colonnes(*classes: int | None) -> int:
    """MAX en ignorant les colonnes qui ne s'appliquent pas (le « - » du
    classeur, que MAX() d'Excel ignore). 1 si aucune ne s'applique — une paroi
    sans compression du tout est de classe 1."""
    valides = [c for c in classes if c is not None]
    return max(valides) if valides else 1


# ==========================================================================
#  Classes par famille de section
# ==========================================================================
def _classe_i_h(s: CaracteristiquesSection, N_kN: float, My_kNm: float,
                Mz_kNm: float, eps: float) -> tuple[int, int]:
    """(classe d'ame, classe de semelle) d'un profil en I ou H
    (Excel : `Calcul classe`!D7 et D8)."""
    # ---- ame : paroi interne, c = h - 2r - 2tf (Excel : D13/D14) ----------
    c_ame = s.h - 2 * s.r - 2 * s.tf
    c_sur_tw = c_ame / s.tw
    sigma_N = N_kN / s.A * 1000.0
    sigma_My = 1e6 * My_kNm * (s.h / 2 - s.tf - s.r) / s.Iy
    sigma_comprime = sigma_N - sigma_My          # Excel E18 (« max », le plus comprime)
    sigma_oppose = sigma_N + sigma_My            # Excel F18 (« min »)

    col_flexion = _classe_interne_flexion(c_sur_tw, eps)
    col_compression = (_classe_interne_compression(c_sur_tw, eps)
                       if sigma_oppose < 0 else None)
    col_mixte = None
    if sigma_comprime < 0:
        col_mixte = _classe_interne_flexion_compression(
            c_sur_tw, eps, _alpha(sigma_comprime, sigma_oppose),
            _psi(sigma_comprime, sigma_oppose))
        # Excel H27 : la classe 4 de cette colonne est exclue quand le moment
        # est nul (la paroi est alors en compression pure, deja decrite par la
        # colonne « comprimee »). Les classes 1 a 3, elles, restent evaluees —
        # a alpha = psi = 1 elles redonnent exactement les limites 33e/38e/42e
        # de la compression pure.
        if col_mixte == 4 and sigma_My == 0:
            col_mixte = None

    # compression PURE (aucun moment My et barre comprimee) : le classeur
    # bascule sur la seule colonne « comprimee » (Excel : D7)
    if My_kNm == 0 and N_kN < 0:
        classe_ame = _max_colonnes(col_compression)
    else:
        classe_ame = _max_colonnes(col_flexion, col_mixte)

    # ---- semelle : console, c = 0.5b - 0.5tw - r (Excel : D40/D41) --------
    c_semelle = 0.5 * s.b - 0.5 * s.tw - s.r
    c_sur_tf = c_semelle / s.tf
    sigma_base = sigma_N - 1e6 * My_kNm * (s.h / 2) / s.Iy       # Excel C44
    sigma_racine = sigma_base - 1e6 * Mz_kNm * (0.5 * s.tw + s.r) / s.Iz   # F44
    sigma_bout = sigma_base - 1e6 * Mz_kNm / s.Wzel                        # G44

    col_compression = (_classe_console_compression(c_sur_tf, eps)
                       if sigma_racine <= 0 else None)
    col_mixte = None
    # colonne « flechie et comprimee » : seulement si le BOUT est comprime et
    # la racine tendue — sinon la semelle est entierement comprimee, cas deja
    # traite par la colonne precedente (Excel : F51)
    if sigma_bout < 0 <= sigma_racine:
        alpha = abs(sigma_bout) / (sigma_racine - sigma_bout)
        col_mixte = _classe_console_flexion_compression(
            c_sur_tf, eps, alpha,
            _k_sigma(_psi(sigma_bout, sigma_racine), sigma_racine, sigma_bout))
    classe_semelle = _max_colonnes(col_compression, col_mixte)
    return classe_ame, classe_semelle


def _classe_paroi_creuse(c_sur_t: float, eps: float, sigma_comprime: float,
                         sigma_oppose: float, moment_nul: bool) -> int:
    """Une paroi d'un tube rectangulaire (ame ou semelle) — meme aiguillage
    que le classeur (Excel : D69 / D70).

    `sigma_oppose <= 0` : toute la paroi est comprimee, seule la colonne
    « comprimee » s'applique. Sinon on prend le MAX de la colonne « flechie »
    (toujours valable) et de la colonne « flechie et comprimee ».
    """
    if sigma_oppose <= 0:          # paroi entierement comprimee
        return _classe_interne_compression(c_sur_t, eps)
    col_flexion = _classe_interne_flexion(c_sur_t, eps)
    col_mixte = None
    if sigma_comprime < 0:
        col_mixte = _classe_interne_flexion_compression(
            c_sur_t, eps, _alpha(sigma_comprime, sigma_oppose),
            _psi(sigma_comprime, sigma_oppose))
        if col_mixte == 4 and moment_nul:      # Excel H89, meme regle qu'en I/H
            col_mixte = None
    return _max_colonnes(col_flexion, col_mixte)


def _classe_rhs(s: CaracteristiquesSection, N_kN: float, My_kNm: float,
                Mz_kNm: float, eps: float) -> tuple[int, int]:
    """(classe d'ame, classe de semelle) d'un tube rectangulaire ou carre
    (Excel : `Calcul classe`!D69 et D70)."""
    sigma_N = N_kN / s.A * 1000.0

    # ---- ames (parois verticales) : c = h - 3t (Excel : D75/D76) ----------
    c_sur_tw = (s.h - 3 * s.tf) / s.tw
    d_my = 1e6 * My_kNm * (s.h / 2 - 1.5 * s.tf) / s.Iy
    e_mz = 1e6 * Mz_kNm * (s.b / 2) / s.Iz
    classe_ame = _classe_paroi_creuse(
        c_sur_tw, eps, sigma_N - d_my - e_mz, sigma_N + d_my - e_mz, d_my == 0)

    # ---- semelles (parois horizontales) : c = b - 3t (Excel : D101/D102) --
    c_sur_tf = (s.b - 3 * s.tw) / s.tf
    d_my = 1e6 * My_kNm * (s.h / 2) / s.Iy
    e_mz = 1e6 * Mz_kNm * (s.b / 2 - 1.5 * s.tw) / s.Iz
    classe_semelle = _classe_paroi_creuse(
        c_sur_tf, eps, sigma_N - d_my - e_mz, sigma_N - d_my + e_mz, d_my == 0)
    return classe_ame, classe_semelle


def _classe_chs(s: CaracteristiquesSection, eps: float) -> int:
    """Tube circulaire : d/t contre 50e^2, 70e^2, 90e^2 (Excel : D135:D138).
    Ne depend NI des efforts NI du sens de la flexion — c'est la seule famille
    dont la classe est purement geometrique."""
    d_sur_t = s.h / s.tw
    for classe, limite in ((1, 50), (2, 70), (3, 90)):
        if d_sur_t <= limite * eps ** 2:
            return classe
    return 4


# ==========================================================================
def classe_section(section: CaracteristiquesSection, torseur: Torseur,
                   fy: float) -> dict:
    """Classe EC3 §5.5 d'une section sous un torseur donne.

    `fy` : limite elastique NOMINALE de la nuance (MPa), celle qui donne
    epsilon — pas la valeur eventuellement reduite pour forte epaisseur.

    Retour : {"classe": 1..4, "classe_ame": int, "classe_semelle": int|None,
              "epsilon": float}. `classe_semelle` est None pour un CHS, qui
    n'a qu'une paroi (le classeur y met « - »).

    Les moments retenus sont le MAX des quatre valeurs disponibles (les trois
    points du diagramme et la valeur du torseur), comme le classeur.
    """
    eps = epsilon(fy)
    My = max(abs(v) for v in (torseur.My_Ed_kNm, torseur.My_debut_kNm or 0.0,
                              torseur.My_milieu_kNm or 0.0, torseur.My_fin_kNm or 0.0))
    Mz = max(abs(v) for v in (torseur.Mz_Ed_kNm, torseur.Mz_debut_kNm or 0.0,
                              torseur.Mz_milieu_kNm or 0.0, torseur.Mz_fin_kNm or 0.0))
    N = torseur.N_Ed_kN

    if section.deversement_sans_objet:            # CHS
        classe = _classe_chs(section, eps)
        return {"classe": classe, "classe_ame": classe, "classe_semelle": None,
                "epsilon": eps}
    if section.est_section_I_H:
        ame, semelle = _classe_i_h(section, N, My, Mz, eps)
    else:                                          # RHS / SHS
        ame, semelle = _classe_rhs(section, N, My, Mz, eps)
    return {"classe": max(ame, semelle), "classe_ame": ame,
            "classe_semelle": semelle, "epsilon": eps}
