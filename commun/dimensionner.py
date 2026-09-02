# -*- coding: utf-8 -*-
"""
Dimensionnement de la poutre ISO par le modele GSA SEUL.

Hypothese : le modele possede deux combinaisons nommees ELU et ELS (noms
configurables). Les criteres sont lus dans config/dimensionnement.json :

    contrainte (ELU) : sigma <= coefficient x fy (defaut 0.90 x 235 MPa), ou
                       sigma est LA PLUS GRANDE AMPLITUDE (max signe / min
                       signe, tous confondus) des CONTRAINTES CALCULEES PAR
                       GSA sur TOUTES les mesures (combinees C1/C2, axiale A,
                       flexion By/Bz, cisaillements, von Mises... voir
                       MESURES_ELU ; cle "mesures" pour restreindre). Chaque
                       ligne porte le max signe, le min signe et la mesure
                       gouvernante de chacun.
    fleche (ELS)     : |Uz_max|  <=  L / denominateur
                       (defaut : L/300 ; L = distance entre appuis, lue
                        dans le modele)

Parcours DECROISSANT de la serie de sections (ex. IPE600 -> IPE80) : on
diminue la section tant que les deux criteres restent satisfaits, et on
s'arrete a la premiere section qui depasse (les criteres sont monotones
vis-a-vis de la taille). La section RETENUE est la plus petite qui passe.
Pour chaque section essayee : swap du profil (copie de travail uniquement),
re-analyse GSA, extraction de My (ELU) et Uz (ELS).

La logique est exposee en fonctions (`dimensionner`, `serie_sections`...)
pour etre reutilisee par l'interface web (app/server.py). Les algorithmes
d'optimisation de la STRUCTURE GLOBALE (une section par famille de barres)
vivent dans le dossier algo_opti/ (l'ancien `optimiser_global` est devenu
algo_opti/brut_force.py) et reutilisent les briques de ce module.

Sorties CLI :
    - tableau console : section, sigma, taux ELU, fleche, taux ELS, verdict ;
    - result/dimensionnement/Dimensionnement.csv (le meme tableau) ;
    - la section retenue, rappelee en fin d'execution.

Usage :
    venv\\Scripts\\python.exe scripts\\dimensionner.py
    venv\\Scripts\\python.exe scripts\\dimensionner.py --config autre.json
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gsa_bridge.bridge import GsaModel, ConfigurationAnalyseError

CONFIG_DEFAUT = ROOT / "config" / "dimensionnement.json"
SORTIE = ROOT / "result" / "dimensionnement" / "Dimensionnement.csv"


class DimensionnementError(RuntimeError):
    """Configuration ou modele impropre au dimensionnement (message utilisateur)."""


# --------------------------------------------------------------------------- mesures ELU
# Mesures de contrainte du critere ELU. Chaque entree :
# id -> {libelle, groupe, source (methode du bridge), colonnes}.
# Les valeurs viennent des tables de contraintes de GSA (unites Pa). Par
# defaut TOUTES les mesures sont evaluees : le critere prend le max signe et
# le min signe tous stress confondus, la plus grande amplitude gouverne.
# (L'ancienne mesure manuelle "My_Wel" = |My|/Wel_y a ete supprimee.)
MESURES_ELU = {
    "C1":     {"libelle": "Combinée C1 (A+B max)",  "groupe": "combinées",
               "source": "stress", "colonnes": ("C1",)},
    "C2":     {"libelle": "Combinée C2 (A+B min)",  "groupe": "combinées",
               "source": "stress", "colonnes": ("C2",)},
    "A":      {"libelle": "Axiale A",               "groupe": "normales",
               "source": "stress", "colonnes": ("A",)},
    "By":     {"libelle": "Flexion By (fibres ±z)", "groupe": "normales",
               "source": "stress", "colonnes": ("By_pz", "By_nz")},
    "Bz":     {"libelle": "Flexion Bz (fibres ±y)", "groupe": "normales",
               "source": "stress", "colonnes": ("Bz_py", "Bz_ny")},
    "VM":     {"libelle": "von Mises",              "groupe": "dérivées",
               "source": "derive", "colonnes": ("VM",)},
    "Sy":     {"libelle": "Cisaillement Sy",        "groupe": "cisaillement",
               "source": "stress", "colonnes": ("Sy",)},
    "Sz":     {"libelle": "Cisaillement Sz",        "groupe": "cisaillement",
               "source": "stress", "colonnes": ("Sz",)},
    "SEy":    {"libelle": "Cisaillement él. SEy",   "groupe": "cisaillement",
               "source": "derive", "colonnes": ("SEy",)},
    "SEz":    {"libelle": "Cisaillement él. SEz",   "groupe": "cisaillement",
               "source": "derive", "colonnes": ("SEz",)},
    "St":     {"libelle": "Torsion St",             "groupe": "cisaillement",
               "source": "derive", "colonnes": ("St",)},
}
MESURES_DEFAUT = list(MESURES_ELU)      # toutes les mesures


def valider_mesures(mesures) -> list[str]:
    """Liste de mesures ELU validee (ids connus, non vide)."""
    if not mesures:
        return list(MESURES_DEFAUT)
    inconnues = [m for m in mesures if m not in MESURES_ELU]
    if inconnues:
        raise DimensionnementError(
            f"Mesure(s) de contrainte inconnue(s) : {', '.join(inconnues)}. "
            f"Disponibles : {', '.join(MESURES_ELU)}.")
    return list(mesures)


def lire_config(path: Path = CONFIG_DEFAUT) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def serie_sections(cfg: dict) -> list[dict]:
    """Serie de sections du catalogue, triee par masse DECROISSANTE.

    cfg["hauteur_max_m"] (optionnel) : exclut les sections dont la hauteur
    nominale (colonne `h_m` du catalogue — hauteur pour HE, cote pour RHS/SHS)
    depasse cette limite. cfg["epaisseur_max_mm"] (optionnel) : exclut celles
    dont l'epaisseur (colonne `tf_m` — flanc HE — ou `tw_m` — paroi RHS/SHS,
    en mm) depasse cette limite. Repere de conception usuel de depart (algo
    escalade, cf. algo_opti/escalade.py) : hauteur ~ longueur de barre / 20,
    epaisseur minimale — ces plafonds bornent l'ensemble de la recherche pour
    tous les algorithmes (pas seulement escalade)."""
    catalogue = ROOT / cfg["catalogue"]
    if not catalogue.exists():
        raise DimensionnementError(
            f"Catalogue introuvable : {catalogue} "
            "(lancer catalogues/extract_catalogues.py)")
    with catalogue.open(encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f)
                if re.fullmatch(cfg["serie_regex"], r["nom"])]
    hmax = cfg.get("hauteur_max_m")
    if hmax:
        rows = [r for r in rows if not r.get("h_m") or float(r["h_m"]) <= hmax]
    emax_mm = cfg.get("epaisseur_max_mm")
    if emax_mm:
        rows = [r for r in rows
                if not (r.get("tf_m") or r.get("tw_m"))
                or float(r.get("tf_m") or r["tw_m"]) * 1e3 <= emax_mm]
    if not rows:
        raise DimensionnementError(
            f"Aucune section du catalogue ne correspond a {cfg['serie_regex']!r}"
            + (f" avec une hauteur <= {hmax:g} m" if hmax else "")
            + (f" et une epaisseur <= {emax_mm:g} mm" if emax_mm else ""))
    rows.sort(key=lambda r: float(r["masse_kg_m"]), reverse=True)
    return rows


def trouver_combinaisons(model: GsaModel, voulues: dict) -> dict[str, str]:
    """{'ELU': 'C1', 'ELS': 'C2'} depuis les NOMS des combinaisons du modele."""
    combos = model.combination_cases()
    par_nom = {c["nom"].strip().upper(): c["combinaison"] for c in combos}
    refs = {}
    for cle, nom in voulues.items():
        if cle.startswith("_"):
            continue
        cid = par_nom.get(nom.strip().upper())
        if cid is None:
            noms = ", ".join(repr(c["nom"]) for c in combos) or "aucune"
            raise DimensionnementError(
                f"Le modele n'a pas de combinaison nommee {nom!r}. "
                f"Combinaisons presentes : {noms}. Le dimensionnement suppose "
                "deux combinaisons ELU et ELS (noms configurables).")
        refs[cle] = f"C{cid}"
    return refs


def portee(model: GsaModel) -> float:
    """Portee L = plus grande distance entre deux noeuds d'appui."""
    appuis = [(n["x"], n["y"], n["z"]) for n in model.nodes()
              if n["res_x"] or n["res_y"] or n["res_z"]]
    if len(appuis) < 2:
        raise DimensionnementError(
            "Moins de deux noeuds d'appui : portee indeterminable.")
    return max(math.dist(a, b) for i, a in enumerate(appuis) for b in appuis[i + 1:])


