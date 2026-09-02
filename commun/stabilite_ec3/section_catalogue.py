# -*- coding: utf-8 -*-
"""`CaracteristiquesSection` depuis le CATALOGUE, sans Excel.

Le classeur Predim lisait la geometrie d'un profil dans l'onglet de sa famille
(`Calcul!AC12:AC34`, par VLOOKUP sur un index). Ces onglets ont ete remplis
depuis `catalogues/*.csv` (cf. `catalogues/scripts/load_in_predim_acier.py`) :
on repart donc de la MEME source, ce qui garantit les memes chiffres sans
ouvrir Excel.

DEUX GRANDEURS NE SONT PAS DANS LE CSV et sont reconstruites ici, exactement
comme le classeur les obtient :

  Iw (inertie de gauchissement)  0.25*(h-tf)^2*Iz pour un profil en I ou H —
                                 formule de l'Annexe MCR §2, et formule
                                 litterale de la colonne U de l'onglet IPN du
                                 classeur ; verifiee au chiffre pres contre les
                                 valeurs figees des onglets IPE et HE.
                                 NULLE pour un tube (colonne U vide cote
                                 classeur) : un profil creux ne gauchit pas.
  courbes de flambement          Tableau 6.2, exactement les formules des
                                 colonnes X et Y des onglets du classeur
                                 (cf. `courbes_flambement`).

`tf` est absent du CSV pour les tubes (CHS et RHS/SHS n'ont qu'une epaisseur) ;
le classeur, lui, recopie l'epaisseur dans les deux colonnes. On fait pareil :
`tf = tw`. Idem pour `b` d'un CHS, laisse vide des deux cotes — c'est ce qui
rend `courbe_deversement` indefini, sans consequence puisqu'un CHS ne deverse
pas (cf. `deversement.py`).

CE MODULE PORTE AUSSI la resolution PROFIL GSA -> (feuille, designation)
catalogue (`profil_predim`, `nom_catalogue_par_dimensions`, `FAMILLES_CLASSEUR`,
`ONGLET_PREDIM`) : deplacee ici depuis `appv2/server.py` le 01/09/2026 quand
`commun/criteres.py` en a eu besoin a son tour (classification EC3 §5.5 du
critere ELU « combine », qui a besoin de la MEME geometrie que la stabilite) —
`section_catalogue()` en etait deja le seul point d'entree, il n'y avait pas de
raison que la fonction qui lui fournit `(feuille, nom)` reste ailleurs.
`appv2/server.py` importe desormais ces noms d'ici au lieu de les definir.
"""
from __future__ import annotations

from commun.catalogues import charger_catalogue
from commun.dimensionner import DimensionnementError
from commun.ec3 import geometrie

from ._commun import CaracteristiquesSection, drapeaux_famille

# Limite elastique NOMINALE de chaque nuance, et sa valeur reduite pour les
# fortes epaisseurs — Tableau 3.1 (Excel : plage `Calcul!AF4:AH9`, colonnes
# « t<40 mm » et « t>40 mm »).
NUANCES = {
    "S235": (235.0, 215.0), "S275": (275.0, 255.0), "S355": (355.0, 335.0),
    "S420": (420.0, 390.0), "S460": (460.0, 430.0),
}
NUANCE_DEFAUT = "S235"


def fy_nuance(nuance: str, tf_mm: float) -> tuple[float, float]:
    """(fy de calcul, fy nominale) en MPa, pour une nuance et une epaisseur de
    semelle — Excel : `AH2 = IF(tf<=40, colonne 2, colonne 3)` pour la premiere,
    `AG2 = colonne 2` pour la seconde.

    Les deux ne servent pas a la meme chose, et le classeur les distingue :
      - la fy de CALCUL (reduite au-dela de 40 mm) entre dans toutes les
        resistances ;
      - la fy NOMINALE decide de la courbe de flambement (le test « = 460 »)
        et de epsilon dans la classification (`Calcul classe`!D6 lit bien la
        colonne « t<40 mm », meme pour une semelle epaisse).
    """
    nominale, reduite = NUANCES.get(str(nuance).upper(), NUANCES[NUANCE_DEFAUT])
    return (reduite if tf_mm > 40.0 else nominale), nominale


