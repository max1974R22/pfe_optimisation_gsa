# -*- coding: utf-8 -*-
"""
Chargement des catalogues de sections GSA : catalogues/{feuille}.csv (IPE,
IPN, HD, HE, CHS, RHS), exportes par catalogues/scripts/exporter_csv.py a
partir de catalogues/catalogues_sections.xlsx (lui-meme extrait de
sectlib.db3 par catalogues/scripts/extract_catalogues.py — le classeur xlsx
est la reference consultable/modifiable a la main ; les CSV sont la copie
rapide a charger qu'utilise le code).

Format des dicts renvoyes : cles SI historiques (`h_m`, `Iyy_m4`,
`masse_kg_m`...), valeurs texte (comme un csv.DictReader) — a convertir par
l'appelant (`float(r["masse_kg_m"])`...), comme avant.
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOGUES_DIR = ROOT / "catalogues"


def charger_catalogue(feuille: str) -> list[dict]:
    """Sections de catalogues/{feuille}.csv (IPE/IPN/HD/HE/CHS/RHS), triees
    par masse croissante (ordre du fichier)."""
    chemin = CATALOGUES_DIR / f"{feuille}.csv"
    if not chemin.exists():
        raise FileNotFoundError(
            f"Catalogue introuvable : {chemin} "
            "(lancer catalogues/scripts/extract_catalogues.py puis catalogues/scripts/exporter_csv.py)")
    with chemin.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))
