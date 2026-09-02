"""
Coeur de l'automatisation Excel pour le classeur EC3 "Predim poutre acier".

Pilote une copie de travail du classeur via COM (xlwings), jamais le fichier
maitre. Le lien externe casse (`Profiel`) et les macros VBA sont neutralises
a l'ouverture : le moteur de calcul du classeur repose entierement sur des
formules natives, aucune macro n'est necessaire pour obtenir un resultat.

Particularite importante de ce classeur : la designation d'un profil (ex.
"IPE300") n'est pas ecrite telle quelle dans la feuille de calcul. La cellule
AB10 attend un INDEX numerique correspondant a la position de ce profil dans
la colonne B de l'onglet de sa famille (colonne A = index, colonne B = nom).
`set_inputs` fait cette resolution texte -> index automatiquement.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import xlwings as xw

FAMILY_SHEETS = {
    "IPE": 1,
    "IPN": 2,
    "HE": 3,
    "HD": 4,
    "CHS": 5,
    "RHS": 6,
    "Custom": 7,
}


def load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def new_working_copy(source_path: Path, destination_path: Path) -> Path:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, destination_path)
    return destination_path


def _normaliser_designation(s: str) -> str:
    """Designation de profil normalisee pour comparer GSA <-> classeur Predim :
    espaces retires, casse ignoree, virgule decimale -> point, et zero de fin
    d'un nombre entier retire ('10.0' == '10') — deux notations numeriques du
    meme profil, frequentes sur les tubes CHS/RHS (cf. `resolve_profile_index`)."""
    s = "".join(s.split()).lower().replace(",", ".")
    return re.sub(r"(\d)\.0(?=x|$)", r"\1", s)


def merge_with_defaults(defaults: dict, entree: dict) -> dict:
    """Complete l'entree utilisateur (potentiellement partielle) avec les valeurs par defaut."""
    merged = dict(defaults)
    merged.update({k: v for k, v in entree.items() if v is not None})
    return merged


class BeamWorkbook:
    """Une instance Excel + un classeur ouvert sur la feuille de calcul EC3."""

    def __init__(self, path: Path, sheet_name: str, visible: bool = False):
        self.path = Path(path)
        self.sheet_name = sheet_name
        self.visible = visible
        self.app: xw.App | None = None
        self.book: xw.Book | None = None

    def open(self) -> None:
        self.app = xw.App(visible=self.visible, add_book=False)
        self.app.display_alerts = False
        self.app.screen_updating = False
        # msoAutomationSecurityForceDisable : aucune macro VBA ne s'execute a l'ouverture
        self.app.api.AutomationSecurity = 3
        self.app.api.AskToUpdateLinks = False
        # ignore_read_only_recommended : sans lui, display_alerts=False accepte
        # la "lecture seule recommandee" du classeur et l'utilisateur recoit un
        # classeur non modifiable
        self.book = self.app.books.open(str(self.path), update_links=0,
                                        read_only=False,
                                        ignore_read_only_recommended=True)
        # Calculation ne peut etre fixe qu'une fois un classeur ouvert
        self.app.calculation = "manual"

    def sheet(self) -> xw.Sheet:
        return self.book.sheets[self.sheet_name]

    def resolve_range(self, spec: dict[str, Any]) -> xw.Range:
        if spec.get("namedRange"):
            return self.book.names[spec["namedRange"]].refers_to_range
        if spec.get("address"):
            return self.sheet().range(spec["address"])
        raise ValueError(f"Spec sans 'address' ni 'namedRange' : {spec}")

    def resolve_profile_index(self, family_sheet_name: str, designation: str) -> float:
        """Cherche `designation` dans la colonne B de l'onglet de famille et renvoie
        l'index (colonne A) correspondant, tel qu'attendu par la cellule AB10.

        La comparaison ignore espaces et casse (le classeur ecrit 'IPE 80' mais
        'IPE100', et 'HE 100 A' la ou GSA ecrit 'HE100A'), la virgule decimale
        (les onglets tubulaires CHS/RHS ecrivent p. ex. 'RHS150x100x8,0' la ou
        GSA ecrit 'RHS150x100x8.0') et le zero de fin d'une epaisseur entiere
        ('CHS1016x10' cote classeur, 'CHS1016x10.0' cote GSA)."""
        profil_sheet = self.book.sheets[family_sheet_name]
        # colonne B jusqu'a la derniere ligne renseignee (l'onglet RHS peut
        # depasser 500 lignes depuis l'injection des sections GSA — SHS+RHS)
        derniere = profil_sheet.range((profil_sheet.cells.last_cell.row, 2)).end("up").row
        col_a = profil_sheet.range((1, 1), (derniere, 1)).value
        col_b = profil_sheet.range((1, 2), (derniere, 2)).value
        target = _normaliser_designation(designation)
        for a_val, b_val in zip(col_a, col_b):
            if isinstance(b_val, str) and _normaliser_designation(b_val) == target:
                return a_val
        raise ValueError(
            f"Designation de profil introuvable dans l'onglet '{family_sheet_name}' "
            f"du classeur Predim : {designation!r}"
        )

    def set_profile(self, io_map: dict, famille: str, nom: str) -> None:
        selector = io_map["profileSelector"]
        if famille not in FAMILY_SHEETS:
            raise ValueError(f"Famille de profil inconnue : {famille!r}. Attendu : {list(FAMILY_SHEETS)}")
        self.sheet().range(selector["familyAddress"]).value = FAMILY_SHEETS[famille]
        index = self.resolve_profile_index(famille, nom)
        self.sheet().range(selector["designationAddress"]).value = index

    def set_inputs(self, io_map: dict, donnees: dict) -> None:
        donnees = dict(donnees)
        if "profil_famille" in donnees or "profil_nom" in donnees:
            famille = donnees.pop("profil_famille")
            nom = donnees.pop("profil_nom")
            self.set_profile(io_map, famille, nom)

        inputs = io_map["inputs"]
        for key, value in donnees.items():
            spec = inputs.get(key)
            if spec is None:
                print(f"[avertissement] cle '{key}' absente de io_map.json (inputs) : ignoree")
                continue
            value_map = spec.get("valueMap")
            if value_map and isinstance(value, str) and value in value_map:
                value = value_map[value]
            self.resolve_range(spec).value = value

    def recalc(self, full: bool = False) -> None:
        if full:
            self.app.api.CalculateFullRebuild()
        else:
            self.app.calculate()

    def get_outputs(self, io_map: dict) -> dict:
        return {key: self.resolve_range(spec).value for key, spec in io_map["outputs"].items()}

    def close(self) -> None:
        if self.book is not None:
            self.book.close()
        if self.app is not None:
            self.app.quit()