def max_abs(rows: list[dict], colonne: str) -> float:
    return max((abs(r[colonne]) for r in rows
                if not math.isnan(r[colonne])), default=0.0)


def max_abs_element(rows: list[dict], colonne: str) -> tuple[float, int | None]:
    """(max absolu, element ou il se produit) — pour designer la barre gouvernante."""
    val, elem = 0.0, None
    for r in rows:
        if not math.isnan(r[colonne]) and abs(r[colonne]) >= val:
            val, elem = abs(r[colonne]), r["element"]
    return val, elem


def extremes_mesures(tables: dict, mesures: list[str]) -> dict:
    """Extremes SIGNES de chaque mesure de contrainte sur les lignes fournies.

    tables : {"stress": rows, "derive": rows} (tables de contraintes GSA).
    Renvoie {mid: {"max", "element_max", "min", "element_min"}} (Pa) — les
    mesures sans valeur lisible (tout NaN) sont omises.
    """
    # colonne -> mesures qui la lisent, par source : UNE seule passe par table
    # (les tables enveloppe — permutations x positions — peuvent etre grosses)
    par_source: dict[str, dict[str, list[str]]] = {}
    for mid in mesures:
        mes = MESURES_ELU[mid]
        cols = par_source.setdefault(mes["source"], {})
        for col in mes["colonnes"]:
            cols.setdefault(col, []).append(mid)

    acc: dict[str, list] = {}       # mid -> [vmax, emax, vmin, emin]
    for source, cols in par_source.items():
        items = list(cols.items())
        for r in tables.get(source) or []:
            eid = r["element"]
            for col, mids in items:
                v = r[col]
                if isinstance(v, float) and math.isnan(v):
                    continue
                for mid in mids:
                    a = acc.get(mid)
                    if a is None:
                        acc[mid] = [v, eid, v, eid]
                    else:
                        if v > a[0]:
                            a[0], a[1] = v, eid
                        if v < a[2]:
                            a[2], a[3] = v, eid
    return {mid: {"max": acc[mid][0], "element_max": acc[mid][1],
                  "min": acc[mid][2], "element_min": acc[mid][3]}
            for mid in mesures if mid in acc}


