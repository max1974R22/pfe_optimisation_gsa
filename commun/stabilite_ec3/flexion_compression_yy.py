# -*- coding: utf-8 -*-
"""EN 1993-1-1 §6.3.3 — Barre flechie et comprimee, equation [6.61] (plan yy).

N_Ed/(chi_y*NRk/gM1) + kyy*My_Ed/(chi_LT*MyRk/gM1) + kyz*Mz_Ed/(MzRk/gM1) <= 1

Necessite les resultats de `flambement.taux_flambement` (chi_y, chi_z,
lambda_bar_y, lambda_bar_z, Nb_Rd_y/z) et de `deversement.taux_deversement`
(chi_LT, Mb_Rd) — ne pas recalculer, les reutiliser en argument.

kyy/kyz : facteurs d'interaction, Annexe B Tableau B.1, methode 2, membre
NON sensible aux deformations de torsion, section I/H. Formules dependantes
de la classe (1/2 vs 3/4) — cf. correspondance cellules ci-dessous.

Correspondance classeur :
  kyy (classe1/2) : AB78 = Cmy*[1+(lambda_bar_y-0.2)*nY] <= Cmy*[1+0.8*nY]
  kyy (classe3/4) : AC78 = Cmy*[1+0.6*lambda_bar_y*nY] <= Cmy*[1+0.6*nY]
  kzz (classe1/2, I/H)    : AE80 = Cmz*[1+(2*lambda_bar_z-0.6)*nZ] <= Cmz*[1+1.4*nZ]
  kzz (classe1/2, creuse) : AF80 = Cmz*[1+(lambda_bar_z-0.2)*nZ] <= Cmz*[1+0.8*nZ]
                    (Excel: AB81 = IF(AH76="h i", AE80, AF80) — c'est
                     `section.est_section_I_H` qui tranche)
  kzz (classe3/4) : AC81 = Cmz*[1+0.6*lambda_bar_z*nZ] <= Cmz*[1+0.6*nZ]
                    (identique pour les deux formes)
  kyz (classe1/2) : AB79 = 0.6*kzz(classe1/2)
  kyz (classe3/4) : AC79 = kzz(classe3/4)
  taux            : X37 = V96
"""
from __future__ import annotations

from ._commun import (CaracteristiquesSection, ParametresBarre, Torseur,
                      facteur_kzz_creux, facteur_kzz_I_H, moment_max_diagramme)
from .coefficients_cm_b3 import cm_tableau_b3


def facteur_kyy(Cmy: float, lambda_bar_y: float, n_y: float, classe3: bool) -> float:
    """kyy — Tableau B.1, Annexe B.

    classe 1/2 : Cmy*[1+(lambda_bar_y-0.2)*nY] <= Cmy*[1+0.8*nY]  (Excel: AB78)
    classe 3/4 : Cmy*[1+0.6*lambda_bar_y*nY] <= Cmy*[1+0.6*nY]    (Excel: AC78)
    """
    if classe3:
        return min(Cmy * (1 + 0.6 * lambda_bar_y * n_y), Cmy * (1 + 0.6 * n_y))
    return min(Cmy * (1 + (lambda_bar_y - 0.2) * n_y), Cmy * (1 + 0.8 * n_y))


def facteur_kyz(Cmz: float, lambda_bar_z: float, n_z: float, classe3: bool,
                section_I_H: bool = True) -> float:
    """kyz — Tableau B.1, membre non sensible a la torsion.

    classe 1/2 : kyz = 0.6*kzz   (Excel: AB79 = 0.6*AB81)
    classe 3/4 : kyz = kzz       (Excel: AC79 = AC81, pas de reduction)

    kzz vient de `_commun` (formule partagee avec
    `flexion_compression_zz.facteur_kzz`) : ligne « H I » du Tableau B.1
    (AE80) ou ligne « Creux » (AF80) selon `section_I_H`, exactement comme
    Excel AB81 = IF(AH76="h i", AE80, AF80)."""
    kzz = (facteur_kzz_I_H if section_I_H else facteur_kzz_creux)(
        Cmz, lambda_bar_z, n_z, classe3)
    return kzz if classe3 else 0.6 * kzz


