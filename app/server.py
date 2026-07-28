# -*- coding: utf-8 -*-
"""
Interface web locale du dimensionneur de poutre GSA.

Serveur HTTP en bibliotheque standard (aucune dependance nouvelle), page
unique app/static/index.html.

ARCHITECTURE DES THREADS : serveur multi-thread (ThreadingHTTPServer) pour
que la page et les requetes courtes ne soient jamais bloquees (les
navigateurs ouvrent des connexions speculatives sans requete, qui gelaient
l'ancien serveur mono-thread) ; MAIS tous les appels GsaAPI passent par UN
THREAD TRAVAILLEUR UNIQUE (classe TravailGsa) car l'API .NET de GSA exige
d'etre pilotee depuis un seul thread. Les calculs GSA restent donc traites
en serie, les autres requetes en parallele.

API :
    GET  /api/etat                  etat general (modeles .gwb, familles, criteres)
    GET  /api/progression           avancement des calculs longs, par canal
                                    (performance, stabilite, dimensionner,
                                    global...) — polle par la page pendant
                                    qu'elle attend la reponse d'un calcul
    GET  /api/resume?modele=<nom>   resume complet d'un modele (controle visuel)
    GET  /api/vue-sections?modele=<nom>  geometrie 3D reelle (sections des
                                    barres extrudees, via GsaAPI Model.Draw,
                                    aucune fenetre GSA ouverte) pour la vue
                                    « sections » du panneau 3D — sans analyse
    GET  /api/performance?modele=<nom>  performances du modele tel quel :
                                    poids, contraintes extremes (ELU), fleche
                                    (ELS), detail barre par barre + efforts
                                    d'extremite par membre (1D member results)
    POST /api/performance/start     {modele, elu?, els?, coefs?} -> demarre un
                                    job de performances EN FLUX (extraction
                                    barre par barre + stabilite EC3 parallele)
                                    et renvoie {job}
    GET  /api/performance/poll?job=<id>&depuis=<n>  nouvelles lignes de perf
                                    depuis l'indice n, stabilites connues, meta
                                    (refs, rho, total) et etat (en_cours/fini/
                                    arrete/erreur)
    POST /api/performance/stop      {job} -> arrete le job (coupe entre 2 barres)
    GET  /api/stabilite?modele=<nom>  taux de stabilite EC3 (§6.3) de chaque
                                    barre via le classeur Predim en mode
                                    torseur (Excel invisible) : taux max +
                                    cas dimensionnant (flambement,
                                    deversement, flechi+comprime yy/zz)
    POST /api/excel-barre           {modele, element} -> ouvre le classeur
                                    Predim VISIBLE pre-rempli avec le torseur
                                    ELU de la barre (enveloppe 0/25/50/75/100%,
                                    sans chargement) pour verification manuelle
    POST /api/upload?nom=<f.gwb>    depose un .gwb dans GSA_model/ (corps = octets)
    POST /api/dimensionner          {modele, famille, criteres?, cible?} -> tableau
                                    + retenue (cible = {elements, libelle} :
                                    ELU restreint a la barre la plus sollicitee
                                    de la cible, section dediee pour la cible) ;
                                    chaque ligne porte le torseur de sa barre
                                    gouvernante (barre_gouvernante)
    POST /api/stabilite-lignes      {nuance, barres: [torseurs|null]} -> taux de
                                    stabilite EC3 par indice (classeur Predim,
                                    Excel invisible) : remplit en differe les
                                    colonnes stabilite du tableau de resultats
    POST /api/global                {modele, famille, criteres?, groupes,
                                    continuite?, algo?} -> optimisation globale :
                                    une section par famille de barres, algorithme
                                    du dossier algo_opti/ (defaut brut_force),
                                    table par famille + bilan global ; ecrit aussi
                                    un compte-rendu texte dans optimisations/
    POST /api/global/config         {modele, famille, criteres?, groupes, config}
                                    -> reevalue UNE configuration precise (config =
                                    {libelle: section}, ex. un point du graphe de
                                    progression) : meme table que /api/global mais
                                    une seule analyse GSA, sans stabilite EC3
    POST /api/appliquer             {modele, famille, section, cible?} ou
                                    {modele, famille, applications: [...]} ->
                                    applique et SAUVEGARDE le modele (ecrase
                                    directement le fichier, sans copie)
    POST /api/excel-famille         {libelle, nuance, barre} -> ouvre le classeur
                                    Predim VISIBLE pre-rempli avec le torseur ELU
                                    de la barre gouvernante d'un resultat
                                    d'optimisation (barre, groupe ou globale) —
                                    l'etat porte la section retenue

    NB : le classeur Predim est TOUJOURS alimente en mode torseur (enveloppe
    ELU des efforts a 0/25/50/75/100 % de la barre, extraite de GSA), jamais
    par transposition des chargements exterieurs : l'outil doit fonctionner
    pour tout modele, pas seulement pour une poutre isostatique chargee.

Usage :
    venv\\Scripts\\python.exe app\\server.py            # http://localhost:8765
    venv\\Scripts\\python.exe app\\server.py --port 9000 --no-browser
"""
from __future__ import annotations

import argparse
import json
import math
import queue
import re
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from gsa_bridge.bridge import GsaModel, ConfigurationAnalyseError
from excel_bridge.predim import ouvrir_predim
from dimensionner import (MESURES_ELU, _COMPOSANTES_TORSEUR, _torseur_barre,
                          amplitude_c1_c2, contrainte_combinee, dimensionner,
                          lire_config, portee, serie_sections, taux_elu_fy,
                          trouver_combinaisons, valider_mesures,
                          DimensionnementError)
from algo_opti import ALGOS, ALGO_DEFAUT

STATIC = Path(__file__).resolve().parent / "static"
MODEL_DIR = ROOT / "GSA_model"
JOURNAL_DIR = ROOT / "optimisations"
FAMILLES = {k: v for k, v in json.loads(
    (ROOT / "config" / "familles.json").read_text(encoding="utf-8")).items()
    if not k.startswith("_")}

MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml",
        ".png": "image/png"}


# ------------------------------------------------------------------ thread GSA
class TravailGsa(threading.Thread):
    """Thread unique par lequel passent TOUS les appels GsaAPI.

    Les handlers HTTP (multi-thread) soumettent une fonction via executer() ;
    elle est executee ici en serie, sur ce thread, et le resultat (ou
    l'exception) est renvoye a l'appelant. Le runtime .NET et le moteur GSA
    ne sont ainsi jamais touches que par ce thread.
    """

    def __init__(self):
        super().__init__(daemon=True, name="gsa")
        self.file = queue.Queue()
        self.start()

    def run(self):
        while True:
            fonc, args, retour = self.file.get()
            try:
                retour.put(("ok", fonc(*args)))
            except BaseException as e:                          # noqa: BLE001
                retour.put(("erreur", e))

    def executer(self, fonc, *args):
        retour = queue.Queue(1)
        self.file.put((fonc, args, retour))
        statut, valeur = retour.get()
        if statut == "erreur":
            raise valeur
        return valeur

    def soumettre(self, fonc, *args):
        """Soumet du travail au thread GSA SANS attendre le resultat (fire and
        forget) : pour une tache longue (extraction barre par barre) pilotee
        via un etat partage plutot que par sa valeur de retour. Le callable
        DOIT gerer ses propres exceptions — personne ne lit le retour."""
        self.file.put((fonc, args, queue.Queue(1)))


GSA = TravailGsa()
EXCEL = threading.Lock()        # une seule ouverture de classeur Predim a la fois


# ------------------------------------------------------------ suivi d'avancement
# Etat d'avancement des calculs longs, par canal ("performance", "stabilite",
# "dimensionner", "global"...). Les fonctions de calcul le mettent a jour (y
# compris depuis le thread GSA) ; la page l'interroge via GET /api/progression
# pendant qu'elle attend la reponse du calcul. Purement indicatif : aucune
# logique ne repose dessus.
PROGRES: dict[str, dict] = {}
_PROGRES_LOCK = threading.Lock()


def progres(canal: str, etape: str, fait: int | None = None,
            total: int | None = None) -> None:
    """Publie l'etape courante d'un canal (et son avancement fait/total)."""
    with _PROGRES_LOCK:
        PROGRES[canal] = {"etape": etape, "fait": fait, "total": total}


def etat_progression() -> dict:
    with _PROGRES_LOCK:
        return {k: dict(v) for k, v in PROGRES.items()}


# ------------------------------------------------------------------ metier
def liste_modeles() -> list[str]:
    return sorted(p.name for p in MODEL_DIR.glob("*.gwb"))


def resume_modele(nom: str) -> dict:
    """Tables resumees d'un modele, pour le controle visuel avant calcul.

    Relance TOUJOURS l'analyse ici (si le modele est analysable), au moment
    du chargement : le fichier source peut contenir des resultats perimes
    (calcules lors d'une session GSA anterieure, avant un changement de
    section ou de charge), et chaque appel ulterieur (performances_modele,
    donnees_torseur...) travaille sur sa PROPRE copie fraiche du fichier
    (cf. GsaModel.__init__) — sans ce relancement systematique au chargement,
    rien ne garantit que le calcul de structure qui suit parte d'un etat a
    jour. Un echec d'analyse ne bloque pas le resume (juste signale via
    `analysable`/`probleme`) : l'utilisateur doit pouvoir inspecter un modele
    meme non solvable.
    """
    chemin = MODEL_DIR / Path(nom).name
    if not chemin.exists():
        raise FileNotFoundError(f"Modele introuvable : {chemin.name}")
    cfg = lire_config()
    progres("resume", "copie et ouverture du modele (GsaAPI)…")
    with GsaModel(chemin) as m:
        try:
            m.check_analysis_setup()
            analysable, probleme = True, None
            progres("resume", "analyse GSA du modele…")
            timings = m.analyse()
            if not all(t["ok"] for t in timings):
                analysable, probleme = False, "Analyse GSA en echec sur le modele actuel."
        except ConfigurationAnalyseError as e:
            analysable, probleme = False, str(e)
        progres("resume", "lecture des tables du modele…")
        try:
            refs = trouver_combinaisons(m, cfg["combinaisons"])
        except DimensionnementError:
            refs = None
        try:
            L = portee(m)
        except DimensionnementError:
            L = None
        progres("resume", "terminé")
        return {
            "modele": chemin.name,
            "analysable": analysable,
            "probleme": probleme,
            "combinaisons_trouvees": refs,       # {"ELU": "C1", ...} ou None
            "portee_m": L,
            "noeuds": m.nodes(),
            "elements": m.elements(),
            "sections": m.sections(),
            "materiaux": m.materials(),
            "cas_de_charge": m.load_cases(),
            "charges_poutre": m.beam_loads(),
            "charges_nodales": m.node_loads(),
            "charges_gravite": m.gravity_loads(),
            "listes": m.lists(),
            "taches": m.analysis_tasks(),
            "combinaisons": m.combination_cases(),
        }