# mesures dont le SIGNE a un sens physique traction/compression : les
# contraintes normales. von Mises (toujours positive) et les cisaillements /
# torsion ne peuvent pas designer une barre "en traction" ou "en compression".
MESURES_SIGNEES = ("C1", "C2", "A", "By", "Bz")


def bilan_extremes(ext: dict) -> dict:
    """Extremes GLOBAUX + gouvernant du critere ELU.

    ext : sortie d'extremes_mesures. Renvoie {"sigma" (Pa, plus grande
    amplitude TOUS stress confondus), "mesure", "element", "max": {valeur,
    mesure, element}, "min": {valeur, mesure, element}}.

    "max" est la barre dimensionnante en TRACTION et "min" celle en
    COMPRESSION : extremes signes restreints aux contraintes NORMALES
    (MESURES_SIGNEES — von Mises et les cisaillements, non signes, feraient
    apparaitre une fausse traction en miroir de la compression), et exposes
    seulement si le signe est bien celui attendu (> 0 pour la traction,
    < 0 pour la compression). Une cible qui ne travaille que dans un sens
    n'a pas d'extreme de l'autre sens (None). Le critere ELU (sigma /
    mesure / element) reste la plus grande amplitude sur TOUTES les mesures,
    von Mises compris.
    """
    if not ext:
        return {"sigma": 0.0, "mesure": None, "element": None,
                "max": None, "min": None}
    mid_gmax = max(ext, key=lambda k: ext[k]["max"])
    mid_gmin = min(ext, key=lambda k: ext[k]["min"])
    gouv_max = {"valeur": ext[mid_gmax]["max"], "mesure": mid_gmax,
                "element": ext[mid_gmax]["element_max"]}
    gouv_min = {"valeur": ext[mid_gmin]["min"], "mesure": mid_gmin,
                "element": ext[mid_gmin]["element_min"]}
    gouv = gouv_max if abs(gouv_max["valeur"]) >= abs(gouv_min["valeur"]) else gouv_min

    signees = {k: v for k, v in ext.items() if k in MESURES_SIGNEES}
    traction = compression = None
    if signees:
        mid_max = max(signees, key=lambda k: signees[k]["max"])
        mid_min = min(signees, key=lambda k: signees[k]["min"])
        if signees[mid_max]["max"] > 0:
            traction = {"valeur": signees[mid_max]["max"], "mesure": mid_max,
                        "element": signees[mid_max]["element_max"]}
        if signees[mid_min]["min"] < 0:
            compression = {"valeur": signees[mid_min]["min"], "mesure": mid_min,
                           "element": signees[mid_min]["element_min"]}
    return {"sigma": abs(gouv["valeur"]), "mesure": gouv["mesure"],
            "element": gouv["element"], "max": traction, "min": compression}


