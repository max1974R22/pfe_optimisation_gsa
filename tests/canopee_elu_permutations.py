# -*- coding: utf-8 -*-
"""Efforts de CHAQUE permutation de l'ENVELOPPE ELU, barre acier par barre acier.

Produit un unique tableau large (`resultats/canopee_elu_permutations.csv`) :

  - une LIGNE par (barre acier, position) — 5 positions par barre :
    0 / 25 / 50 / 75 / 100 % de la longueur, soit 5 lignes par barre ;
  - une COLONNE par (permutation de l'enveloppe ELU, composante du torseur),
    soit 668 x 6 = 4008 colonnes de valeurs sur la Canopee ;
  - les 6 composantes sont celles de `Element1dForce` : Fx (axial),
    Fy / Fz (efforts tranchants), Mxx (torsion), Myy / Mzz (moments
    flechissants). Unites SI du modele : N et N.m.

Rien n'est reduit : contrairement a `GsaModel.beam_forces`, qui replie une
combinaison enveloppe en deux lignes max/min par position, chaque permutation
garde ici ses propres colonnes — c'est tout l'objet de l'etude.

Les colonnes sont nommees `permNNN_<libelle>_<composante>` si le fichier
`resultats/canopee_elu_libelles.csv` existe (produit et VALIDE par
`canopee_elu_libelles.py`, a lancer en premier), sinon `permNNN_<composante>`.

Le modele maitre n'est jamais modifie (copie de travail, cf. gsa_bridge).

Usage :
    venv\\Scripts\\python.exe tests\\canopee_elu_permutations.py
    venv\\Scripts\\python.exe tests\\canopee_elu_permutations.py --limite 5
    venv\\Scripts\\python.exe tests\\canopee_elu_permutations.py --paquet 10
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _elu_commun import (CHAMPS, MODELE_DEFAUT, RESULTATS, Chrono,
                         combinaison_enveloppe_elu, duree_lisible,
                         elements_acier, ouvrir_et_analyser,
                         permutations_efforts)

IDENTITE = ["element", "type", "section", "nom_section", "profil",
            "longueur_m", "pos_pct"]


def charger_libelles(chemin: Path) -> list[str]:
    """Libelles de permutation ('C10p03'...) dans l'ordre, [] si indisponible."""
    if not chemin.exists():
        return []
    with chemin.open(encoding="utf-8-sig", newline="") as f:
        lignes = list(csv.DictReader(f))
    if not lignes:
        return []
    if any((l.get("valide") or "").strip().lower() not in ("true", "1", "vrai")
           for l in lignes):
        print(f"  ! {chemin.name} marque comme NON valide : colonnes generiques")
        return []
    return [l["libelle"] for l in lignes]


