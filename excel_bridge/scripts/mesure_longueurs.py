"""
Calcule 10 portees differentes selon deux strategies, pour savoir si le temps
est domine par l'ouverture/fermeture d'Excel ou par le recalcul lui-meme :
  - COLD : nouvelle instance Excel + reouverture du classeur a chaque longueur
  - WARM : une seule instance Excel gardee ouverte, on ne fait que
           reecrire la portee + recalculer + relire

Usage:
    python scripts/mesure_longueurs.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bridge import BeamWorkbook, load_json, merge_with_defaults, new_working_copy  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
LONGUEURS = [3.0, 4.0, 5.0, 6.0, 6.5, 7.0, 8.0, 9.0, 10.0, 12.0]


def main() -> None:
    io_map = load_json(ROOT / "config" / "io_map.json")
    defaults = load_json(ROOT / "config" / "defaults.json")
    entree = load_json(ROOT / "scenarios" / "entree.json")
    donnees_base = merge_with_defaults(defaults, entree)

    source_path = ROOT.parent / io_map["workbookRelativePath"]
    working_path = ROOT / "runtime" / "mesure_longueurs.xlsm"
    new_working_copy(source_path, working_path)

    # --- COLD : nouvelle instance Excel + reouverture du classeur a chaque longueur ---
    print(f"=== Mode COLD ({len(LONGUEURS)} longueurs, Excel rouvert a chaque fois) ===")
    t_cold_total = time.perf_counter()
    for lo in LONGUEURS:
        t0 = time.perf_counter()
        wb = BeamWorkbook(working_path, io_map["sheet"])
        wb.open()
        donnees = dict(donnees_base)
        donnees["portee_m"] = lo
        wb.set_inputs(io_map, donnees)
        wb.recalc()
        sorties = wb.get_outputs(io_map)
        wb.close()
        elapsed = time.perf_counter() - t0
        print(f"  Lo={lo:>5.1f} m : {elapsed:5.2f} s  -> {sorties}")
    cold_total = time.perf_counter() - t_cold_total
    print(f"Total COLD : {cold_total:.2f} s (moyenne {cold_total / len(LONGUEURS):.2f} s/calcul)")

    # --- WARM : une seule instance Excel, reutilisee pour toutes les longueurs ---
    print(f"\n=== Mode WARM ({len(LONGUEURS)} longueurs, Excel garde ouvert) ===")
    t_warm_total = time.perf_counter()
    wb = BeamWorkbook(working_path, io_map["sheet"])
    wb.open()
    for lo in LONGUEURS:
        t0 = time.perf_counter()
        donnees = dict(donnees_base)
        donnees["portee_m"] = lo
        wb.set_inputs(io_map, donnees)
        wb.recalc()
        sorties = wb.get_outputs(io_map)
        elapsed = time.perf_counter() - t0
        print(f"  Lo={lo:>5.1f} m : {elapsed:5.2f} s  -> {sorties}")
    wb.close()
    warm_total = time.perf_counter() - t_warm_total
    print(f"Total WARM : {warm_total:.2f} s (moyenne {warm_total / len(LONGUEURS):.2f} s/calcul)")

    gain = cold_total - warm_total
    pct = 100 * (1 - warm_total / cold_total) if cold_total else 0
    print(f"\nGain du mode WARM : {gain:.2f} s ({pct:.0f}% plus rapide sur {len(LONGUEURS)} calculs)")


if __name__ == "__main__":
    main()
