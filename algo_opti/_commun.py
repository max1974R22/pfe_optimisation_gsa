# -*- coding: utf-8 -*-
"""
Briques communes aux algorithmes d'optimisation globale (dossier algo_opti/).

Contexte de calcul, verification des familles, evaluation d'un ETAT COMPLET du
modele (une analyse GSA partagee entre toutes les familles), masse totale d'une
configuration et mise en forme des lignes de resultat — factorises pour que la
force brute et l'algorithme genetique produisent EXACTEMENT le meme contrat de
sortie (memes cles de `groupes`, meme integration de la stabilite EC3).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dimensionner import (DimensionnementError, _torseur_barre, amplitude_c1_c2,
                          contrainte_combinee, max_abs, portee, taux_elu_fy,
                          trouver_combinaisons)


def preparer_contexte(m, cfg: dict) -> dict:
    """Contexte commun : limites, mesures, combinaisons, portee, infos barres.

    `m` : GsaModel deja ouvert (check_analysis_setup fait). Renvoie un dict
    reutilise a chaque evaluation (evite de reinterroger le modele)."""
    refs = trouver_combinaisons(m, cfg["combinaisons"])
    L = portee(m)
    fy_Pa = cfg["critere_contrainte"]["fy_Pa"]
    coefficient = cfg["critere_contrainte"]["coefficient"]
    return {
        "fy_Pa": fy_Pa,
        "coefficient": coefficient,
        "sigma_lim": coefficient * fy_Pa,
        "positions": cfg.get("positions", 3),
        "refs": refs,
        "L": L,
        "fleche_lim": L / cfg["critere_fleche"]["denominateur"],
        "infos_elem": {e["element"]: e for e in m.elements()},
    }


def verifier_familles(groupes: list[dict], infos_elem: dict) -> None:
    """Refuse un chevauchement (une barre dans deux familles) ou une barre
    absente du modele."""
    tous, total = set(), 0
    for g in groupes:
        tous.update(g["elements"])
        total += len(g["elements"])
    if len(tous) != total:
        raise DimensionnementError(
            "Optimisation globale : des familles se chevauchent "
            "(une barre ne peut appartenir qu'a une famille).")
    absents = tous - set(infos_elem)
    if absents:
        raise DimensionnementError(f"Barres absentes du modele : {sorted(absents)}")


def adjacence(groupes: list[dict], infos_elem: dict) -> list[set[int]]:
    """Familles adjacentes (partageant un noeud), pour la contrainte de
    continuite."""
    noeuds = [set().union(*(set(infos_elem[e]["topologie"]) for e in g["elements"]))
              for g in groupes]
    return [{j for j in range(len(groupes)) if j != i and noeuds[i] & noeuds[j]}
            for i in range(len(groupes))]


def masse_totale(indices: list[int], groupes: list[dict], serie: list[dict],
                 infos_elem: dict) -> float:
    """Masse d'acier totale (kg) d'une configuration (une section par famille),
    calculee sans GSA (Σ masse_lineique · longueur)."""
    total = 0.0
    for gi, g in enumerate(groupes):
        long_tot = sum(infos_elem[e]["longueur_m"] or 0 for e in g["elements"])
        total += float(serie[indices[gi]]["masse_kg_m"]) * long_tot
    return total


def evaluer_etat(m, groupes: list[dict], ctx: dict,
                 sections_courantes: list[dict]) -> tuple[list[dict], float]:
    """UNE analyse GSA + extraction unique -> details par famille + uz global.

    `sections_courantes` : la section (dict de la serie) actuellement affectee
    a chaque famille (pour C1/C2 et le profil de la barre gouvernante).
    Efforts (`beam_forces`) et deplacements (`beam_displacements`) sont
    extraits UNE SEULE FOIS pour tout le modele puis filtres par famille —
    PAS de tables de contraintes GSA (evite plusieurs appels couteux par
    famille, cf. `dimensionner.contrainte_combinee`).

    Renvoie ([{gi, ids, c1, c2, element_c1, element_c2, sigma,
    element_sigma, uz_famille, barre_gouvernante}], uz_global) : `sigma` =
    amplitude max entre C1 et |C2| (comparable a `ctx["sigma_lim"]`),
    calculee par `dimensionner.amplitude_c1_c2` — MEME reduction que
    `_perf_ligne` (app/server.py) pour le taux ELU de l'onglet Performances ;
    `uz_famille` = plus grand |Uz| parmi les elements de la famille
    (comparable a `ctx["fleche_lim"]` — meme critere ELS que `ctx["fleche_lim"]`
    mais applique par famille, comme le taux de fleche par barre de l'onglet
    Performances)."""
    timings = m.analyse()
    if not all(t["ok"] for t in timings):
        raise DimensionnementError("Analyse GSA en echec.")
    refs, positions, infos_elem = ctx["refs"], ctx["positions"], ctx["infos_elem"]
    forces_all = m.beam_forces(refs["ELU"], 5)         # 0/25/50/75/100 %
    disp_all = m.beam_displacements(refs["ELS"], positions)
    uz_global = max_abs(disp_all, "Uz")
    forces_par_elem: dict[int, list[dict]] = {}
    for r in forces_all:
        forces_par_elem.setdefault(r["element"], []).append(r)

    details = []
    for gi, g in enumerate(groupes):
        ids = set(g["elements"])
        rows_f = [r for r in forces_all if r["element"] in ids]
        rows_d = [r for r in disp_all if r["element"] in ids]
        section = sections_courantes[gi]
        cc = contrainte_combinee(rows_f, section.get("aire_m2"),
                                 section.get("Wel_y_m3"), section.get("Wel_z_m3"))
        sigma, elem_sigma = amplitude_c1_c2(cc)
        uz_famille = max_abs(rows_d, "Uz")
        barre_gouv = None
        if elem_sigma is not None and forces_par_elem.get(elem_sigma):
            barre_gouv = {
                "element": elem_sigma,
                "profil_gsa": sections_courantes[gi]["profil_gsa"],
                "longueur_m": round(infos_elem[elem_sigma]["longueur_m"] or 0, 3),
                **_torseur_barre(forces_par_elem[elem_sigma]),
            }
        details.append({
            "gi": gi, "ids": ids,
            "c1": cc["c1"], "c2": cc["c2"],
            "element_c1": cc["element_c1"], "element_c2": cc["element_c2"],
            "sigma": sigma, "element_sigma": elem_sigma,
            "uz_famille": uz_famille,
            "barre_gouvernante": barre_gouv,
        })
    return details, uz_global


def etat_faisable(details: list[dict], ctx: dict) -> bool:
    """Une configuration est faisable si TOUTES les familles tiennent a la
    fois la contrainte ELU (sigma) et la fleche ELS (uz_famille) — sur
    TOUTES les familles simultanement, pas seulement celle en cours
    d'ajustement (sinon un point du graphe de progression peut apparaitre
    « faisable » alors qu'une AUTRE famille, non reevaluee a cet instant,
    depasse toujours — c'est le bug corrige ici)."""
    return all(d["sigma"] <= ctx["sigma_lim"] and d["uz_famille"] <= ctx["fleche_lim"]
              for d in details)