def vue_sections_modele(nom: str) -> dict:
    """Geometrie 3D reelle du modele (sections des barres extrudees, via
    GsaAPI Model.Draw — cf. GsaModel.rendu_geometrie), pour le rendu « vue
    sections » du panneau 3D (app/static/viewer3d.js). Aucune analyse
    requise : lecture pure de la geometrie non deformee."""
    chemin = MODEL_DIR / Path(nom).name
    if not chemin.exists():
        raise FileNotFoundError(f"Modele introuvable : {chemin.name}")
    with GsaModel(chemin) as m:
        return m.rendu_geometrie()


def _ref_combinaison(m, valeur, cle: str) -> str:
    """Valide une combinaison choisie par l'utilisateur (id ou 'C<n>') contre
    le modele et la renvoie normalisee ('C<n>')."""
    v = str(valeur or "").strip().upper()
    if not v:
        raise DimensionnementError(f"Aucune combinaison {cle} choisie.")
    if not v.startswith("C"):
        v = "C" + v
    try:
        num = int(v[1:])
    except ValueError:
        raise DimensionnementError(f"Combinaison {cle} invalide : {valeur!r}.")
    if num not in {c["combinaison"] for c in m.combination_cases()}:
        raise DimensionnementError(f"Combinaison {cle} {v} absente du modele.")
    return v


def resoudre_refs(m, elu: str = "", els: str = "") -> dict:
    """Combinaisons ELU/ELS a utiliser pour un calcul.

    Si l'utilisateur a choisi des combinaisons (elu/els = id ou 'C<n>'), on
    les valide contre le modele et on les utilise telles quelles ; sinon on
    detecte par NOM (config combinaisons : combinaisons nommees ELU/ELS).
    Permet de travailler sur un modele dont aucune combinaison ne s'appelle
    explicitement ELU/ELS (l'utilisateur les designe alors dans la page). Un
    choix partiel (un seul des deux) est refuse : le calcul a besoin des deux.
    """
    if elu or els:
        return {"ELU": _ref_combinaison(m, elu, "ELU"),
                "ELS": _ref_combinaison(m, els, "ELS")}
    return trouver_combinaisons(m, lire_config()["combinaisons"])


def performances_modele(nom: str, elu: str = "", els: str = "") -> dict:
    """Performances du modele TEL QUEL (aucune modification) : poids d'acier,
    contraintes extremes a l'ELU — max SIGNE et min SIGNE de TOUTES les
    contraintes GSA (axiale, flexions, combinees C1/C2, cisaillements, von
    Mises...), avec la mesure gouvernante de chacun —, deplacement max (ELS),
    detail barre par barre, et efforts aux extremites par MEMBRE
    (la sortie « 1D member results » de GSA : la barre prise de bout en bout).

    L'analyse est TOUJOURS relancee ici (GsaModel travaille sur sa propre
    copie fraiche du fichier source, cf. resume_modele) : on ne fait jamais
    confiance a d'eventuels resultats deja presents dans le fichier, qui
    peuvent etre perimes (section/charge modifiee depuis leur calcul). Le
    poids est calcule Σ L·A·ρ, avec la densite REELLE du materiau de CHAQUE
    section (cf. `_densites_sections` — un modele mixte acier/bois... aurait
    sinon des masses fausses sur le materiau minoritaire).
    """
    chemin = MODEL_DIR / Path(nom).name
    if not chemin.exists():
        raise FileNotFoundError(f"Modele introuvable : {chemin.name}")
    cfg = lire_config()
    positions = cfg.get("positions", 3)
    t0 = time.perf_counter()

    def suivi(etape):
        # avancement par barre extraite : c'est l'extraction des combinaisons
        # (permutations recalculees a la volee par GSA) qui est longue
        return lambda fait, total: progres("performance", etape, fait, total)

    progres("performance", "copie et ouverture du modele (GsaAPI)…")
    with GsaModel(chemin) as m:
        m.check_analysis_setup()
        refs = resoudre_refs(m, elu, els)
        progres("performance", "analyse GSA du modele…")
        timings = m.analyse()
        if not all(t["ok"] for t in timings):
            raise DimensionnementError(
                "Analyse GSA en echec sur le modele actuel.")

        elements = m.elements()
        sections = {s["section"]: s for s in m.sections()}
        mats = m.materials()
        # l'appel .NET lui-meme (avant le premier callback) peut etre long :
        # GSA y recombine toutes les permutations de la combinaison
        progres("performance",
                f"contraintes ELU {refs['ELU']} — GSA recombine les permutations…")
        stress = m.beam_stresses(refs["ELU"], positions,
                                 progress=suivi("contraintes ELU (enveloppe des permutations)"))
        progres("performance", "contraintes dérivées ELU — appel GSA…")
        derive = m.beam_derived_stresses(refs["ELU"], positions,
                                         progress=suivi("contraintes dérivées ELU"))
        progres("performance", f"déplacements ELS {refs['ELS']} — appel GSA…")
        disp = m.beam_displacements(refs["ELS"], positions,
                                    progress=suivi("déplacements ELS"))
        # extremites seulement (pos 0 et 1) : les efforts i/j n'ont pas besoin
        # des positions intermediaires, et chaque position coute l'extraction
        # de toutes les permutations de la combinaison
        progres("performance", "efforts d'extrémité par membre — appel GSA…")
        membres = m.member_forces(refs["ELU"], 2,
                                  progress=suivi("efforts d'extrémité par membre"))
    progres("performance", "agrégation des résultats par barre…")

    densites = _densites_sections(mats, sections.values())
    # densites REELLEMENT utilisees (sections portees par au moins une barre) :
    # plusieurs valeurs distinctes -> pas de densite unique a afficher pour le modele
    densites_utilisees = {round(densites.get(e["propriete"], 7850.0), 3) for e in elements}
    materiaux_mixtes = len(densites_utilisees) > 1

    # --- une ligne par barre : masse + enveloppes de contrainte et de fleche
    par_barre: dict[int, dict] = {}
    for e in elements:
        s = sections.get(e["propriete"], {})
        rho_barre = densites.get(e["propriete"], 7850.0)
        par_barre[e["element"]] = {
            "element": e["element"],
            "profil": s.get("profil", ""),
            "longueur_m": round(e["longueur_m"], 3),
            "masse_kg": round(e["longueur_m"] * (s.get("aire_m2") or 0.0) * rho_barre, 2),
            "sigma_max_MPa": None, "mesure_max": None,
            "sigma_min_MPa": None, "mesure_min": None,
            "sigmas": {},        # mid -> {"max", "min"} (MPa) : detail par mesure
            "Uz_max_mm": None,
        }
    # max SIGNE et min SIGNE de TOUTES les colonnes de contraintes, avec la
    # mesure gouvernante (colonne de table -> id de mesure affiche)
    for rows, cols in ((stress, _COLS_MESURE["stress"]),
                       (derive, _COLS_MESURE["derive"])):
        for r in rows:
            b = par_barre.get(r["element"])
            if b is None:
                continue
            for col, mid in cols.items():
                v = r[col]
                if isinstance(v, float) and math.isnan(v):
                    continue
                v = round(v / 1e6, 2)
                if b["sigma_max_MPa"] is None or v > b["sigma_max_MPa"]:
                    b["sigma_max_MPa"], b["mesure_max"] = v, mid
                if b["sigma_min_MPa"] is None or v < b["sigma_min_MPa"]:
                    b["sigma_min_MPa"], b["mesure_min"] = v, mid
                sig = b["sigmas"].setdefault(mid, {"max": v, "min": v})
                sig["max"] = max(sig["max"], v)
                sig["min"] = min(sig["min"], v)
    for r in disp:
        b = par_barre.get(r["element"])
        v = r["Uz"]
        if b is None or (isinstance(v, float) and math.isnan(v)):
            continue
        v = round(abs(v) * 1000, 3)
        b["Uz_max_mm"] = v if b["Uz_max_mm"] is None else max(b["Uz_max_mm"], v)

    # --- efforts aux extremites par membre (ids = elements : 1 membre = 1 element)
    # une combinaison enveloppe fournit DEUX lignes par position (perm max/min) :
    # on retient par extremite la valeur signee de plus grande amplitude
    def _enveloppe(rows: list[dict], col: str) -> float | None:
        vals = [r[col] for r in rows
                if not (isinstance(r[col], float) and math.isnan(r[col]))]
        return max(vals, key=abs) if vals else None

    par_membre: dict[int, list[dict]] = {}
    for r in membres:
        par_membre.setdefault(r["member"], []).append(r)
    for mid, lignes in par_membre.items():
        b = par_barre.get(mid)
        if b is None:
            continue
        pos_i = min(r["pos"] for r in lignes)
        pos_j = max(r["pos"] for r in lignes)
        for suffixe, p in (("i", pos_i), ("j", pos_j)):
            sel = [r for r in lignes if r["pos"] == p]
            for cle, col in (("N", "Fx"), ("Vz", "Fz")):
                v = _enveloppe(sel, col)
                b[f"{cle}_{suffixe}_kN"] = None if v is None else round(v / 1e3, 2)
            v = _enveloppe(sel, "Myy")
            b[f"My_{suffixe}_kNm"] = None if v is None else round(v / 1e3, 2)

    barres = sorted(par_barre.values(), key=lambda b: b["element"])

    def extreme(cle: str, pire, cle_mesure: str | None = None) -> dict | None:
        vals = [(b[cle], b["element"], b.get(cle_mesure))
                for b in barres if b[cle] is not None]
        if not vals:
            return None
        v, eid, mes = pire(vals, key=lambda t: t[0])
        out = {"valeur": v, "element": eid}
        if cle_mesure:
            out["mesure"] = mes
        return out

    progres("performance", "terminé")
    return {
        "modele": chemin.name,
        "refs": refs,
        "rho_kg_m3": next(iter(densites_utilisees), 7850.0),  # info : NON fiable si materiaux_mixtes
        "materiaux_mixtes": materiaux_mixtes,
        "poids_total_kg": round(sum(b["masse_kg"] for b in barres), 1),
        "extremes": {
            "sigma_max": extreme("sigma_max_MPa", max, "mesure_max"),
            "sigma_min": extreme("sigma_min_MPa", min, "mesure_min"),
            "fleche_mm": extreme("Uz_max_mm", max),
        },
        "barres": barres,
        "duree_s": round(time.perf_counter() - t0, 2),
    }