def taux_flechie_comprimee_yy(section: CaracteristiquesSection,
                              parametres: ParametresBarre, torseur: Torseur,
                              resultat_flambement: dict,
                              resultat_deversement: dict) -> dict:
    """Assemble le taux [6.61]. 0 si N_Ed > 0 (traction, "N >0, ok").

    My/Mz : MAX(|debut|,|milieu|,|fin|) du diagramme si fourni sur `torseur`
    (mode normal), sinon repli sur My_Ed_kNm/Mz_Ed_kNm seuls (mode degrade).
    Cmy/Cmz : recalcules depuis les MEMES diagrammes (Tableau B.3, cf.
    `coefficients_cm_b3.cm_tableau_b3`) si fournis, sinon repli sur
    `parametres.Cmy`/`Cmz` (saisie manuelle).

    Retour :
      {"taux": float, "kyy": float, "kyz": float, "n_y": float}

    (Excel : X37 = V96 = ABS(N_Ed)/(chi_y*NRk/gM1)
                        + kyy*MAX(|My,debut|,|My,milieu|,|My,fin|)/(chi_LT*MyRk/gM1)
                        + kyz*MAX(|Mz,debut|,|Mz,milieu|,|Mz,fin|)/(MzRk/gM1))
    """
    if torseur.N_Ed_kN > 0:          # traction : sans objet
        return {"taux": 0.0, "kyy": 0.0, "kyz": 0.0, "n_y": 0.0}

    # `classe_section` ne peut valoir que 1, 2 ou 3 ici (la classe 4 est
    # refusee plus haut, cf. `SectionClasse4` dans verification.py) : W
    # elastique en classe 3, PLASTIQUE en classe 1 ET 2 (pas seulement 1) ;
    # `classe3` sert aussi de bascule Tableau B.1 "classe 1,2" / "classe 3,4"
    # pour les facteurs kyy/kyz — les deux usages restent corrects une fois
    # la classe 4 exclue.
    classe3 = parametres.classe_section == 3

    n_y = abs(torseur.N_Ed_kN) / resultat_flambement["Nb_Rd_y_kN"]
    n_z = abs(torseur.N_Ed_kN) / resultat_flambement["Nb_Rd_z_kN"]

    if (torseur.My_debut_kNm is not None and torseur.My_milieu_kNm is not None
            and torseur.My_fin_kNm is not None):
        Cmy = cm_tableau_b3(torseur.My_debut_kNm, torseur.My_milieu_kNm,
                            torseur.My_fin_kNm, parametres.repartition_charge)
    else:
        Cmy = parametres.Cmy
    if (torseur.Mz_debut_kNm is not None and torseur.Mz_milieu_kNm is not None
            and torseur.Mz_fin_kNm is not None):
        Cmz = cm_tableau_b3(torseur.Mz_debut_kNm, torseur.Mz_milieu_kNm,
                            torseur.Mz_fin_kNm, parametres.repartition_charge)
    else:
        Cmz = parametres.Cmz

    kyy = facteur_kyy(Cmy, resultat_flambement["lambda_bar_y"], n_y, classe3)
    kyz = facteur_kyz(Cmz, resultat_flambement["lambda_bar_z"], n_z, classe3,
                      section.est_section_I_H)

    Wz = section.Wzel if classe3 else section.Wzpl
    Mz_Rd = Wz * parametres.fy / parametres.gamma_M1 / 1e6   # kN.m (Excel: W11/W12)

    My_max = moment_max_diagramme(torseur.My_debut_kNm, torseur.My_milieu_kNm,
                                  torseur.My_fin_kNm, torseur.My_Ed_kNm)
    Mz_max = moment_max_diagramme(torseur.Mz_debut_kNm, torseur.Mz_milieu_kNm,
                                  torseur.Mz_fin_kNm, torseur.Mz_Ed_kNm)

    taux = (n_y
            + kyy * My_max / resultat_deversement["Mb_Rd_kNm"]
            + kyz * Mz_max / Mz_Rd)

    return {"taux": taux, "kyy": kyy, "kyz": kyz, "n_y": n_y}
