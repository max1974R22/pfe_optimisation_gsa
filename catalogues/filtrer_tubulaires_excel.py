# -*- coding: utf-8 -*-
"""
Filtre les catalogues CHS/RHS (extraits de GSA par extract_catalogues.py) aux
seules sections AUSSI presentes dans le classeur Predim (onglets CHS/RHS) :
contrairement a IPE/HE/IPN (catalogue ArcelorMittal, ~85-95% deja couverts
cote Predim), les catalogues GSA EN-CHS/EN-RHS (EN10210) et les onglets
CHS/RHS du classeur ne se recoupent qu'a ~20% (gammes de dimensions
differentes, meme apres normalisation virgule/zero de fin — cf.
excel_bridge.bridge._normaliser_designation) : une section GSA hors de ce
recoupement ne pourrait jamais etre verifiee en stabilite EC3 (§6.3) dans
Predim (« profil hors classeur »).

Sortie : catalogues/CHS.csv et catalogues/RHS.csv (memes colonnes que les
catalogues source EN-CHS.csv/EN-RHS.csv, sous-ensemble filtre) — ce sont ces
fichiers, et non les catalogues GSA bruts, que config/familles.json expose a
l'application (dimensionnement ET verification garantis compatibles).

A relancer si le classeur Predim change de gamme, ou apres une reextraction
de catalogues/EN-CHS.csv / EN-RHS.csv (extract_catalogues.py).

Usage :
    venv\\Scripts\\python.exe catalogues\\filtrer_tubulaires_excel.py
"""
from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from excel_bridge.bridge import (BeamWorkbook, _normaliser_designation,
                                 load_json, new_working_copy)

OUT_DIR = Path(__file__).resolve().parent
IO_MAP = ROOT / "excel_bridge" / "config" / "io_map.json"

# (famille du catalogue GSA, catalogue source, catalogue filtre en sortie,
#  onglet Predim a interroger, transformation de designation avant comparaison)
# SHS (carre) n'a PAS d'onglet dedie dans le classeur : ses tailles y sont
# rangees dans l'onglet RHS, sous le prefixe "RHS..." (ex. designation GSA
# 'SHS100x100x5.0' -> designation Predim 'RHS100x100x5,0') — cf.
# app/server.py::_profil_predim, qui applique la meme traduction a l'usage.
def _shs_vers_rhs(nom: str) -> str:
    return "RHS" + nom[3:]


FAMILLES = [
    ("CHS", OUT_DIR / "EN-CHS.csv", OUT_DIR / "CHS.csv", "CHS", lambda n: n),
    ("RHS", OUT_DIR / "EN-RHS.csv", OUT_DIR / "RHS.csv", "RHS", lambda n: n),
    ("SHS", OUT_DIR / "EN-SHS.csv", OUT_DIR / "SHS.csv", "RHS", _shs_vers_rhs),
]


def designations_predim(wb: BeamWorkbook, onglet: str) -> set[str]:
    """Designations (normalisees) de l'onglet `onglet` du classeur ouvert."""
    sh = wb.book.sheets[onglet]
    col_b = sh.range("B1:B500").value
    return {_normaliser_designation(b) for b in col_b
            if b and isinstance(b, str) and b != onglet}


def main() -> None:
    io_map = load_json(IO_MAP)
    maitre = ROOT / io_map["workbookRelativePath"]
    copie = Path(tempfile.gettempdir()) / "PredimGSA_filtre_tubulaires.xlsm"
    new_working_copy(maitre, copie)
    wb = BeamWorkbook(copie, io_map["sheet"], visible=False)
    wb.open()
    try:
        cache_dispo: dict[str, set[str]] = {}
        for famille, source, sortie, onglet, transformer in FAMILLES:
            if not source.exists():
                print(f"  {famille} : {source.name} introuvable "
                      "(lancer extract_catalogues.py d'abord), ignore")
                continue
            if onglet not in cache_dispo:
                cache_dispo[onglet] = designations_predim(wb, onglet)
            dispo = cache_dispo[onglet]
            with source.open(encoding="utf-8-sig") as f:
                lecteur = csv.DictReader(f)
                champs = lecteur.fieldnames
                gardees = [r for r in lecteur
                          if _normaliser_designation(transformer(r["nom"])) in dispo]
            with sortie.open("w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=champs)
                w.writeheader()
                w.writerows(gardees)
            print(f"  {sortie.name} : {len(gardees)} section(s) "
                  f"(sur {sum(1 for _ in open(source, encoding='utf-8-sig')) - 1} "
                  f"dans {source.name}, {len(dispo)} dispo. dans l'onglet Predim {onglet!r})")
    finally:
        wb.close()
        copie.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print("Filtrage des catalogues tubulaires (GSA ∩ classeur Predim) :")
    main()