def courbes_flambement(famille: str, h_mm: float, b_mm: float, tf_mm: float,
                       fy_nominale: float) -> tuple[str, str]:
    """(courbe y-y, courbe z-z) du Tableau 6.2 — port des colonnes X et Y des
    onglets du classeur.

    Tubes (CHS, RHS/SHS) : « a », ou « a0 » en S460 — profils FINIS A CHAUD
    (`=IF(fy=460,"a0","a")` dans les deux colonnes). Un tube forme a froid
    releverait de la courbe c : le classeur ne le prevoit pas, on ne le prevoit
    pas non plus.

    Profils en I ou H lamines : la formule complete des onglets HE et HD, qui
    depend de h/b et de l'epaisseur de semelle. Elle couvre aussi IPE et IPN,
    dont les onglets portent la version simplifiee (`a`/`b`, ou `a0`/`a0` en
    S460) : leurs h/b valent tous plus de 1,2 et leurs semelles moins de 40 mm,
    la formule generale y redonne exactement le meme couple.
    """
    if not drapeaux_famille(famille)["est_section_I_H"]:
        courbe = "a0" if fy_nominale == 460 else "a"
        return courbe, courbe
    trapu = bool(b_mm) and (h_mm / b_mm) <= 1.2
    if trapu:
        if tf_mm <= 100:
            return ("a", "a") if fy_nominale == 460 else ("b", "c")
        return ("c", "c") if fy_nominale == 460 else ("d", "d")
    if tf_mm <= 40:
        return ("a0", "a0") if fy_nominale == 460 else ("a", "b")
    return ("a", "a") if fy_nominale == 460 else ("b", "c")


def inertie_gauchissement(famille: str, h_mm: float, tf_mm: float,
                          Iz_mm4: float) -> float:
    """Iw en mm6. `0.25*(h-tf)^2*Iz` pour un I/H (Annexe MCR §2), 0 pour un
    tube. Verifie contre les valeurs figees du classeur : IPEAA80 -> 93 270 285
    mm6, HE100AA -> 1 683 185 062,5 mm6."""
    if not drapeaux_famille(famille)["est_section_I_H"]:
        return 0.0
    return 0.25 * (h_mm - tf_mm) ** 2 * Iz_mm4


class SectionInconnue(LookupError):
    """Designation absente du catalogue de sa famille."""


# ==========================================================================
#  Profil GSA -> (feuille, designation) catalogue — ce que `section_catalogue`
#  attend en entree. Deplace depuis `appv2/server.py` (cf. en-tete du module) :
#  sert a la fois a choisir le catalogue/lire les caracteristiques de section
#  et a l'ONGLET du classeur Predim quand on ouvre celui-ci a la main. Les deux
#  partagent les memes noms de famille, ce qui est voulu — les onglets du
#  classeur ont ete remplis depuis ce meme catalogue.
# ==========================================================================
FAMILLES_CLASSEUR = ("IPE", "IPN", "CHS", "RHS", "SHS", "HD", "HE", "UB", "UC", "W")

# SHS (carre), UB (Universal Beam) et UC (Universal Column) n'ont pas d'onglet
# dedie dans le classeur Predim : ranges TELS QUELS (designation inchangee)
# dans les onglets RHS, HE et HD respectivement (cf. `profil_predim`).
# W (AISC) N'EST PAS dans cette table : catalogue dedie (catalogues/W.csv,
# feuille "W"), pas d'onglet Predim non plus, mais pas de translation de
# famille — contrairement a SHS/UB/UC, une section W reste "W" de bout en
# bout (optimisation ET stabilite cherchent dans catalogues/W.csv, jamais
# dans HE). Le classeur Excel (bouton "Ouvrir dans Excel") ne sait donc pas
# verifier une barre en W — seul le moteur Python (commun/stabilite_ec3) le
# peut, ce qui est le cas par defaut depuis le 01/09/2026 (cf. README.md).
ONGLET_PREDIM = {"SHS": "RHS", "UB": "HE", "UC": "HD"}


