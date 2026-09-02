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
import time
from pathlib import Path
from typing import Any

import xlwings as xw

from commun.catalogues import charger_catalogue

# ouverture Excel (BeamWorkbook.open) : nombre de tentatives et pause entre
# deux essais, cf. son docstring — encaisse les erreurs COM transitoires
# ("RPC server unavailable", -2147023174) observees quand plusieurs sessions
# Excel demarrent coup sur coup.
_OUVERTURE_ESSAIS = 3
_OUVERTURE_DELAI_S = 1.5

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
    espaces retires, casse ignoree, virgule decimale -> point, zero de fin
    d'un nombre entier retire ('10.0' == '10') — deux notations numeriques du
    meme profil, frequentes sur les tubes CHS/RHS (cf. `resolve_profile_index`) —
    et point NON decimal retire ('HE120.A' == 'HE120A', gabarit HE saisi avec un
    point cote GSA mais sans separateur dans l'onglet HE du classeur : constate
    sur un modele reel, un point suivi d'un chiffre reste un separateur decimal,
    tout autre point (avant une lettre de gabarit A/B/M...) n'en est pas un)."""
    s = "".join(s.split()).lower().replace(",", ".")
    s = re.sub(r"\.(?!\d)", "", s)
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
        """Lance Excel et ouvre `self.path`. RETENTE jusqu'a `_OUVERTURE_ESSAIS`
        fois si l'activation COM echoue ("Le serveur RPC n'est pas disponible",
        -2147023174) : erreur TRANSITOIRE constatee en pratique quand deux
        sessions Excel demarrent coup sur coup (ex. onglets Performances puis
        Optimisation d'appv2, cf. `appv2/server.py::_stabilite` et
        `_extraire_optim`) — le sous-systeme DCOM met parfois une seconde ou
        deux a liberer le serveur precedent avant d'en accepter un nouveau.
        Sans retry, cette latence transitoire faisait tomber TOUT le calcul de
        stabilite en cours (0 barre lue, cf. le `except BaseException` qui
        entoure la boucle de `_stabilite`), pour une erreur qui disparaissait
        d'elle-meme a la tentative suivante. Chaque essai rate est nettoye
        (`_fermer_partiel`) avant le suivant, pour ne pas laisser un EXCEL.EXE
        invisible orphelin a chaque tentative."""
        derniere_erreur: Exception | None = None
        for essai in range(1, _OUVERTURE_ESSAIS + 1):
            try:
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
                return
            except Exception as e:                                  # noqa: BLE001
                derniere_erreur = e
                self._fermer_partiel()
                if essai < _OUVERTURE_ESSAIS:
                    time.sleep(_OUVERTURE_DELAI_S)
        raise derniere_erreur

    def _fermer_partiel(self) -> None:
        """Referme une App/Book eventuellement ouverte avant un echec (cf.
        `open`), sans jamais lever : apres une erreur COM, l'App peut deja
        etre dans un etat casse ou son process avoir disparu — meme raison
        que le `except BaseException` autour de `session.close()` dans
        `appv2/server.py::_stabilite`."""
        if self.book is not None:
            try:
                self.book.close()
            except Exception:                                       # noqa: BLE001
                pass
            self.book = None
        if self.app is not None:
            try:
                self.app.quit()
            except Exception:                                       # noqa: BLE001
                pass
            self.app = None

    def sheet(self) -> xw.Sheet:
        return self.book.sheets[self.sheet_name]

    def resolve_range(self, spec: dict[str, Any]) -> xw.Range:
        if spec.get("namedRange"):
            return self.book.names[spec["namedRange"]].refers_to_range
        if spec.get("address"):
            return self.sheet().range(spec["address"])
        raise ValueError(f"Spec sans 'address' ni 'namedRange' : {spec}")

    def resolve_profile_index(self, family_sheet_name: str,
                              designation: str) -> tuple[float, str | None]:
        """Cherche `designation` dans la colonne B de l'onglet de famille et renvoie
        (index colonne A, designation de REPLI utilisee si differente de celle
        demandee, sinon None), l'index etant celui attendu par la cellule AB10.

        La comparaison ignore espaces et casse (le classeur ecrit 'IPE 80' mais
        'IPE100', et 'HE 100 A' la ou GSA ecrit 'HE100A'), la virgule decimale
        (les onglets tubulaires CHS/RHS ecrivent p. ex. 'RHS150x100x8,0' la ou
        GSA ecrit 'RHS150x100x8.0') et le zero de fin d'une epaisseur entiere
        ('CHS1016x10' cote classeur, 'CHS1016x10.0' cote GSA).

        Si la designation demandee est absente de l'onglet (classeur Predim
        perime par rapport au catalogue GSA), REPLI CONSERVATIF : la plus
        petite section PLUS LOURDE (donc plus resistante) qui existe a la fois
        dans le catalogue partage (commun/catalogues.py, meme source que
        l'onglet, triee par masse croissante) et dans l'onglet lui-meme — cf.
        `_section_au_dessus`. Sans repli possible, l'erreur d'origine est
        levee."""
        profil_sheet = self.book.sheets[family_sheet_name]
        # colonne B jusqu'a la derniere ligne renseignee (l'onglet RHS peut
        # depasser 500 lignes depuis l'injection des sections GSA — SHS+RHS)
        derniere = profil_sheet.range((profil_sheet.cells.last_cell.row, 2)).end("up").row
        col_a = profil_sheet.range((1, 1), (derniere, 1)).value
        col_b = profil_sheet.range((1, 2), (derniere, 2)).value
        target = _normaliser_designation(designation)
        presentes: dict[str, tuple[float, str]] = {}
        for a_val, b_val in zip(col_a, col_b):
            if not isinstance(b_val, str):
                continue
            norm = _normaliser_designation(b_val)
            presentes.setdefault(norm, (a_val, b_val))
            if norm == target:
                return a_val, None
        repli = self._section_au_dessus(family_sheet_name, designation, presentes)
        if repli is not None:
            return repli
        raise ValueError(
            f"Designation de profil introuvable dans l'onglet '{family_sheet_name}' "
            f"du classeur Predim : {designation!r}"
        )

    def _section_au_dessus(self, family_sheet_name: str, designation: str,
                           presentes: dict[str, tuple[float, str]]
                           ) -> tuple[float, str] | None:
        """Repli quand `designation` est absente de l'onglet : cherche, dans le
        catalogue partage (meme source ayant servi a remplir l'onglet, cf.
        commun/catalogues.py::charger_catalogue, triee par masse croissante),
        la PREMIERE section plus lourde que `designation` qui existe AUSSI
        dans l'onglet (`presentes`, cle = designation normalisee). Renvoie
        (index, designation utilisee) ou None si `designation` elle-meme est
        absente du catalogue, ou si aucune section plus lourde n'y figure a la
        fois cataloguee et presente dans l'onglet."""
        try:
            catalogue = charger_catalogue(family_sheet_name)
        except FileNotFoundError:
            return None          # pas de catalogue pour cette famille (ex. "Custom")
        cible = _normaliser_designation(designation)
        position = next((i for i, r in enumerate(catalogue)
                         if _normaliser_designation(r["nom"]) == cible), None)
        if position is None:
            return None          # designation absente du catalogue lui-meme : rien a proposer
        for r in catalogue[position + 1:]:
            norm = _normaliser_designation(r["nom"])
            if norm in presentes:
                index, designation_brute = presentes[norm]
                print(f"[avertissement] section {designation!r} absente de l'onglet "
                      f"'{family_sheet_name}' du classeur Predim — repli sur la section "
                      f"existante superieure {designation_brute!r}")
                return index, designation_brute
        return None

    def set_profile(self, io_map: dict, famille: str, nom: str) -> str | None:
        selector = io_map["profileSelector"]
        if famille not in FAMILY_SHEETS:
            raise ValueError(f"Famille de profil inconnue : {famille!r}. Attendu : {list(FAMILY_SHEETS)}")
        self.sheet().range(selector["familyAddress"]).value = FAMILY_SHEETS[famille]
        index, repli = self.resolve_profile_index(famille, nom)
        self.sheet().range(selector["designationAddress"]).value = index
        return repli

    def set_inputs(self, io_map: dict, donnees: dict) -> str | None:
        """Renvoie la designation de REPLI utilisee si la section demandee etait
        absente de l'onglet Predim (cf. `resolve_profile_index`), sinon None."""
        donnees = dict(donnees)
        profil_substitue = None
        if "profil_famille" in donnees or "profil_nom" in donnees:
            famille = donnees.pop("profil_famille")
            nom = donnees.pop("profil_nom")
            profil_substitue = self.set_profile(io_map, famille, nom)

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
        return profil_substitue

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