# colonnes des tables de contraintes GSA -> id de mesure affiche (perfs) ;
# meme decoupage que MESURES_ELU (By regroupe les fibres +z/-z, Bz +y/-y)
_COLS_MESURE = {
    "stress": {"A": "A", "Sy": "Sy", "Sz": "Sz",
               "By_pz": "By", "By_nz": "By", "Bz_py": "Bz", "Bz_ny": "Bz",
               "C1": "C1", "C2": "C2"},
    "derive": {"SEy": "SEy", "SEz": "SEz", "St": "St", "VM": "VM"},
}

_FAMILLES_CLASSEUR = ("IPE", "IPN", "CHS", "RHS", "SHS", "HD", "HE")


def _profil_predim(profil_gsa: str) -> tuple[str, str]:
    """'CAT IPE-AM IPE80 20170912' -> ('IPE', 'IPE80') pour le classeur Predim.

    SHS (carre) n'a PAS d'onglet dedie dans le classeur : le catalogue GSA
    EN-SHS (designations 'SHS...') existe, mais Predim range ces memes tailles
    dans son onglet RHS, sous le prefixe 'RHS...' (ex. 'SHS100x100x5.0' ->
    'RHS100x100x5,0') — cf. catalogues/filtrer_tubulaires_excel.py, qui
    applique la meme traduction pour construire catalogues/SHS.csv."""
    parts = (profil_gsa or "").split()
    if len(parts) < 3 or parts[0] != "CAT":
        raise DimensionnementError(
            f"Profil non transposable vers le classeur Predim : {profil_gsa!r}")
    nom = parts[2]
    famille = next((f for f in _FAMILLES_CLASSEUR if nom.upper().startswith(f)), None)
    if famille is None:
        raise DimensionnementError(
            f"Le classeur Predim n'a pas d'onglet pour le profil {nom!r}.")
    if famille == "SHS":
        return "RHS", "RHS" + nom[3:]
    return famille, nom


def _nuance_acier(mats: list[dict]) -> str:
    """Nuance lue dans le nom du materiau acier (S235 a defaut)."""
    noms = [str(m["nom"] or "").strip().upper().replace(" ", "")
            for m in mats if m["type"] == "acier"]
    return next((n for n in noms if n in NUANCES_PREDIM), "S235")


# GsaAPI (anglais, Section.MaterialTypeAsString()) -> cle francaise de materials()
_TYPE_GSA_VERS_FR = {
    "STEEL": "acier", "CONCRETE": "beton", "TIMBER": "bois",
    "ALUMINIUM": "aluminium", "FRP": "frp", "GLASS": "verre", "FABRIC": "textile",
    "REBAR": "armature",
}


def _densites_sections(mats: list[dict], sections) -> dict[int, float]:
    """Densite REELLE (kg/m3) de chaque section, par SON materiau effectif —
    et non une densite unique appliquee a tout le modele.

    `sections()` donne le materiau d'une section par (type, grade) : `materiau`
    (ex. "STEEL"/"TIMBER", cf. `_TYPE_GSA_VERS_FR`) et `materiau_grade` (id DANS
    la collection de ce type — ex. SteelMaterials id 2 — qui recoupe l'id de
    `materials()` via (type, id)). Un modele MIXTE (acier + bois...) appliquer
    la densite de l'acier a des barres bois les feraient peser jusqu'a ~19x
    trop lourd (7850 vs ~420 kg/m3) : chaque section a donc sa propre densite.

    Repli (materiau non resolu — grade absent, type non reconnu...) : densite
    acier du modele, sinon 7850.
    """
    par_cle = {(m["type"], m["id"]): m["densite_kg_m3"] for m in mats
               if m["densite_kg_m3"]}
    secours = next((m["densite_kg_m3"] for m in mats
                    if m["type"] == "acier" and m["densite_kg_m3"]),
                   next((m["densite_kg_m3"] for m in mats if m["densite_kg_m3"]), 7850.0))
    return {s["section"]: par_cle.get(
                (_TYPE_GSA_VERS_FR.get(s["materiau"]), s.get("materiau_grade")), secours)
            for s in sections}


def donnees_torseur(nom: str, elu: str = "", els: str = "",
                    canal: str | None = None) -> dict:
    """Enveloppe ELU du torseur de chaque barre, pour la verification Predim.

    Efforts lus dans « Beam and Spring Forces and Moments » (beam_forces) a
    0/25/50/75/100 % de la barre, combinaison ELU — pour une combinaison
    enveloppe, TOUTES les permutations sont prises en compte (lignes perm
    max/min du bridge, reduites par `_torseur_barre`). Par composante : max,
    min, et enveloppe (valeur signee de plus grande amplitude) ; My et Mz
    aussi en debut / milieu / fin pour la distribution de moments (facteurs
    Cm). Unites converties en kN / kNm (convention GSA : N > 0 = traction).
    L'analyse est TOUJOURS relancee (meme raison que performances_modele :
    ne jamais faire confiance a des resultats deja presents, potentiellement
    perimes). `canal` : canal de progression a alimenter (cf. progres).
    """
    def pub(etape, fait=None, total=None):
        if canal:
            progres(canal, etape, fait, total)

    chemin = MODEL_DIR / Path(nom).name
    if not chemin.exists():
        raise FileNotFoundError(f"Modele introuvable : {chemin.name}")
    pub("copie et ouverture du modele (GsaAPI)…")
    with GsaModel(chemin) as m:
        m.check_analysis_setup()
        refs = resoudre_refs(m, elu, els)
        pub("analyse GSA du modele…")
        timings = m.analyse()
        if not all(t["ok"] for t in timings):
            raise DimensionnementError(
                "Analyse GSA en echec sur le modele actuel.")
        elements = m.elements()
        sections = {s["section"]: s for s in m.sections()}
        nuance = _nuance_acier(m.materials())
        pub("torseurs ELU — GSA recombine les permutations…")
        forces = m.beam_forces(          # 0 / 25 / 50 / 75 / 100 %
            refs["ELU"], 5,
            progress=lambda f, t: pub("extraction des torseurs ELU", f, t))

    par_barre: dict[int, list[dict]] = {}
    for r in forces:
        par_barre.setdefault(r["element"], []).append(r)

    barres: dict[int, dict] = {}
    for e in elements:
        rows = par_barre.get(e["element"], [])
        if not rows:
            continue
        s = sections.get(e["propriete"], {})
        barres[e["element"]] = {
            "element": e["element"],
            "profil_gsa": s.get("profil", ""),
            "longueur_m": round(e["longueur_m"], 3),
            **_torseur_barre(rows),
        }
    return {"refs": refs, "nuance": nuance, "barres": barres}


def _entrees_classeur(b: dict, nuance: str) -> dict:
    """Dict d'entrees io_map pour la verification d'UNE barre isolee."""
    famille, nom_profil = _profil_predim(b["profil_gsa"])
    t = b["torseur"]
    return {
        "profil_famille": famille,
        "profil_nom": nom_profil,
        "nuance_acier": nuance,
        "portee_m": b["longueur_m"],
        "conditions_appui": "appuye-appuye",
        "prise_en_compte_poids_propre": "non",
        # torseur ELU = enveloppe signee ; ELS sans objet (pas de chargement)
        "torseur_N_ELU_kN":  t["N"]["enveloppe"],
        "torseur_Vz_ELU_kN": t["Vz"]["enveloppe"],
        "torseur_Vy_ELU_kN": t["Vy"]["enveloppe"],
        "torseur_My_ELU_kNm": t["My"]["enveloppe"],
        "torseur_Mz_ELU_kNm": t["Mz"]["enveloppe"],
        "torseur_N_ELS_kN": 0, "torseur_Vz_ELS_kN": 0, "torseur_Vy_ELS_kN": 0,
        "torseur_My_ELS_kNm": 0, "torseur_Mz_ELS_kNm": 0,
        # distribution de moments -> facteurs Cm du §6.3.3
        "my_debut_kNm": b["my_debut_milieu_fin"][0],
        "my_milieu_kNm": b["my_debut_milieu_fin"][1],
        "my_fin_kNm": b["my_debut_milieu_fin"][2],
        "mz_debut_kNm": b["mz_debut_milieu_fin"][0],
        "mz_milieu_kNm": b["mz_debut_milieu_fin"][1],
        "mz_fin_kNm": b["mz_debut_milieu_fin"][2],
    }


# coefficients de stabilite (deversement, annexe F) editables depuis la page ;
# cle de requete -> (cle io_map, valeur par defaut du classeur Predim)
COEFS_STABILITE = {
    "k":  ("facteur_k_deversement", 0.5),
    "kw": ("facteur_kw_deversement", 1.0),
    "C1": ("facteur_C1_deversement", 1.13),
    "C2": ("facteur_C2_deversement", 0.46),
}

# type de repartition de charge (tableau B.3) -> facteurs de moment Cmy/Cmz/CmLT
# cote classeur (cf. io_map repartition_charge, cellule P35 : U/C/N). « noeuds
# deplacables » impose Cmy = Cmz = CmLT = 0.9. Valeurs acceptees = cles du
# valueMap io_map ; la traduction en U/C/N est faite par BeamWorkbook.set_inputs.
REPARTITIONS_STABILITE = {"uniforme", "concentree", "noeuds_deplacables"}


def valider_coefs(params: dict) -> dict:
    """Coefficients k/kw/C1/C2 + type de repartition de charge de la requete
    -> entrees io_map (vide si absents).

    Accepte aussi bien un dict facon parse_qs (valeurs en listes) qu'un objet
    JSON plat (k/kw/C1/C2 -> nombre, repartition -> chaine)."""
    coefs = {}
    for cle, (cle_io, _) in COEFS_STABILITE.items():
        v = params.get(cle)
        if v not in (None, "", []):
            coefs[cle_io] = float(v[0] if isinstance(v, list) else v)
    rep = params.get("repartition")
    if isinstance(rep, list):
        rep = rep[0] if rep else None
    if rep in REPARTITIONS_STABILITE:
        coefs["repartition_charge"] = rep
    return coefs