def entetes(nb_perm: int, libelles: list[str]) -> list[str]:
    cols = list(IDENTITE)
    for p in range(1, nb_perm + 1):
        etiq = f"perm{p:03d}"
        if libelles:
            etiq += "_" + libelles[p - 1]
        cols.extend(f"{etiq}_{comp}" for comp, _ in CHAMPS)
    return cols


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modele", default=str(MODELE_DEFAUT), help="fichier .gwb")
    ap.add_argument("--positions", type=int, default=5,
                    help="positions le long de la barre (defaut 5 : 0/25/50/75/100%%)")
    ap.add_argument("--paquet", type=int, default=20,
                    help="barres extraites par appel GSA (defaut 20)")
    ap.add_argument("--limite", type=int, default=0,
                    help="ne traiter que les N premieres barres (essai)")
    ap.add_argument("--precision", type=int, default=6,
                    help="chiffres significatifs ecrits (defaut 6)")
    ap.add_argument("--sortie", default=str(RESULTATS / "canopee_elu_permutations.csv"))
    args = ap.parse_args()

    fmt = f"%.{args.precision}g"
    RESULTATS.mkdir(parents=True, exist_ok=True)
    chrono = Chrono()
    print("Efforts par permutation de l'ENVELOPPE ELU")
    print("=" * 70)

    m = ouvrir_et_analyser(Path(args.modele), chrono)
    try:
        cid, nom, definition = combinaison_enveloppe_elu(m)
        print(f"  combinaison C{cid} = {nom!r}  ->  {definition!r}")
        resultat = m._result(f"C{cid}")

        barres = elements_acier(m)
        if args.limite:
            barres = barres[:args.limite]
        print(f"  {len(barres)} barres acier x {args.positions} positions "
              f"= {len(barres) * args.positions} lignes")
        chrono.top("lecture des tables du modele")

        # nombre de permutations : mesure sur la 1re barre (1 appel, sert aussi
        # a dimensionner l'entete avant d'ouvrir le CSV)
        temoin = barres[0]["element"]
        nb_perm = len(permutations_efforts(resultat, str(temoin), args.positions)[temoin])
        libelles = charger_libelles(RESULTATS / "canopee_elu_libelles.csv")
        if libelles and len(libelles) != nb_perm:
            print(f"  ! {len(libelles)} libelles pour {nb_perm} permutations : "
                  "colonnes generiques")
            libelles = []
        cols = entetes(nb_perm, libelles)
        print(f"  {nb_perm} permutations x {len(CHAMPS)} composantes "
              f"= {nb_perm * len(CHAMPS)} colonnes de valeurs"
              + ("  (libellees)" if libelles else ""))
        chrono.top(f"sondage des permutations sur la barre {temoin}")

        # --- extraction, ecriture au fil de l'eau ---------------------------
        sortie = Path(args.sortie)
        sortie.parent.mkdir(parents=True, exist_ok=True)
        paquets = [barres[i:i + args.paquet]
                   for i in range(0, len(barres), args.paquet)]
        anomalies: list[str] = []
        nb_lignes = 0
        t_extraction = Chrono()

        with sortie.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for ip, paquet in enumerate(paquets, start=1):
                ids = [b["element"] for b in paquet]
                data = permutations_efforts(resultat, " ".join(map(str, ids)),
                                            args.positions)
                for b in paquet:
                    perms = data.get(b["element"])
                    if not perms:
                        anomalies.append(f"element {b['element']} : aucun resultat")
                        continue
                    if len(perms) != nb_perm:
                        anomalies.append(f"element {b['element']} : {len(perms)} "
                                         f"permutations au lieu de {nb_perm}")
                        continue
                    npos = len(perms[0])
                    # une ligne par position : valeurs de toutes les permutations
                    lignes = [[] for _ in range(npos)]
                    for perm in perms:
                        for i in range(npos):
                            v, ligne = perm[i], lignes[i]
                            for _, attr in CHAMPS:
                                x = getattr(v, attr)
                                ligne.append("" if x != x else fmt % x)  # NaN -> vide
                    for i, valeurs in enumerate(lignes):
                        pos = round(100.0 * i / (npos - 1), 1) if npos > 1 else 0.0
                        w.writerow([b["element"], b["type"], b["section"],
                                    b["nom_section"], b["profil"],
                                    b["longueur_m"], pos] + valeurs)
                        nb_lignes += 1
                f.flush()
                fait = min(ip * args.paquet, len(barres))
                ecoule = t_extraction.total
                reste = ecoule / fait * (len(barres) - fait)
                print(f"    {fait:>5}/{len(barres)} barres  "
                      f"({ecoule / fait:.2f} s/barre, "
                      f"restant ~{duree_lisible(reste)})", flush=True)

        chrono.top(f"extraction + ecriture ({nb_lignes} lignes)")
        taille = sortie.stat().st_size / 1e6
        print("-" * 70)
        print(f"  -> {sortie}")
        print(f"     {nb_lignes} lignes x {len(cols)} colonnes, {taille:.1f} Mo")
        if anomalies:
            print(f"  ! {len(anomalies)} anomalies :")
            for a in anomalies[:10]:
                print(f"      {a}")
    finally:
        m.close()

    print("=" * 70)
    print(chrono.resume())
    (RESULTATS / "canopee_elu_permutations_chrono.txt").write_text(
        chrono.resume() + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
