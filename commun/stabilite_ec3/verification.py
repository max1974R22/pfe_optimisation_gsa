# -*- coding: utf-8 -*-
"""Assemble les 4 taux (flambement, deversement, [6.61], [6.62]) et retient
le cas dimensionnant — equivalent de `Calcul!L4` (= MAX(X35:X38)) et de
`commun.excel_bridge.stabilite.SessionStabilite.verifier`, sans Excel.
"""
from __future__ import annotations

from ._commun import CaracteristiquesSection, ParametresBarre, Torseur
from .deversement import taux_deversement
from .flambement import taux_flambement
from .flexion_compression_yy import taux_flechie_comprimee_yy
from .flexion_compression_zz import taux_flechie_comprimee_zz

# libelles des cas dimensionnants, alignes sur
# `commun.excel_bridge.stabilite.CAS_STABILITE` (memes cles, meme ordre)
CAS_STABILITE = {
    "taux_flambement": "Flambement",
    "taux_deversement": "Déversement",
    "taux_flechie_comprimee_yy": "Fléchi + comprimé yy",
    "taux_flechie_comprimee_zz": "Fléchi + comprimé zz",
}


class SectionClasse4(ValueError):
    """Section de classe 4 (EN 1993-1-1 §5.5) : NON VERIFIEE par ce module.

    Une section de classe 4 voile localement avant d'atteindre sa resistance
    elastique : l'EC3 (§6.3.2.1(1), §6.3.3(1)) exige alors les caracteristiques
    EFFICACES de la section (aire efficace, module efficace, decalage du centre
    de gravite — EN 1993-1-5) pour TOUTES les formules de resistance a l'appui
    (deversement, flexion composee [6.61]/[6.62]) — pas seulement le choix
    Wel/Wpl. Ce module ne les calcule pas : plutot que de se rabattre sur Wpl
    (ce qu'il faisait implicitement avant cette exception, en traitant toute
    section "pas classe 3" comme classe 1/2 — SURESTIMATION dangereuse pour une
    classe 4) ou sur Wel (encore non conservatif, une section efficace est plus
    petite que la section brute), il refuse la verification."""


def verifier_stabilite(section: CaracteristiquesSection, parametres: ParametresBarre,
                       torseur: Torseur) -> dict:
    """Verifie la stabilite EC3 §6.3 complete d'une barre.

    Retour :
      {"taux_stabilite": float, "cas": str, "taux": {libelle: float, ...},
       "classe": int, "detail": {...}}

    `detail` porte les quatre resultats intermediaires complets (chi, elancements
    reduits, Mcr, Mb,Rd, C1, C2, kyy/kyz/kzy/kzz) : le taux seul ne permet pas
    de refaire le calcul a la main, ni de pre-remplir le classeur Predim avec
    les C1/C2 qu'on vient de calculer (cf. `appv2/server.py::ouvrir_excel_barre`).

    Leve `SectionClasse4` si `parametres.classe_section == 4` — AVANT tout
    calcul (aucun des 4 taux n'est evalue) : c'est le SEUL point d'entree
    public du module, donc le seul endroit ou cette regle doit etre imposee.
    Une fois passe ce garde-fou, `deversement.py`/`flexion_compression_yy.py`/
    `flexion_compression_zz.py` savent que `classe_section` ne peut plus valoir
    que 1, 2 ou 3 — leur choix de module (W plastique en classe 1/2, elastique
    en classe 3, cf. `classe3 = parametres.classe_section == 3`) est donc exact,
    et non plus un repli implicite sur "tout ce qui n'est pas 3".

    (Excel : L4 = MAX(X35:X38), avec les 4 taux individuels en X35:X38 — le
    classeur, lui, ne refuse jamais une classe 4 : il continue avec Wpl, ce qui
    le rend NON CONSERVATIF sur ce cas precis. Ce module s'en ecarte
    deliberement — cf. `commun/stabilite_ec3/README.md`.)
    """
    if parametres.classe_section == 4:
        raise SectionClasse4(
            "Section de classe 4 : verification EC3 §6.3 non geree (modules "
            "efficaces requis, EN 1993-1-5) — a verifier a la main.")
    resultat_flambement = taux_flambement(section, parametres, torseur)
    resultat_deversement = taux_deversement(section, parametres, torseur)
    resultat_yy = taux_flechie_comprimee_yy(section, parametres, torseur,
                                            resultat_flambement, resultat_deversement)
    resultat_zz = taux_flechie_comprimee_zz(section, parametres, torseur,
                                            resultat_flambement, resultat_deversement)

    taux = {
        "taux_flambement": resultat_flambement["taux"],
        "taux_deversement": resultat_deversement["taux"],
        "taux_flechie_comprimee_yy": resultat_yy["taux"],
        "taux_flechie_comprimee_zz": resultat_zz["taux"],
    }
    cle_max = max(taux, key=taux.get)

    return {
        "taux_stabilite": taux[cle_max],
        "cas": CAS_STABILITE[cle_max],
        "taux": {CAS_STABILITE[cle]: valeur for cle, valeur in taux.items()},
        "classe": parametres.classe_section,
        "detail": {"flambement": resultat_flambement,
                   "deversement": resultat_deversement,
                   "flechie_comprimee_yy": resultat_yy,
                   "flechie_comprimee_zz": resultat_zz},
    }
