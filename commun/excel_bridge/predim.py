# -*- coding: utf-8 -*-
"""
Ouverture du classeur Predim pre-rempli, rendu a l'utilisateur.

A la difference des verifications automatisees de `bridge.py` (Excel invisible,
ferme apres lecture), ce module prepare une copie de travail du classeur
"Predim poutre acier", y injecte les donnees transposees du modele GSA (portee,
charges, appuis, nuance) et la section optimisee, puis LAISSE EXCEL OUVERT ET
VISIBLE : le classeur appartient ensuite a l'ingenieur, qui l'ajuste et le
sauvegarde ou il veut. Le fichier maitre n'est jamais touche.

Familles disponibles dans le classeur : IPE, IPN, HE (+ HD/CHS/RHS non relies
au dimensionneur). Les familles UPE/UPN du dimensionneur n'ont pas d'onglet
Predim : `famille_predim` leve une erreur claire dans ce cas.
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from commun.excel_bridge.bridge import (BeamWorkbook, load_json, merge_with_defaults,
                                        new_working_copy)

PKG = Path(__file__).resolve().parent
ROOT = PKG.parent.parent
IO_MAP = PKG / "config" / "io_map.json"
DEFAUTS = PKG / "config" / "defaults.json"
# HORS OneDrive impérativement : le projet est synchronisé, et OneDrive
# verrouille en écriture toute copie fraîche pendant sa synchronisation ->
# Excel ouvrirait le classeur en lecture seule (constaté le 2026-07-15).
# L'utilisateur fait "Enregistrer sous" s'il veut conserver le classeur.
COPIES = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "PredimGSA"

# famille du dimensionneur (config/familles.json) -> onglet du classeur Predim
FAMILLES_PREDIM = {
    "IPE": "IPE", "IPN": "IPN",
    "HEA": "HE", "HEB": "HE", "HEM": "HE",
}


def famille_predim(famille: str) -> str:
    """Onglet Predim correspondant a une famille du dimensionneur."""
    onglet = FAMILLES_PREDIM.get(famille)
    if onglet is None:
        raise ValueError(
            f"Le classeur Predim n'a pas d'onglet pour la famille {famille!r} "
            f"(familles transposables : {', '.join(FAMILLES_PREDIM)}).")
    return onglet


def ouvrir_predim(donnees: dict, etiquette: str = "predim") -> tuple[Path, str | None]:
    """Copie le classeur maitre, le remplit avec `donnees` (cles de
    io_map.json + profil_famille/profil_nom) et le laisse ouvert dans une
    instance Excel visible. Renvoie (chemin de la copie de travail, designation
    de REPLI utilisee si la section demandee etait absente de l'onglet Predim
    — cf. `BeamWorkbook.resolve_profile_index` —, sinon None).

    En cas d'echec de saisie (ex. profil absent de l'onglet ET du catalogue,
    aucun repli possible), Excel est referme et l'exception propagee : on ne
    rend pas a l'utilisateur un classeur a moitie rempli.
    """
    # Les handlers HTTP appellent depuis des threads quelconques : l'apartment
    # COM du thread doit etre initialise avant tout usage de xlwings.
    import pythoncom
    pythoncom.CoInitialize()

    io_map = load_json(IO_MAP)
    defauts = load_json(DEFAUTS)
    maitre = ROOT / io_map["workbookRelativePath"]

    horodatage = time.strftime("%Y%m%d_%H%M%S")
    copie = new_working_copy(maitre, COPIES / f"{etiquette}_{horodatage}.xlsm")

    wb = BeamWorkbook(copie, io_map["sheet"], visible=True)
    wb.open()
    try:
        profil_substitue = wb.set_inputs(io_map, merge_with_defaults(defauts, donnees))
        wb.recalc()
        # rendre la main a l'utilisateur : Excel redevient interactif
        wb.app.calculation = "automatic"
        wb.app.screen_updating = True
        wb.app.display_alerts = True
        wb.book.activate(steal_focus=True)
    except Exception:
        wb.close()
        raise
    return copie, profil_substitue