_COMPOSANTES_TORSEUR = {"N": "Fx", "Vy": "Fy", "Vz": "Fz", "My": "Myy", "Mz": "Mzz"}


def _torseur_barre(rows: list[dict]) -> dict:
    """Enveloppe ELU du torseur d'une barre + distribution My/Mz debut/milieu/
    fin, depuis les lignes beam_forces de la barre (memes conventions que la
    verification Predim : kN / kNm, N > 0 = traction).

    Pour une combinaison enveloppe, le bridge fournit DEUX lignes par position
    (perm max/min) : le max/min par composante les balaie toutes, et la
    distribution My/Mz retient par POSITION la valeur signee de plus grande
    amplitude (l'enveloppe), pour rester une liste debut -> fin.
    """
    rows = sorted(rows, key=lambda r: r["pos"])
    torseur = {}
    for cle, col in _COMPOSANTES_TORSEUR.items():
        vals = [r[col] / 1e3 for r in rows if not math.isnan(r[col])]
        if not vals:
            torseur[cle] = {"max": 0.0, "min": 0.0, "enveloppe": 0.0}
            continue
        vmax, vmin = max(vals), min(vals)
        torseur[cle] = {"max": round(vmax, 3), "min": round(vmin, 3),
                        "enveloppe": round(vmax if abs(vmax) >= abs(vmin) else vmin, 3)}

    def par_pos(col: str) -> list[float]:
        env: dict[float, float] = {}
        for r in rows:
            v = r[col]
            if math.isnan(v):
                continue
            cur = env.get(r["pos"])
            if cur is None or abs(v) > abs(cur):
                env[r["pos"]] = v
        return [env[p] / 1e3 for p in sorted(env)] or [0.0]

    my, mz = par_pos("Myy"), par_pos("Mzz")
    dmf = lambda v: [round(v[0], 3), round(v[len(v) // 2], 3), round(v[-1], 3)]
    return {"torseur": torseur,
            "my_debut_milieu_fin": dmf(my), "mz_debut_milieu_fin": dmf(mz)}


def contrainte_combinee(rows: list[dict], aire, wel_y, wel_z) -> dict:
    """SEULE implementation de la contrainte combinee C1/C2 — partagee par
    l'optimisation globale (algo_opti/_commun.py::evaluer_etat) et l'onglet
    Performances (app/server.py::_perf_ligne) : les deux DOIVENT calculer
    exactement la meme chose, donc appellent cette fonction plutot que de
    reimplementer la formule chacun de leur cote.

    C1 (A+B, max signe) / C2 (A-B, min signe), calculees DIRECTEMENT depuis
    les efforts (Fx, Myy, Mzz de `beam_forces`/`member_forces`) plutot que
    les tables de contraintes GSA (beam_stresses/beam_derived_stresses —
    plusieurs appels couteux, cf. `dimensionner()` qui les utilise, elle,
    pour les AUTRES mesures — von Mises, cisaillements... — indisponibles
    depuis les seuls efforts).

    A = N/aire (contrainte axiale), B = |My|/Wel_y + |Mz|/Wel_z (flexion
    bi-axiale cumulee, cas le plus defavorable des fibres). C1 = A+B
    (traction/fibre tendue gouvernante), C2 = A-B (compression/fibre
    comprimee gouvernante) — memes conventions que la colonne C1/C2 des
    tables de contraintes GSA.

    Calculee LIGNE PAR LIGNE (meme position/permutation pour N, My et Mz :
    combiner l'extreme de chaque composante prise separement — a des
    positions/permutations differentes — ne serait pas physique), puis
    reduite au max (C1) / min (C2) sur toutes les lignes fournies.

    `rows` : lignes beam_forces/member_forces (Fx, Myy, Mzz, "element"),
    deja filtrees a la cible voulue (une barre, une famille, une position...).
    `aire`/`wel_y`/`wel_z` : caracteristiques de LA section actuellement
    affectee a cette cible (aire_m2, Wel_y_m3/Zy_m3, Wel_z_m3/Zz_m3 — accepte
    aussi bien des floats (sections GSA) que des chaines (catalogue CSV)).

    Renvoie {"c1", "c2", "element_c1", "element_c2"} en PASCAL (Pa) — None
    si les lignes ou la section manquent. `element_c1`/`element_c2` designent
    la barre ou l'extreme se produit (utile pour une famille de plusieurs
    barres ; sans objet — mais sans danger — pour une seule barre)."""
    aire = float(aire) if aire else None
    wel_y = float(wel_y) if wel_y else None
    wel_z = float(wel_z) if wel_z else None
    if not rows or not aire or not wel_y or not wel_z:
        return {"c1": None, "c2": None, "element_c1": None, "element_c2": None}
    c1 = c2 = None
    elem_c1 = elem_c2 = None
    for r in rows:
        n, my, mz = r["Fx"], r["Myy"], r["Mzz"]
        if any(isinstance(v, float) and math.isnan(v) for v in (n, my, mz)):
            continue
        a = n / aire
        b = abs(my) / wel_y + abs(mz) / wel_z
        v1, v2 = a + b, a - b
        if c1 is None or v1 > c1:
            c1, elem_c1 = v1, r.get("element")
        if c2 is None or v2 < c2:
            c2, elem_c2 = v2, r.get("element")
    return {"c1": c1, "c2": c2, "element_c1": elem_c1, "element_c2": elem_c2}


def amplitude_c1_c2(cc: dict) -> tuple[float, int | None]:
    """Amplitude ELU gouvernante (max(|C1|, |C2|), en Pa) + la barre qui la
    porte, depuis le dict renvoye par `contrainte_combinee` — SEULE
    implementation de cette reduction, partagee pour la meme raison (cf.
    `contrainte_combinee`).

    Comme C1 >= C2 toujours (C1 - C2 = 2B >= 0), max(|C1|, |C2|) vaut
    exactement max(C1, -C2) : pas besoin de comparer les valeurs absolues des
    deux, juste le signe qui les separe. Renvoie (0.0, None) si aucune des
    deux valeurs n'est disponible (section/lignes manquantes)."""
    c1, c2 = cc.get("c1"), cc.get("c2")
    if c1 is None and c2 is None:
        return 0.0, None
    c1v, c2v = c1 or 0.0, c2 or 0.0
    if -c2v >= c1v:
        return -c2v, cc.get("element_c2")
    return c1v, cc.get("element_c1")


def taux_elu_fy(sigma_Pa: float, fy_Pa: float) -> float:
    """Taux ELU = sigma / fy — SEULE implementation de ce taux, partagee par
    `dimensionner()` (plus bas), l'optimisation globale
    (algo_opti/_commun.py::construire_ligne) et l'onglet Performances
    (app/server.py::_perf_ligne), pour qu'un « taux ELU » affiche exactement
    la MEME chose partout dans l'application.

    `sigma_Pa` : amplitude ELU gouvernante (Pa, max signe / min signe
    confondus — cf. `bilan_extremes` pour la version « toutes mesures GSA »
    ou `amplitude_c1_c2` pour la version « C1/C2 recalcules depuis les
    efforts »). Le taux est exprime PAR RAPPORT A fy (la limite elastique),
    PAS a la limite admissible (coefficient x fy) : la limite a NE PAS
    depasser est donc le COEFFICIENT du critere (ex. 0.9), pas 1.0 —
    sigma <= coefficient*fy <=> taux <= coefficient. Choix : rester lisible
    (« a X% de la limite elastique ») et comparable d'un calcul a l'autre
    meme si le coefficient de securite change entre les deux."""
    return sigma_Pa / fy_Pa


def dimensionner(modele: Path, cfg: dict, log=lambda s: None,
                 progress=None) -> dict:
    """Boucle de dimensionnement complete sur un modele.

    Cible (cfg["cible"], optionnel) : {"elements": [ids], "libelle": str}
    restreint le critere ELU a ces elements — la contrainte retenue a chaque
    section essayee est celle de la BARRE LA PLUS SOLLICITEE de la cible, et
    seule la section de la cible est changee (propriete dediee creee au besoin
    via `section_dediee`, le reste du modele garde ses sections). Sans cible :
    comportement historique (1re section du modele, ELU sur tout).

    Le critere ELS (fleche <= L/denominateur) reste GLOBAL dans tous les cas :
    changer une barre modifie la raideur d'ensemble, c'est bien la fleche de
    la structure qu'on borne.

    Renvoie {"lignes": [...], "retenue": ligne|None, "portee_m", "fleche_limite_m",
             "sigma_limite_Pa", "refs": {"ELU": "C1", ...}, "cible": ...}.
    Chaque ligne porte "element_gouvernant" (barre la plus sollicitee).
    Leve DimensionnementError / ConfigurationAnalyseError si le modele ou la
    config ne permettent pas le calcul.
    """
    fy_Pa = cfg["critere_contrainte"]["fy_Pa"]
    coefficient = cfg["critere_contrainte"]["coefficient"]
    sigma_lim = coefficient * fy_Pa
    mesures = valider_mesures(cfg["critere_contrainte"].get("mesures"))
    sources = {MESURES_ELU[mid]["source"] for mid in mesures}
    denom = cfg["critere_fleche"]["denominateur"]
    positions = cfg.get("positions", 3)
    sections = serie_sections(cfg)
    cible = cfg.get("cible") or {}
    ids_cible = sorted({int(e) for e in cible.get("elements") or []}) or None

    lignes: list[dict] = []
    retenue: dict | None = None
    with GsaModel(modele) as m:
        m.check_analysis_setup()
        refs = trouver_combinaisons(m, cfg["combinaisons"])
        L = portee(m)
        fleche_lim = L / denom

        if ids_cible:
            section_id = m.section_dediee(
                ids_cible, nom=f"Optim {cible.get('libelle') or 'cible'}")
        else:
            ids = [s["section"] for s in m.sections()]
            section_id = cfg.get("section_id") if cfg.get("section_id") in ids else ids[0]

        # masse totale de chaque configuration essayee = base fixe (barres hors
        # cible, sections inchangees) + cible x aire de la section essayee
        elements_tous = m.elements()
        infos_elem = {e["element"]: e for e in elements_tous}
        aires = {s["section"]: s["aire_m2"] or 0.0 for s in m.sections()}
        mats = m.materials()
        rho = next((x["densite_kg_m3"] for x in mats
                    if x["type"] == "acier" and x["densite_kg_m3"]),
                   next((x["densite_kg_m3"] for x in mats
                         if x["densite_kg_m3"]), 7850.0))
        L_swap = sum(e["longueur_m"] for e in elements_tous
                     if e["propriete"] == section_id)
        base_kg = sum(e["longueur_m"] * aires.get(e["propriete"], 0.0) * rho
                      for e in elements_tous if e["propriete"] != section_id)

        log(f"Portee L = {L:g} m -> fleche limite {fleche_lim * 1000:.1f} mm ; "
            f"ELU = {refs['ELU']}, ELS = {refs['ELS']} ; "
            f"mesures ELU = {', '.join(mesures)} ; "
            + (f"cible = {cible.get('libelle') or ids_cible} ; " if ids_cible else "")
            + f"serie {sections[0]['nom']} -> {sections[-1]['nom']}")

        def filtrer(rows: list[dict]) -> list[dict]:
            if ids_cible is None:
                return rows
            garde = set(ids_cible)
            return [r for r in rows if r["element"] in garde]

        for i_sec, sec in enumerate(sections):
            if progress:
                progress(i_sec + 1, len(sections), sec["nom"])
            info = m.set_section_profile(section_id, sec["profil_gsa"])
            timings = m.analyse()
            if not all(t["ok"] for t in timings):
                raise DimensionnementError(f"Analyse en echec pour {sec['nom']}")

            # tables de contraintes ELU (restreintes a la cible)
            tables = {}
            if "stress" in sources:
                tables["stress"] = filtrer(m.beam_stresses(refs["ELU"], positions))
            if "derive" in sources:
                tables["derive"] = filtrer(m.beam_derived_stresses(refs["ELU"], positions))

            # extremes SIGNES de toutes les mesures : max, min, gouvernant
            ext = extremes_mesures(tables, mesures)
            bilan = bilan_extremes(ext)
            sigma = bilan["sigma"]

            # ELS global : fleche de la structure entiere
            uz = max_abs(m.beam_displacements(refs["ELS"], positions), "Uz")
            # taux ELU relatif a fy (ex. 235 MPa), pas a sigma_lim : la limite
            # a ne pas depasser est le coefficient du critere (ex. 0.9), pas
            # 1.0 — condition inchangee (sigma <= coefficient*fy <=> taux <= coefficient)
            taux_elu = taux_elu_fy(sigma, fy_Pa)
            taux_els = uz / fleche_lim
            ok = taux_elu <= coefficient and taux_els <= 1.0

            # torseur ELU de la barre gouvernante, dans l'etat DE CETTE SECTION
            # essayee (la cible porte deja le profil essaye) : sert a la
            # verification de stabilite EC3 / a l'export Predim en mode torseur
            elem_gouv = bilan["element"]
            barre_gouv = None
            if elem_gouv is not None:
                rows5 = [r for r in m.beam_forces(refs["ELU"], 5)
                         if r["element"] == elem_gouv]
                if rows5:
                    barre_gouv = {
                        "element": elem_gouv,
                        "profil_gsa": sec["profil_gsa"],
                        "longueur_m": round(
                            infos_elem.get(elem_gouv, {}).get("longueur_m") or 0, 3),
                        **_torseur_barre(rows5),
                    }

            lignes.append({
                "section": sec["nom"],
                "profil": info["profil"],
                "masse_kg_m": float(sec["masse_kg_m"]),
                "masse_totale_kg": round(base_kg + L_swap * info["aire_m2"] * rho, 1),
                "sigma_MPa": round(sigma / 1e6, 2),
                "mesure": bilan["mesure"],
                "element_gouvernant": bilan["element"],
                "sigma_max_MPa": round(bilan["max"]["valeur"] / 1e6, 2) if bilan["max"] else None,
                "mesure_max": bilan["max"]["mesure"] if bilan["max"] else None,
                "element_max": bilan["max"]["element"] if bilan["max"] else None,
                "sigma_min_MPa": round(bilan["min"]["valeur"] / 1e6, 2) if bilan["min"] else None,
                "mesure_min": bilan["min"]["mesure"] if bilan["min"] else None,
                "element_min": bilan["min"]["element"] if bilan["min"] else None,
                # detail par mesure : enveloppe signee (valeur de plus grande amplitude)
                **{f"sigma_{mid}_MPa": round(
                       (e["max"] if abs(e["max"]) >= abs(e["min"]) else e["min"]) / 1e6, 2)
                   for mid, e in ext.items()},
                "taux_ELU": round(taux_elu, 3),
                "fleche_ELS_mm": round(uz * 1000, 2),
                "fleche_limite_mm": round(fleche_lim * 1000, 2),
                "taux_ELS": round(taux_els, 3),
                "verdict": "OK" if ok else "DEPASSE",
                "barre_gouvernante": barre_gouv,
            })
            log(f"{sec['nom']:10s} sigma {sigma / 1e6:7.1f} MPa [{bilan['mesure']}"
                f"{' barre ' + str(bilan['element']) if ids_cible else ''}] "
                f"(taux {taux_elu:.3f}) "
                f"fleche {uz * 1000:7.2f} mm (taux {taux_els:.3f}) "
                f"{'OK' if ok else 'DEPASSE'}")

            if ok:
                retenue = lignes[-1]
            else:
                break   # criteres monotones : les sections plus petites echoueront aussi

    return {
        "lignes": lignes,
        "retenue": retenue,
        "portee_m": L,
        "fleche_limite_m": fleche_lim,
        "sigma_limite_Pa": sigma_lim,
        "mesures": mesures,
        "refs": refs,
        "cible": {"elements": ids_cible, "libelle": cible.get("libelle")} if ids_cible else None,
        "materiaux": mats,      # pour la nuance d'acier (retire par le serveur)
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dimensionnement de la poutre ISO (criteres ELU/ELS, GSA seul)")
    parser.add_argument("--config", default=str(CONFIG_DEFAUT),
                        help=f"fichier de criteres (defaut : {CONFIG_DEFAUT.name})")
    args = parser.parse_args()

    cfg = lire_config(Path(args.config))
    modele = ROOT / cfg["modele"]
    print(f"Modele    : {modele.name}")
    print(f"Criteres  : sigma <= {cfg['critere_contrainte']['coefficient'] * cfg['critere_contrainte']['fy_Pa'] / 1e6:.1f} MPa "
          f"({cfg['critere_contrainte']['coefficient']:.0%} de "
          f"{cfg['critere_contrainte']['fy_Pa'] / 1e6:.0f} MPa) "
          f"sur {', '.join(valider_mesures(cfg['critere_contrainte'].get('mesures')))} ; "
          f"fleche <= L/{cfg['critere_fleche']['denominateur']}")
    t_debut = time.perf_counter()

    try:
        res = dimensionner(modele, cfg, log=print)
    except (DimensionnementError, ConfigurationAnalyseError) as e:
        sys.exit(f"\nERREUR : {e}")

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    with SORTIE.open("w", newline="", encoding="utf-8-sig") as f:
        champs = [k for k in res["lignes"][0] if k != "barre_gouvernante"]
        w = csv.DictWriter(f, fieldnames=champs, extrasaction="ignore")
        w.writeheader()
        w.writerows(res["lignes"])

    print(f"\n{len(res['lignes'])} section(s) essayee(s) en "
          f"{time.perf_counter() - t_debut:.1f} s -> {SORTIE}")
    if res["retenue"] is None:
        print("AUCUNE section de la serie ne satisfait les criteres "
              "(meme la plus grande depasse).")
    else:
        r = res["retenue"]
        print(f"=> Section retenue : {r['section']} "
              f"(taux ELU {r['taux_ELU']:.3f}, taux ELS {r['taux_ELS']:.3f})")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
