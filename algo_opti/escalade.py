# -*- coding: utf-8 -*-
"""
Algorithme « escalade » — dimensionnement guide par gabarit de depart, plutot
que force brute sur tout le catalogue (algo_opti/brut_force.py) ou recherche
aleatoire (algo_opti/genetique.py).

DEPART (regles de conception, configurables via cfg) : chaque famille demarre
sur le profil le PLUS FIN de la serie (echelon A pour HE — HEA est toujours
le plus fin a hauteur egale ; epaisseur de paroi minimale pour RHS/SHS), a
une hauteur nominale = L / cfg["ratio_hauteur_depart"] (defaut 20) et, pour
RHS (largeur reglable independamment), une largeur = hauteur /
cfg["ratio_largeur_depart"] (defaut 3). L = longueur de LA BARRE (la plus
longue de la famille si elle en a plusieurs), PAS la portee globale du
modele : une famille faite d'une seule barre de 1 m demarre donc a 5 cm de
hauteur, la largeur la plus proche de 5/3 cm, epaisseur minimale — jamais un
repere calcule sur la portee totale de la structure.

DEUX PHASES (cf. `optimiser`) :
    1. CROISSANCE SEULE, jusqu'a ce que TOUTES les familles verifient ELU ET
       ELS SIMULTANEMENT (pas seulement celle qu'on vient d'ajuster — sinon
       le graphe de progression peut afficher un point « faisable » alors
       qu'une autre famille, non reevaluee a cet instant, est toujours en
       defaut). A chaque passe, CHAQUE famille encore en defaut est escaladee
       d'UN cran — priorite EPAISSEUR (A -> B -> M pour HE ; palier de paroi
       superieur pour RHS/SHS, plafonne a cfg["epaisseur_max_mm"], defaut
       10 mm), puis LARGEUR (RHS uniquement), puis HAUTEUR (plafonnee a
       cfg["hauteur_max_m"], defaut 0.5 m) — jusqu'a satisfaire les criteres
       ou epuiser les crans disponibles (repli : la plus grosse configuration
       atteignable, famille marquee en echec).
    2. ALLEGEMENT, UNIQUEMENT si la phase 1 a converge (sinon la structure
       n'est pas encore entierement faisable — inutile d'essayer de
       l'alleger) : chaque famille est allegee — priorite LARGEUR puis
       EPAISSEUR (ordre inverse) — tant que la structure ENTIERE (toutes
       familles, pas seulement celle allegee) reste faisable, sinon la
       tentative est annulee.
Comme les familles interagissent (raideur, poids propre), plusieurs passes
sont necessaires dans chaque phase ; la contrainte de stabilite EC3, si
activee, est verifiee en BOUCLE EXTERNE, APRES les deux phases (meme
mecanique que brut_force : une passe Excel sur les barres gouvernantes,
escalade d'un cran les familles instables, reconverge).
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from gsa_bridge.bridge import GsaModel
from dimensionner import DimensionnementError
from . import _commun

LIBELLE = "Escalade (gabarit)"
DESCRIPTION = ("Part du profil le plus fin (hauteur ~ portée/20, largeur "
               "telle que h/b ~ 3 pour RHS) ; les familles qui ne passent pas "
               "sont épaissies puis élargies puis rehaussées, celles qui "
               "passent sont allégées — jusqu'à convergence ELU/ELS/stabilité.")

CATALOGUES = ROOT / "catalogues"


# ============================================================ navigateur HE
class _EtatHE(NamedTuple):
    hauteur: int    # nominal, mm (ex. 200 pour HEA200/HEB200/HEM200)
    echelon: int    # indice dans NavigateurHE.ECHELONS (0=A, 1=B, 2=M)


class NavigateurHE:
    """Navigue le catalogue HE-AM.csv (HEA/HEB/HEM confondus) le long de deux
    axes : l'echelon d'epaisseur (A -> B -> M, a hauteur NOMINALE fixe — les
    hauteurs REELLES h_m different legerement entre A/B/M du meme nominal,
    d'ou le regroupement par le nombre du nom plutot que par h_m) et la
    hauteur nominale (aucun axe largeur independant : la largeur suit le
    profil choisi)."""

    ECHELONS = ("A", "B", "M")

    def __init__(self):
        with (CATALOGUES / "HE-AM.csv").open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        self._par_hauteur: dict[int, dict[str, dict]] = {}
        for r in rows:
            m = re.fullmatch(r"HE(\d+)([ABM])", r["nom"])
            if not m:
                continue
            self._par_hauteur.setdefault(int(m.group(1)), {})[m.group(2)] = r
        if not self._par_hauteur:
            raise DimensionnementError("Catalogue HE-AM.csv illisible ou vide.")
        self._hauteurs = sorted(self._par_hauteur)

    def depart(self, L: float, echelon_min: str, hauteur_max_m: float | None,
              ratio_hauteur: float = 20.0) -> _EtatHE:
        cible_mm = (L / ratio_hauteur) * 1000
        candidats = [h for h in self._hauteurs
                    if echelon_min in self._par_hauteur[h]
                    and (hauteur_max_m is None or h / 1000 <= hauteur_max_m)]
        if not candidats:
            raise DimensionnementError(
                "Algorithme escalade : aucune section HE"
                + (f" <= {hauteur_max_m:g} m de hauteur" if hauteur_max_m else "")
                + " disponible pour le depart.")
        h0 = min(candidats, key=lambda h: abs(h - cible_mm))
        return _EtatHE(h0, self.ECHELONS.index(echelon_min))

    def section(self, etat: _EtatHE) -> dict:
        return self._par_hauteur[etat.hauteur][self.ECHELONS[etat.echelon]]

    def plus_epais(self, etat: _EtatHE, epaisseur_max_mm: float | None = None) -> _EtatHE | None:
        for e in range(etat.echelon + 1, len(self.ECHELONS)):
            if self.ECHELONS[e] in self._par_hauteur[etat.hauteur]:
                candidate = self._par_hauteur[etat.hauteur][self.ECHELONS[e]]
                # tf croit avec l'echelon (A -> B -> M) a hauteur nominale fixe :
                # si ce palier depasse deja la limite, les suivants aussi -> arret
                if (epaisseur_max_mm is not None
                        and float(candidate["tf_m"]) * 1000 > epaisseur_max_mm):
                    return None
                return etat._replace(echelon=e)
        return None

    def plus_fin(self, etat: _EtatHE, echelon_min: int = 0) -> _EtatHE | None:
        for e in range(etat.echelon - 1, echelon_min - 1, -1):
            if self.ECHELONS[e] in self._par_hauteur[etat.hauteur]:
                return etat._replace(echelon=e)
        return None

    def plus_large(self, etat: _EtatHE) -> _EtatHE | None:
        return None    # pas d'axe largeur independant pour HE

    def plus_etroit(self, etat: _EtatHE) -> _EtatHE | None:
        return None

    def plus_haut(self, etat: _EtatHE, hauteur_max_m: float | None) -> _EtatHE | None:
        suivantes = [h for h in self._hauteurs if h > etat.hauteur
                    and self.ECHELONS[etat.echelon] in self._par_hauteur[h]
                    and (hauteur_max_m is None or h / 1000 <= hauteur_max_m)]
        return etat._replace(hauteur=min(suivantes)) if suivantes else None


# ===================================================== navigateur tubulaire
class _EtatTube(NamedTuple):
    hauteur: float          # h_m (diametre pour CHS, cote pour SHS)
    largeur: float | None   # b_m (None : CHS/SHS, b = h implicite)
    rang: int               # indice (epaisseur croissante) dans le gabarit (hauteur,largeur)


class NavigateurTubulaire:
    """Navigue un catalogue CHS/RHS/SHS le long de trois axes : epaisseur de
    paroi (a gabarit hauteur x largeur fixe — les lignes du catalogue y sont
    triees par masse croissante), largeur (RHS seulement — CHS/SHS ont b = h,
    aucun axe largeur independant) et hauteur (diametre/cote nominal)."""

    def __init__(self, catalogue: Path, largeur_ajustable: bool):
        if not catalogue.exists():
            raise DimensionnementError(f"Catalogue introuvable : {catalogue}")
        with catalogue.open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        self.largeur_ajustable = largeur_ajustable
        self._gabarits: dict[tuple[float, float | None], list[dict]] = {}
        for r in rows:
            h = round(float(r["h_m"]), 5)
            b = round(float(r["b_m"]), 5) if largeur_ajustable and r.get("b_m") else None
            self._gabarits.setdefault((h, b), []).append(r)
        for lignes in self._gabarits.values():
            lignes.sort(key=lambda r: float(r["masse_kg_m"]))
        if not self._gabarits:
            raise DimensionnementError(f"Catalogue vide : {catalogue}")
        self._hauteurs = sorted({h for h, _ in self._gabarits})

    def _largeurs(self, h: float) -> list[float | None]:
        return sorted((b for hh, b in self._gabarits if hh == h),
                     key=lambda b: b if b is not None else 0.0)

    def depart(self, L: float, hauteur_max_m: float | None,
              ratio_hauteur: float = 20.0, ratio_largeur: float = 3.0) -> _EtatTube:
        cible_h = L / ratio_hauteur
        candidats = [h for h in self._hauteurs
                    if hauteur_max_m is None or h <= hauteur_max_m]
        if not candidats:
            raise DimensionnementError(
                "Algorithme escalade : aucune section tubulaire"
                + (f" <= {hauteur_max_m:g} m de hauteur" if hauteur_max_m else "")
                + " disponible pour le depart.")
        h0 = min(candidats, key=lambda h: abs(h - cible_h))
        largeurs = self._largeurs(h0)
        if self.largeur_ajustable:
            cible_b = h0 / ratio_largeur
            b0 = min(largeurs, key=lambda b: abs(b - cible_b))
        else:
            b0 = largeurs[0]
        return _EtatTube(h0, b0, 0)

    def section(self, etat: _EtatTube) -> dict:
        return self._gabarits[(etat.hauteur, etat.largeur)][etat.rang]

    def plus_epais(self, etat: _EtatTube, epaisseur_max_mm: float | None = None) -> _EtatTube | None:
        gabarit = self._gabarits[(etat.hauteur, etat.largeur)]
        if etat.rang + 1 >= len(gabarit):
            return None
        candidate = gabarit[etat.rang + 1]
        if epaisseur_max_mm is not None and float(candidate["tw_m"]) * 1000 > epaisseur_max_mm:
            return None
        return etat._replace(rang=etat.rang + 1)

    def plus_fin(self, etat: _EtatTube) -> _EtatTube | None:
        return etat._replace(rang=etat.rang - 1) if etat.rang > 0 else None

    def plus_large(self, etat: _EtatTube) -> _EtatTube | None:
        if not self.largeur_ajustable:
            return None
        plus_grandes = [b for b in self._largeurs(etat.hauteur)
                        if b is not None and etat.largeur is not None and b > etat.largeur]
        return etat._replace(largeur=min(plus_grandes), rang=0) if plus_grandes else None

    def plus_etroit(self, etat: _EtatTube) -> _EtatTube | None:
        if not self.largeur_ajustable:
            return None
        plus_petites = [b for b in self._largeurs(etat.hauteur)
                        if b is not None and etat.largeur is not None and b < etat.largeur]
        if not plus_petites:
            return None
        b1 = max(plus_petites)
        rang = min(etat.rang, len(self._gabarits[(etat.hauteur, b1)]) - 1)
        return etat._replace(largeur=b1, rang=rang)

    def plus_haut(self, etat: _EtatTube, hauteur_max_m: float | None) -> _EtatTube | None:
        suivantes = [h for h in self._hauteurs if h > etat.hauteur
                    and (hauteur_max_m is None or h <= hauteur_max_m)]
        if not suivantes:
            return None
        h1 = min(suivantes)
        largeurs = self._largeurs(h1)
        if self.largeur_ajustable and etat.largeur is not None and largeurs:
            b1 = min(largeurs, key=lambda b: abs(b - etat.largeur))
        else:
            b1 = largeurs[0] if largeurs else None
        return etat._replace(hauteur=h1, largeur=b1, rang=0)


# ==================================================== choix du navigateur
# famille HE : une seule famille pour HEA/HEB/HEM confondus, depart TOUJOURS
# au plus fin (echelon A) — l'escalade en epaisseur peut alors monter A -> B
# -> M librement (plus de plancher impose par une sous-famille HEA/HEB).
_HE_ECHELON_DEPART = {"HE": "A"}
# famille RHS : tubes rectangulaires ET carres (SHS) confondus (memes sections
# que celles injectees dans le classeur Excel, cf. injecter_sections_gsa.py) ;
# largeur ajustable (axe b independant de h, cf. NavigateurTubulaire).
_TUBES = {"RHS": ("RHS.csv", True)}


def _navigateur(famille: str):
    """(navigateur, kind, echelon_min) — kind = 'HE' ou 'tube'."""
    if famille in _HE_ECHELON_DEPART:
        return NavigateurHE(), "HE", _HE_ECHELON_DEPART[famille]
    if famille in _TUBES:
        nom_fichier, ajustable = _TUBES[famille]
        return NavigateurTubulaire(CATALOGUES / nom_fichier, ajustable), "tube", 0
    raise DimensionnementError(
        f"Algorithme escalade : famille non prise en charge {famille!r} "
        f"(disponibles : {', '.join([*_HE_ECHELON_DEPART, *_TUBES])}).")


def familles_ko_depart(modele: Path, cfg: dict) -> list[int]:
    """Indices des familles KO (ELU ou ELS depasse) a la CONFIG 0 de l'escalade
    — chaque famille au gabarit de DEPART (profil le plus fin, h0 =
    L/ratio_hauteur, cf. docstring du module), AVANT toute escalade.

    Une seule analyse GSA. Utile pour cibler un balayage d'ORDRE des familles
    (cf. comparaison_modele/B2_ordres_aleatoires.py) : en phase de croissance,
    seules les familles KO sont escaladees (les OK ne sont jamais touchees),
    donc seul l'ordre RELATIF de ces familles-la influence le resultat — les
    permutations qui ne reordonnent que des familles OK sont equivalentes.

    Renvoie les indices dans cfg["groupes"], dans l'ordre de cette liste
    (la config de depart est independante de l'ordre : toutes les familles
    sont posees a leur gabarit de depart puis evaluees en une passe)."""
    groupes = cfg.get("groupes") or []
    if not groupes:
        raise DimensionnementError("Optimisation globale : aucune famille de barres.")
    famille = cfg.get("famille")
    if not famille:
        raise DimensionnementError("Algorithme escalade : famille manquante.")
    hauteur_max = cfg.get("hauteur_max_m", 0.5)
    ratio_hauteur = float(cfg.get("ratio_hauteur_depart") or 20.0)
    ratio_largeur = float(cfg.get("ratio_largeur_depart") or 3.0)
    navigateur, kind, echelon_min = _navigateur(famille)

    with GsaModel(modele) as m:
        m.check_analysis_setup()
        ctx = _commun.preparer_contexte(m, cfg)
        _commun.verifier_familles(groupes, ctx["infos_elem"])
        sigma_lim, fleche_lim = ctx["sigma_lim"], ctx["fleche_lim"]
        infos_elem = ctx["infos_elem"]
        props = [m.section_dediee(g["elements"], nom=f"Optim {g['libelle']}")
                 for g in groupes]
        longueurs = [max((infos_elem[e]["longueur_m"] or 0) for e in g["elements"])
                    for g in groupes]
        depart_args = ((echelon_min, hauteur_max, ratio_hauteur) if kind == "HE"
                       else (hauteur_max, ratio_hauteur, ratio_largeur))
        etats = [navigateur.depart(longueurs[gi], *depart_args) for gi in range(len(groupes))]
        sections = [navigateur.section(etats[gi]) for gi in range(len(groupes))]
        for gi in range(len(groupes)):
            m.set_section_profile(props[gi], sections[gi]["profil_gsa"])
        details, _ = _commun.evaluer_etat(m, groupes, ctx, sections)
    return [d["gi"] for d in details
            if d["sigma"] > sigma_lim or d["uz_famille"] > fleche_lim]


def optimiser(modele: Path, cfg: dict, log=lambda s: None) -> dict:
    """Optimisation GLOBALE par escalade guidee (cf. docstring du module).

    cfg["famille"] : cle de familles.json (HE ou RHS) — determine le
    navigateur (HE part toujours a l'echelon A, le plus fin).
    cfg["hauteur_max_m"] (defaut 0.5), cfg["epaisseur_max_mm"] (defaut 10)
    plafonnent l'escalade. cfg["ratio_hauteur_depart"] (defaut 20),
    cfg["ratio_largeur_depart"] (defaut 3) : regles de conception du depart
    (h0 = L_barre/ratio_hauteur, b0 = h0/ratio_largeur). cfg["stabilite"]/
    cfg["stab_verifier"] : meme contrat que algo_opti/brut_force (boucle
    externe Predim, APRES les deux phases). Renvoie le meme contrat de
    sortie que les autres algorithmes (cf. algo_opti/__init__.py).
    """
    groupes = cfg.get("groupes") or []
    if not groupes:
        raise DimensionnementError("Optimisation globale : aucune famille de barres.")
    famille = cfg.get("famille")
    if not famille:
        raise DimensionnementError("Algorithme escalade : famille manquante.")
    hauteur_max = cfg.get("hauteur_max_m", 0.5)
    epaisseur_max_mm = cfg.get("epaisseur_max_mm", 10.0)
    ratio_hauteur = float(cfg.get("ratio_hauteur_depart") or 20.0)
    ratio_largeur = float(cfg.get("ratio_largeur_depart") or 3.0)
    navigateur, kind, echelon_min = _navigateur(famille)
    max_passes = int(cfg.get("max_passes", 20))

    stabilite = bool(cfg.get("stabilite")) and callable(cfg.get("stab_verifier"))
    stab_verifier = cfg.get("stab_verifier")
    taux_stab_max = float(cfg.get("critere_stabilite", {}).get("coefficient", 1.0))
    max_boucles = int(cfg.get("max_boucles_stabilite", 6))

    analyses = 0
    historique: list[dict] = []
    with GsaModel(modele) as m:
        m.check_analysis_setup()
        ctx = _commun.preparer_contexte(m, cfg)
        _commun.verifier_familles(groupes, ctx["infos_elem"])
        sigma_lim, fleche_lim = ctx["sigma_lim"], ctx["fleche_lim"]
        infos_elem = ctx["infos_elem"]

        props = [m.section_dediee(g["elements"], nom=f"Optim {g['libelle']}")
                 for g in groupes]

        # longueur de reference par famille (h0 = L/ratio_hauteur) : la plus
        # longue DE SES PROPRES BARRES — jamais la portee globale du modele
        longueurs = [max((infos_elem[e]["longueur_m"] or 0) for e in g["elements"])
                    for g in groupes]

        depart_args = ((echelon_min, hauteur_max, ratio_hauteur) if kind == "HE"
                       else (hauteur_max, ratio_hauteur, ratio_largeur))
        etats = [navigateur.depart(longueurs[gi], *depart_args) for gi in range(len(groupes))]

        def appliquer(gi: int) -> dict:
            sec = navigateur.section(etats[gi])
            m.set_section_profile(props[gi], sec["profil_gsa"])
            return sec

        for gi in range(len(groupes)):
            appliquer(gi)

        def evaluer_tout() -> list[dict]:
            """Details PAR FAMILLE (C1/C2, taux ELU/ELS) de l'etat COURANT du
            modele — UNE analyse GSA, TOUTES les familles a la fois (cf.
            _commun.evaluer_etat, rapide : C1/C2 depuis les seuls efforts)."""
            nonlocal analyses
            sections = [navigateur.section(etats[gi]) for gi in range(len(groupes))]
            details, _ = _commun.evaluer_etat(m, groupes, ctx, sections)
            analyses += 1
            return details

        def famille_ok(d: dict) -> bool:
            return d["sigma"] <= sigma_lim and d["uz_famille"] <= fleche_lim

        def config_actuelle() -> dict[str, str]:
            """{libelle famille -> section courante} — snapshot pour le
            graphe de progression (survol d'un point, cf. app.js::afficherProgression)."""
            return {groupes[gi]["libelle"]: navigateur.section(etats[gi])["nom"]
                    for gi in range(len(groupes))}

        def masse_courante() -> float:
            total = 0.0
            for gi, g in enumerate(groupes):
                long_tot = sum(infos_elem[e]["longueur_m"] or 0 for e in g["elements"])
                total += float(navigateur.section(etats[gi])["masse_kg_m"]) * long_tot
            return total

        def historiser(details: list[dict]) -> None:
            historique.append({"masse": round(masse_courante(), 1),
                               "ok": all(famille_ok(d) for d in details),
                               "config": config_actuelle()})

        def escalader(gi: int) -> str | None:
            """Fait passer la famille gi au cran superieur — priorite
            epaisseur (plafonnee a epaisseur_max_mm) -> largeur -> hauteur
            (plafonnee a hauteur_max). Renvoie le nom de l'etape faite, ou
            None si le gabarit le plus grand (ou la limite) est deja atteint."""
            for nom_etape, fonc in (
                    ("epaisseur", lambda e: navigateur.plus_epais(e, epaisseur_max_mm)),
                    ("largeur", navigateur.plus_large),
                    ("hauteur", lambda e: navigateur.plus_haut(e, hauteur_max))):
                nouvel_etat = fonc(etats[gi])
                if nouvel_etat is not None:
                    etats[gi] = nouvel_etat
                    appliquer(gi)
                    return nom_etape
            return None

        def alleger(gi: int) -> bool:
            """Tente un cran plus leger — priorite largeur -> epaisseur
            (ordre inverse de l'escalade). Renvoie si un cran a ete pris."""
            for fonc in (navigateur.plus_etroit, navigateur.plus_fin):
                nouvel_etat = fonc(etats[gi])
                if nouvel_etat is not None:
                    etats[gi] = nouvel_etat
                    appliquer(gi)
                    return True
            return False

        log(f"Optimisation globale [escalade] : {len(groupes)} famille(s), famille {famille} "
            f"({kind}), depart h0 = L/{ratio_hauteur:g}"
            + (f", b0 = h0/{ratio_largeur:g}" if kind == "tube" else "")
            + f", epaisseur minimale, hauteur max {hauteur_max:g} m, "
            f"epaisseur max {epaisseur_max_mm:g} mm, stabilite {'ON' if stabilite else 'OFF'}")

        def phase_croissance() -> tuple[bool, int, set[int]]:
            """PHASE 1 : escalade SEULE (jamais d'allegement) jusqu'a ce que
            TOUTES les familles soient simultanement OK (ELU+ELS), ou que
            plus aucune ne puisse escalader (repli, familles en echec)."""
            passe = 0
            for passe in range(1, max_passes + 1):
                avant = list(etats)
                details = evaluer_tout()
                historiser(details)
                if all(famille_ok(d) for d in details):
                    return True, passe, set()
                for gi, d in enumerate(details):
                    if famille_ok(d):
                        continue
                    # escalade la famille gi JUSQU'A ce qu'elle passe seule (ou
                    # epuisement des crans) avant de passer a la suivante —
                    # convergence rapide meme pour une famille tres sous-
                    # dimensionnee au depart (plusieurs crans d'un coup) ;
                    # l'historique reste correct car reevalue TOUJOURS les
                    # AUTRES familles (cf. historiser -> famille_ok globale)
                    while True:
                        if escalader(gi) is None:
                            break
                        details = evaluer_tout()
                        historiser(details)
                        if famille_ok(details[gi]):
                            break
                log(f"croissance · passe {passe} : " + ", ".join(
                    f"{g['libelle']}={navigateur.section(etats[i])['nom']}"
                    for i, g in enumerate(groupes)))
                if etats == avant:
                    break
            details = evaluer_tout()
            historiser(details)
            echecs = {gi for gi, d in enumerate(details) if not famille_ok(d)}
            return not echecs, passe, echecs

        def phase_allegement() -> int:
            """PHASE 2 : allegement, en verifiant apres CHAQUE tentative que
            la structure ENTIERE (toutes familles) reste faisable — sinon on
            revient en arriere. Ne s'execute que si la phase 1 a converge."""
            passe = 0
            for passe in range(1, max_passes + 1):
                avant = list(etats)
                for gi in range(len(groupes)):
                    while True:
                        avant_etat = etats[gi]
                        if not alleger(gi):
                            break
                        details = evaluer_tout()
                        historiser(details)
                        if not all(famille_ok(d) for d in details):
                            etats[gi] = avant_etat
                            appliquer(gi)
                            break
                log(f"allegement · passe {passe} : " + ", ".join(
                    f"{g['libelle']}={navigateur.section(etats[i])['nom']}"
                    for i, g in enumerate(groupes)))
                if etats == avant:
                    break
            return passe

        converge, passe_croissance, echecs = phase_croissance()
        passe_allegement = 0
        if converge:
            log("croissance : toutes les familles verifient ELU et ELS — allegement…")
            passe_allegement = phase_allegement()
        else:
            log(f"croissance : {len(echecs)} famille(s) en echec meme au gabarit maximal "
                f"({', '.join(groupes[gi]['libelle'] for gi in echecs)}) — pas d'allegement.")
        passe = passe_croissance + passe_allegement

        details = evaluer_tout()
        uz_f = max((d["uz_famille"] for d in details), default=0.0)
        stab_par_famille: dict[int, dict] = {}
        boucle = 0
        if stabilite:
            for boucle in range(1, max_boucles + 1):
                barres = [{"cle": d["gi"], **d["barre_gouvernante"]}
                         for d in details if d["barre_gouvernante"]]
                log(f"boucle {boucle} : verification stabilite EC3 de "
                    f"{len(barres)} barre(s) gouvernante(s) (classeur Predim)…")
                stab_par_famille = stab_verifier(barres, m.materials()) if barres else {}

                change = False
                for gi in range(len(groupes)):
                    r = stab_par_famille.get(gi)
                    taux = r.get("taux_stabilite") if r else None
                    if taux is not None and taux > taux_stab_max:
                        etape = escalader(gi)
                        if etape is not None:
                            change = True
                            log(f"boucle {boucle} : {groupes[gi]['libelle']} instable "
                                f"(taux {taux}) -> escalade {etape} "
                                f"({navigateur.section(etats[gi])['nom']})")
                if not change:
                    log(f"boucle {boucle} : stabilite satisfaite (ou gabarit maximal atteint)")
                    break
                details = evaluer_tout()
                uz_f = max((d["uz_famille"] for d in details), default=0.0)

        lignes = [
            _commun.construire_ligne(
                groupes[d["gi"]], navigateur.section(etats[d["gi"]]), d, ctx,
                echec=d["gi"] in echecs, stabilite=stabilite,
                stab=stab_par_famille.get(d["gi"]) if stabilite else None,
                taux_stab_max=taux_stab_max)
            for d in details
        ]

    return {
        "groupes": lignes,
        "portee_m": ctx["L"],
        "fleche_ELS_mm": round(uz_f * 1000, 2),
        "fleche_limite_mm": round(fleche_lim * 1000, 2),
        "taux_ELS": round(uz_f / fleche_lim, 3),
        "masse_totale_kg": round(sum(l["masse_kg"] for l in lignes), 1),
        "sigma_limite_Pa": sigma_lim,
        "refs": ctx["refs"],
        "passes": passe,
        "analyses": analyses,
        "converge": converge,
        "continuite": False,
        "depart_max": False,
        "stabilite": stabilite,
        "boucles_stabilite": boucle if stabilite else 0,
        "hauteur_max_m": hauteur_max,
        "historique": historique,
    }
