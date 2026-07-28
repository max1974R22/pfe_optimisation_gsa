# -*- coding: utf-8 -*-
"""Identifie et VALIDE les permutations de la combinaison 'ENVELOPPE ELU'.

L'enveloppe ELU de la Canopee est definie par 'C9 to C46' : GSA la developpe
en plusieurs centaines de permutations (668 attendues), car certaines des 38
combinaisons enveloppees referencent elles-memes une enveloppe (C2/C3 =
env. min/max TIC, 36 permutations chacune). L'API ne dit PAS a quelle
combinaison correspond la permutation n : ce script le retrouve, et le prouve.

Methode, sur UNE SEULE barre (donc rapide) :
  1. lire les N permutations de l'enveloppe ;
  2. lire separement chaque combinaison enveloppee (C9, C10, ... C46) et
     compter ses propres permutations ;
  3. verifier que la CONCATENATION dans l'ordre de definition redonne, valeur
     par valeur, les N permutations de l'enveloppe.

Si la verification passe, l'etiquetage est certain et le fichier
`resultats/canopee_elu_libelles.csv` est utilise par
`canopee_elu_permutations.py` pour nommer ses colonnes.

Usage :
    venv\\Scripts\\python.exe tests\\canopee_elu_libelles.py
    venv\\Scripts\\python.exe tests\\canopee_elu_libelles.py --element 100
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _elu_commun import (CHAMPS, MODELE_DEFAUT, RESULTATS, Chrono,
                         combinaison_enveloppe_elu, elements_acier,
                         ouvrir_et_analyser, permutations_efforts,
                         refs_enveloppe)

POSITIONS = 3          # suffisant pour valider l'ordre des permutations
TOLERANCE = 1e-6       # ecart relatif admis entre enveloppe et combinaison seule


def _ecart_relatif(a: float, b: float) -> float:
    """Ecart relatif entre deux valeurs, robuste au zero et aux NaN."""
    if a != a and b != b:          # deux NaN : identiques
        return 0.0
    if a != a or b != b:
        return float("inf")
    ech = max(abs(a), abs(b))
    if ech < 1e-9:                 # les deux quasi nuls
        return 0.0
    return abs(a - b) / ech


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modele", default=str(MODELE_DEFAUT), help="fichier .gwb")
    ap.add_argument("--element", type=int, default=None,
                    help="id de la barre temoin (defaut : 1re barre acier)")
    ap.add_argument("--sortie", default=str(RESULTATS / "canopee_elu_libelles.csv"))
    args = ap.parse_args()

    RESULTATS.mkdir(parents=True, exist_ok=True)
    chrono = Chrono()
    print("Identification des permutations de l'ENVELOPPE ELU")
    print("=" * 70)

    m = ouvrir_et_analyser(Path(args.modele), chrono)
    try:
        cid, nom, definition = combinaison_enveloppe_elu(m)
        print(f"  combinaison C{cid} = {nom!r}  ->  {definition!r}")

        refs = refs_enveloppe(definition)
        if not refs:
            print(f"  ! definition non decomposable ({definition!r}) : "
                  "pas d'etiquetage possible")
            return 2
        print(f"  {len(refs)} combinaisons enveloppees : C{refs[0]} .. C{refs[-1]}")

        aciers = elements_acier(m)
        eid = args.element if args.element is not None else aciers[0]["element"]
        print(f"  barre temoin : element {eid}")
        chrono.top("lecture des tables du modele")

        # --- 1. permutations de l'enveloppe ---------------------------------
        env = permutations_efforts(m._result(f"C{cid}"), str(eid), POSITIONS)[eid]
        chrono.top(f"lecture de l'enveloppe C{cid} sur 1 barre "
                   f"({len(env)} permutations)")

        # --- 2. permutations de chaque combinaison enveloppee ----------------
        lignes: list[dict] = []
        attendus: list = []            # valeurs concatenees, dans l'ordre
        noms = {c["combinaison"]: c["nom"] for c in m.combination_cases()}
        defs = {c["combinaison"]: c["definition"] for c in m.combination_cases()}
        for c in refs:
            perms = permutations_efforts(m._result(f"C{c}"), str(eid), POSITIONS)[eid]
            n = len(perms)
            for k, p in enumerate(perms, start=1):
                lignes.append({
                    "perm": len(lignes) + 1,
                    "libelle": f"C{c}p{k:02d}" if n > 1 else f"C{c}",
                    "combinaison": f"C{c}",
                    "nom_combinaison": noms.get(c, ""),
                    "definition": defs.get(c, ""),
                    "perm_dans_combinaison": k,
                    "nb_perm_combinaison": n,
                })
                attendus.append(p)
            print(f"    C{c:<3} {n:>3} perm.  {noms.get(c, '')}", flush=True)
        chrono.top(f"lecture des {len(refs)} combinaisons enveloppees sur 1 barre")

        # --- 3. verification : concatenation == enveloppe --------------------
        print("-" * 70)
        if len(attendus) != len(env):
            print(f"  ECHEC : {len(attendus)} permutations concatenees contre "
                  f"{len(env)} dans l'enveloppe")
            valide = False
            ecart_max = float("inf")
        else:
            ecart_max = 0.0
            fautives = []
            for j, (a, b) in enumerate(zip(attendus, env)):
                e = 0.0
                for ia in range(len(a)):
                    for _, attr in CHAMPS:
                        e = max(e, _ecart_relatif(getattr(a[ia], attr),
                                                  getattr(b[ia], attr)))
                ecart_max = max(ecart_max, e)
                if e > TOLERANCE:
                    fautives.append((j + 1, e))
            valide = not fautives
            if valide:
                print(f"  OK : les {len(env)} permutations de C{cid} sont, dans "
                      f"l'ordre, celles de C{refs[0]}..C{refs[-1]}")
                print(f"       ecart relatif maximal : {ecart_max:.2e}")
            else:
                print(f"  ECHEC : {len(fautives)} permutations ne concordent pas "
                      f"(1re : perm {fautives[0][0]}, ecart {fautives[0][1]:.2e})")
        chrono.top("verification valeur par valeur")

        # --- 4. ecriture -----------------------------------------------------
        sortie = Path(args.sortie)
        sortie.parent.mkdir(parents=True, exist_ok=True)
        with sortie.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["perm", "libelle", "combinaison",
                                              "nom_combinaison", "definition",
                                              "perm_dans_combinaison",
                                              "nb_perm_combinaison", "valide"])
            w.writeheader()
            for l in lignes:
                w.writerow({**l, "valide": valide})
        print(f"  -> {sortie}  ({len(lignes)} permutations)")
    finally:
        m.close()

    print("=" * 70)
    print(chrono.resume())
    return 0 if valide else 1


if __name__ == "__main__":
    raise SystemExit(main())