def calculer_stabilites(nom: str, coefs: dict | None = None,
                        elu: str = "", els: str = "") -> dict:
    """Taux de stabilite EC3 (classeur Predim, Excel invisible) de chaque barre.

    Les donnees GSA sont extraites sur le thread GSA ; la passe Excel se fait
    sur le thread appelant, sous le verrou EXCEL. `coefs` : entrees io_map
    supplementaires (facteurs k/kw/C1/C2 du deversement) appliquees a chaque
    barre. `elu`/`els` : combinaisons choisies par l'utilisateur (sinon
    detection par nom, cf. resoudre_refs).
    """
    from excel_bridge.stabilite import verifier_stabilites

    paquet = GSA.executer(donnees_torseur, nom, elu, els, "stabilite")
    entrees, ecartees = [], []
    for eid, b in sorted(paquet["barres"].items()):
        try:
            entrees.append({"element": eid, **_entrees_classeur(b, paquet["nuance"]),
                            **(coefs or {})})
        except DimensionnementError as e:
            ecartees.append({"element": eid, "erreur": str(e)})

    t0 = time.perf_counter()
    progres("stabilite", "ouverture du classeur Predim (Excel invisible)…",
            0, len(entrees))
    with EXCEL:
        lignes = verifier_stabilites(
            entrees,
            progress=lambda f, t: progres(
                "stabilite", "vérification EC3 des barres", f, t),
        ) if entrees else []
    progres("stabilite", "terminé")
    return {
        "modele": Path(nom).name,
        "refs": paquet["refs"],
        "barres": lignes + ecartees,
        "duree_s": round(time.perf_counter() - t0, 2),
    }


def ouvrir_excel_barre(params: dict) -> dict:
    """Ouvre le classeur Predim VISIBLE, pre-rempli avec le torseur d'une barre
    (mode barre isolee, sans chargement), pour la verification manuelle."""
    nom = params.get("modele") or ""
    element = int(params.get("element") or 0)
    paquet = GSA.executer(donnees_torseur, nom,
                          params.get("elu") or "", params.get("els") or "")
    b = paquet["barres"].get(element)
    if b is None:
        raise DimensionnementError(f"Barre {element} introuvable dans le modele.")
    donnees = _entrees_classeur(b, paquet["nuance"])
    etiquette = f"stabilite_{Path(nom).stem}_barre{element}".replace(" ", "_")
    with EXCEL:
        chemin = ouvrir_predim(donnees, etiquette)
    return {"ok": True, "fichier": chemin.name, "chemin": str(chemin),
            "element": element, "torseur": b["torseur"],
            "profil": donnees["profil_nom"], "nuance": donnees["nuance_acier"],
            "longueur_m": b["longueur_m"]}


def valider_cible(cible) -> dict | None:
    """Cible d'optimisation envoyee par la page : {"elements": [ids], "libelle"}.

    None = comportement historique (modele entier). Les ids sont valides
    entiers ici ; leur existence dans le modele est verifiee par le bridge.
    """
    if not cible:
        return None
    elements = cible.get("elements") or []
    try:
        ids = sorted({int(e) for e in elements})
    except (TypeError, ValueError):
        raise DimensionnementError("Cible invalide : ids d'elements non entiers.")
    if not ids:
        raise DimensionnementError("Cible vide : aucun element selectionne.")
    return {"elements": ids, "libelle": str(cible.get("libelle") or "")[:80]}


def config_requete(params: dict) -> tuple[Path, str, dict]:
    """(chemin du modele, famille, cfg criteres) communs aux calculs."""
    nom = params.get("modele") or ""
    chemin = MODEL_DIR / Path(nom).name
    if not chemin.exists():
        raise FileNotFoundError(f"Modele introuvable : {chemin.name}")
    famille = params.get("famille") or next(iter(FAMILLES))
    if famille not in FAMILLES:
        raise DimensionnementError(f"Famille inconnue : {famille!r}")

    cfg = lire_config()
    cfg["catalogue"] = FAMILLES[famille]["catalogue"]
    cfg["serie_regex"] = FAMILLES[famille]["regex"]
    crit = params.get("criteres") or {}
    if "fy_Pa" in crit:
        cfg["critere_contrainte"]["fy_Pa"] = float(crit["fy_Pa"])
    if "coefficient" in crit:
        cfg["critere_contrainte"]["coefficient"] = float(crit["coefficient"])
    if "mesures" in crit:
        cfg["critere_contrainte"]["mesures"] = valider_mesures(crit["mesures"])
    if "denominateur" in crit:
        cfg["critere_fleche"]["denominateur"] = float(crit["denominateur"])
    # hauteur/epaisseur maximales (h_m/tw_m,tf_m du catalogue) : plafonds de
    # l'algorithme escalade (algo_opti/escalade.py), defauts dans
    # config/dimensionnement.json (0.5 m / 10 mm), editables cote page
    if crit.get("hauteur_max_m"):
        cfg["hauteur_max_m"] = float(crit["hauteur_max_m"])
    if crit.get("epaisseur_max_mm"):
        cfg["epaisseur_max_mm"] = float(crit["epaisseur_max_mm"])
    # regles de conception de depart de l'escalade : h0 = L_barre/ratio_hauteur,
    # b0 = h0/ratio_largeur (RHS seulement) — L_barre, jamais la portee globale
    if crit.get("ratio_hauteur_depart"):
        cfg["ratio_hauteur_depart"] = float(crit["ratio_hauteur_depart"])
    if crit.get("ratio_largeur_depart"):
        cfg["ratio_largeur_depart"] = float(crit["ratio_largeur_depart"])
    return chemin, famille, cfg


def _echo_criteres(res: dict, cfg: dict) -> None:
    res["criteres"] = {
        "sigma_limite_MPa": round(res["sigma_limite_Pa"] / 1e6, 2),
        "fy_MPa": cfg["critere_contrainte"]["fy_Pa"] / 1e6,
        "coefficient": cfg["critere_contrainte"]["coefficient"],
        "denominateur": cfg["critere_fleche"]["denominateur"],
        "fleche_limite_mm": res.get("fleche_limite_mm")
                            or round(res["fleche_limite_m"] * 1000, 2),
        "mesures": res.get("mesures"),
        "hauteur_max_m": cfg.get("hauteur_max_m"),
        "epaisseur_max_mm": cfg.get("epaisseur_max_mm"),
        "ratio_hauteur_depart": cfg.get("ratio_hauteur_depart"),
        "ratio_largeur_depart": cfg.get("ratio_largeur_depart"),
    }


def lancer_dimensionnement(params: dict) -> dict:
    """Dimensionnement d'une cible unique (barre ou groupe)."""
    chemin, famille, cfg = config_requete(params)
    cfg["cible"] = valider_cible(params.get("cible"))

    t0 = time.perf_counter()
    res = dimensionner(
        chemin, cfg,
        log=lambda s: progres("dimensionner", s),
        progress=lambda f, t, nom_sec: progres(
            "dimensionner", f"analyse de la section {nom_sec}", f, t))
    progres("dimensionner", "terminé")
    res["duree_s"] = round(time.perf_counter() - t0, 2)
    res["famille"] = famille
    res["nuance"] = _nuance_acier(res.pop("materiaux", []))
    _echo_criteres(res, cfg)
    return res


def lancer_optimisation_globale(params: dict) -> dict:
    """Optimisation globale : une section par famille de barres, par
    l'algorithme demande (dossier algo_opti/, defaut brut_force)."""
    chemin, famille, cfg = config_requete(params)
    algo = params.get("algo") or ALGO_DEFAUT
    if algo not in ALGOS:
        raise DimensionnementError(
            f"Algorithme d'optimisation inconnu : {algo!r}. "
            f"Disponibles : {', '.join(ALGOS)}.")
    groupes = [valider_cible(g) for g in (params.get("groupes") or [])]
    if not groupes:
        raise DimensionnementError(
            "Optimisation globale : aucune famille de barres fournie.")
    cfg["groupes"] = groupes
    cfg["famille"] = famille   # algo_opti/escalade : choix du navigateur de catalogue
    cfg["continuite"] = bool(params.get("continuite"))
    # force brute : configuration de depart (defaut = sections maximales) ;
    # sans effet pour genetique (boost initial propre) ni escalade (depart au
    # gabarit le plus fin, toujours)
    cfg["depart_max"] = bool(params.get("depart_max", True))
    # parametres de l'algorithme genetique (valides/bornes dans le module)
    if isinstance(params.get("genetique"), dict):
        cfg["genetique"] = params["genetique"]
    # contrainte de stabilite EC3 (optionnelle) : l'algorithme la verifie en
    # boucle externe (efforts -> stabilite Predim -> sections plus grosses),
    # via ce verificateur injecte (il detient le classeur et le verrou EXCEL)
    if params.get("stabilite"):
        cfg["stabilite"] = True
        cfg["stab_verifier"] = _verifier_stabilites_familles

    def log_global(s: str) -> None:
        print("  " + s)
        progres("global", s)

    t0 = time.perf_counter()
    progres("global", "démarrage de l'optimisation globale…")
    res = ALGOS[algo]["optimiser"](chemin, cfg, log=log_global)
    progres("global", "terminé")
    res["duree_s"] = round(time.perf_counter() - t0, 2)
    res["famille"] = famille
    res["algo"] = algo
    with GsaModel(chemin) as m:
        res["nuance"] = _nuance_acier(m.materials())
    _echo_criteres(res, cfg)
    return res


def evaluer_configuration_globale(params: dict) -> dict:
    """Reevalue UNE configuration precise (une section par famille) parmi
    celles essayees pendant une optimisation globale deja terminee — pour le
    point du graphe de progression que la page regarde (clic ou navigation au
    clavier, cf. app.js::selectionnerPoint). `config` : {libelle -> nom de
    section}, tel que renvoye par l'historique d'algo_opti/*.py.

    UNE SEULE analyse GSA (pas de recherche), meme forme de resultat par
    famille que /api/global (section, contraintes, taux ELU, masse, barre
    gouvernante — pour que les boutons « charger dans le modele »/« Excel »
    fonctionnent a l'identique) mais SANS verification de stabilite EC3
    (couteuse — une passe Excel par famille — reservee au resultat final
    retenu par l'algorithme)."""
    from algo_opti import _commun

    chemin, famille, cfg = config_requete(params)
    groupes = [valider_cible(g) for g in (params.get("groupes") or [])]
    if not groupes:
        raise DimensionnementError("Configuration : aucune famille de barres fournie.")
    config = params.get("config") or {}

    # PAS de plafond hauteur/epaisseur ici : les sections a relire ont deja
    # ete choisies par l'optimisation en cours (potentiellement avec des
    # plafonds differents de ceux par defaut) — on cherche juste ces sections
    # PAR NOM dans la serie de la famille, pas une nouvelle recherche bornee
    cfg.pop("hauteur_max_m", None)
    cfg.pop("epaisseur_max_mm", None)
    serie = {r["nom"]: r for r in serie_sections(cfg)}
    try:
        sections = [serie[config[g["libelle"]]] for g in groupes]
    except KeyError as e:
        raise DimensionnementError(f"Section absente de la serie {famille} : {e}")

    with GsaModel(chemin) as m:
        m.check_analysis_setup()
        ctx = _commun.preparer_contexte(m, cfg)
        _commun.verifier_familles(groupes, ctx["infos_elem"])
        props = [m.section_dediee(g["elements"], nom=f"Config {g['libelle']}")
                 for g in groupes]
        for p, s in zip(props, sections):
            m.set_section_profile(p, s["profil_gsa"])
        details, uz = _commun.evaluer_etat(m, groupes, ctx, sections)
        lignes = [_commun.construire_ligne(groupes[d["gi"]], sections[d["gi"]], d, ctx)
                 for d in details]
        nuance = _nuance_acier(m.materials())

    res = {
        "groupes": lignes,
        "famille": famille,
        "nuance": nuance,
        "masse_totale_kg": round(sum(l["masse_kg"] for l in lignes), 1),
        "fleche_ELS_mm": round(uz * 1000, 2),
        "fleche_limite_mm": round(ctx["fleche_lim"] * 1000, 2),
        "taux_ELS": round(uz / ctx["fleche_lim"], 3),
        "portee_m": ctx["L"],
        "sigma_limite_Pa": ctx["sigma_lim"],
        "refs": ctx["refs"],
        "stabilite": False,
    }
    _echo_criteres(res, cfg)
    return res


