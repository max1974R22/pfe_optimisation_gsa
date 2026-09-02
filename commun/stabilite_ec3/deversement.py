# -*- coding: utf-8 -*-
"""EN 1993-1-1 §6.3.2 — Deversement (flambement lateral d'une barre flechie).
Methode GENERALE (§6.3.2.2, moment critique Mcr par la formule d'Annexe F) —
PAS la methode simplifiee des profils lamines (§6.3.2.3). Independant du
signe de N_Ed (verifie meme sans compression).

Correspondance classeur :
  Mcr        : W73 (nomme `Mcr`), Annexe F, facteurs C1/C2/k/kw saisis
               manuellement (P32/P33/P30/P31 — lecture d'abaque). ICI, si le
               diagramme de My a 3 points est fourni (`Torseur.My_debut_kNm`
               etc.), C1/C2 sont a la place CALCULES analytiquement par
               `coefficients_c1_c2.C1_C2_depuis_diagramme` (§3.5, Annexe MCR
               de la NF EN 1993-1-1/NA) — le classeur, lui, n'a pas cet
               automatisme.
  lambda_LT  : S76 = SQRT(Wy*fy/(Mcr*1e6)), Wy = Wyel (classe 3) ou
               Wypl (classe 1/2) — la classe 4 (module efficace requis, non
               calcule ici) est refusee en amont par
               `verification.verifier_stabilite`, cf. `SectionClasse4` : ce
               fichier ne voit donc jamais que 1, 2 ou 3
  courbe_LT  : Q71/U71 (h/b<=2 -> courbe a, sinon b — tableau 6.4)
  chi_LT     : S78 (Phi_LT) -> S80 (chi_LT), meme forme que le flambement,
               MAIS force a 1 pour un CHS (S80 = IF(AB2=5, 1, ...)) : un tube
               circulaire n'a pas d'axe faible, il ne deverse pas
  Mb,Rd      : Q83 = chi_LT * Wy * fy / gM1
  taux       : X36 = Q86 = MAX(|My,debut|,|My,milieu|,|My,fin|) / Mb,Rd
"""
from __future__ import annotations

import math

from ._commun import (ALPHA_COURBES, CaracteristiquesSection, ParametresBarre,
                      Torseur, coefficient_reduction_chi)
from .coefficients_c1_c2 import C1_C2_depuis_diagramme


def moment_critique_elastique(section: CaracteristiquesSection, L_m: float,
                              C1: float, C2: float, k: float, kw: float,
                              E: float, G: float) -> float:
    """Mcr, formule generale d'Annexe F, en kN.m :
    Mcr = C1*pi^2*E*Iz/(k*L)^2 * [sqrt((k/kw)^2*Iw/Iz
          + (k*L)^2*G*It/(pi^2*E*Iz) + (C2*zg)^2) - C2*zg]
    (Excel : W73, nomme `Mcr`)
    """
    L_mm = L_m * 1000.0
    zg = section.zg
    racine = math.sqrt((k / kw) ** 2 * section.Iw / section.Iz
                       + (k * L_mm) ** 2 * G * section.It / (math.pi ** 2 * E * section.Iz)
                       + (C2 * zg) ** 2)
    Mcr_Nmm = (C1 * math.pi ** 2 * E * section.Iz / (k * L_mm) ** 2) * (racine - C2 * zg)
    return Mcr_Nmm / 1e6   # N.mm -> kN.m


def elancement_reduit_deversement(Wy_mm3: float, fy: float, Mcr_kNm: float) -> float:
    """lambda_bar_LT = sqrt(Wy*fy / Mcr), §6.3.2.2 [6.56].
    (Excel : S76 — Wy = Wyel si classe 3, Wypl sinon)"""
    return math.sqrt(Wy_mm3 * fy / (Mcr_kNm * 1e6))


def resistance_deversement(section: CaracteristiquesSection, chi_LT: float,
                           fy: float, gamma_M1: float, classe3: bool) -> float:
    """Mb,Rd = chi_LT * Wy * fy / gamma_M1, §6.3.2.1 [6.55], en kN.m.
    (Excel : Q83 = IF(classe=3, chi_LT*Wyel*fy/W14, chi_LT*Wypl*fy/W14))"""
    Wy = section.Wyel if classe3 else section.Wypl
    return chi_LT * Wy * fy / gamma_M1 / 1e6