def nom_catalogue_par_dimensions(feuille: str, h: float, t: float,
                                 b: float | None = None) -> str:
    """Plus petite section du catalogue `feuille` (masse croissante, cf.
    commun/catalogues.py) dont les dimensions COUVRENT celles demandees (h/b/t
    en m) -> sa designation ('CHS355.6x8', 'RHS150x100x8'...).

    Repli conservatif pour un profil 'STD ...' saisi a la main dans GSA (pas
    de designation catalogue a chercher dans l'onglet Predim, contrairement a
    un profil 'CAT ...') : SUR-dimensionne plutot que d'echouer — meme principe
    que `BeamWorkbook._section_au_dessus` pour un profil catalogue absent de
    l'onglet."""
    for r in charger_catalogue(feuille):
        try:
            h_cat, t_cat = float(r["h_m"]), float(r["tw_m"])
        except (TypeError, ValueError):
            continue
        if h_cat + 1e-9 < h or t_cat + 1e-9 < t:
            continue
        if b is not None:
            try:
                b_cat = float(r["b_m"] or h_cat)
            except (TypeError, ValueError):
                b_cat = h_cat
            if b_cat + 1e-9 < b:
                continue
        return r["nom"]
    raise DimensionnementError(
        f"Aucune section du catalogue {feuille!r} ne couvre les dimensions "
        f"demandees ({h * 1000:.1f} x {(b or h) * 1000:.1f} x {t * 1000:.1f} mm).")


def profil_predim(profil_gsa: str) -> tuple[str, str, str | None]:
    """'CAT IPE-AM IPE80 20170912' -> ('IPE', 'IPE80', None) pour le classeur
    Predim (feuille catalogue = onglet Predim). Le 3e element est une NOTE de
    repli (designation catalogue utilisee en remplacement) quand le profil GSA
    est saisi A LA MAIN ('STD CHS 323,9 5,4'...) plutot que pris dans un
    catalogue : ce genre de profil n'a par construction AUCUNE designation
    catalogue, donc aucune ligne ou lire ses caracteristiques de section —
    sans ce repli, TOUTE barre dont la section est saisie a la main echouait
    la stabilite ("Profil non transposable"), meme quand une section
    catalogue plus grande couvrant ses dimensions existe. Bug repere sur le
    modele gymnase (240320_gymnase_v27_CG.gwb), dont plusieurs sections
    tubulaires sont saisies en 'STD CHS d t' : la stabilite n'y etait JAMAIS
    calculee.

    SHS/UB/UC : cf. `ONGLET_PREDIM` — seul l'ONGLET change, jamais la
    designation. Verifie sur le classeur courant : 251 tubes carres dans
    l'onglet RHS, tous nommes 'SHS...', aucun 'RHS<c>x<c>x...'."""
    parts = (profil_gsa or "").split()
    if len(parts) >= 3 and parts[0] == "CAT":
        nom = parts[2]
        famille = next((f for f in FAMILLES_CLASSEUR if nom.upper().startswith(f)), None)
        if famille is None:
            raise DimensionnementError(
                f"Aucune famille de sections connue pour le profil {nom!r} : "
                "ni catalogue de caractéristiques, ni onglet Predim.")
        return ONGLET_PREDIM.get(famille, famille), nom, None

    g = geometrie(profil_gsa)
    if g is None:
        raise DimensionnementError(
            f"Profil non transposable vers une famille catalogue : {profil_gsa!r}")
    if g["forme"] == "CHS":
        nom = nom_catalogue_par_dimensions("CHS", h=g["d"], t=g["t"])
        return "CHS", nom, nom
    if g["forme"] == "RHS":
        # designation catalogue gardee telle quelle, SHS compris (cf. supra)
        nom = nom_catalogue_par_dimensions("RHS", h=g["h"], t=g["t"], b=g["b"])
        return "RHS", nom, nom
    raise DimensionnementError(
        f"Aucune famille de sections connue pour le profil {profil_gsa!r}.")