def _parametres_algo_texte(res: dict) -> list[str]:
    """Lignes « Parametres » du journal (cf. enregistrer_journal_optimisation) —
    specifiques a l'algorithme utilise (les cles presentes dans `res` varient
    d'un module algo_opti/* a l'autre, cf. leurs `return` respectifs)."""
    lignes = []
    if "genetique" in res:
        gp = res["genetique"]
        lignes.append(f"  population {gp['population']} — generations demandees "
                      f"{gp['generations']} (faites {res.get('generations_faites', res.get('passes'))})")
        lignes.append(f"  mutation {gp['taux_mutation']:.0%} — selection "
                      f"{gp['pourcentage_gagnants']:.0%} — croisement {gp['taux_croisement']:.0%} — "
                      f"boost initial {gp['boost_initial']:.0%} — elitisme {gp['elitisme']}")
    else:
        depart = ("gabarit le plus fin" if res.get("algo") == "escalade"
                  else ("sections maximales" if res.get("depart_max") else "configuration existante"))
        lignes.append(f"  depart : {depart}")
        if res.get("algo") == "brut_force":   # seul brut_force a une continuite reglable
            lignes.append(f"  continuite entre familles adjacentes : "
                          f"{'ON' if res.get('continuite') else 'OFF'}")
    hmax = res.get("hauteur_max_m")
    lignes.append(f"  hauteur maximale : {f'{hmax:g} m' if hmax else '—'}")
    if res.get("stabilite"):
        lignes.append(f"  stabilite EC3 : ON — {res.get('boucles_stabilite', 0)} boucle(s) effectuee(s)")
    else:
        lignes.append("  stabilite EC3 : OFF")
    return lignes


def enregistrer_journal_optimisation(res: dict, params: dict) -> None:
    """Ecrit un compte-rendu texte succinct de l'optimisation dans
    JOURNAL_DIR (une famille = un groupe de barres a section commune, cf.
    valider_cible) : en-tete (algo, parametres, criteres), une ligne par
    configuration essayee (cf. le champ "config" de chaque entree de
    res["historique"], alimente par algo_opti/*.py) et la section retenue par
    famille en clôture. Best-effort : n'importe pas le resultat renvoye a la
    page si l'ecriture echoue (disque plein, dossier verrouille...)."""
    algo = res.get("algo", "?")
    libelle_algo = ALGOS.get(algo, {}).get("libelle", algo)
    modele = params.get("modele") or "?"
    horodatage = datetime.now()

    lignes = [
        f"Optimisation globale — {libelle_algo} ({algo}) — "
        f"{horodatage.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Modele : {modele} (nuance {res.get('nuance', '?')}) — duree {res.get('duree_s', '?')} s",
        f"Famille de sections : {res.get('famille', '?')}",
        "Groupes optimises (ordre) : " + ", ".join(
            g["libelle"] for g in res.get("groupes") or []),
        "",
        "Parametres :",
        *_parametres_algo_texte(res),
    ]
    crit = res.get("criteres") or {}
    lignes.append(
        f"Criteres : sigma <= {crit.get('sigma_limite_MPa', '?')} MPa "
        f"({crit.get('coefficient', 0):.0%} de {crit.get('fy_MPa', '?')} MPa) ; "
        f"fleche <= L/{crit.get('denominateur', '?')} = {crit.get('fleche_limite_mm', '?')} mm"
        + (f" ; hauteur max {crit['hauteur_max_m']:g} m" if crit.get("hauteur_max_m") else ""))
    lignes += [
        "",
        f"Resultat : masse totale {res.get('masse_totale_kg', '?')} kg — "
        f"convergence {'OUI' if res.get('converge') else 'NON'} — "
        f"{res.get('passes', '?')} passe(s) — {res.get('analyses', '?')} analyse(s) GSA",
        "",
    ]

    hist = res.get("historique") or []
    lignes.append(f"--- Configurations essayees ({len(hist)}) ---")
    for i, p in enumerate(hist, 1):
        detail = ", ".join(f"{lib}={sec}" for lib, sec in (p.get("config") or {}).items())
        lignes.append(f"#{i:<5}{p['masse']:>10.1f} kg  {'OK ' if p['ok'] else 'KO '} {detail}")

    lignes += ["", "--- Retenu ---"]
    for g in res.get("groupes") or []:
        stab = (f" — stabilite {g['taux_stabilite']:.3f}" if g.get("taux_stabilite") is not None else "")
        lignes.append(
            f"{g['libelle']} : {g['section']} ({g['masse_kg']} kg) — "
            f"taux ELU {g.get('taux_ELU', '?')}{stab} — {g.get('verdict', '?')}")

    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    nom_modele = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(modele).stem)
    chemin = JOURNAL_DIR / f"{horodatage.strftime('%Y%m%d-%H%M%S')}_{nom_modele}_{algo}.txt"
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")


def calculer_stabilites_lignes(params: dict) -> dict:
    """Taux de stabilite EC3 des barres gouvernantes d'un tableau de resultats
    (dimensionnement barre/groupe). `barres` : une entree par ligne du tableau,
    dans l'ordre — le torseur `barre_gouvernante` renvoye par /api/dimensionner,
    ou null. Aucune extraction GSA : les torseurs ont ete captures pendant la
    boucle de dimensionnement, a l'etat de CHAQUE section essayee. Une seule
    passe Excel (classeur Predim invisible) pour toutes les lignes.
    """
    from excel_bridge.stabilite import verifier_stabilites

    nuance = params.get("nuance") or "S235"
    entrees, erreurs = [], {}
    for i, b in enumerate(params.get("barres") or []):
        if not b or not b.get("element"):
            continue
        try:
            # `element` = indice de la ligne, pour recoller les resultats
            entrees.append({"element": i, **_entrees_classeur(b, nuance)})
        except DimensionnementError as e:
            erreurs[i] = str(e)

    t0 = time.perf_counter()
    progres("stabilite-lignes", "ouverture du classeur Predim (Excel invisible)…",
            0, len(entrees))
    with EXCEL:
        lignes = verifier_stabilites(
            entrees,
            progress=lambda f, t: progres(
                "stabilite-lignes", "vérification EC3 des sections essayées", f, t),
        ) if entrees else []
    progres("stabilite-lignes", "terminé")
    resultats = {}
    for l in lignes:
        if l.get("erreur"):
            erreurs[l["element"]] = l["erreur"]
        else:
            resultats[l["element"]] = {"taux_stabilite": l["taux_stabilite"],
                                       "cas": l["cas"], "taux": l["taux"]}
    return {"resultats": resultats, "erreurs": erreurs,
            "duree_s": round(time.perf_counter() - t0, 2)}


def ajouter_stabilites_globales(res: dict) -> None:
    """Complete chaque famille du resultat global avec le taux de stabilite
    EC3 de sa barre gouvernante (classeur Predim, Excel invisible), calcule
    sur le torseur de l'etat OPTIMISE renvoye par l'algorithme (algo_opti/). Une
    famille en echec (profil hors classeur...) porte `stabilite_erreur` sans
    interrompre les autres."""
    from excel_bridge.stabilite import verifier_stabilites

    entrees = []
    for gi, g in enumerate(res.get("groupes") or []):
        b = g.get("barre_gouvernante")
        if not b:
            continue
        try:
            # `element` = indice de la famille, pour recoller les resultats
            entrees.append({"element": gi,
                            **_entrees_classeur(b, res.get("nuance", "S235"))})
        except DimensionnementError as e:
            g["stabilite_erreur"] = str(e)
    if not entrees:
        return
    with EXCEL:
        lignes = verifier_stabilites(entrees)
    for l in lignes:
        g = res["groupes"][l["element"]]
        if l.get("erreur"):
            g["stabilite_erreur"] = l["erreur"]
        else:
            g["taux_stabilite"] = l["taux_stabilite"]
            g["cas_stabilite"] = l["cas"]
            g["stabilite_detail"] = l["taux"]


def _verifier_stabilites_familles(barres: list[dict], materiaux: list[dict]) -> dict:
    """Verificateur de stabilite injecte dans l'algorithme d'optimisation
    globale (algo_opti/brut_force). Recoit les barres gouvernantes de chaque
    famille (chacune avec une `cle` = indice de famille) + les materiaux du
    modele, calcule la stabilite EC3 via le classeur Predim, et renvoie
    {cle: {taux_stabilite, cas, taux} | {erreur}}.

    La passe Excel tourne sur un THREAD DEDIE (COM hors du thread GSA, qui
    appelle ce verificateur pendant l'optimisation) sous le verrou EXCEL,
    comme les autres acces au classeur — le thread GSA attend (join) le
    resultat entre deux boucles efforts.
    """
    from excel_bridge.stabilite import verifier_stabilites

    nuance = _nuance_acier(materiaux)
    entrees, erreurs = [], {}
    for b in barres:
        cle = b["cle"]
        try:
            entrees.append({"element": cle, **_entrees_classeur(b, nuance)})
        except DimensionnementError as e:
            erreurs[cle] = str(e)

    resultat: dict = {"lignes": [], "erreur": None}

    def _passe() -> None:
        try:
            with EXCEL:
                resultat["lignes"] = verifier_stabilites(entrees) if entrees else []
        except BaseException as e:                              # noqa: BLE001
            resultat["erreur"] = e
            traceback.print_exc()

    t = threading.Thread(target=_passe, name="stab-optim", daemon=True)
    t.start()
    t.join()
    if resultat["erreur"] is not None:
        raise resultat["erreur"]

    out: dict = {}
    for l in resultat["lignes"]:
        if l.get("erreur"):
            out[l["element"]] = {"erreur": l["erreur"]}
        else:
            out[l["element"]] = {"taux_stabilite": l["taux_stabilite"],
                                 "cas": l["cas"], "taux": l["taux"]}
    for cle, msg in erreurs.items():
        out[cle] = {"erreur": msg}
    return out