def taux_deversement(section: CaracteristiquesSection, parametres: ParametresBarre,
                     torseur: Torseur) -> dict:
    """Assemble le taux de deversement — independant du signe de N_Ed.

    C1/C2 : si `torseur.My_debut_kNm`/`My_milieu_kNm`/`My_fin_kNm` sont
    renseignes, calcules via §3.5 de l'Annexe MCR (formule generale,
    combinaison moments d'extremite + charge repartie, kz=kw=1 — cf.
    `coefficients_c1_c2.py`). Sinon — ou si `parametres.c1_c2_manuels` est
    vrai —, `parametres.C1`/`C2` (saisie manuelle, comportement du classeur).

    Le My retenu au numerateur, lui, vient TOUJOURS du diagramme quand il est
    fourni (MAX des trois points, comme Excel Q86) : `c1_c2_manuels` ne
    debranche que le calcul des coefficients.

    chi_LT vaut 1 sans condition pour un CHS (`section.deversement_sans_objet`,
    Excel S80) : le taux se reduit alors a My,max / (Wy fy / gamma_M1).

    Retour :
      {"taux": float, "chi_LT": float, "lambda_bar_LT": float,
       "Mcr_kNm": float, "Mb_Rd_kNm": float, "C1": float, "C2": float}

    (Excel : X36 = Q86 = MAX(|My,debut|,|My,milieu|,|My,fin|)/Mb,Rd)
    """
    # `classe_section` ne peut valoir que 1, 2 ou 3 ici (la classe 4 est
    # refusee plus haut, cf. `SectionClasse4` dans verification.py) : W
    # elastique en classe 3, PLASTIQUE en classe 1 ET 2 (pas seulement 1).
    classe3 = parametres.classe_section == 3
    Wy = section.Wyel if classe3 else section.Wypl

    diagramme_fourni = (torseur.My_debut_kNm is not None
                        and torseur.My_milieu_kNm is not None
                        and torseur.My_fin_kNm is not None)
    if diagramme_fourni and not parametres.c1_c2_manuels:
        C1, C2 = C1_C2_depuis_diagramme(torseur.My_debut_kNm, torseur.My_milieu_kNm,
                                        torseur.My_fin_kNm)
        My_max = max(abs(torseur.My_debut_kNm), abs(torseur.My_milieu_kNm),
                    abs(torseur.My_fin_kNm))
    else:
        C1, C2 = parametres.C1, parametres.C2
        My_max = (max(abs(torseur.My_debut_kNm), abs(torseur.My_milieu_kNm),
                      abs(torseur.My_fin_kNm)) if diagramme_fourni
                  else abs(torseur.My_Ed_kNm))

    Mcr = moment_critique_elastique(section, parametres.L_deversement_m,
                                    C1, C2, parametres.k, parametres.kw,
                                    parametres.E, parametres.G)
    lambda_bar_LT = elancement_reduit_deversement(Wy, parametres.fy, Mcr)
    if section.deversement_sans_objet:
        # CHS : Excel S80 = IF(AB2=5, 1, ...). Inertie de flexion identique
        # dans toutes les directions -> pas d'axe faible, pas de deversement.
        # Mcr et lambda_bar_LT restent calcules et renvoyes (le classeur les
        # calcule aussi, en W73/S76) mais ne servent plus a rien ici.
        chi_LT = 1.0
    else:
        chi_LT = coefficient_reduction_chi(
            lambda_bar_LT, ALPHA_COURBES[section.courbe_deversement])
    Mb_Rd = resistance_deversement(section, chi_LT, parametres.fy, parametres.gamma_M1, classe3)

    taux = My_max / Mb_Rd

    return {"taux": taux, "chi_LT": chi_LT, "lambda_bar_LT": lambda_bar_LT,
            "Mcr_kNm": Mcr, "Mb_Rd_kNm": Mb_Rd, "C1": C1, "C2": C2}