def depassement(details: list[dict], ctx: dict) -> float:
    """Somme des depassements relatifs (contrainte + fleche, par famille) —
    0 si faisable ; sert a classer les configurations infaisables (plus
    c'est petit, plus on est proche du domaine admissible)."""
    d = 0.0
    for det in details:
        d += max(0.0, det["sigma"] / ctx["sigma_lim"] - 1.0)
        d += max(0.0, det["uz_famille"] / ctx["fleche_lim"] - 1.0)
    return d


def construire_ligne(groupe: dict, section: dict, detail: dict, ctx: dict,
                     echec: bool = False, stabilite: bool = False,
                     stab: dict | None = None, taux_stab_max: float = 1.0) -> dict:
    """Ligne de resultat d'une famille (meme forme pour tous les algorithmes) —
    C1/C2 (contrainte combinee, cf. `dimensionner.contrainte_combinee`) + taux ELU ET taux ELS
    PAR FAMILLE (pas seulement une fleche globale) : une famille n'est OK que
    si elle tient les DEUX a la fois, comme demande pour la convergence de
    l'algorithme escalade (cf. `etat_faisable`).

    `echec` : la famille n'a pas trouve de section admissible (repli).
    `stabilite`/`stab`/`taux_stab_max` : si la contrainte de stabilite EC3 est
    active, `stab` porte {taux_stabilite, cas, taux} ou {erreur} pour la barre
    gouvernante ; le verdict integre alors le taux de stabilite."""
    sigma, uz_famille = detail["sigma"], detail["uz_famille"]
    sigma_lim, fleche_lim = ctx["sigma_lim"], ctx["fleche_lim"]
    infos_elem = ctx["infos_elem"]
    long_tot = sum(infos_elem[e]["longueur_m"] or 0 for e in groupe["elements"])
    taux_stab = stab.get("taux_stabilite") if stab else None
    stab_ok = (not stabilite) or taux_stab is None or taux_stab <= taux_stab_max
    taux_elu = taux_elu_fy(sigma, ctx["fy_Pa"])
    taux_els = uz_famille / fleche_lim if fleche_lim else 0.0
    ok = not echec and sigma <= sigma_lim and uz_famille <= fleche_lim and stab_ok
    ligne = {
        "libelle": groupe["libelle"],
        "n_barres": len(groupe["elements"]),
        "elements": sorted(groupe["elements"]),
        "section": section["nom"],
        "profil": section["profil_gsa"],
        "masse_kg_m": float(section["masse_kg_m"]),
        "masse_kg": round(float(section["masse_kg_m"]) * long_tot, 1),
        "C1_MPa": round(detail["c1"] / 1e6, 2) if detail["c1"] is not None else None,
        "C2_MPa": round(detail["c2"] / 1e6, 2) if detail["c2"] is not None else None,
        "element_c1": detail["element_c1"],
        "element_c2": detail["element_c2"],
        "element_gouvernant": detail["element_sigma"],
        "fleche_ELS_mm": round(uz_famille * 1000, 2),
        "taux_ELU": round(taux_elu, 3),
        "taux_ELS": round(taux_els, 3),
        "verdict": "OK" if ok else "DEPASSE",
        "barre_gouvernante": detail["barre_gouvernante"],
    }
    if stabilite:
        if stab and stab.get("erreur"):
            ligne["stabilite_erreur"] = stab["erreur"]
        elif stab:
            ligne["taux_stabilite"] = taux_stab
            ligne["cas_stabilite"] = stab.get("cas")
            ligne["stabilite_detail"] = stab.get("taux")
    return ligne