def ouvrir_excel_famille(params: dict) -> dict:
    """Ouvre le classeur Predim VISIBLE, pre-rempli avec le torseur d'une
    barre gouvernante renvoyee par une optimisation (barre, groupe ou
    globale) : l'etat analyse porte la section retenue, meme si le modele
    n'a pas ete enregistre. Mode torseur : enveloppe ELU a 0/25/50/75/100 %,
    aucun chargement saisi."""
    b = params.get("barre") or {}
    if not b.get("element"):
        raise DimensionnementError("Aucune barre gouvernante fournie.")
    donnees = _entrees_classeur(b, params.get("nuance") or "S235")
    libelle = re.sub(r"[^A-Za-z0-9_-]+", "_", str(params.get("libelle") or "famille"))
    etiquette = f"optim_{libelle}_barre{b['element']}"
    with EXCEL:
        chemin = ouvrir_predim(donnees, etiquette)
    return {"ok": True, "fichier": chemin.name, "chemin": str(chemin),
            "element": b["element"], "torseur": b["torseur"],
            "profil": donnees["profil_nom"], "nuance": donnees["nuance_acier"],
            "longueur_m": b["longueur_m"]}


def appliquer_section(params: dict) -> dict:
    """Applique une ou plusieurs sections du catalogue et SAUVEGARDE le modele.

    Deux formes : {cible, section} (une cible), ou {applications: [{elements,
    libelle, section}, ...]} (optimisation globale : toutes les familles d'un
    coup). C'est la seule action de l'application qui modifie un fichier de
    GSA_model/ — ECRASE DIRECTEMENT le fichier, aucune copie de sauvegarde
    (le fichier charge est toujours la seule source de verite)."""
    nom = params.get("modele") or ""
    chemin = MODEL_DIR / Path(nom).name
    if not chemin.exists():
        raise FileNotFoundError(f"Modele introuvable : {chemin.name}")
    famille = params.get("famille") or next(iter(FAMILLES))
    if famille not in FAMILLES:
        raise DimensionnementError(f"Famille inconnue : {famille!r}")

    # normalise en liste d'applications {cible valide, section}
    if params.get("applications"):
        demandes = [(valider_cible(a), a.get("section") or "")
                    for a in params["applications"]]
    else:
        demandes = [(valider_cible(params.get("cible")), params.get("section") or "")]
    if any(not s for _, s in demandes):
        raise ValueError("Aucune section a appliquer.")

    cfg = lire_config()
    cfg["catalogue"] = FAMILLES[famille]["catalogue"]
    cfg["serie_regex"] = FAMILLES[famille]["regex"]
    # PAS de plafond hauteur/epaisseur ici : la section a appliquer a deja ete
    # choisie par un dimensionnement/optimisation qui a pu utiliser des
    # plafonds plus larges (ou differents) que les defauts de ce fichier de
    # config — on verifie seulement qu'elle appartient bien a la famille,
    # pas qu'elle passerait les memes plafonds de RECHERCHE
    cfg.pop("hauteur_max_m", None)
    cfg.pop("epaisseur_max_mm", None)
    serie = {r["nom"]: r for r in serie_sections(cfg)}
    absentes = [s for _, s in demandes if s not in serie]
    if absentes:
        raise DimensionnementError(
            f"Section(s) {', '.join(absentes)} absente(s) de la serie {famille}.")

    faites = []
    with GsaModel(chemin) as m:
        for cible, section in demandes:
            if cible:
                libelle = cible["libelle"] or f"barres {cible['elements']}"
                prop = m.section_dediee(cible["elements"], nom=f"{libelle} - {section}")
            else:
                libelle = "modele"
                prop = m.sections()[0]["section"]
            info = m.set_section_profile(prop, serie[section]["profil_gsa"])
            faites.append({"libelle": libelle, "section": section,
                           "profil": info["profil"], "propriete": prop,
                           "elements": cible["elements"] if cible else None})
        # reanalyse AVANT d'enregistrer : sans cela, le fichier sauvegarde
        # garde les resultats d'analyse d'AVANT ce changement de section
        # (GSA ne les invalide pas automatiquement), ce qui affiche des
        # resultats perimes si le modele est rouvert directement dans GSA.
        # Best-effort : un modele pas encore configure pour l'analyse (pas
        # de cas de charge...) n'empeche pas d'appliquer/enregistrer la section.
        try:
            m.check_analysis_setup()
            m.analyse()
        except Exception:    # noqa: BLE001
            pass
        m.save_to(chemin)

    return {"ok": True, "modele": chemin.name, "applications": faites,
            # champs de compatibilite avec la forme simple
            "section": faites[0]["section"], "propriete": faites[0]["propriete"],
            "elements": faites[0]["elements"]}


NUANCES_PREDIM = {"S235", "S275", "S355", "S420", "S460"}

# NB : l'ancienne transposition des CHARGEMENTS exterieurs du modele vers le
# classeur Predim (donnees_predim / POST /api/excel) a ete supprimee : elle ne
# valait que pour une poutre isostatique chargee en travee (modele Poutre ISO).
# Le classeur est desormais toujours alimente en MODE TORSEUR (enveloppe ELU a
# 0/25/50/75/100 % extraite de GSA), quel que soit le modele.


# ============================================================================
#  PERFORMANCES EN FLUX (barre par barre) — job de fond + stabilite parallele
# ============================================================================
# Sur un gros modele avec une combinaison enveloppe (des centaines de
# permutations recalculees par GSA A CHAQUE barre), extraire toutes les barres
# d'un coup peut prendre plusieurs minutes sans aucun retour. Ici le calcul
# tourne en tache de fond : le thread GSA extrait les barres UNE PAR UNE (ELU
# contraintes + ELS fleche + torseur, en une passe par barre), et pousse le
# torseur de chaque barre vers un thread Excel SEPARE qui calcule la stabilite
# EC3 EN PARALLELE (ressource distincte : GSA n'est pas mobilise par Excel).
# La page interroge l'etat (poll) et remplit son tableau au fur et a mesure ;
# un stop coupe la boucle entre deux barres (modele 1000+ barres maitrisable).

def _c1_c2_lignes(rows: list[dict], aire: float | None,
                  wel_y: float | None, wel_z: float | None) -> dict:
    """Contraintes combinees C1 (A+B max) / C2 (A+B min), en MPa arrondis,
    pour l'affichage de l'onglet Performances. Calcul delegue a
    `dimensionner.contrainte_combinee` — SEULE implementation de la formule
    (A = N/aire, B = |My|/Wel_y + |Mz|/Wel_z, C1/C2 = A±B), partagee avec
    l'optimisation globale (cf. `algo_opti._commun.evaluer_etat`) pour
    garantir que les deux calculent exactement la meme chose. `rows` :
    lignes `beam_forces` (Fx, Myy, Mzz), deja filtrees a la barre et, pour la
    version par position, a une seule position."""
    cc = contrainte_combinee(rows, aire, wel_y, wel_z)
    return {"C1_MPa": round(cc["c1"] / 1e6, 2) if cc["c1"] is not None else None,
            "C2_MPa": round(cc["c2"] / 1e6, 2) if cc["c2"] is not None else None}


def _efforts_lignes(rows: list[dict]) -> dict:
    """Max/min signes de N/Vy/Vz/My/Mz (kN, kNm) sur les lignes fournies —
    memes conventions que `_torseur_barre` (N > 0 = traction), sans le detail
    debut/milieu/fin (inutile ici, cf. `dimensionner._torseur_barre`)."""
    out = {}
    for cle, col in _COMPOSANTES_TORSEUR.items():
        vals = [r[col] for r in rows if not math.isnan(r[col])]
        out[cle] = {"max": round(max(vals) / 1e3, 3), "min": round(min(vals) / 1e3, 3)} \
            if vals else {"max": None, "min": None}
    return out


def _efforts_par_position(rows: list[dict], aire: float | None,
                          wel_y: float | None, wel_z: float | None) -> list[dict]:
    """Efforts + C1/C2 DISTINGUES par position (0/25/50/75/100 %) plutot que
    reduits sur toute la barre — mode « enveloppe sur les membres » : `rows`
    peut porter 1 ligne par position (cas simple) ou 2 (perm max/min, pour une
    combinaison enveloppe), regroupees ici par `pos`."""
    par_pos: dict[float, list[dict]] = {}
    for r in rows:
        par_pos.setdefault(r["pos"], []).append(r)
    return [{"pos": p, **_efforts_lignes(par_pos[p]),
            **_c1_c2_lignes(par_pos[p], aire, wel_y, wel_z)}
            for p in sorted(par_pos)]


