# -*- coding: utf-8 -*-
"""EN 1993-1-1 §6.3.3 — Barre flechie et comprimee, equation [6.62] (plan zz).

N_Ed/(chi_z*NRk/gM1) + kzy*My_Ed/(chi_LT*MyRk/gM1) + kzz*Mz_Ed/(MzRk/gM1) <= 1

Meme logique que `flexion_compression_yy.py` (memes resultats de flambement /
deversement a reutiliser), Annexe B. kzz/kyz : Tableau B.1 TOUJOURS (aucune
des deux formules du classeur ne depend de P36), ligne « H I » ou « Creux »
selon `CaracteristiquesSection.est_section_I_H`. kzy :
Tableau B.1 OU B.2 selon `ParametresBarre.sensible_torsion` (cf.
`facteur_kzy`/`_commun.facteur_kzy_torsion_sensible` — le classeur bascule
entre les deux via P36, et vaut "oui"/torsion-sensible PAR DEFAUT, jamais
decoche par appv2).

Correspondance classeur :
  kzy (classe1/2) : AB80 = IF(P36="non", AG80, AH80)
                     AG80 (tableau B.1) = 0.6*kyy(classe1/2), 0 si diagramme
                     de Mz nul sur toute la barre
                     AH80 (tableau B.2) = cf. `facteur_kzy_torsion_sensible`
  kzy (classe3/4) : AC80 = IF(P36="non", AG81, AH81), meme bascule
  kzz (classe1/2) : AB81 = IF(AH76="h i", AE80, AF80) — section I/H ou
                     creuse (meme formule que dans flexion_compression_yy.py :
                     a reutiliser depuis `_commun`, pas redupliquer)
  kzz (classe3/4) : AC81 (identique pour les deux formes)
  taux            : X38 = V100
"""
from __future__ import annotations

from ._commun import (CaracteristiquesSection, ParametresBarre, Torseur,
                      facteur_kzy_torsion_sensible, facteur_kzz_creux,
                      facteur_kzz_I_H, moment_max_diagramme)
from .coefficients_cm_b3 import cm_tableau_b3
from .flexion_compression_yy import facteur_kyy


def facteur_kzy_tableau_b1(Cmy: float, lambda_bar_y: float, n_y: float, classe3: bool,
                           diagramme_moment_nul: bool) -> float:
    """kzy — Tableau B.1, membre NON sensible a la torsion (Excel: P36="non",
    jamais le cas par defaut du classeur -- cf. `facteur_kzy` pour le cas
    reel). 0 si le diagramme de Mz est nul sur toute la barre (Excel:
    AG80/AG81 testent D35=D36=D37=0 — garde-fou du classeur, pas une
    exigence EC3).

    classe 1/2 : kzy = 0.6*kyy   (Excel: AG80 = 0.6*AB78)
    classe 3/4 : kzy = 0.8*kyy   (Excel: AG81 = 0.8*AC78)

    kyy vient de `flexion_compression_yy.facteur_kyy` (meme formule,
    reutilisee plutot que redupliquee)."""
    if diagramme_moment_nul:
        return 0.0
    kyy = facteur_kyy(Cmy, lambda_bar_y, n_y, classe3)
    return 0.8 * kyy if classe3 else 0.6 * kyy


def facteur_kzy(Cmy: float, CmLT: float, lambda_bar_y: float, lambda_bar_z: float,
                n_y: float, N_Ed_kN: float, Nb_Rd_z_kN: float, classe3: bool,
                diagramme_moment_nul: bool, sensible_torsion: bool) -> float:
    """kzy, Tableau B.1 ou B.2 selon `sensible_torsion` (Excel: AB80/AC80 =
    IF(P36="non", <B.1>, <B.2>)) -- voir `facteur_kzy_tableau_b1` et
    `_commun.facteur_kzy_torsion_sensible` pour chaque formule."""
    if sensible_torsion:
        return facteur_kzy_torsion_sensible(CmLT, lambda_bar_z, N_Ed_kN, Nb_Rd_z_kN, classe3)
    return facteur_kzy_tableau_b1(Cmy, lambda_bar_y, n_y, classe3, diagramme_moment_nul)


