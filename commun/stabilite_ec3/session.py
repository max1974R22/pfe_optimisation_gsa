# -*- coding: utf-8 -*-
"""`SessionStabilitePython` — la stabilite EC3 §6.3 avec la MEME interface que
`commun/excel_bridge/stabilite.py::SessionStabilite`, mais sans Excel.

Meme API (`open` / `verifier` / `close`, utilisable en context manager), meme
dict d'ENTREE (les cles `io_map` que produit `appv2/server.py::_entrees_classeur`)
et meme dict de SORTIE (`element`, `taux_stabilite`, `cas`, `taux`, `classe`,
`profil_substitue`). Basculer d'un moteur a l'autre ne demande donc que de
changer la classe instanciee — c'est tout ce qu'a coute la bascule d'appv2.

CE QU'ELLE FAIT DE PLUS QUE LE CLASSEUR :

  - elle CALCULE C1 et C2 (§3.5 de l'Annexe MCR) depuis le diagramme de moment
    de la barre, au lieu de lire deux cellules saisies a la main. Les valeurs
    retenues sont renvoyees (`C1`, `C2`) pour que la page puisse les afficher
    et les recopier dans le classeur quand on veut verifier une barre a la main ;
  - elle calcule aussi la CLASSE de section (§5.5, `classe_section.py`), que le
    classeur fournissait et que le module recevait jusqu'ici en entree.

CE QU'ELLE NE FAIT PAS, contrairement au classeur : le repli « section absente
de l'onglet Predim » (`BeamWorkbook._section_au_dessus`). Il n'a plus lieu
d'etre — le catalogue EST la source, il ne peut plus y avoir de desaccord entre
lui et une copie dans un classeur. Le repli de `_profil_predim` pour les
profils saisis a la main (`STD CHS 323,9 5,4`), lui, est en amont et reste en
place : `profil_nom` est toujours une designation de catalogue quand on arrive
ici.

CE QU'ELLE IMPOSE : k = k_w = 1. Les formules analytiques de C1/C2 du §3.5 ne
valent que dans ce cas (« Les valeurs de C1 et C2 ont ete determinees pour
kz = 1 et kw = 1 », Annexe MCR). Une longueur de deversement differente de la
portee s'exprime par `longueur_deversement_m`, qui reste libre : k*L et L_dev
jouent le meme role dans Mcr, il n'y a donc rien de perdu.

CE QU'ELLE REFUSE : une section de CLASSE 4. Le module de flexion utilise pour
les contraintes liees au moment (deversement, [6.61], [6.62]) est PLASTIQUE en
classe 1 et 2, ELASTIQUE en classe 3 — et la classe 4 (modules efficaces,
EN 1993-1-5, non implementes ici) n'est PAS calculee du tout : `verifier_barre`
renvoie une erreur plutot qu'un taux, cf. `SectionClasse4`.
"""
from __future__ import annotations

from ._commun import ParametresBarre, Torseur
from .classe_section import classe_section
from .section_catalogue import NUANCE_DEFAUT, SectionInconnue, section_catalogue
from .verification import CAS_STABILITE, SectionClasse4, verifier_stabilite

# k et kw imposes, cf. l'en-tete du module
K_DEVERSEMENT = 1.0
KW_DEVERSEMENT = 1.0

# valeurs de `repartition_charge` acceptees par `coefficients_cm_b3`
_REPARTITIONS = ("uniforme", "concentree", "noeuds_deplacables")


def _f(entree: dict, cle: str, defaut: float = 0.0) -> float:
    v = entree.get(cle)
    try:
        return float(v)
    except (TypeError, ValueError):
        return defaut


