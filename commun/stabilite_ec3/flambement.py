# -*- coding: utf-8 -*-
"""EN 1993-1-1 §6.3.1 — Flambement d'une barre comprimee (flexion pure, sans
moment). Sans objet si N_Ed > 0 (traction, convention classeur).

Correspondance classeur (`Calcul` du classeur Predim) :
  axe y-y : P58 (lambda_1) -> P59 (lambda_bar_y) -> P61 (alpha_y) ->
            P62 (Phi_y) -> P63 (chi_y) -> P65 (Nb,Rd,y)
  axe z-z : memes colonnes en U (U59, U61, U62, U63, U65)
  taux    : X35 = P67 = IF(N_Ed<=0, |N_Ed|/MIN(P65,U65), "N >0, ok")
"""
from __future__ import annotations

from ._commun import (ALPHA_COURBES, CaracteristiquesSection, ParametresBarre,
                      Torseur, coefficient_reduction_chi, lambda_1)


def elancement_reduit(Lcr_m: float, i_mm: float, fy: float, E: float) -> float:
    """lambda_bar = Lcr / (i * lambda_1), §6.3.1.3(1).
    (Excel : P59 = G15*1000/(AC20*P58) pour l'axe y-y, U59 pour z-z)"""
    return Lcr_m * 1000.0 / (i_mm * lambda_1(E, fy))


def resistance_flambement(A_mm2: float, fy: float, chi: float, gamma_M1: float) -> float:
    """Nb,Rd = chi * A * fy / gamma_M1, §6.3.1.1 [6.47], en kN.
    (Excel : P65 = P63*A*fy/(W14*1000) pour l'axe y-y, U65 pour z-z)"""
    return chi * A_mm2 * fy / gamma_M1 / 1000.0


def taux_flambement(section: CaracteristiquesSection, parametres: ParametresBarre,
                    torseur: Torseur) -> dict:
    """Assemble le taux de flambement (les deux axes, on garde le pire).

    Retour :
      {"taux": float, "chi_y": float, "chi_z": float,
       "lambda_bar_y": float, "lambda_bar_z": float,
       "Nb_Rd_y_kN": float, "Nb_Rd_z_kN": float}

    (Excel : X35 = P67 = IF(N_Ed<=0, |N_Ed|/MIN(P65,U65), "N >0, ok"))
    """
    lambda_bar_y = elancement_reduit(parametres.Lcr_y_m, section.iy, parametres.fy, parametres.E)
    lambda_bar_z = elancement_reduit(parametres.Lcr_z_m, section.iz, parametres.fy, parametres.E)

    chi_y = coefficient_reduction_chi(lambda_bar_y, ALPHA_COURBES[section.courbe_flambement_y])
    chi_z = coefficient_reduction_chi(lambda_bar_z, ALPHA_COURBES[section.courbe_flambement_z])

    Nb_Rd_y = resistance_flambement(section.A, parametres.fy, chi_y, parametres.gamma_M1)
    Nb_Rd_z = resistance_flambement(section.A, parametres.fy, chi_z, parametres.gamma_M1)

    if torseur.N_Ed_kN > 0:          # traction (convention classeur) : sans objet
        taux = 0.0
    else:
        taux = abs(torseur.N_Ed_kN) / min(Nb_Rd_y, Nb_Rd_z)

    return {"taux": taux, "chi_y": chi_y, "chi_z": chi_z,
            "lambda_bar_y": lambda_bar_y, "lambda_bar_z": lambda_bar_z,
            "Nb_Rd_y_kN": Nb_Rd_y, "Nb_Rd_z_kN": Nb_Rd_z}
