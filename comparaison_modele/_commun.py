# -*- coding: utf-8 -*-
"""
Utilitaires partagés pour les scripts de comparaison escalade.
Exécution, traçage, enregistrement CSV.
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
RESULT = Path(__file__).resolve().parent / "result"
RESULT.mkdir(exist_ok=True)

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from algo_opti import escalade
from dimensionner import lire_config

MODELE = ROOT / "GSA_model" / "Pratt_1_rotule.gwb"
FAMILLE = "RHS"

# Défauts pour tous les paramètres
DEFAUTS = {
    "hauteur_max_m": 0.5,
    "epaisseur_max_mm": 10.0,
    "ratio_hauteur_depart": 50.0,
    "ratio_largeur_depart": 3.0,
}

# Les 8 familles du treillis Pratt (listes GSA)
FAMILLES_PRATT = [
    {"libelle": "Membrure haute", "elements": [12, 13, 15, 17]},
    {"libelle": "Diag ext",       "elements": [7, 11]},
    {"libelle": "Diag int",       "elements": [19, 20]},
    {"libelle": "Diag mid",       "elements": [18, 21]},
    {"libelle": "Membrure basse", "elements": [1, 2, 3, 4, 5, 6]},
    {"libelle": "Mont ext",       "elements": [14, 16]},
    {"libelle": "Mont int",       "elements": [8, 10]},
    {"libelle": "Mont mid",       "elements": [9]},
]


def base_cfg(groupes: list[dict], **overrides) -> dict:
    """Construit cfg complet avec critères du modèle + paramètres escalade."""
    import copy
    cfg = lire_config()
    cfg["catalogue"] = f"catalogues/{FAMILLE}.csv"
    cfg["serie_regex"] = r"(RHS|SHS)\d+(\.\d+)?x\d+(\.\d+)?x\d+(\.\d+)?"
    cfg["groupes"] = copy.deepcopy(groupes)
    cfg["famille"] = FAMILLE
    cfg["stabilite"] = False
    for cle, val in DEFAUTS.items():
        cfg[cle] = val
    cfg.update(overrides)
    return cfg


def run(groupes: list[dict], etiquette: str, **overrides) -> dict:
    """Lance escalade.optimiser et renvoie un résumé pour le CSV."""
    cfg = base_cfg(groupes, **overrides)
    t0 = time.perf_counter()
    res = escalade.optimiser(MODELE, cfg, log=lambda s: None)
    duree = time.perf_counter() - t0
    n_ok = sum(1 for g in res["groupes"] if g["verdict"] == "OK")
    print(f"  [{etiquette:<30}] masse={res['masse_totale_kg']:>7.1f} kg | "
          f"analyses={res['analyses']:>3} | converge={res['converge']!s:<5} | "
          f"ELS={res['taux_ELS']:.3f} | {duree:4.1f}s")
    return {
        "masse_totale_kg": res["masse_totale_kg"],
        "analyses": res["analyses"],
        "converge": int(res["converge"]),
        "taux_ELS": res["taux_ELS"],
        "familles_ok": n_ok,
        "duree_s": round(duree, 2),
        "sections": " | ".join(f"{g['libelle']}={g['section']}" for g in res["groupes"]),
    }


def ecrire_csv(nom: str, colonne_var: str, lignes: list[dict]) -> None:
    """Écrit les résultats en CSV."""
    chemin = RESULT / nom
    champs = [colonne_var, "masse_totale_kg", "analyses", "converge",
              "taux_ELS", "familles_ok", "duree_s", "sections"]
    with chemin.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=champs)
        w.writeheader()
        w.writerows(lignes)
    print(f"  -> {chemin.relative_to(ROOT)}")


def lire_csv(nom: str) -> list[dict]:
    """Lit un CSV de résultats."""
    with (RESULT / nom).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def tracer_balayage(nom_csv: str, nom_png: str, cle: str, axe_libelle: str) -> None:
    """Trace masse + analyses GSA pour un balayage d'un paramètre unique."""
    rows = lire_csv(nom_csv)
    x = [float(r[cle]) for r in rows]
    masse = [float(r["masse_totale_kg"]) for r in rows]
    analyses = [int(r["analyses"]) for r in rows]
    converge = [int(r["converge"]) for r in rows]

    fig, ax1 = plt.subplots(figsize=(8, 5))
    ax1.plot(x, masse, "o-", color="#c2185b", label="Masse totale (kg)", zorder=3)
    for xi, mi, ok in zip(x, masse, converge):
        if not ok:
            ax1.plot(xi, mi, "x", color="black", markersize=11, markeredgewidth=2, zorder=4)
    ax1.set_xlabel(axe_libelle)
    ax1.set_ylabel("Masse d'acier totale (kg)", color="#c2185b")
    ax1.tick_params(axis="y", labelcolor="#c2185b")
    ax1.grid(True, alpha=0.3)

    ax2 = ax1.twinx()
    ax2.plot(x, analyses, "s--", color="#1565c0", alpha=0.7, label="Analyses GSA")
    ax2.set_ylabel("Nombre d'analyses GSA", color="#1565c0")
    ax2.tick_params(axis="y", labelcolor="#1565c0")

    lignes1, lab1 = ax1.get_legend_handles_labels()
    lignes2, lab2 = ax2.get_legend_handles_labels()
    ax1.legend(lignes1 + lignes2, lab1 + lab2, loc="best", fontsize=9)
    croix = " (× = non convergent)" if not all(converge) else ""
    ax1.set_title(f"Escalade / Pratt — influence de « {axe_libelle} »{croix}")
    fig.tight_layout()
    sortie = RESULT / nom_png
    fig.savefig(sortie, dpi=120)
    plt.close(fig)
    print(f"  -> {sortie.name}")


def tracer_ordres(nom_csv: str, nom_png: str, col_libelle: str = "ordre") -> None:
    """Trace un diagramme barres pour la comparaison d'ordres de familles."""
    rows = lire_csv(nom_csv)
    rows.sort(key=lambda r: float(r["masse_totale_kg"]))
    noms = [r[col_libelle] for r in rows]
    masse = [float(r["masse_totale_kg"]) for r in rows]
    converge = [int(r["converge"]) for r in rows]
    couleurs = ["#c2185b" if ok else "#9e9e9e" for ok in converge]

    fig, ax = plt.subplots(figsize=(10, 5.5))
    barres = ax.bar(noms, masse, color=couleurs)
    ax.bar_label(barres, fmt="%.1f", padding=3, fontsize=8)
    ax.set_ylabel("Masse d'acier totale (kg)")
    ax.set_xlabel("Ordre d'escalade des familles (trié par masse croissante)")
    ax.set_title("Escalade / Pratt — influence de l'ordre de départ des familles")
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right", fontsize=8)
    if masse:
        ax.axhline(min(masse), color="#2e7d32", linestyle=":", alpha=0.7,
                   label=f"meilleur : {min(masse):.1f} kg")
    if not all(converge):
        ax.bar(0, 0, color="#9e9e9e", label="non convergent")
    ax.legend(fontsize=9)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    sortie = RESULT / nom_png
    fig.savefig(sortie, dpi=120)
    plt.close(fig)
    print(f"  -> {sortie.name}")
