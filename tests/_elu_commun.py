# -*- coding: utf-8 -*-
"""Briques communes aux scripts d'etude des permutations de l'ENVELOPPE ELU.

Ce n'est PAS un script a lancer. Il factorise ce dont ont besoin
`canopee_elu_libelles.py` et `canopee_elu_permutations.py` :

  - ouverture + analyse du modele (toujours sur une copie, cf. gsa_bridge) ;
  - reperage de la combinaison enveloppe ELU par son nom ;
  - selection des barres 1D dont la SECTION est en acier ;
  - lecture BRUTE des permutations d'un resultat 1D.

Ce dernier point est la seule raison de ne pas passer par
`GsaModel.beam_forces` : le pont reduit une combinaison enveloppe a deux
lignes max/min par position (cf. `bridge._table_1d`). Ici on veut au
contraire CHAQUE permutation separement, une colonne par permutation.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gsa_bridge.bridge import GsaModel  # noqa: E402

MODELE_DEFAUT = ROOT / "GSA_model" / "Canopée - Modèle de Vent.gwb"
RESULTATS = ROOT / "tests" / "resultats"

# colonnes de sortie -> attribut .NET du Double6 (meme convention que le pont).
# Unites SI du modele : N pour les efforts, N.m pour les moments.
CHAMPS = (("Fx", "X"), ("Fy", "Y"), ("Fz", "Z"),
          ("Mxx", "XX"), ("Myy", "YY"), ("Mzz", "ZZ"))

# marqueur present sur un Double6 mais absent d'une collection de permutations
_MARQUEUR = "YY"


class Chrono:
    """Petit chronometre a etapes nommees, affiche puis exportable."""

    def __init__(self) -> None:
        self.etapes: list[tuple[str, float]] = []
        self._t0 = time.perf_counter()
        self.depart = self._t0

    def top(self, nom: str) -> float:
        dt = time.perf_counter() - self._t0
        self.etapes.append((nom, dt))
        print(f"  [{dt:8.2f} s] {nom}", flush=True)
        self._t0 = time.perf_counter()
        return dt

    @property
    def total(self) -> float:
        return time.perf_counter() - self.depart

    def resume(self) -> str:
        lignes = ["Chronometrage", "=" * 60]
        lignes += [f"{dt:10.2f} s  {nom}" for nom, dt in self.etapes]
        lignes += ["-" * 60, f"{self.total:10.2f} s  TOTAL"]
        return "\n".join(lignes)


def ouvrir_et_analyser(modele: Path = MODELE_DEFAUT, chrono: Chrono | None = None) -> GsaModel:
    """Ouvre le modele (copie de travail) et relance toutes les taches."""
    m = GsaModel(modele)
    if chrono:
        chrono.top(f"ouverture du modele ({Path(modele).name})")
    m.check_analysis_setup()
    m.analyse()
    if chrono:
        chrono.top("analyse (toutes les taches)")
    return m


def combinaison_enveloppe_elu(m: GsaModel) -> tuple[int, str, str]:
    """(id, nom, definition) de la combinaison dont le nom porte ENVELOPPE + ELU."""
    for c in m.combination_cases():
        nom = (c["nom"] or "").upper()
        if "ENVELOPPE" in nom and "ELU" in nom:
            return c["combinaison"], c["nom"], c["definition"]
    raise LookupError("aucune combinaison dont le nom contient 'ENVELOPPE' et 'ELU'")


def _cid(jeton: str) -> int | None:
    """'C12' -> 12 ; tout le reste -> None."""
    jeton = jeton.strip().upper()
    if len(jeton) > 1 and jeton[0] == "C" and jeton[1:].isdigit():
        return int(jeton[1:])
    return None


def refs_enveloppe(definition: str) -> list[int]:
    """Combinaisons enveloppees par une definition du type 'C9 to C46'.

    Renvoie [] si la definition n'est PAS une simple liste de combinaisons
    (une expression avec coefficients ou 'or' n'est pas decomposable ainsi).
    """
    jetons = definition.replace(",", " ").split()
    ids: list[int] = []
    i = 0
    while i < len(jetons):
        if jetons[i].lower() == "to" and ids and i + 1 < len(jetons):
            fin = _cid(jetons[i + 1])
            if fin is None:
                return []
            ids.extend(range(ids[-1] + 1, fin + 1))
            i += 2
            continue
        c = _cid(jetons[i])
        if c is None:
            return []
        ids.append(c)
        i += 1
    return ids


def elements_acier(m: GsaModel) -> list[dict]:
    """Barres 1D dont la section est en acier, triees par id d'element.

    Une ligne par element : element, type, section, nom_section, profil,
    longueur_m. Les elements factices (hors analyse) sont ecartes.
    """
    sections = {s["section"]: s for s in m.sections()}
    acier = {sid for sid, s in sections.items() if s["materiau"] == "STEEL"}
    lignes = []
    for e in m.elements():
        if e["factice"] or e["propriete"] not in acier:
            continue
        if e["type"] not in ("BAR", "BEAM", "TIE", "STRUT"):
            continue
        s = sections[e["propriete"]]
        lignes.append({
            "element": e["element"],
            "type": e["type"],
            "section": e["propriete"],
            "nom_section": s["nom"],
            "profil": s["profil"],
            "longueur_m": round(e["longueur_m"], 4),
        })
    lignes.sort(key=lambda l: l["element"])
    return lignes


def permutations_efforts(resultat, selecteur: str, positions: int) -> dict[int, list]:
    """{element: [permutation][position] -> Double6}, AUCUNE reduction.

    `resultat` est un CombinationCaseResult (ou AnalysisCaseResult) GSA,
    `selecteur` une definition d'entites GSA ("all", "12", "1 2 3"...).
    Un cas d'analyse (ou une combinaison a permutation unique) renvoie une
    collection plate : elle est traitee comme une permutation unique.
    """
    data = resultat.Element1dForce(selecteur, positions, None)
    sortie: dict[int, list] = {}
    for eid in data.Keys:
        coll = data[eid]
        if coll.Count == 0:
            continue
        if hasattr(coll[0], _MARQUEUR):
            sortie[eid] = [list(coll)]
        else:
            sortie[eid] = [list(p) for p in coll]
    return sortie


def duree_lisible(secondes: float) -> str:
    s = int(secondes)
    if s < 60:
        return f"{secondes:.0f} s"
    if s < 3600:
        return f"{s // 60} min {s % 60:02d} s"
    return f"{s // 3600} h {(s % 3600) // 60:02d} min {s % 60:02d} s"
