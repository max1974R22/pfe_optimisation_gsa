# -*- coding: utf-8 -*-
"""
Extraction des catalogues de sections de GSA vers des CSV de reference.

Source : la base SQLite installee avec GSA
    C:\\Program Files\\Oasys\\GSA 10.2\\sectlib.db3
(tables Catalogues / Types / Sect). C'est la que GSA lit les designations
"CAT <type> <section> <date>" utilisees dans les profils (champ Profile).

Sorties (dans ce dossier) :
  - Catalogues.csv : les catalogues disponibles (British, ArcelorMittal...) ;
  - Types.csv      : tous les types de sections (IPE-AM, HE-AM, UB...) avec
                     leur catalogue et leur abreviation (= cle des designations) ;
  - <TYPE>.csv     : une CSV par type liste dans TYPES_EXPORTES, avec les
                     proprietes utiles (geometrie, aire, inerties, modules...)
                     et surtout la colonne `profil_gsa` : la designation exacte
                     a passer a GSA (ex. "CAT IPE-AM IPE200 20170912").

Axes : convention du modele GSA (poutre le long de x local) — Iyy = axe fort
(SECT_I_XX de la base), Izz = axe faible (SECT_I_YY). Unites SI (m, kg).

Usage :
    venv\\Scripts\\python.exe catalogues\\extract_catalogues.py
"""
from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

SECTLIB = Path(r"C:\Program Files\Oasys\GSA 10.2\sectlib.db3")
OUT_DIR = Path(__file__).resolve().parent

# Types a exporter en CSV individuelles (abreviation TYPE_ABR de la base).
# Gamme europeenne ArcelorMittal (profils lamines), la plus courante en
# pratique francaise ; EN-CHS/EN-RHS (tubes creux EN10210) sont la gamme
# europeenne standard des sections tubulaires GSA — celle deja utilisee dans
# les modeles reels du projet (ex. Canopee, profils "CAT EN-CHS ...").
TYPES_EXPORTES = ["IPE-AM", "HE-AM", "UPE-AM", "UPN-AM", "IPN-AM", "EN-CHS", "EN-RHS", "EN-SHS"]

# Colonnes de la table Sect retenues : (colonne SQL, nom de sortie)
COLONNES_SECT = [
    ("SECT_NAME", "nom"),
    ("SECT_MASS_PER_L", "masse_kg_m"),
    ("SECT_DEPTH_DIAM", "h_m"),
    ("SECT_WIDTH", "b_m"),
    ("SECT_WEB_THICK", "tw_m"),
    ("SECT_FLG_THICK", "tf_m"),
    ("SECT_ROOT_RAD", "r_m"),
    ("SECT_AREA", "aire_m2"),
    ("SECT_I_XX", "Iyy_m4"),          # axe fort (convention modele GSA)
    ("SECT_I_YY", "Izz_m4"),          # axe faible
    ("SECT_RAD_GYR_XX", "iy_m"),
    ("SECT_RAD_GYR_YY", "iz_m"),
    ("SECT_Z_XX", "Wel_y_m3"),
    ("SECT_Z_YY", "Wel_z_m3"),
    ("SECT_ZP_XX", "Wpl_y_m3"),
    ("SECT_ZP_YY", "Wpl_z_m3"),
    ("SECT_TORS_J", "J_m4"),
    ("SECT_WARP_CONST", "Iw_m6"),
    ("SECT_SUPERSEDED", "obsolete"),
    ("SECT_DATE_ADDED", "date"),
]


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"  {path.name} : {len(rows)} ligne(s)")


def main() -> None:
    if not SECTLIB.exists():
        sys.exit(f"Base catalogue introuvable : {SECTLIB}")
    con = sqlite3.connect(f"file:{SECTLIB}?mode=ro", uri=True)  # lecture seule
    con.row_factory = sqlite3.Row

    # 1. catalogues
    cats = [dict(r) for r in con.execute(
        "SELECT CAT_NUM AS num, CAT_NAME AS nom, CAT_ABR AS abreviation "
        "FROM Catalogues ORDER BY CAT_NUM")]
    _write_csv(OUT_DIR / "Catalogues.csv", cats)

    # 2. types (tous, avec leur catalogue)
    types = [dict(r) for r in con.execute(
        "SELECT t.TYPE_NUM AS num, c.CAT_NAME AS catalogue, "
        "       t.TYPE_NAME AS nom, t.TYPE_ABR AS abreviation, "
        "       t.TYPE_SUPERSEDED AS obsolete "
        "FROM Types t LEFT JOIN Catalogues c ON c.CAT_NUM = t.TYPE_CAT_NUM "
        "ORDER BY t.TYPE_NUM")]
    _write_csv(OUT_DIR / "Types.csv", types)

    # 3. une CSV par type demande, avec la designation GSA prete a l'emploi
    sql_cols = ", ".join(sql for sql, _ in COLONNES_SECT)
    for abr in TYPES_EXPORTES:
        type_rows = con.execute(
            "SELECT TYPE_NUM FROM Types WHERE TYPE_ABR = ?", (abr,)).fetchall()
        if not type_rows:
            print(f"  {abr} : type inconnu dans la base, ignore")
            continue
        rows = []
        for (type_num,) in type_rows:
            for r in con.execute(
                    f"SELECT {sql_cols} FROM Sect WHERE SECT_TYPE_NUM = ? "
                    "ORDER BY SECT_MASS_PER_L", (type_num,)):
                row = {out: r[sql] for sql, out in COLONNES_SECT}
                # variante remplacee par une plus recente (ex. certains EN-RHS
                # coexistent en "x4" et "x4.0" pour la meme epaisseur nominale,
                # l'ancienne etant marquee obsolete) : exclue, comme les
                # variantes AA/O/V deja filtrees par la regex de familles.json
                if str(row["obsolete"]) in ("1", "True"):
                    continue
                date = (row["date"] or "")[:10].replace("-", "")
                row["date"] = date
                row["profil_gsa"] = f"CAT {abr} {row['nom']} {date}".strip()
                rows.append(row)
        _write_csv(OUT_DIR / f"{abr}.csv", rows)

    con.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"Extraction depuis {SECTLIB} :")
    main()
