# -*- coding: utf-8 -*-
"""
Algorithme GENETIQUE d'optimisation globale (une section par famille de barres).

Genome = un indice de section (dans la serie, triee par masse decroissante) par
famille. Fitness = masse d'acier totale a MINIMISER, sous contrainte de
faisabilite (ELU sur chaque famille + fleche globale, evaluee par GSA) : les
individus faisables sont toujours classes devant les infaisables, les faisables
entre eux par masse croissante, les infaisables par depassement croissant (donc
« du plus proche du domaine admissible »). Une seule analyse GSA par individu
DISTINCT (memoisation), partagee entre toutes les familles.

Boucle standard : population initiale (avec « boost » = une fraction demarree
sur la plus grosse section, garantie faisable) -> a chaque generation :
evaluation, tri, elitisme (les meilleurs passent tels quels), selection des
« gagnants » (meilleure fraction), croisement uniforme + mutation par pas de
section. Arret au nombre de generations demande (ou par stagnation).

Parametres (cfg["genetique"], tous optionnels) :
    population           taille de la population           (defaut 50)
    generations          nombre de generations (arret)     (defaut 30)
    taux_mutation        proba de mutation par gene         (defaut 0.10)
    pourcentage_gagnants fraction retenue pour la reproduction (defaut 0.30)
    boost_initial        fraction initiale sur la + grosse section (defaut 0.20)
    taux_croisement      proba de croisement (sinon clone)  (defaut 0.90)
    elitisme             nb de meilleurs conserves tels quels (defaut 2)
    arret_stagnation     generations sans amelioration -> arret (defaut 0 = off)
    graine               graine aleatoire (reproductibilite) (defaut : aleatoire)

NB : la contrainte de CONTINUITE et la contrainte de STABILITE EC3 ne sont pas
prises en compte par cet algorithme (elles restent propres a la force brute) ;
la stabilite affichee sur le resultat genetique est purement informative.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from gsa_bridge.bridge import GsaModel
from dimensionner import DimensionnementError, serie_sections
from . import _commun

LIBELLE = "Génétique"
DESCRIPTION = ("Algorithme génétique : population de configurations (une section "
               "par famille), sélection des plus légères qui passent, croisement "
               "et mutation sur plusieurs générations. Paramètres réglables "
               "(population, mutation, sélection, boost initial, générations).")

DEFAUTS = {
    "population": 50,
    "generations": 30,
    "taux_mutation": 0.10,
    "pourcentage_gagnants": 0.30,
    "boost_initial": 0.20,
    "taux_croisement": 0.90,
    "elitisme": 2,
    "arret_stagnation": 0,
    "graine": None,
}


def _params(cfg: dict) -> dict:
    """Parametres genetiques valides/bornes a partir de cfg["genetique"]."""
    gp = {**DEFAUTS, **(cfg.get("genetique") or {})}
    p = {
        "population": max(4, int(gp["population"])),
        "generations": max(1, int(gp["generations"])),
        "taux_mutation": min(1.0, max(0.0, float(gp["taux_mutation"]))),
        "pourcentage_gagnants": min(1.0, max(0.05, float(gp["pourcentage_gagnants"]))),
        "boost_initial": min(1.0, max(0.0, float(gp["boost_initial"]))),
        "taux_croisement": min(1.0, max(0.0, float(gp["taux_croisement"]))),
        "elitisme": max(0, int(gp["elitisme"])),
    }
    p["elitisme"] = min(p["elitisme"], p["population"])
    stagn = int(gp["arret_stagnation"] or 0)
    p["arret_stagnation"] = stagn if stagn > 0 else p["generations"]
    g = gp["graine"]
    p["graine"] = None if g in (None, "", 0, "0") else int(g)
    return p


def optimiser(modele: Path, cfg: dict, log=lambda s: None) -> dict:
    """Optimisation globale par algorithme genetique. Meme contrat de sortie que
    algo_opti/brut_force.optimiser (cf. dossier algo_opti/) + champs propres :
    "generations_faites", "population", "genetique" (parametres), "historique"."""
    serie = serie_sections(cfg)                 # triee par masse DECROISSANTE
    n = len(serie)
    groupes = cfg.get("groupes") or []
    if not groupes:
        raise DimensionnementError("Optimisation globale : aucune famille de barres.")
    ng = len(groupes)
    p = _params(cfg)
    rng = random.Random(p["graine"])

    analyses = 0
    historique: list[dict] = []
    with GsaModel(modele) as m:
        m.check_analysis_setup()
        ctx = _commun.preparer_contexte(m, cfg)
        _commun.verifier_familles(groupes, ctx["infos_elem"])
        props = [m.section_dediee(g["elements"], nom=f"Optim {g['libelle']}")
                 for g in groupes]

        cache: dict[tuple, dict] = {}          # genome -> resultat d'evaluation

        def evaluer(genome: list[int]) -> dict:
            """Evalue un genome (memoise) : faisabilite, masse, details GSA."""
            nonlocal analyses
            cle = tuple(genome)
            if cle in cache:
                return cache[cle]
            for gi, idx in enumerate(genome):
                m.set_section_profile(props[gi], serie[idx]["profil_gsa"])
            details, uz = _commun.evaluer_etat(
                m, groupes, ctx, [serie[i] for i in genome])
            analyses += 1
            faisable = _commun.etat_faisable(details, ctx)
            masse = _commun.masse_totale(genome, groupes, serie, ctx["infos_elem"])
            r = {"faisable": faisable, "masse": masse, "uz": uz, "details": details,
                 "depassement": 0.0 if faisable else _commun.depassement(details, ctx)}
            cache[cle] = r
            config = {groupes[gi]["libelle"]: serie[idx]["nom"] for gi, idx in enumerate(genome)}
            historique.append({"masse": round(masse, 1), "ok": faisable, "config": config})
            return r

        def cle_tri(genome: list[int]) -> tuple:
            """Cle de comparaison : faisables (par masse) avant infaisables
            (par depassement)."""
            r = evaluer(genome)
            return (0 if r["faisable"] else 1,
                    r["masse"] if r["faisable"] else r["depassement"])

        # --- population initiale : « boost » = fraction sur la plus grosse
        # section (faisable), le reste tire au hasard dans la serie
        n_boost = int(round(p["boost_initial"] * p["population"]))
        pop: list[list[int]] = []
        for i in range(p["population"]):
            pop.append([0] * ng if i < n_boost
                       else [rng.randrange(n) for _ in range(ng)])

        log(f"Optimisation globale [génétique] : {ng} famille(s), serie "
            f"{serie[0]['nom']} -> {serie[-1]['nom']} ({n} sections), "
            f"population {p['population']}, {p['generations']} génération(s) max, "
            f"mutation {p['taux_mutation']:.0%}, sélection {p['pourcentage_gagnants']:.0%}, "
            f"boost {p['boost_initial']:.0%}")

        meilleur: tuple[list[int], dict] | None = None
        stagnation = 0
        gen = 0
        for gen in range(1, p["generations"] + 1):
            log(f"génération {gen}/{p['generations']} : évaluation de "
                f"{p['population']} individu(s)…")
            pop.sort(key=cle_tri)              # evalue (memoise) puis trie
            tete, r_tete = pop[0], evaluer(pop[0])
            if meilleur is None or cle_tri(tete) < cle_tri(meilleur[0]):
                meilleur = (list(tete), r_tete)
                stagnation = 0
            else:
                stagnation += 1
            log(f"génération {gen} : meilleur {round(r_tete['masse'], 1)} kg "
                f"({'faisable' if r_tete['faisable'] else 'infaisable'}), "
                f"{len(cache)} config. évaluées")
            if stagnation >= p["arret_stagnation"]:
                log(f"arrêt : {stagnation} génération(s) sans amélioration")
                break
            if gen == p["generations"]:
                break

            # --- selection des gagnants + reproduction
            n_gagnants = max(2, int(round(p["pourcentage_gagnants"] * p["population"])))
            gagnants = pop[:n_gagnants]
            nouvelle = [list(g) for g in pop[:p["elitisme"]]]   # elitisme
            while len(nouvelle) < p["population"]:
                a, b = rng.choice(gagnants), rng.choice(gagnants)
                enfant = ([rng.choice((x, y)) for x, y in zip(a, b)]  # croisement uniforme
                          if rng.random() < p["taux_croisement"] else list(a))
                for gi in range(ng):                                 # mutation par pas
                    if rng.random() < p["taux_mutation"]:
                        enfant[gi] = min(n - 1, max(0, enfant[gi] + rng.choice((-2, -1, 1, 2))))
                nouvelle.append(enfant)
            pop = nouvelle

        best_genome, best_r = meilleur
        for gi, idx in enumerate(best_genome):     # remet le modele sur le meilleur
            m.set_section_profile(props[gi], serie[idx]["profil_gsa"])
        details, uz_f = best_r["details"], best_r["uz"]

        lignes = [
            _commun.construire_ligne(groupes[d["gi"]], serie[best_genome[d["gi"]]],
                                     d, ctx)
            for d in details
        ]

    return {
        "groupes": lignes,
        "portee_m": ctx["L"],
        "fleche_ELS_mm": round(uz_f * 1000, 2),
        "fleche_limite_mm": round(ctx["fleche_lim"] * 1000, 2),
        "taux_ELS": round(uz_f / ctx["fleche_lim"], 3),
        "masse_totale_kg": round(sum(l["masse_kg"] for l in lignes), 1),
        "sigma_limite_Pa": ctx["sigma_lim"],
        "refs": ctx["refs"],
        "passes": gen,
        "analyses": analyses,
        "converge": best_r["faisable"],
        "continuite": False,
        "stabilite": False,
        "generations_faites": gen,
        "population": p["population"],
        "genetique": {k: p[k] for k in (
            "population", "generations", "taux_mutation", "pourcentage_gagnants",
            "boost_initial", "taux_croisement", "elitisme")},
        "historique": historique,
    }