def _mm(valeur, defaut: float = 0.0) -> float:
    """m -> mm (les CSV sont en SI ; le classeur et ce paquet travaillent en
    mm). Cellule vide -> `defaut`."""
    try:
        return float(valeur) * 1000.0
    except (TypeError, ValueError):
        return defaut


def _normaliser(nom: str) -> str:
    """Comparaison de designations insensible aux espaces, a la casse, a la
    virgule decimale et au zero final d'une epaisseur entiere — memes regles
    que `commun/excel_bridge/bridge.py::_normaliser_designation`, pour que les
    deux moteurs acceptent exactement les memes noms."""
    from commun.excel_bridge.bridge import _normaliser_designation
    return _normaliser_designation(nom)


_CACHE: dict[str, dict[str, dict]] = {}


def _index(feuille: str) -> dict[str, dict]:
    """{designation normalisee: ligne du catalogue}, mise en cache — la
    stabilite est appelee des milliers de fois par optimisation, relire et
    reparser le CSV a chaque barre serait le seul cout notable du module."""
    if feuille not in _CACHE:
        _CACHE[feuille] = {_normaliser(r["nom"]): r for r in charger_catalogue(feuille)}
    return _CACHE[feuille]


def section_catalogue(feuille: str, nom: str,
                      nuance: str = NUANCE_DEFAUT) -> tuple[CaracteristiquesSection, float, float]:
    """(section, fy de calcul, fy nominale) pour une designation de catalogue.

    `feuille` : nom du catalogue ET onglet Predim de la famille — 'IPE', 'IPN',
    'HE', 'HD', 'CHS', 'RHS' (cf. `appv2/server.py::_ONGLET_PREDIM` : un SHS
    est dans 'RHS', un UB dans 'HE', un UC dans 'HD', sous leur nom d'origine).

    Leve `SectionInconnue` si la designation n'y figure pas — a l'appelant de
    decider du repli (le classeur, lui, substituait la section superieure la
    plus proche, cf. `BeamWorkbook._section_au_dessus`).
    """
    ligne = _index(feuille).get(_normaliser(nom))
    if ligne is None:
        raise SectionInconnue(
            f"Désignation absente du catalogue {feuille!r} : {nom!r}")

    tw = _mm(ligne["tw_m"])
    tf = _mm(ligne["tf_m"], defaut=tw)      # tubes : une seule epaisseur
    h = _mm(ligne["h_m"])
    b = _mm(ligne["b_m"])                   # 0 pour un CHS (colonne vide)
    Iz = float(ligne["Izz_m4"]) * 1e12
    fy, fy_nominale = fy_nuance(nuance, tf)
    cy, cz = courbes_flambement(feuille, h, b, tf, fy_nominale)

    section = CaracteristiquesSection(
        nom=ligne["nom"], h=h, b=b, tw=tw, tf=tf,
        A=float(ligne["aire_m2"]) * 1e6,
        Iy=float(ligne["Iyy_m4"]) * 1e12, Iz=Iz,
        Wyel=float(ligne["Wel_y_m3"]) * 1e9, Wypl=float(ligne["Wpl_y_m3"]) * 1e9,
        Wzel=float(ligne["Wel_z_m3"]) * 1e9, Wzpl=float(ligne["Wpl_z_m3"]) * 1e9,
        iy=_mm(ligne["iy_m"]), iz=_mm(ligne["iz_m"]),
        It=float(ligne["J_m4"]) * 1e12,
        Iw=inertie_gauchissement(feuille, h, tf, Iz),
        courbe_flambement_y=cy, courbe_flambement_z=cz,
        r=_mm(ligne.get("r_m")),
        **drapeaux_famille(feuille))
    return section, fy, fy_nominale
