"""
Execute une verification EC3 sur le classeur Excel a partir d'un fichier
d'entree (JSON). Les champs absents du fichier d'entree sont completes avec
config/defaults.json.

Usage:
    python scripts/run_check.py
    python scripts/run_check.py --input scenarios/entree.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bridge import BeamWorkbook, load_json, merge_with_defaults, new_working_copy  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(ROOT / "scenarios" / "entree.json"))
    parser.add_argument("--io-map", default=str(ROOT / "config" / "io_map.json"))
    parser.add_argument("--defaults", default=str(ROOT / "config" / "defaults.json"))
    args = parser.parse_args()

    io_map = load_json(Path(args.io_map))
    defaults = load_json(Path(args.defaults))
    entree = load_json(Path(args.input))
    donnees = merge_with_defaults(defaults, entree)

    source_path = ROOT.parent / io_map["workbookRelativePath"]
    working_path = ROOT / "runtime" / "working.xlsm"
    new_working_copy(source_path, working_path)

    t0 = time.perf_counter()
    wb = BeamWorkbook(working_path, io_map["sheet"])
    wb.open()
    wb.set_inputs(io_map, donnees)
    wb.recalc()
    sorties = wb.get_outputs(io_map)
    wb.close()
    temps_calcul_s = round(time.perf_counter() - t0, 2)

    result = {
        "entrees_utilisees": donnees,
        "sorties": sorties,
        "temps_calcul_s": temps_calcul_s,
        "horodatage": datetime.now().isoformat(),
    }

    results_dir = ROOT / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    result_path = results_dir / f"resultat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\nTemps de calcul : {temps_calcul_s} s")
    print(f"Resultat ecrit : {result_path}")


if __name__ == "__main__":
    main()