def facteur_kzz(Cmz: float, lambda_bar_z: float, n_z: float, classe3: bool,
                section_I_H: bool = True) -> float:
    """kzz — Tableau B.1 (Excel: AB81 = IF(AH76="h i", AE80, AF80) en
    classe 1/2, AC81 en classe 3/4 quelle que soit la forme).
    Formules partagees avec `flexion_compression_yy.facteur_kyz`, cf.
    `_commun.facteur_kzz_I_H` / `facteur_kzz_creux`."""
    return (facteur_kzz_I_H if section_I_H else facteur_kzz_creux)(
        Cmz, lambda_bar_z, n_z, classe3)


def taux_flechie_comprimee_zz(section: CaracteristiquesSection,
                              parametres: ParametresBarre, torseur: Torseur,
                              resultat_flambement: dict,
                              resultat_deversement: dict) -> dict:
    """Assemble le taux [6.62]. 0 si N_Ed > 0 (traction, "N >0, ok").

    My/Mz, Cmy/Cmz : memes regles que `flexion_compression_yy.py` (repli sur
    My_Ed_kNm/Mz_Ed_kNm/Cmy/Cmz manuels si le diagramme n'est pas fourni).

    Retour :
      {"taux": float, "kzy": float, "kzz": float, "n_z": float}

    (Excel : X38 = V100 = ABS(N_Ed)/(chi_z*NRk/gM1)
                         + kzy*MAX(|My,debut|,|My,milieu|,|My,fin|)/(chi_LT*MyRk/gM1)
                         + kzz*MAX(|Mz,debut|,|Mz,milieu|,|Mz,fin|)/(MzRk/gM1))
    """
    if torseur.N_Ed_kN > 0:          # traction : sans objet
        return {"taux": 0.0, "kzy": 0.0, "kzz": 0.0, "n_z": 0.0}

    # `classe_section` ne peut valoir que 1, 2 ou 3 ici (la classe 4 est
    # refusee plus haut, cf. `SectionClasse4` dans verification.py) : W
    # elastique en classe 3, PLASTIQUE en classe 1 ET 2 (pas seulement 1) ;
    # `classe3` sert aussi de bascule Tableau B.1 "classe 1,2" / "classe 3,4"
    # pour les facteurs kzy/kzz — les deux usages restent corrects une fois
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
        # (Excel: AG80 = IF(AND(D35=0,D36=0,D37=0), 0, 0.6*AB78)) -- garde-fou
        # du classeur sur les 3 points du diagramme, pas sur Mz_Ed seul
        diagramme_moment_nul = (torseur.Mz_debut_kNm == 0.0
                                and torseur.Mz_milieu_kNm == 0.0
                                and torseur.Mz_fin_kNm == 0.0)
    else:
        Cmz = parametres.Cmz
        diagramme_moment_nul = torseur.Mz_Ed_kNm == 0.0

    kzy = facteur_kzy(Cmy, parametres.CmLT, resultat_flambement["lambda_bar_y"],
                      resultat_flambement["lambda_bar_z"], n_y, torseur.N_Ed_kN,
                      resultat_flambement["Nb_Rd_z_kN"], classe3,
                      diagramme_moment_nul, parametres.sensible_torsion)
    kzz = facteur_kzz(Cmz, resultat_flambement["lambda_bar_z"], n_z, classe3,
                      section.est_section_I_H)

    Wz = section.Wzel if classe3 else section.Wzpl
    Mz_Rd = Wz * parametres.fy / parametres.gamma_M1 / 1e6   # kN.m (Excel: W11/W12)

    My_max = moment_max_diagramme(torseur.My_debut_kNm, torseur.My_milieu_kNm,
                                  torseur.My_fin_kNm, torseur.My_Ed_kNm)
    Mz_max = moment_max_diagramme(torseur.Mz_debut_kNm, torseur.Mz_milieu_kNm,
                                  torseur.Mz_fin_kNm, torseur.Mz_Ed_kNm)

    taux = (n_z
            + kzy * My_max / resultat_deversement["Mb_Rd_kNm"]
            + kzz * Mz_max / Mz_Rd)

    return {"taux": taux, "kzy": kzy, "kzz": kzz, "n_z": n_z}
