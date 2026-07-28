# -*- coding: utf-8 -*-
"""
Point d'entree : ouvre un modele GSA, ecrit ses tables de donnees, RELANCE
l'analyse (en chronometrant), puis ecrit les tables de resultats en CSV, le
tout dans  result/export/<nom du modele>/  a la racine du projet.

Deroulement :
    1. lecture du fichier (copie de travail) ;
    2. ecriture des tables du modele (noeuds, elements, sections, charges...) ;
    3. analyse SEULEMENT si le fichier ne contient pas deja de resultats
       (sinon on les reutilise ; --reanalyse force le recalcul), chronometree ;
    4. ecriture des tables de resultats (efforts, contraintes 1D et contraintes
       derivees, deplacements, reactions).

Sans argument, le programme liste les modeles du dossier GSA_model/ et demande
lequel analyser (on ne traite qu'un modele a la fois). On peut aussi passer
directement un chemin pour automatiser.

L'extraction des resultats depuis GSA (surtout les combinaisons, recalculees a
la volee) est de loin l'etape la plus couteuse ; --cases permet de ne sortir
que les cas voulus au lieu de tous.

Usage :
    venv\\Scripts\\python.exe scripts\\export_model.py                  # menu interactif
    venv\\Scripts\\python.exe scripts\\export_model.py "GSA_model\\Poutre ISO.gwb"
    venv\\Scripts\\python.exe scripts\\export_model.py mon.gwb --positions 3
    venv\\Scripts\\python.exe scripts\\export_model.py mon.gwb --cases C1,C3   # 2 combinaisons
    venv\\Scripts\\python.exe scripts\\export_model.py mon.gwb --cases A       # tous les cas d'analyse
    venv\\Scripts\\python.exe scripts\\export_model.py mon.gwb --limit 10      # (debug) 10 premiers cas
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from gsa_bridge.bridge import GsaModel, ConfigurationAnalyseError
from export_gsa import export_model_tables, export_results, _write_table

MODEL_DIR = ROOT / "GSA_model"
RESULT_ROOT = ROOT / "result" / "export"


def parse_cases(spec: str | None, disponibles: dict) -> list[str]:
    """Traduit une specification de cas en liste de refs ('A1','C3'...).

    spec : None -> tous ; sinon liste separee par des virgules de :
      'A' (tous les cas d'analyse), 'C' (toutes les combinaisons),
      'A1' / 'C3' (un cas precis), 'C1-C5' (une plage).
    Seules les refs qui ont reellement des resultats sont conservees.
    """
    tous = ([f"A{i}" for i in sorted(disponibles["A"])]
            + [f"C{i}" for i in sorted(disponibles["C"])])
    if not spec:
        return tous
    presents = set(tous)
    refs: list[str] = []
    for tok in spec.upper().replace(" ", "").split(","):
        if not tok:
            continue
        if tok in ("A", "C"):
            refs += [r for r in tous if r[0] == tok]
        elif "-" in tok:
            a, b = tok.split("-", 1)
            kind = a[0]
            lo, hi = int(a[1:]), int(b[1:] if b[0].isalpha() else b)
            refs += [f"{kind}{i}" for i in range(lo, hi + 1) if f"{kind}{i}" in presents]
        elif tok in presents:
            refs.append(tok)
    # dedoublonne en gardant l'ordre
    vus, ordonne = set(), []
    for r in refs:
        if r not in vus:
            vus.add(r); ordonne.append(r)
    return ordonne


def choisir_modele() -> Path:
    """Liste les .gwb de GSA_model/ et demande lequel analyser."""
    modeles = sorted(MODEL_DIR.glob("*.gwb"))
    if not modeles:
        sys.exit(f"Aucun modele .gwb dans {MODEL_DIR}")
    if len(modeles) == 1:
        print(f"Seul modele disponible : {modeles[0].name}")
        return modeles[0]
    print("Modeles disponibles :")
    for i, p in enumerate(modeles, 1):
        print(f"  {i}. {p.name}")
    while True:
        try:
            rep = input(f"Quel modele analyser ? [1-{len(modeles)}] : ").strip()
        except EOFError:
            sys.exit("Aucune selection (entree fermee).")
        if rep.isdigit() and 1 <= int(rep) <= len(modeles):
            return modeles[int(rep) - 1]
        print("  Choix invalide, reessayez.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export CSV d'un modele GSA")
    parser.add_argument("modele", nargs="?", default=None,
                        help="chemin du .gwb (si omis : menu interactif sur GSA_model/)")
    parser.add_argument("--positions", type=int, default=3,
                        help="nb de points par element pour les efforts/deplacements (defaut 3 = extremites)")
    parser.add_argument("--cases", default=None,
                        help="cas a exporter, ex 'C' (toutes combinaisons), 'A', 'C1-C10', 'C1,C3,A2'. Defaut : tous.")
    parser.add_argument("--reanalyse", action="store_true",
                        help="forcer le recalcul meme si le fichier contient deja des resultats")
    parser.add_argument("--limit", type=int, default=None,
                        help="(debug) n'exporter que les N premiers cas retenus")
    args = parser.parse_args()

    if args.modele is None:
        modele = choisir_modele()
    else:
        modele = Path(args.modele)
        if not modele.is_absolute():
            modele = ROOT / modele
    if not modele.exists():
        sys.exit(f"Modele introuvable : {modele}")

    result_dir = RESULT_ROOT / modele.stem
    print(f"Modele  : {modele}")
    t_debut = time.perf_counter()

    # 1. lecture du fichier (copie de travail interne a GsaModel)
    with GsaModel(modele) as m:

        # verifie que le modele est analysable (ne modifie rien) ; sinon -> erreur,
        # AVANT de creer quoi que ce soit en sortie
        try:
            m.check_analysis_setup()
        except ConfigurationAnalyseError as e:
            sys.exit(f"\nERREUR : {e}")

        result_dir.mkdir(parents=True, exist_ok=True)
        print(f"Sortie  : {result_dir}")

        # 2. tables du modele
        print("\n[1/3] Tables du modele :")
        export_model_tables(m, result_dir)

        # 3. analyse : seulement si le fichier n'a pas deja de resultats
        #    (ou si --reanalyse force le recalcul). Chronometree quand elle a lieu.
        print("\n[2/3] Analyse :")
        deja = m.result_cases()
        deja_calcule = bool(deja["A"] or deja["C"])
        if deja_calcule and not args.reanalyse:
            print("  resultats deja presents dans le fichier -> analyse NON relancee")
            print("  (--reanalyse pour forcer un recalcul)")
        else:
            t0 = time.perf_counter()
            timings = m.analyse()
            duree_analyse = time.perf_counter() - t0
            for t in timings:
                print(f"  tache {t['tache']} — {t['nom']} : {t['duree_s']} s (ok={t['ok']})")
            print(f"  => analyse totale : {duree_analyse:.1f} s")
            _write_table(result_dir / "Analysis Timing.csv", timings + [
                {"tache": "TOTAL", "nom": "", "ok": all(t["ok"] for t in timings),
                 "duree_s": round(duree_analyse, 2)}
            ])

        # 4. tables de resultats
        print("\n[3/3] Tables de resultats (consolidees, facon GSA) :")
        cases = parse_cases(args.cases, m.result_cases())
        if args.limit is not None:
            cases = cases[:args.limit]
        if not cases:
            sys.exit("Aucun cas de resultat a exporter (voir --cases).")
        export_results(m, result_dir, positions=args.positions, cases=cases)

    print(f"\nTermine en {time.perf_counter() - t_debut:.1f} s -> {result_dir}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