def _perf_ligne(e: dict, section: dict, densite: float, stress: list[dict],
                derive: list[dict], disp: list[dict],
                forces5: list[dict] | None = None,
                avec_stress: bool = True, enveloppe_membres: bool = False,
                fy_Pa: float | None = None, coefficient: float | None = None,
                fleche_lim_mm: float | None = None) -> dict:
    """Ligne de performances d'UNE barre (memes champs que performances_modele,
    calcules sur les tables deja filtrees a cette barre). `densite` : densite
    REELLE (kg/m3) du materiau DE CETTE barre (cf. `_densites_sections`).

    `forces5` (`beam_forces` a 5 positions, TOUJOURS extraits — rapide) donne
    les efforts/moments (N/Vy/Vz/My/Mz, max/min) et les contraintes combinees
    C1/C2 (calculees nous-memes depuis N/My/Mz, cf. `_c1_c2_lignes` — PAS un
    appel GSA aux tables de contraintes). `avec_stress` : si vrai, `stress`/
    `derive` (extraits en plus, couteux) alimentent aussi sigma_max/min sur
    toutes les mesures GSA (comme avant). `enveloppe_membres` : si vrai,
    efforts/C1/C2 sont aussi distingues par position (0/25/50/75/100 %).

    `fy_Pa`/`coefficient`/`fleche_lim_mm` (criteres de dimensionnement
    courants, cf. config/dimensionnement.json) donnent taux_ELU (amplitude
    C1/C2, reduite par `dimensionner.amplitude_c1_c2`, puis exprimee par
    rapport a fy via `dimensionner.taux_elu_fy` — MEME calcul que
    l'optimisation globale, cf. `algo_opti._commun.construire_ligne`, et que
    `dimensionner()`) et taux_ELS = |Uz| / fleche_lim — memes criteres que
    l'onglet Optimisation, ou fleche_lim = portee GLOBALE de l'ouvrage /
    denominateur (PAS la longueur de la barre : une petite barre tres
    flechie par rapport a sa propre longueur peut rester negligeable a
    l'echelle de l'ouvrage). La limite a ne pas depasser pour taux_ELU est
    `coefficient` (ex. 0.9), PAS 1.0 (cf. `taux_elu_fy`) — taux_ELS reste
    limite a 1.0. `ok` resume les deux (None si l'un des taux est
    indisponible ; la stabilite EC3, calculee a part, est combinee cote page
    une fois le resultat arrive)."""
    b = {
        "element": e["element"],
        "profil": section.get("profil", ""),
        "longueur_m": round(e["longueur_m"], 3),
        "masse_kg": round(e["longueur_m"] * (section.get("aire_m2") or 0.0) * densite, 2),
        "sigma_max_MPa": None, "mesure_max": None,
        "sigma_min_MPa": None, "mesure_min": None,
        "sigmas": {}, "Uz_max_mm": None,
    }
    aire, wel_y, wel_z = section.get("aire_m2"), section.get("Zy_m3"), section.get("Zz_m3")
    cc = None
    if forces5:
        b["efforts"] = _efforts_lignes(forces5)
        cc = contrainte_combinee(forces5, aire, wel_y, wel_z)
        b["C1_MPa"] = round(cc["c1"] / 1e6, 2) if cc["c1"] is not None else None
        b["C2_MPa"] = round(cc["c2"] / 1e6, 2) if cc["c2"] is not None else None
        if enveloppe_membres:
            b["positions"] = _efforts_par_position(forces5, aire, wel_y, wel_z)
    if avec_stress:
        for rows, cols in ((stress, _COLS_MESURE["stress"]),
                           (derive, _COLS_MESURE["derive"])):
            for r in rows:
                for col, mid in cols.items():
                    v = r[col]
                    if isinstance(v, float) and math.isnan(v):
                        continue
                    v = round(v / 1e6, 2)
                    if b["sigma_max_MPa"] is None or v > b["sigma_max_MPa"]:
                        b["sigma_max_MPa"], b["mesure_max"] = v, mid
                    if b["sigma_min_MPa"] is None or v < b["sigma_min_MPa"]:
                        b["sigma_min_MPa"], b["mesure_min"] = v, mid
                    sig = b["sigmas"].setdefault(mid, {"max": v, "min": v})
                    sig["max"] = max(sig["max"], v)
                    sig["min"] = min(sig["min"], v)
    for r in disp:
        v = r["Uz"]
        if isinstance(v, float) and math.isnan(v):
            continue
        v = round(abs(v) * 1000, 3)
        b["Uz_max_mm"] = v if b["Uz_max_mm"] is None else max(b["Uz_max_mm"], v)

    sigma_Pa, _ = amplitude_c1_c2(cc) if cc and cc["c1"] is not None else (None, None)
    taux_elu = taux_elu_fy(sigma_Pa, fy_Pa) if fy_Pa and sigma_Pa is not None else None
    taux_els = b["Uz_max_mm"] / fleche_lim_mm \
        if fleche_lim_mm and b["Uz_max_mm"] is not None else None
    b["taux_ELU"] = round(taux_elu, 3) if taux_elu is not None else None
    b["taux_ELS"] = round(taux_els, 3) if taux_els is not None else None
    b["ok"] = (taux_elu <= coefficient and taux_els <= 1) \
        if taux_elu is not None and coefficient is not None and taux_els is not None else None
    return b


class JobPerf:
    """Calcul de performances en flux : etat partage entre le thread GSA
    (extraction barre par barre), le thread Excel (stabilite) et les requetes
    de poll de la page. Tout acces a lignes/stab/meta/etat passe par `lock`."""

    def __init__(self, nom: str, elu: str, els: str, coefs: dict,
                avec_stress: bool = False, enveloppe_membres: bool = False):
        self.nom = nom
        self.elu = elu
        self.els = els
        self.coefs = coefs or {}
        # avec_stress : extrait aussi les tables de contraintes GSA (couteuses
        # — plusieurs appels par barre) pour sigma_max/min sur toutes les
        # mesures ; par defaut seuls les efforts/moments (rapides, un seul
        # appel `beam_forces`) sont extraits, et C1/C2 en sont deduits (cf.
        # _c1_c2_lignes). enveloppe_membres : distingue en plus les efforts
        # par position (0/25/50/75/100 %) plutot que de les reduire sur la barre.
        self.avec_stress = avec_stress
        self.enveloppe_membres = enveloppe_membres
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.lignes: list[dict] = []          # une ligne de perf par barre, en ordre
        self.stab: dict[int, dict] = {}       # element -> resultat de stabilite EC3
        self.torseurs: queue.Queue = queue.Queue()   # (eid, entree|None, erreur|None) ; None = fin
        self.meta: dict = {}                  # refs, rho, nuance, total
        self.etat = "en_cours"                # en_cours | fini | arrete | erreur (extraction GSA)
        self.erreur: str | None = None        # echec de l'extraction GSA
        self.stab_fini = False                # la passe Excel (parallele) a-t-elle fini ?
        self.stab_erreur: str | None = None   # echec global de la passe Excel


PERF_JOBS: dict[str, JobPerf] = {}
PERF_JOBS_LOCK = threading.Lock()


def _perf_extraire(job: JobPerf) -> None:
    """Thread GSA : ouvre + analyse une fois, puis extrait barre par barre
    (contraintes ELU, fleche ELS, efforts d'extremite, torseur) en verifiant le
    stop entre chaque barre. Pousse le torseur de chaque barre vers le thread
    stabilite. Ne leve jamais : les echecs sont stockes dans job.erreur."""
    try:
        chemin = MODEL_DIR / Path(job.nom).name
        if not chemin.exists():
            raise FileNotFoundError(f"Modele introuvable : {chemin.name}")
        cfg = lire_config()
        positions = cfg.get("positions", 3)
        # criteres courants (memes reglages que l'onglet Optimisation) pour les
        # taux ELU/ELS affiches barre par barre, cf. _perf_ligne / taux_elu_fy
        fy_Pa = cfg["critere_contrainte"]["fy_Pa"]
        coefficient = cfg["critere_contrainte"]["coefficient"]
        with GsaModel(chemin) as m:
            m.check_analysis_setup()
            # fleche limite = portee GLOBALE de l'ouvrage / denominateur (pas
            # la longueur de chaque barre, cf. _perf_ligne) — memes appuis que
            # le resume du modele (cf. dimensionner.portee)
            fleche_lim_mm = portee(m) * 1000 / cfg["critere_fleche"]["denominateur"]
            refs = resoudre_refs(m, job.elu, job.els)
            timings = m.analyse()
            if not all(t["ok"] for t in timings):
                raise DimensionnementError("Analyse GSA en echec sur le modele actuel.")
            elements = m.elements()
            sections = {s["section"]: s for s in m.sections()}
            mats = m.materials()
            nuance = _nuance_acier(mats)
            # densite REELLE par section (pas une densite unique pour tout le
            # modele) : un modele mixte acier/bois... aurait sinon des masses
            # fausses sur le materiau minoritaire (cf. _densites_sections)
            densites = _densites_sections(mats, sections.values())
            densites_utilisees = {round(densites.get(e["propriete"], 7850.0), 3)
                                  for e in elements}
            with job.lock:
                job.meta = {"refs": refs,
                            "rho_kg_m3": next(iter(densites_utilisees), 7850.0),
                            "materiaux_mixtes": len(densites_utilisees) > 1,
                            "nuance": nuance, "total": len(elements),
                            # coefficient EFFECTIVEMENT utilise pour taux_ELU
                            # (cf. taux_elu_fy) : la page en a besoin pour la
                            # barre de progression (limite = coefficient, pas 1)
                            "coefficient": coefficient}

            for e in elements:
                if job.stop.is_set():
                    break
                eid = e["element"]
                sel = str(eid)
                # tables de contraintes : SEULEMENT si demande (case a cocher,
                # cf. avec_stress) — plusieurs appels GSA couteux par barre,
                # inutiles pour les efforts/C1/C2 (deduits de beam_forces seul)
                stress = m.beam_stresses(refs["ELU"], positions, elements=sel) \
                    if job.avec_stress else []
                derive = m.beam_derived_stresses(refs["ELU"], positions, elements=sel) \
                    if job.avec_stress else []
                disp = m.beam_displacements(refs["ELS"], positions, elements=sel)
                forces5 = m.beam_forces(refs["ELU"], 5, elements=sel)
                section = sections.get(e["propriete"], {})
                densite_barre = densites.get(e["propriete"], 7850.0)
                ligne = _perf_ligne(e, section, densite_barre, stress, derive, disp,
                                    forces5=forces5, avec_stress=job.avec_stress,
                                    enveloppe_membres=job.enveloppe_membres,
                                    fy_Pa=fy_Pa, coefficient=coefficient,
                                    fleche_lim_mm=fleche_lim_mm)
                with job.lock:
                    job.lignes.append(ligne)
                # torseur -> entree classeur Predim -> file de stabilite
                barre_t = {"element": eid, "profil_gsa": section.get("profil", ""),
                           "longueur_m": round(e["longueur_m"], 3),
                           **_torseur_barre(forces5)}
                try:
                    entree = {"element": eid, **_entrees_classeur(barre_t, nuance),
                              **job.coefs}
                    job.torseurs.put((eid, entree, None))
                except DimensionnementError as ex:
                    job.torseurs.put((eid, None, str(ex)))
        with job.lock:
            job.etat = "arrete" if job.stop.is_set() else "fini"
    except BaseException as e:                                  # noqa: BLE001
        with job.lock:
            job.etat = "erreur"
            job.erreur = str(e)
        if not isinstance(e, (DimensionnementError, ConfigurationAnalyseError,
                              FileNotFoundError, ValueError)):
            traceback.print_exc()
    finally:
        job.torseurs.put(None)                 # sentinelle : fin pour la stabilite


