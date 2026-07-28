# -*- coding: utf-8 -*-
"""
Verification de la stabilite EC3 (§6.3) d'une liste de barres via le classeur
Predim, en MODE TORSEUR : les sollicitations (enveloppe ELU extraite de GSA)
sont ecrites directement dans le torseur du classeur — aucun chargement n'est
saisi. La barre est traitee ISOLEE : portee = longueur de la barre, appuis
appuye-appuye, longueurs de flambement / deversement = portee (defauts du
classeur), poids propre non.

Un SEUL classeur Excel invisible est ouvert pour toute la liste : pour chaque
barre on ecrit profil + nuance + portee + torseur + distribution de moments,
on recalcule, et on lit les quatre taux du §6.3 (flambement, deversement,
flechie et comprimee yy [6.61] et zz [6.62]). Le cas dimensionnant est celui
du taux maximal.

Meme mecanique que predim.py (copie de travail, fichier maitre intact), mais
Excel reste invisible et est referme a la fin.
"""
from __future__ import annotations

import os
import tempfile
import time
import uuid
from pathlib import Path

from excel_bridge.bridge import (BeamWorkbook, load_json, merge_with_defaults,
                                 new_working_copy)

PKG = Path(__file__).resolve().parent
ROOT = PKG.parent
IO_MAP = PKG / "config" / "io_map.json"
DEFAUTS = PKG / "config" / "defaults.json"
COPIES = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "PredimGSA"

# libelles des cas dimensionnants, dans l'ordre des sorties du classeur
CAS_STABILITE = {
    "taux_flambement": "Flambement",
    "taux_deversement": "Déversement",
    "taux_flechie_comprimee_yy": "Fléchi + comprimé yy",
    "taux_flechie_comprimee_zz": "Fléchi + comprimé zz",
}


def _nombre(v) -> float | None:
    """Sortie de classeur -> float (les cas non applicables renvoient du texte)."""
    return float(v) if isinstance(v, (int, float)) else None


class SessionStabilite:
    """Un classeur Predim ouvert une fois, verifiant les barres au fil de l'eau.

    Permet la verification EC3 EN FLUX : on ouvre le classeur une seule fois
    (`open`), on verifie chaque barre a mesure qu'elle arrive (`verifier`),
    puis on referme (`close`). Utilisable comme context manager. C'est la
    brique commune a `verifier_stabilites` (liste connue d'avance) et au calcul
    de performances barre par barre (barres produites par GSA au fur et a
    mesure). L'appelant DOIT etre sur un thread ou `CoInitialize` est valable
    (fait ici a l'ouverture).
    """

    def __init__(self, visible: bool = False):
        self.visible = visible
        self.io_map = None
        self.defauts = None
        self.copie = None
        self.wb = None
        self._sorties = list(CAS_STABILITE)

    def open(self) -> "SessionStabilite":
        import pythoncom
        pythoncom.CoInitialize()   # thread HTTP quelconque -> apartment COM requis
        self.io_map = load_json(IO_MAP)
        self.defauts = load_json(DEFAUTS)
        maitre = ROOT / self.io_map["workbookRelativePath"]
        # suffixe uuid : plusieurs sessions peuvent coexister (perf en flux +
        # verification manuelle) dans la meme seconde -> pas de collision de copie
        self.copie = new_working_copy(
            maitre,
            COPIES / f"stabilite_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.xlsm")
        self.wb = BeamWorkbook(self.copie, self.io_map["sheet"], visible=self.visible)
        self.wb.open()
        return self

    def verifier(self, barre: dict) -> dict:
        """Verifie une barre et renvoie {element, taux_stabilite, cas, taux} ou
        {element, erreur}. `barre` : dict d'entrees du classeur + `element`."""
        eid = barre.get("element")
        donnees = {k: v for k, v in barre.items() if k != "element"}
        try:
            self.wb.set_inputs(self.io_map, merge_with_defaults(self.defauts, donnees))
            self.wb.recalc()
            sortie = self.wb.get_outputs(self.io_map)
            taux = {k: _nombre(sortie.get(k)) for k in self._sorties}
            valides = {k: v for k, v in taux.items() if v is not None}
            if valides:
                cle = max(valides, key=lambda k: valides[k])
                return {
                    "element": eid,
                    "taux_stabilite": round(valides[cle], 3),
                    "cas": CAS_STABILITE[cle],
                    "taux": {CAS_STABILITE[k]: (round(v, 3) if v is not None else None)
                             for k, v in taux.items()},
                }
            return {"element": eid, "erreur": "aucun taux de stabilité lisible"}
        except Exception as e:                                  # noqa: BLE001
            return {"element": eid, "erreur": str(e)}

    def close(self) -> None:
        if self.wb is not None:
            self.wb.close()
            self.wb = None
        if self.copie is not None:
            try:
                self.copie.unlink()     # copie jetable : Excel est referme
            except OSError:
                pass
            self.copie = None

    def __enter__(self) -> "SessionStabilite":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()


def verifier_stabilites(barres: list[dict], log=lambda s: None,
                        progress=None) -> list[dict]:
    """Verifie la stabilite EC3 de chaque barre (une passe Excel invisible).

    `barres` : liste de dicts avec au moins `element` et les cles d'entree du
    classeur (profil_famille, profil_nom, nuance_acier, portee_m, torseur_*,
    my_*/mz_*). Renvoie une ligne par barre : {element, taux_stabilite, cas,
    taux (detail des 4), erreur}. Une barre en echec (profil hors classeur...)
    n'interrompt pas les autres. `progress(fait, total)` est appele apres
    chaque barre verifiee (suivi d'avancement cote interface).
    """
    resultats: list[dict] = []
    with SessionStabilite() as session:
        for i_b, b in enumerate(barres):
            r = session.verifier(b)
            resultats.append(r)
            log(f"barre {r.get('element')} : "
                + (f"{r.get('taux_stabilite')}" if "taux" in r
                   else r.get("erreur", "?")))
            if progress:
                progress(i_b + 1, len(barres))
    return resultats
