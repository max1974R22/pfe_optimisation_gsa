# -*- coding: utf-8 -*-
"""Facteur de moment equivalent Cm (Annexe B, Tableau B.3), depuis un
diagramme de moment a 3 points (debut/milieu/fin) — port fidele du bloc
`AB45:AL70` du classeur Predim, lu formule par formule (xlwings, sur une
copie de travail) :

  Cmy = Calcul!AL51, depuis My,Ed,debut/milieu/fin (D31/D32/D33)
  Cmz = Calcul!AL64, depuis Mz,Ed,debut/milieu/fin (D35/D36/D37) — BLOC
        IDENTIQUE a celui de Cmy, verifie cellule par cellule a +13 lignes
        (AC65↔AC52, AC66↔AC53, AC69↔AC56, AF65↔AF52, AH66↔AH53, AJ66↔AJ53,
        AF68↔AF55, AH69/AI69↔AH56/AI56, AH70/AI70↔AH57/AI57 — memes formules,
        D35:D37 au lieu de D31:D33).

`repartition_charge` (Excel: P35, "U"/"C"/"N") choisit la formule :
  - "noeuds_deplacables" (N) : Cm = 0.9 fixe, quel que soit le diagramme
    (Excel: AL51/AL64 = IF(P35="N", 0.9, ...) — mode d'instabilite a noeuds
    deplacables, note du classeur "AB51/AB64").
  - "uniforme" (U, defaut) / "concentree" (C) : cascade a 3 cas EXCLUSIFS
    selon la forme du diagramme (Excel: AF52/AF55/AF59 — AUCUN rapport avec
    `coefficients_c1_c2.py`, qui sert au deversement/Mcr, tableau EC3
    different) :
      1. "diagramme 1" — milieu de diagramme nul (AC56=D32=0, cas
         antisymetrique ou moments d'extremite seuls) :
         Cm = MAX(0.6 + 0.4*psi, 0.4), psi = M_autre/M (ratio des extremites)
      2. "diagramme 2" — l'extremite domine (|M_end/M_mid| > 1) :
         Cm = MAX(f(alpha_s = M_mid/M_end, psi), 0.4)
      3. "diagramme 3" — le milieu domine (|M_end/M_mid| <= 1, charge
         repartie preponderante) :
         Cm = g(alpha_h = M_end/M_mid, psi)   (deja >= ~0.9, pas de plancher)

Les constantes des formules f/g different entre "uniforme" et "concentree"
(cf. le corps des fonctions ci-dessous, chaque branche commentee avec sa
cellule Excel d'origine).
"""
from __future__ import annotations


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def cm_tableau_b3(M_debut_kNm: float, M_milieu_kNm: float, M_fin_kNm: float,
                  repartition: str = "uniforme") -> float:
    """Cm depuis un diagramme de moment a 3 points, Tableau B.3.

    Appeler une fois avec le diagramme de My -> Cmy, une fois avec celui de
    Mz -> Cmz (meme fonction, cf. docstring du module). `repartition` :
    "uniforme" (defaut), "concentree" ou "noeuds_deplacables".

    (Excel : AL51 pour Cmy, AL64 pour Cmz)
    """
    if repartition == "noeuds_deplacables":              # Excel: P35="N"
        return 0.9

    if abs(M_debut_kNm) >= abs(M_fin_kNm):                # AC52/AC65 (M)
        M_end_max, M_end_min = M_debut_kNm, M_fin_kNm      # AC53/AC66 (psi*M)
    else:
        M_end_max, M_end_min = M_fin_kNm, M_debut_kNm
    M_mid = M_milieu_kNm                                   # AC56/AC69 = D32/D36

    # --- "diagramme 1" : milieu nul -> Cm = 0.6+0.4*psi >=0.4, MEME formule
    # uniforme/concentree (Excel : AF52/AH53/AJ53 -- pas de branche AI53/AK53
    # distincte : le classeur applique la meme Ci quelle que soit P35 ici)
    if M_mid == 0.0:
        if M_end_max == 0.0:
            # diagramme entierement nul : AF52 vide -> Excel calcule quand
            # meme 0.6+0.4*0=0.6 (arithmetique sur cellule vide = 0) ; sans
            # consequence sur le taux final (le terme M correspondant du
            # [6.61]/[6.62] est alors multiplie par |M|=0)
            return 0.6
        psi = _clamp(M_end_min / M_end_max, -1.0, 1.0)      # AF52
        return max(0.6 + 0.4 * psi, 0.4)                    # AH53 -> AJ53

    # --- au-dela (milieu non nul), deux branches EXCLUSIVES selon
    # |M_end_max/M_mid> 1 ou <=1 (Excel : AF55 numerique <=> AF59 = texte, et
    # inversement -- jamais les deux a la fois)
    if M_end_max == 0.0 or abs(M_end_max / M_mid) <= 1.0:
        # "diagramme 3" : le milieu (charge repartie) domine
        # (Excel : AF59/AF60, AH60/AH61 uniforme, AI60/AI61 concentree)
        alpha_h = M_end_max / M_mid if M_end_max != 0.0 else 0.0    # AF59
        psi_h = (M_end_min / M_end_max) if M_end_max != 0.0 else 1.0  # AF60
        if repartition == "concentree":
            if alpha_h >= 0:
                return 0.9 + 0.1 * alpha_h                          # AI60
            if psi_h >= 0:
                return 0.9 + 0.1 * alpha_h                          # AI61 (psi>=0)
            return 0.95 - 0.1 * alpha_h * (1 + 2 * psi_h)           # AI61 (psi<0)
        if alpha_h >= 0:
            return 0.95 + 0.05 * alpha_h                            # AH60
        if psi_h >= 0:
            return 0.95 + 0.05 * alpha_h                            # AH61 (psi>=0)
        return 0.95 + 0.05 * alpha_h * (1 + 2 * psi_h)              # AH61 (psi<0)

    # "diagramme 2" : l'extremite domine
    # (Excel : AF55/AF56, AH56/AH57 uniforme -> AJ56/AJ57, AI56/AI57
    # concentree -> AK56/AK57 -- toujours plancher a 0.4)
    alpha_s = M_mid / M_end_max                                     # AF55
    psi_s = M_end_min / M_end_max                                   # AF56
    if repartition == "concentree":
        if alpha_s > 0:
            Ci = 0.2 + 0.8 * alpha_s                                # AI56 (strict >0)
        elif psi_s >= 0:
            Ci = -0.8 * alpha_s                                     # AI57 (psi>=0)
        else:
            Ci = 0.2 * (-psi_s) - 0.8 * alpha_s                     # AI57 (psi<0)
    else:
        if alpha_s >= 0:
            Ci = 0.2 + 0.8 * alpha_s                                # AH56
        elif psi_s >= 0:
            Ci = 0.1 - 0.8 * alpha_s                                # AH57 (psi>=0)
        else:
            Ci = 0.1 * (1 - psi_s) - 0.8 * alpha_s                  # AH57 (psi<0)
    return max(Ci, 0.4)                                             # AJ56/AJ57/AK56/AK57