def verifier_barre(entree: dict) -> dict:
    """Verifie UNE barre. `entree` : les cles `io_map` de `_entrees_classeur`
    (+ `element`). Ne leve jamais : un echec part dans `erreur`, comme
    `SessionStabilite.verifier`."""
    eid = entree.get("element")
    try:
        portee = _f(entree, "portee_m")
        nuance = str(entree.get("nuance_acier") or NUANCE_DEFAUT)
        section, fy, fy_nominale = section_catalogue(
            str(entree["profil_famille"]), str(entree["profil_nom"]), nuance)

        torseur = Torseur(
            N_Ed_kN=_f(entree, "torseur_N_ELU_kN"),
            My_Ed_kNm=_f(entree, "torseur_My_ELU_kNm"),
            Mz_Ed_kNm=_f(entree, "torseur_Mz_ELU_kNm"),
            My_debut_kNm=_f(entree, "my_debut_kNm"),
            My_milieu_kNm=_f(entree, "my_milieu_kNm"),
            My_fin_kNm=_f(entree, "my_fin_kNm"),
            Mz_debut_kNm=_f(entree, "mz_debut_kNm"),
            Mz_milieu_kNm=_f(entree, "mz_milieu_kNm"),
            Mz_fin_kNm=_f(entree, "mz_fin_kNm"))

        # classe d'abord : elle decide des modules que la verification de
        # stabilite utilisera pour les contraintes liees au moment — plastique
        # en classe 1/2, elastique en classe 3 ; une classe 4 est refusee par
        # `verifier_stabilite` (cf. SectionClasse4), jamais calculee ici
        classe = classe_section(section, torseur, fy_nominale)

        repartition = str(entree.get("repartition_charge") or "uniforme")
        parametres = ParametresBarre(
            fy=fy,
            # les longueurs valent la portee par defaut, comme la formule
            # '=Lo' des cellules G15:G17 du classeur
            Lcr_y_m=_f(entree, "longueur_flambement_y_m", portee) or portee,
            Lcr_z_m=_f(entree, "longueur_flambement_z_m", portee) or portee,
            L_deversement_m=_f(entree, "longueur_deversement_m", portee) or portee,
            k=K_DEVERSEMENT, kw=KW_DEVERSEMENT,
            classe_section=classe["classe"],
            # « sensible aux deformations par torsion » : defaut "oui" du
            # classeur (P36), qu'appv2 n'a jamais expose
            sensible_torsion=str(
                entree.get("sensible_deformation_torsion") or "oui").lower() != "non",
            repartition_charge=(repartition if repartition in _REPARTITIONS
                                else "uniforme"))

        r = verifier_stabilite(section, parametres, torseur)
        deversement = r["detail"]["deversement"]
        return {
            "element": eid,
            "taux_stabilite": round(r["taux_stabilite"], 3),
            "cas": r["cas"],
            "taux": {libelle: round(v, 3) for libelle, v in r["taux"].items()},
            "classe": classe["classe"],
            # ce que le classeur ne savait pas produire : les coefficients
            # reellement utilises, pour l'affichage et pour pre-remplir le
            # classeur quand on verifie la barre a la main
            "C1": round(deversement["C1"], 4),
            "C2": round(deversement["C2"], 4),
            "k": K_DEVERSEMENT, "kw": KW_DEVERSEMENT,
            "Mcr_kNm": round(deversement["Mcr_kNm"], 2),
            "fy_MPa": fy,
            "classe_ame": classe["classe_ame"],
            "classe_semelle": classe["classe_semelle"],
        }
    except (SectionInconnue, SectionClasse4) as e:
        return {"element": eid, "erreur": str(e)}
    except Exception as e:                                      # noqa: BLE001
        return {"element": eid, "erreur": f"{type(e).__name__} : {e}"}


class SessionStabilitePython:
    """Copie conforme de l'interface de `SessionStabilite`, sans etat.

    `open()` et `close()` ne font rien : il n'y a ni processus a lancer, ni
    classeur a copier, ni verrou a prendre. Ils existent pour que les appelants
    (`appv2/server.py`, trois endroits) gardent exactement la meme forme d'un
    moteur a l'autre — et pour qu'un retour en arriere reste une ligne.
    """

    def __init__(self, visible: bool = False):
        # `visible` ignore : il n'y a pas de fenetre a montrer. L'argument est
        # garde pour que la signature reste interchangeable.
        self.visible = visible

    def open(self) -> "SessionStabilitePython":
        return self

    def verifier(self, barre: dict) -> dict:
        return verifier_barre(barre)

    def close(self) -> None:
        return None

    def __enter__(self) -> "SessionStabilitePython":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()


def verifier_stabilites(barres: list[dict], log=lambda s: None,
                        progress=None) -> list[dict]:
    """Equivalent de `commun.excel_bridge.stabilite.verifier_stabilites` — une
    ligne par barre, un echec n'interrompt pas les autres."""
    resultats = []
    for i_b, b in enumerate(barres):
        r = verifier_barre(b)
        resultats.append(r)
        log(f"barre {r.get('element')} : "
            + (f"{r.get('taux_stabilite')}" if "taux" in r else r.get("erreur", "?")))
        if progress:
            progress(i_b + 1, len(barres))
    return resultats


__all__ = ["CAS_STABILITE", "SessionStabilitePython", "verifier_barre",
           "verifier_stabilites", "K_DEVERSEMENT", "KW_DEVERSEMENT"]
