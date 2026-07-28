# -*- coding: utf-8 -*-
"""
Etude parametrique : la Poutre ISO calculee avec 10 sections IPE differentes.

Pour chaque section du catalogue (catalogues/IPE-AM.csv, lui-meme extrait de
la base sectlib.db3 de GSA) :
    1. swap du profil de la section 1 dans la copie de travail
       (le fichier maitre GSA_model/Poutre ISO.gwb n'est JAMAIS modifie) ;
    2. re-analyse (obligatoire : les resultats precedents sont obsoletes) ;
    3. export complet dans result/sections/<SECTION>/ au meme format que les
       exports de scripts/export_model.py (tables du modele + resultats).

Un recapitulatif result/sections/_Comparatif.csv empile, pour chaque section
et chaque cas, les extremes utiles : My max, Vz appui, fleche max.

Par defaut : les 10 premieres sections de la serie IPE standard (IPE80 ->
IPE270, hors variantes A/AA/O/V). Modifiable par --sections.

Usage :
    venv\\Scripts\\python.exe scripts\\etude_sections.py
    venv\\Scripts\\python.exe scripts\\etude_sections.py --sections IPE100,IPE300,IPE500
    venv\\Scripts\\python.exe scripts\\etude_sections.py --nombre 5 --positions 9
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from gsa_bridge.bridge import GsaModel, ConfigurationAnalyseError
from export_gsa import export_model_tables, export_results, _write_table

MODELE = ROOT / "GSA_model" / "Poutre ISO.gwb"
CATALOGUE = ROOT / "catalogues" / "IPE-AM.csv"
RESULT_ROOT = ROOT / "result" / "sections"
SECTION_ID = 1  # la Poutre ISO n'a qu'une section


def lire_catalogue() -> dict[str, dict]:
    """Catalogue IPE-AM -> {nom: ligne}. Regenerer via catalogues/extract_catalogues.py."""
    if not CATALOGUE.exists():
        sys.exit(f"Catalogue introuvable : {CATALOGUE}\n"
                 "Lancer d'abord : venv\\Scripts\\python.exe catalogues\\extract_catalogues.py")
    with CATALOGUE.open(encoding="utf-8-sig") as f:
        return {r["nom"]: r for r in csv.DictReader(f)}


def choisir_sections(catalogue: dict[str, dict], spec: str | None, nombre: int) -> list[dict]:
    """Sections a tester : serie IPE standard (IPE80, IPE100, ...) ou liste explicite."""
    if spec:
        noms = [t.strip().upper().replace(" ", "") for t in spec.split(",") if t.strip()]
        absents = [n for n in noms if n not in catalogue]
        if absents:
            sys.exit(f"Sections hors catalogue IPE-AM : {', '.join(absents)}")
        return [catalogue[n] for n in noms]
    standards = [r for nom, r in catalogue.items() if re.fullmatch(r"IPE\d+", nom)]
    standards.sort(key=lambda r: float(r["masse_kg_m"]))
    return standards[:nombre]


def extremes(model: GsaModel, case: str, positions: int) -> dict:
    """Extremes utiles d'un cas : My max (signe), Vz max aux appuis, fleche max (signee)."""
    forces = model.beam_forces(case, positions)
    displ = model.beam_displacements(case, positions)
    react = model.node_reactions(case)
    my = max((f["Myy"] for f in forces), key=abs, default=None)
    vz = max((f["Fz"] for f in forces), key=abs, default=None)
    uz = max((d["Uz"] for d in displ), key=abs, default=None)
    rz = max((r["Fz"] for r in react if r["Fz"] == r["Fz"]), key=abs, default=None)  # NaN exclus
    return {"My_max_Nm": my, "Vz_max_N": vz, "fleche_max_m": uz, "reaction_Fz_N": rz}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Poutre ISO : etude parametrique sur les sections IPE")
    parser.add_argument("--sections", default=None,
                        help="liste explicite, ex 'IPE100,IPE300,IPE500' (defaut : 10 premieres IPE standard)")
    parser.add_argument("--nombre", type=int, default=10,
                        help="nombre de sections de la serie standard (defaut 10)")
    parser.add_argument("--positions", type=int, default=3,
                        help="points par element pour les resultats (defaut 3)")
    args = parser.parse_args()

    catalogue = lire_catalogue()
    sections = choisir_sections(catalogue, args.sections, args.nombre)
    print(f"Modele   : {MODELE}")
    print(f"Sections : {', '.join(r['nom'] for r in sections)}")
    t_debut = time.perf_counter()

    comparatif: list[dict] = []
    with GsaModel(MODELE) as m:
        try:
            m.check_analysis_setup()
        except ConfigurationAnalyseError as e:
            sys.exit(f"\nERREUR : {e}")

        RESULT_ROOT.mkdir(parents=True, exist_ok=True)
        print(f"Sortie   : {RESULT_ROOT}\n")

        for i, sec in enumerate(sections, 1):
            nom = sec["nom"]
            print(f"[{i}/{len(sections)}] {nom}")

            # 1. swap de section (copie de travail uniquement)
            info = m.set_section_profile(SECTION_ID, sec["profil_gsa"])
            print(f"  profil : {info['profil']} (A={info['aire_m2']:.5f} m2, "
                  f"Iyy={info['Iyy_m4']:.4g} m4)")

            # 2. re-analyse (les resultats de la section precedente sont obsoletes)
            timings = m.analyse()
            for t in timings:
                print(f"  tache {t['tache']} — {t['nom']} : {t['duree_s']} s (ok={t['ok']})")
            if not all(t["ok"] for t in timings):
                sys.exit(f"ERREUR : l'analyse a echoue pour {nom}")

            # 3. export au format de scripts/export_model.py
            out_dir = RESULT_ROOT / nom
            out_dir.mkdir(parents=True, exist_ok=True)
            export_model_tables(m, out_dir)
            _write_table(out_dir / "Analysis Timing.csv", timings)
            cases = ([f"A{i}" for i in sorted(m.result_cases()["A"])]
                     + [f"C{i}" for i in sorted(m.result_cases()["C"])])
            export_results(m, out_dir, positions=args.positions, cases=cases)

            # 4. recapitulatif
            for case in cases:
                comparatif.append({
                    "section": nom,
                    "masse_kg_m": sec["masse_kg_m"],
                    "aire_m2": info["aire_m2"],
                    "Iyy_m4": info["Iyy_m4"],
                    "case": case,
                    **extremes(m, case, args.positions),
                })
            print()

    n = _write_table(RESULT_ROOT / "_Comparatif.csv", comparatif)
    print(f"_Comparatif.csv : {n} ligne(s) (sections x cas)")
    print(f"\nTermine en {time.perf_counter() - t_debut:.1f} s -> {RESULT_ROOT}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