def _perf_stabilite(job: JobPerf) -> None:
    """Thread Excel : consomme les torseurs produits par l'extraction et calcule
    la stabilite EC3 barre par barre, dans un classeur Predim ouvert une seule
    fois. Tourne en PARALLELE de l'extraction GSA (ressources distinctes)."""
    from excel_bridge.stabilite import SessionStabilite

    session = None
    try:
        with EXCEL:
            while True:
                item = job.torseurs.get()
                if item is None or job.stop.is_set():
                    break
                eid, entree, erreur = item
                if erreur is not None:
                    with job.lock:
                        job.stab[eid] = {"element": eid, "erreur": erreur}
                    continue
                if session is None:
                    session = SessionStabilite()
                    session.open()
                r = session.verifier(entree)
                with job.lock:
                    job.stab[eid] = r
    except BaseException as e:                                  # noqa: BLE001
        with job.lock:
            job.stab_erreur = str(e)
        traceback.print_exc()
    finally:
        if session is not None:
            session.close()
        with job.lock:
            job.stab_fini = True


def perf_demarrer(params: dict) -> dict:
    """Demarre un job de performances en flux et renvoie son identifiant.

    Le thread GSA (extraction) est lance en fire-and-forget ; un thread Excel
    (stabilite) tourne en parallele. La page suit via /api/performance/poll."""
    nom = params.get("modele") or ""
    chemin = MODEL_DIR / Path(nom).name
    if not chemin.exists():
        raise FileNotFoundError(f"Modele introuvable : {chemin.name}")
    coefs = valider_coefs(params.get("coefs") or {})
    job = JobPerf(nom, params.get("elu") or "", params.get("els") or "", coefs,
                 avec_stress=bool(params.get("avec_stress")),
                 enveloppe_membres=bool(params.get("enveloppe_membres")))
    jid = uuid.uuid4().hex
    with PERF_JOBS_LOCK:
        # purge des jobs termines (evite l'accumulation en memoire)
        for k in [k for k, j in PERF_JOBS.items() if j.etat != "en_cours"]:
            del PERF_JOBS[k]
        PERF_JOBS[jid] = job
    GSA.soumettre(_perf_extraire, job)
    threading.Thread(target=_perf_stabilite, args=(job,),
                     daemon=True, name=f"stab-{jid[:8]}").start()
    return {"job": jid, "modele": chemin.name}


def perf_etat(jid: str, depuis: int) -> dict:
    """Etat d'un job de performances : nouvelles lignes depuis `depuis`, resultats
    de stabilite connus, meta et statut. N'utilise PAS le thread GSA (lecture
    d'etat partage) : la page peut poller pendant l'extraction."""
    with PERF_JOBS_LOCK:
        job = PERF_JOBS.get(jid)
    if job is None:
        raise DimensionnementError("Job de performances inconnu ou expiré.")
    with job.lock:
        return {
            "lignes": job.lignes[depuis:],
            "recus": len(job.lignes),
            "stab": {str(k): v for k, v in job.stab.items()},
            "meta": job.meta,
            "etat": job.etat,
            "erreur": job.erreur,
            "stab_fini": job.stab_fini,
            "stab_erreur": job.stab_erreur,
        }


def perf_arreter(jid: str) -> dict:
    """Demande l'arret d'un job de performances (coupe entre deux barres)."""
    with PERF_JOBS_LOCK:
        job = PERF_JOBS.get(jid)
    if job is not None:
        job.stop.set()
    return {"ok": True}


# ------------------------------------------------------------------ serveur
class Handler(BaseHTTPRequestHandler):

    timeout = 30        # une connexion muette (preconnexion navigateur) est lachee

    def log_message(self, fmt, *args):          # journal compact
        print(f"  [{self.log_date_time_string()}] {fmt % args}")

    # -- reponses ----------------------------------------------------------
    def _json(self, data, code=200):
        corps = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def _erreur(self, e: Exception, code=400):
        if not isinstance(e, (DimensionnementError, ConfigurationAnalyseError,
                              FileNotFoundError, ValueError)):
            traceback.print_exc()
            code = 500
        self._json({"erreur": str(e)}, code)

    def _fichier(self, chemin: Path):
        if not chemin.is_file():
            self.send_error(404)
            return
        corps = chemin.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(chemin.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    # -- routes ------------------------------------------------------------
    def do_GET(self):
        url = urlparse(self.path)
        try:
            if url.path in ("/", "/index.html"):
                self._fichier(STATIC / "index.html")
            elif url.path.startswith("/static/"):
                self._fichier(STATIC / Path(url.path).name)
            elif url.path == "/api/etat":
                cfg = lire_config()
                self._json({
                    "modeles": liste_modeles(),
                    "familles": list(FAMILLES),
                    "algos": [{"id": aid, "libelle": a["libelle"],
                               "description": a["description"]}
                              for aid, a in ALGOS.items()],
                    "algo_defaut": ALGO_DEFAUT,
                    "mesures_elu": [{"id": mid, "libelle": m["libelle"],
                                     "groupe": m["groupe"]}
                                    for mid, m in MESURES_ELU.items()],
                    "criteres": {
                        "fy_MPa": cfg["critere_contrainte"]["fy_Pa"] / 1e6,
                        "coefficient": cfg["critere_contrainte"]["coefficient"],
                        "denominateur": cfg["critere_fleche"]["denominateur"],
                        "mesures": valider_mesures(
                            cfg["critere_contrainte"].get("mesures")),
                    },
                })
            elif url.path == "/api/progression":
                # etat d'avancement des calculs longs (poll par la page)
                self._json(etat_progression())
            elif url.path == "/api/resume":
                nom = parse_qs(url.query).get("modele", [""])[0]
                self._json(GSA.executer(resume_modele, nom))
            elif url.path == "/api/vue-sections":
                nom = parse_qs(url.query).get("modele", [""])[0]
                self._json(GSA.executer(vue_sections_modele, nom))
            elif url.path == "/api/performance":
                q = parse_qs(url.query)
                nom = q.get("modele", [""])[0]
                elu = q.get("elu", [""])[0]
                els = q.get("els", [""])[0]
                self._json(GSA.executer(performances_modele, nom, elu, els))
            elif url.path == "/api/performance/poll":
                # etat d'un job de performances en flux (ne touche pas GSA)
                q = parse_qs(url.query)
                jid = q.get("job", [""])[0]
                depuis = int(q.get("depuis", ["0"])[0] or 0)
                self._json(perf_etat(jid, depuis))
            elif url.path == "/api/stabilite":
                # la passe Excel se fait sur CE thread (verrou EXCEL) ;
                # seuls les acces GSA passent par le thread travailleur
                q = parse_qs(url.query)
                nom = q.get("modele", [""])[0]
                elu = q.get("elu", [""])[0]
                els = q.get("els", [""])[0]
                self._json(calculer_stabilites(nom, valider_coefs(q), elu, els))
            else:
                self.send_error(404)
        except Exception as e:                                  # noqa: BLE001
            self._erreur(e)

    def do_POST(self):
        url = urlparse(self.path)
        try:
            taille = int(self.headers.get("Content-Length", 0))
            corps = self.rfile.read(taille)
            if url.path == "/api/upload":
                nom = Path(parse_qs(url.query).get("nom", [""])[0]).name
                if not nom.lower().endswith(".gwb"):
                    raise ValueError("Seuls les fichiers .gwb sont acceptes.")
                if not corps:
                    raise ValueError("Fichier vide.")
                (MODEL_DIR / nom).write_bytes(corps)
                self._json({"ok": True, "modele": nom, "modeles": liste_modeles()})
            elif url.path == "/api/performance/start":
                # demarre un job de performances en flux (barre par barre)
                params = json.loads(corps or b"{}")
                self._json(perf_demarrer(params))
            elif url.path == "/api/performance/stop":
                params = json.loads(corps or b"{}")
                self._json(perf_arreter(params.get("job") or ""))
            elif url.path == "/api/dimensionner":
                params = json.loads(corps or b"{}")
                self._json(GSA.executer(lancer_dimensionnement, params))
            elif url.path == "/api/stabilite-lignes":
                # passe Excel pure (torseurs deja captures) : sur CE thread,
                # sous le verrou EXCEL — aucun appel GSA
                params = json.loads(corps or b"{}")
                self._json(calculer_stabilites_lignes(params))
            elif url.path == "/api/global":
                params = json.loads(corps or b"{}")
                res = GSA.executer(lancer_optimisation_globale, params)
                # si la contrainte de stabilite etait active, l'algorithme a
                # deja verifie chaque famille (taux par ligne) ; sinon on
                # ajoute une passe Excel INFORMATIVE (non contraignante), sur
                # CE thread, hors GSA
                if not res.get("stabilite"):
                    try:
                        ajouter_stabilites_globales(res)
                    except Exception as e:                      # noqa: BLE001
                        res["stabilite_erreur"] = str(e)
                try:
                    enregistrer_journal_optimisation(res, params)
                except Exception as e:                          # noqa: BLE001
                    print(f"[avertissement] journal d'optimisation non ecrit : {e}")
                self._json(res)
            elif url.path == "/api/global/config":
                # reevaluation d'UN point du graphe de progression (survol/
                # navigation clavier cote page) : pas de journal, pas de
                # stabilite (couteux, reserve au resultat final retenu)
                params = json.loads(corps or b"{}")
                self._json(GSA.executer(evaluer_configuration_globale, params))
            elif url.path == "/api/appliquer":
                params = json.loads(corps or b"{}")
                self._json(GSA.executer(appliquer_section, params))
            elif url.path == "/api/excel-famille":
                params = json.loads(corps or b"{}")
                self._json(ouvrir_excel_famille(params))
            elif url.path == "/api/excel-barre":
                params = json.loads(corps or b"{}")
                self._json(ouvrir_excel_barre(params))
            else:
                self.send_error(404)
        except Exception as e:                                  # noqa: BLE001
            self._erreur(e)


def main() -> None:
    parser = argparse.ArgumentParser(description="Interface web du dimensionneur GSA")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true",
                        help="ne pas ouvrir le navigateur au demarrage")
    args = parser.parse_args()

    adresse = f"http://localhost:{args.port}"

    # allow_reuse_address laisserait, sous Windows, DEUX instances se lier au
    # meme port sans erreur (le navigateur tombe alors sur la mauvaise et la
    # page ne repond plus) : on exige un port libre et on echoue clairement.
    class Serveur(ThreadingHTTPServer):
        allow_reuse_address = False

    try:
        # Requetes en parallele ; les appels GsaAPI sont serialises par TravailGsa.
        serveur = Serveur(("127.0.0.1", args.port), Handler)
    except OSError:
        sys.exit(f"Le port {args.port} est deja pris : le dimensionneur est "
                 "probablement deja lance (verifier les processus python), "
                 "ou choisir un autre port avec --port.")
    print(f"Dimensionneur GSA -> {adresse}   (Ctrl+C pour arreter)")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(adresse)).start()
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        print("\nArret.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
