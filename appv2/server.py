# -*- coding: utf-8 -*-
"""Interface web locale d'appv2 — dimensionneur GSA par GROUPES de barres.

Deuxieme version de l'interface (`app_old/`, la premiere, reste en place et
peut tourner en meme temps sur un autre port). Meme charte graphique
qu'`app_old/`, mais une AUTRE ORGANISATION DE PAGE et trois partis pris de
calcul differents.

DISPOSITION DE LA PAGE (01/09/2026) : entrees a gauche, sorties a droite.
  - le BANDEAU (en haut a droite) porte le chargement du modele : il n'est dans
    aucune des deux colonnes, parce que les deux en dependent ;
  - COLONNE GAUCHE, cinq onglets : Resume, Criteres (ELU / ELS / instabilite),
    Performances, Optimisation, Opt. globale. Les deux onglets d'optimisation
    n'y montrent qu'un RESUME (cartes de statistiques, bilan par famille, et
    pour la globale un graphique poids/essai) ;
  - COLONNE DROITE, deux onglets facon navigateur : Vue 3D (par defaut) et
    Detail optimisation — le tableau complet, une ligne par section essayee,
    exportable en CSV, et l'endroit ou l'on choisit la section a charger dans
    le modele.
Cote serveur, cette reorganisation n'a demande que deux champs de plus par
essai : `aire_m2` (colonne du tableau detaille) et, pour l'optimisation
globale, `poids_modele_kg` (l'ordonnee du graphique — poids du perimetre
optimise dans l'etat ou l'essai laisse le modele, cf. `_CtxGlobal.essayer`).

Les trois partis pris de calcul :

  1. GROUPES. On ne raisonne plus sur le modele entier d'un coup mais sur une
     FAMILLE de barres — celles qui partagent la meme propriete de section GSA.
     Le groupe se choisit AVANT les onglets ; tout ce qu'ils affichent porte sur
     lui seul (et l'extraction ne paie que ces barres).
  2. ELEMENTS SEULEMENT. Aucune lecture par MEMBRE GSA (`Member1dForce`) :
     l'element du maillage est la seule maille de raisonnement.
  3. QUATRE CRITERES COMPARABLES. Pour chaque barre, la combinaison
     dimensionnante est cherchee sur TOUTES les permutations de l'enveloppe ELU
     (aucune reduction max/min, cf. commun/gsa_bridge/permutations.py) et pour
     CHACUN des quatre criteres de `commun/criteres.py` — contrainte combinee,
     torsion, cisaillement, von Mises. Le serveur renvoie les quatre ; la page
     coche/decoche les trois derniers et recalcule le critere retenu SANS
     revenir au serveur (cf. `criteres.criteres_dimensionnants`).

STABILITE EC3 §6.3 : depuis le 01/09/2026 elle est calculee par
`commun/stabilite_ec3` (Python pur), plus par le classeur Predim. Meme
interface, meme dict d'entree, meme dict de sortie — la bascule tient dans
`_session_stabilite()` ci-dessous. Ce que ca change :
  - environ 2.10^4 fois plus rapide (0,60 s par barre contre ~30 us), donc plus
    aucune raison d'economiser les verifications ;
  - plus de verrou `EXCEL` sur les calculs, plus de classeur a ouvrir, plus
    d'erreur COM transitoire a encaisser ;
  - C1 et C2 (facteurs de moment du Mcr de deversement) ne sont plus SAISIS
    mais CALCULES barre par barre depuis le diagramme de moment (§3.5 de
    l'Annexe MCR) — ils ont donc disparu de l'encadre Instabilite, et k = kw = 1
    est impose (domaine de validite de ces formules) ;
  - la classe de section, que le classeur fournissait, est calculee elle aussi
    (`commun/stabilite_ec3/classe_section.py`).
Le classeur reste utilise pour UNE chose : le bouton « Ouvrir dans Excel »
d'une barre (`ouvrir_excel_barre`), qui sert a refaire le calcul a la main. Il
y est pre-rempli avec les C1/C2 QUE LE MODULE VIENT DE CALCULER, pour que les
deux donnent la meme chose.

L'onglet Optimisation reduit la section d'UN groupe : pour chaque section
catalogue plus legere de la meme categorie, elle est REELLEMENT ecrite dans
le modele GSA (`GsaModel.set_section_profile`) et l'analyse relancee — pas
une approximation sur les efforts de la section actuelle — puis les taux
ELU sont determines par la MEME methode que l'onglet Performances
(combinaison dimensionnante par critere retenu, cf. `_extraire_optim`), et les
criteres ELS du modele reevalues sur les deplacements frais. La stabilite EC3
(Excel) n'est verifiee que pour les candidats qui passent ELU et ELS, mais
alors pour TOUTES les barres du groupe (pas seulement la plus sollicitee en
ELU — la barre gouvernante en stabilite peut differer).

ELS PAR NOEUDS NOMMES. Le critere de service n'est plus une fleche de barre
comparee a L/denominateur : ce sont des DEPLACEMENTS DE NOEUDS que le modele
declare lui-meme en les NOMMANT (`ELS_glob_X`, `ELS_3pts_X` — cf.
commun/els_noeuds.py). La page ne renseigne, par critere trouve, que la
direction comparee et la limite en mm. Consequence sur l'affichage : l'ELS
n'est plus une colonne du tableau par barre (il ne porte pas sur les barres)
mais un tableau a lui, qualifiant la structure entiere.

ARCHITECTURE DES THREADS : identique a `app_old/server.py` — serveur multi-thread
pour que la page ne soit jamais bloquee, mais UN SEUL thread travailleur pour
tous les appels GsaAPI (l'API .NET de GSA exige d'etre pilotee depuis un seul
thread).

API :
    GET  /api/etat                  modeles .gwb, criteres par defaut, criteres
                                    ELU comparables et leurs libelles
    GET  /api/progression           avancement des calculs longs, par canal
    GET  /api/resume?modele=<nom>   resume complet d'un modele — la page en
                                    deduit elle-meme les GROUPES (elements
                                    regroupes par propriete de section) — dont
                                    `criteres_els` : les criteres de service
                                    declares par les NOMS des noeuds
    GET  /api/vue-sections?modele=<nom>  geometrie 3D reelle (sections extrudees)
    POST /api/elu/start             {modele, sections?: [id], criteres?,
                                    nuance_modele?, elu?, els?, criteres_els?,
                                    coefs?} -> demarre
                                    le calcul EN FLUX du groupe (dont, EN PARALLELE,
                                    la stabilite EC3 de chaque barre — thread Excel
                                    separe, cf. _stabilite) et renvoie {job}
    GET  /api/elu/poll?job=<id>&depuis=<n>  nouvelles lignes depuis l'indice n,
                                    stabilites connues (`stab`), meta et etat
                                    (en_cours/fini/arrete/erreur), `stab_fini`
    POST /api/elu/stop              {job} -> arrete le job (coupe entre deux
                                    paquets de barres)
    POST /api/excel-barre           {modele, element, elu?, coefs?} -> ouvre
                                    le classeur Predim VISIBLE pre-rempli avec le
                                    torseur ELU de la barre sur SA combinaison
                                    dimensionnante ET avec les C1/C2 calcules
                                    pour elle (k = kw = 1), pour verification
                                    manuelle ; renvoie aussi `stabilite`, le
                                    resultat complet du module
    POST /api/optim/start           {modele, section: [id], criteres?, coefs?,
                                    elu?, els?, criteres_els?} -> demarre l'optimisation
                                    du groupe (reanalyse GSA reelle par candidat,
                                    cf. _extraire_optim) et renvoie {job}
    GET  /api/optim/poll?job=<id>&depuis=<n>  nouveaux candidats depuis l'indice n,
                                    stabilites connues, meta, etat, `arret_auto`
                                    (arret automatique apres SEUIL_KO_CONSECUTIFS echecs)
    POST /api/optim/stop            {job} -> arrete le job (coupe entre deux candidats)
    POST /api/optim/charger-section {modele, section, elements?, profil_gsa} ->
                                    enregistre <modele>_opti.gwb avec cette section
                                    affectee au groupe et l'ouvre dans GSA
    POST /api/global/start          {modele, familles: [{section, coefs?}] DANS
                                    L'ORDRE, algo, profondeur?, criteres?, coefs?,
                                    elu?, els?, criteres_els?, avec_stabilite?,
                                    stabilite_approfondie?, elu_perimetre_complet?}
                                    -> demarre l'optimisation GLOBALE (plusieurs
                                    familles enchainees, cf. _optimiser_global)
    GET  /api/global/poll?job=<id>&depuis=<n>  nouveaux essais depuis l'indice n,
                                    bilan par famille, meta (etat initial/final,
                                    gain total) et etat
    POST /api/global/stop           {job} -> arrete (coupe entre deux essais)
    POST /api/global/charger        {modele, familles: [{section, elements, profil_gsa}]}
                                    -> enregistre <modele>_opti.gwb avec TOUTES les
                                    sections retenues et l'ouvre dans GSA
    POST /api/upload?nom=<f.gwb>    depose un .gwb dans GSA_model/

Usage :
    venv\\Scripts\\python.exe appv2\\server.py            # http://localhost:8767
    venv\\Scripts\\python.exe appv2\\server.py --port 9000 --no-browser
"""
from __future__ import annotations

import argparse
import json
import math
import os
import queue
import sys
import threading
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "commun"))

from commun.gsa_bridge.bridge import GsaModel, ConfigurationAnalyseError
from commun.els_noeuds import (appliquer_reglages as appliquer_reglages_els,
                               criteres_du_modele as criteres_els_du_modele,
                               evaluer as evaluer_els, reglages_config,
                               taux_max as taux_els_max)
from commun.gsa_bridge.permutations import (contraintes_derivees_par_permutation,
                                            deplacements_par_permutation,
                                            efforts_par_permutation,
                                            libelles_permutations, positions_pct)
from commun.excel_bridge.predim import ouvrir_predim
from criteres import CRITERES, CRITERE_BASE, LIBELLES, criteres_dimensionnants, taux_par_permutation
from dimensionner import DimensionnementError, lire_config, portee, trouver_combinaisons
from ec3 import geometrie, sections_acier
from commun.catalogues import charger_catalogue
from commun.stabilite_ec3.section_catalogue import (
    FAMILLES_CLASSEUR as _FAMILLES_CLASSEUR,
    NUANCE_DEFAUT,
    ONGLET_PREDIM as _ONGLET_PREDIM,
    nom_catalogue_par_dimensions as _nom_catalogue_par_dimensions,
    profil_predim as _profil_predim)

STATIC = Path(__file__).resolve().parent / "static"
MODEL_DIR = ROOT / "GSA_model"
WIKI_DIR = ROOT / "Wiki"

MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml",
        ".png": "image/png"}

# positions le long de chaque barre : 0/25/50/75/100 % — meme decoupage que le
# classeur Predim et que l'onglet Performances v2 d'`app_old/`
POSITIONS = 5

# barres extraites par PAQUET : le cout dominant est l'interop .NET, et un
# selecteur GSA portant 20 barres coute a peine plus qu'une seule (cf.
# tests/scripts/canopee_elu_permutations.py). Le stop est verifie entre deux
# paquets, ce qui reste assez fin pour rester reactif.
PAQUET = 20

# types d'elements 1D porteurs (les autres n'ont pas de torseur exploitable)
TYPES_1D = ("BAR", "BEAM", "TIE", "STRUT")

# onglet Optimisation : au-dela de ce nombre de candidats consecutifs qui ne
# verifient pas ELU/ELS (en descendant vers des sections de plus en plus
# legeres), on arrete d'en tester d'autres — au-dela, il est tres improbable
# qu'une section encore plus legere passe (cf. _extraire_optim)
SEUIL_KO_CONSECUTIFS = 10

# criteres ELU compares sur les candidats d'une optimisation (par groupe comme
# globale) : les trois qui se calculent depuis le seul torseur. Le von Mises est
# exclu — il se lit dans les contraintes derivees de GSA, non extraites la par
# economie (cf. `contraintes_derivees_par_permutation`).
CRITERES_OPTIM = ("combine", "torsion", "cisaillement")

# masse equivalente d'une section dont la designation catalogue est inconnue
# (profil 'STD ...' saisi a la main) : aire GSA x densite acier
DENSITE_ACIER_KG_M3 = 7850.0

# familles reconnues par le classeur Predim (onglets) ; nuances acceptees par
# son entree "nuance_acier" — memes constantes que `app_old/server.py`.
# `_FAMILLES_CLASSEUR`/`_ONGLET_PREDIM` : deplacees dans
# `commun/stabilite_ec3/section_catalogue.py` le 01/09/2026 (`commun/criteres.py`
# en a besoin a son tour pour la classification EC3 §5.5 du critere ELU
# « combine ») — importees ici sous leur ancien nom pour ne pas toucher tous
# leurs usages locaux.
NUANCES_PREDIM = {"S235", "S275", "S355", "S420", "S460"}

# longueurs de flambement / deversement editables depuis la page ; cle de
# requete -> cle io_map. Elles sont OPTIONNELLES (defaut = portee de la barre,
# formule '=Lo' du classeur, meme defaut cote module Python) ; le bouton
# « longueur = longueur de l'element » les ecrase PAR BARRE avec sa propre
# longueur (cf. _entrees_classeur), independamment de ces valeurs uniformes.
#
# C1, C2, k et kw N'Y SONT PLUS depuis la bascule vers `commun/stabilite_ec3` :
# C1/C2 sont calcules barre par barre (§3.5 de l'Annexe MCR) et k = kw = 1 est
# impose, parce que ces formules ne valent que dans ce cas (« Les valeurs de C1
# et C2 ont ete determinees pour kz = 1 et kw = 1 »). Rien n'est perdu : k*L et
# la longueur de deversement jouent le meme role dans Mcr, et `Ldev` reste
# libre. Les cles io_map correspondantes existent toujours et sont remplies par
# `ouvrir_excel_barre`, avec les valeurs CALCULEES.
COEFS_STABILITE = {
    "Lfy": "longueur_flambement_y_m", "Lfz": "longueur_flambement_z_m",
    "Ldev": "longueur_deversement_m",
}
REPARTITIONS_STABILITE = {"uniforme", "concentree", "noeuds_deplacables"}


def _session_stabilite():
    """LE POINT DE BASCULE du moteur de stabilite EC3 §6.3.

    Renvoie une session au contrat `open()` / `verifier(entree)` / `close()`,
    utilisable en context manager. Deux implementations existent, avec la MEME
    interface et le MEME dict de sortie :

      commun.stabilite_ec3.session.SessionStabilitePython   (actuelle)
      commun.excel_bridge.stabilite.SessionStabilite        (le classeur)

    Revenir au classeur = changer la ligne ci-dessous. L'egalite des deux a ete
    mesuree a 0,0000 % a coefficients egaux sur 63 barres et 3 modeles
    (`tests/scripts/comparaison_stabilite_excel_python.py`) ; le classeur reste
    l'oracle de ce test, il n'est donc pas du code mort.
    """
    from commun.stabilite_ec3.session import SessionStabilitePython
    return SessionStabilitePython()


# ------------------------------------------------------------------ thread GSA
class TravailGsa(threading.Thread):
    """Thread unique par lequel passent TOUS les appels GsaAPI (cf. en-tete)."""

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
        """Soumet du travail SANS attendre le resultat (tache longue pilotee par
        un etat partage). Le callable DOIT gerer ses propres exceptions."""
        self.file.put((fonc, args, queue.Queue(1)))


GSA = TravailGsa()
# Une seule ouverture de classeur Predim a la fois. Depuis la bascule de la
# stabilite vers `commun/stabilite_ec3`, ce verrou ne protege plus QUE le
# bouton « Ouvrir dans Excel » d'une barre (`ouvrir_excel_barre`) : les calculs
# de stabilite, eux, n'ouvrent plus rien.
EXCEL = threading.Lock()


# ------------------------------------------------------------ suivi d'avancement
PROGRES: dict[str, dict] = {}
_PROGRES_LOCK = threading.Lock()


def progres(canal: str, etape: str, fait: int | None = None,
            total: int | None = None) -> None:
    with _PROGRES_LOCK:
        PROGRES[canal] = {"etape": etape, "fait": fait, "total": total}


def etat_progression() -> dict:
    with _PROGRES_LOCK:
        return {k: dict(v) for k, v in PROGRES.items()}


# ------------------------------------------------------------------ metier
def liste_modeles() -> list[str]:
    return sorted(p.name for p in MODEL_DIR.glob("*.gwb"))


def liste_wiki() -> list[dict]:
    """Un onglet par fichier `Wiki/*.md`, trie par nom de fichier. Le titre de
    l'onglet est la premiere ligne '# ...' du fichier (marqdown), a defaut le
    nom de fichier. Contenu renvoye BRUT (markdown) : c'est app.js qui le
    transforme en HTML, apres avoir echappe tout le texte (cf. rendreMarkdown),
    donc un contenu malveillant dans un .md ne peut pas s'executer."""
    if not WIKI_DIR.is_dir():
        return []
    pages = []
    for chemin in sorted(WIKI_DIR.glob("*.md")):
        markdown = chemin.read_text(encoding="utf-8")
        titre = chemin.stem
        for ligne in markdown.splitlines():
            ligne = ligne.strip()
            if ligne.startswith("#"):
                titre = ligne.lstrip("#").strip() or titre
                break
            if ligne:
                break
        pages.append({"nom": chemin.stem, "titre": titre, "markdown": markdown})
    return pages


def resume_modele(nom: str) -> dict:
    """Tables resumees d'un modele, pour le controle visuel et le regroupement.

    L'analyse est TOUJOURS relancee ici : le fichier source peut porter des
    resultats perimes, et chaque calcul ulterieur travaille sur sa propre copie
    fraiche (cf. GsaModel.__init__). Un echec d'analyse ne bloque pas le resume
    (signale via `analysable`/`probleme`) : on doit pouvoir inspecter un modele
    non solvable.

    La page deduit les GROUPES de ce resume (elements regroupes par
    `propriete`), sans route dediee : tout y est deja.
    """
    chemin = MODEL_DIR / Path(nom).name
    if not chemin.exists():
        raise FileNotFoundError(f"Modele introuvable : {chemin.name}")
    cfg = lire_config()
    progres("resume", "copie et ouverture du modèle (GsaAPI)…")
    with GsaModel(chemin) as m:
        try:
            m.check_analysis_setup()
            analysable, probleme = True, None
            progres("resume", "analyse GSA du modèle…")
            timings = m.analyse()
            if not all(t["ok"] for t in timings):
                analysable, probleme = False, "Analyse GSA en échec sur le modèle actuel."
        except ConfigurationAnalyseError as e:
            analysable, probleme = False, str(e)
        progres("resume", "lecture des tables du modèle…")
        try:
            refs = trouver_combinaisons(m, cfg["combinaisons"])
        except DimensionnementError:
            refs = None
        try:
            L = portee(m)
        except DimensionnementError:
            L = None
        progres("resume", "terminé")
        elements, sections, materiaux = m.elements(), m.sections(), m.materials()
        return {
            "modele": chemin.name,
            "analysable": analysable,
            "probleme": probleme,
            "combinaisons_trouvees": refs,
            "portee_m": L,
            # poids total Sigma L.A.rho (elements reels, densite reelle par
            # materiau de section, cf. _poids_total_kg) — affiche en tete du
            # panneau 3D, calcul pur (aucun appel GSA supplementaire)
            "poids_total_kg": _poids_total_kg(elements, sections, materiaux),
            # criteres de service declares par les NOMS des noeuds du modele
            # (cf. commun/els_noeuds.py) : la page en fait un encadre ou seules
            # la direction et la limite en mm restent a renseigner
            "criteres_els": _criteres_els(m),
            "noeuds": m.nodes(),
            "elements": elements,
            "sections": sections,
            "materiaux": materiaux,
            "cas_de_charge": m.load_cases(),
            "charges_poutre": m.beam_loads(),
            "charges_nodales": m.node_loads(),
            "charges_gravite": m.gravity_loads(),
            "listes": m.lists(),
            "taches": m.analysis_tasks(),
            "combinaisons": m.combination_cases(),
        }


def vue_sections_modele(nom: str) -> dict:
    """Geometrie 3D reelle du modele (sections extrudees, via GsaAPI Model.Draw)
    pour la vue « sections » du panneau 3D. Aucune analyse requise."""
    chemin = MODEL_DIR / Path(nom).name
    if not chemin.exists():
        raise FileNotFoundError(f"Modele introuvable : {chemin.name}")
    with GsaModel(chemin) as m:
        return m.rendu_geometrie()


def _ref_combinaison(m, valeur, cle: str) -> str:
    """Valide une combinaison choisie par l'utilisateur (id ou 'C<n>') contre le
    modele et la renvoie normalisee ('C<n>')."""
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
        raise DimensionnementError(f"Combinaison {cle} {v} absente du modèle.")
    return v


def refs_elu_els(m, elu: str = "", els: str = "") -> dict:
    """{'ELU': 'C47', 'ELS': 'C48'|None}.

    Difference volontaire avec `app_old/server.py::resoudre_refs`, qui exige les
    deux : ici l'ELU seul suffit a remplir le tableau (les quatre criteres sont
    des criteres ELU), l'ELS etant un bilan separe. Des modeles reels n'ont
    aucune combinaison ELS (la Canopee, par exemple) — refuser le calcul entier
    pour ce seul bilan n'aurait pas de sens.

    UNE SEULE combinaison ELS : tous les criteres nodaux du modele
    (ELS_glob_X, ELS_3pts_X) sont verifies sous celle-ci.

    Une combinaison explicitement choisie est validee contre le modele ; sinon
    elle est detectee par NOM (config/dimensionnement.json).
    """
    voulues = lire_config()["combinaisons"]
    nommees = {}
    try:
        nommees = trouver_combinaisons(m, voulues)
    except DimensionnementError:
        pass
    ref_elu = _ref_combinaison(m, elu, "ELU") if elu else nommees.get("ELU")
    if not ref_elu:
        raise DimensionnementError(
            f"Aucune combinaison nommée {voulues.get('ELU', 'ELU')!r} dans ce "
            "modèle : choisir la combinaison ELU dans l'encadré Combinaisons.")
    ref_els = _ref_combinaison(m, els, "ELS") if els else nommees.get("ELS")
    return {"ELU": ref_elu, "ELS": ref_els}


def _criteres_els(m, reglages: dict | None = None) -> list[dict]:
    """Criteres de service du modele (noeuds nommes ELS_glob_X / ELS_3pts_X),
    regles par la page (`reglages`) ou, a defaut, par config/dimensionnement.json.

    Les reglages de la page l'emportent sur ceux du fichier : l'encadre ELS
    est le pilote normal de ces limites, la configuration ne servant que de
    valeurs de depart (et aux entrees sans interface, cf.
    `commun/dimensionner.py`)."""
    par_config, defauts = reglages_config(lire_config())
    criteres = appliquer_reglages_els(criteres_els_du_modele(m), par_config, defauts)
    if reglages:
        criteres = appliquer_reglages_els(criteres, reglages)
    return criteres


def _paquets(elements: list[dict], taille: int = PAQUET):
    for i in range(0, len(elements), taille):
        yield elements[i:i + taille]


def _libelles_els(m, ref: str | None, temoin: int, POSITIONS: int) -> list[str] | None:
    """Etiquettes des permutations de la combinaison ELS ('C48p03'...), pour
    nommer la sous-combinaison qui gouverne chaque critere de service.

    Meme mecanique que l'etiquetage ELU (cf. `_extraire`) : mesure sur UNE
    barre temoin, valable pour tout le modele — l'expansion d'une enveloppe ne
    depend que de sa definition. Les tableaux nodaux suivent le MEME ordre de
    permutations que les tableaux 1D de la meme combinaison (cf.
    `deplacements_noeuds_par_permutation`), donc ces etiquettes valent aussi
    pour eux.

    None si la combinaison n'est pas choisie ou n'a pas de resultat exploitable
    sur la barre temoin : les criteres restent calcules, seule leur
    sous-combinaison gouvernante retombe sur 'perm001'."""
    if not ref:
        return None
    dep0 = deplacements_par_permutation(m._result(ref), str(temoin), POSITIONS).get(temoin)
    if dep0 is None:
        return None
    return libelles_permutations(m, int(ref[1:]), temoin, dep0.shape[0],
                                 POSITIONS)["libelles"]


def _bilan_els(m, ref: str | None, criteres: list[dict],
               libelles: list[str] | None, coefficient: float = 1.0) -> dict:
    """Bilan ELS de l'etat COURANT du modele : une ligne par critere declare,
    plus le taux retenu (le max) et le critere qui le gouverne.

    GLOBAL par nature — un critere porte sur des noeuds nommes, pas sur les
    barres d'un groupe : il qualifie la structure entiere, quel que soit le
    groupe etudie dans l'onglet Performances.

    `coefficient` : seuil de verdict ELS (cf. commun/els_noeuds.py::evaluer),
    meme principe que le coefficient ELU — 1.0 par defaut (pas de marge)."""
    if not ref:
        return {"combinaison": None, "taux": None, "gouvernant": None,
                "criteres": [dict(c, taux=None, valeur_mm=None, ok=None)
                             for c in criteres]}
    lignes = evaluer_els(m._result(ref), criteres, libelles, coefficient)
    taux, gouvernant = taux_els_max(lignes)
    return {"combinaison": ref, "taux": taux, "gouvernant": gouvernant,
            "criteres": lignes}


def _critere_retenu(blocs: dict[str, dict | None],
                    actifs: list[str]) -> tuple[str, dict] | None:
    """(critere, case brute de `criteres.critere_dimensionnant`) de taux
    maximal parmi les criteres ACTIFS (cases cochees cote page, cf.
    `app.js::critereRetenu`, dont c'est la contrepartie serveur) et
    effectivement calculables sur cette barre. None si aucun ne l'est.

    Necessaire depuis que la stabilite EC3 est calculee sur LA combinaison
    dimensionnante du critere retenu plutot que sur une enveloppe (cf.
    `_torseur_dimensionnant`) : contrairement au tableau ELU (recalcule cote
    page a chaque coche/decoche, cf. en-tete d'`app.js`), la stabilite est un
    calcul SERVEUR — elle doit donc connaitre les criteres actifs AU MOMENT DU
    LANCEMENT (`job.criteres_actifs`), et la page relance le calcul quand ils
    changent (cf. `Object.values(CASES_CRITERES)` dans app.js) pour que les
    deux restent coherents."""
    meilleur = None
    for c in actifs:
        b = blocs.get(c)
        if b is None:
            continue
        if meilleur is None or b["taux"] > meilleur[1]["taux"]:
            meilleur = (c, b)
    return meilleur


# index des moments de flexion dans les 6 composantes du torseur, cf.
# commun/gsa_bridge/permutations.py::COMPOSANTES (Fx, Fy, Fz, Mxx, Myy, Mzz)
_I_MYY, _I_MZZ = 4, 5


def _composantes_torseur(eff: np.ndarray, perm: int,
                         position: int) -> tuple[float, float, float, float, float, float]:
    """(N, Vy, Vz, Mxx, My, Mz) en kN/kNm, valeurs BRUTES (non arrondies) de LA
    case (permutation, position) — cf. `_torseur_dimensionnant`, qui les met en
    forme pour la stabilite EC3, et `_valeurs_torseur`, qui les arrondit pour
    l'affichage. N > 0 = traction (convention classeur)."""
    fx, fy_, fz, mxx, myy, mzz = (float(v) for v in eff[perm, position])
    return fx / 1e3, fy_ / 1e3, fz / 1e3, mxx / 1e3, myy / 1e3, mzz / 1e3


def _valeurs_torseur(eff: np.ndarray, perm: int, position: int) -> dict:
    """Les 6 composantes du torseur a LA case (permutation, position), ARRONDIES
    pour l'affichage — mêmes arrondis que `_bloc_critere` (2 decimales pour les
    forces, 3 pour les moments) —, plus le LIEU (`lieu_pct`, 0/25/50/75/100 %)
    ou cette case a ete lue. Sert aux colonnes d'EFFORTS du tableau detaille
    (onglets Optimisation et Opt. globale) : la combinaison et la position
    dimensionnantes y sont deja affichees en texte (`combinaison_elu`,
    `combinaison_stab`...), ces colonnes montrent le TORSEUR qui va avec —
    `lieu_pct` precise A QUEL ENDROIT de la barre il a ete extrait (les 5
    positions du decoupage `POSITIONS = 5` sont toutes accessibles ; la case
    dimensionnante peut tomber sur n'importe laquelle, pas seulement 0 ou 100 %)."""
    N, Vy, Vz, Mxx, My, Mz = _composantes_torseur(eff, perm, position)
    return {"N_kN": round(N, 2), "Vy_kN": round(Vy, 2), "Vz_kN": round(Vz, 2),
            "Mxx_kNm": round(Mxx, 3), "My_kNm": round(My, 3), "Mz_kNm": round(Mz, 3),
            "lieu_pct": positions_pct(eff.shape[1])[position]}


# valeurs par defaut (case dimensionnante inconnue) des 6 colonnes d'efforts
# + le lieu ou elles ont ete lues
_EFFORT_VIDE = {"N_kN": None, "Vy_kN": None, "Vz_kN": None,
                "Mxx_kNm": None, "My_kNm": None, "Mz_kNm": None, "lieu_pct": None}


def _prefixer(prefixe: str, valeurs: dict) -> dict:
    """{"N_kN": v, ...} -> {"elu_N_kN": v, ...} ou {"stab_N_kN": v, ...} : les
    lignes de l'onglet Opt. globale portent l'ELU et la stabilite dans le MEME
    dict a plat (`_CtxGlobal.etat_courant`), le prefixe evite toute collision ;
    on l'applique aussi cote « un groupe » pour que les deux tableaux du
    detail (Un groupe / Globale) partagent exactement les memes noms de
    colonnes cote page (`celulesEfforts` dans app.js)."""
    return {f"{prefixe}_{cle}": v for cle, v in valeurs.items()}


def _torseur_dimensionnant(eff: np.ndarray, perm: int,
                           position: int) -> tuple[dict, list[float], list[float]]:
    """Torseur ELU pour la stabilite EC3, a partir de LA SEULE combinaison
    dimensionnante (`perm`) identifiee par `_critere_retenu`
    — PAS une enveloppe qui melangerait, composante par composante, des
    permutations differentes (`dimensionner._torseur_barre` fait ce melange ;
    utilise ailleurs dans le projet mais plus par appv2 depuis que le bouton
    « Ouvrir dans Excel » a lui aussi ete bascule sur cette methode, pour
    rester coherent avec la combinaison affichee dans le tableau).

    Renvoie (torseur au format attendu par `_entrees_classeur` — kN/kNm,
    N > 0 = traction —, distribution de My/Mz a 0/50/100 % DANS CETTE MEME
    permutation pour les facteurs Cm du deversement, §6.3.3). Les 0/50/100 %
    sont les positions 1/3/5 du decoupage 0/25/50/75/100 % (`POSITIONS = 5`).

    Reutilise `_composantes_torseur` pour l'extraction (valeurs BRUTES, non
    arrondies : ce sont elles qui alimentent le calcul de stabilite, pas
    `_valeurs_torseur`, reservee a l'affichage)."""
    N, Vy, Vz, Mxx, My, Mz = _composantes_torseur(eff, perm, position)
    torseur = {
        "N":  {"max": N,  "min": N,  "enveloppe": N},
        "Vz": {"max": Vz, "min": Vz, "enveloppe": Vz},
        "Vy": {"max": Vy, "min": Vy, "enveloppe": Vy},
        "My": {"max": My, "min": My, "enveloppe": My},
        "Mz": {"max": Mz, "min": Mz, "enveloppe": Mz},
    }
    npos = eff.shape[1]
    i0, imid, ifin = 0, npos // 2, npos - 1
    my_dmf = [float(eff[perm, i, _I_MYY]) / 1e3 for i in (i0, imid, ifin)]
    mz_dmf = [float(eff[perm, i, _I_MZZ]) / 1e3 for i in (i0, imid, ifin)]
    return torseur, my_dmf, mz_dmf


def _bloc_critere(d: dict | None, libelles: list[str], combinaisons: dict,
                  npos: int, fy_Pa: float | None,
                  coefficient: float | None) -> dict | None:
    """Met en forme, pour la page, la case dimensionnante d'UN critere.

    `d` vient de `criteres.critere_dimensionnant` : les six composantes du
    torseur y coexistent (meme permutation, meme position), contrairement a une
    enveloppe reduite max/min.
    """
    if d is None:
        return None
    perm = d["perm"]
    lib = libelles[perm] if perm < len(libelles) else f"perm{perm + 1:03d}"
    info = combinaisons.get(lib, {})
    fx, fy_eff, fz, mxx, myy, mzz = d["efforts"]
    taux = d["taux"]
    bloc = {
        "taux": round(taux, 4),
        "ok": (taux <= coefficient) if coefficient is not None else None,
        "perm": perm + 1,
        "libelle": lib,
        "combinaison": info.get("combinaison", lib),
        "nom_combinaison": info.get("nom", ""),
        "position_pct": positions_pct(npos)[d["position"]],
        "N_kN": round(fx / 1e3, 2), "Vy_kN": round(fy_eff / 1e3, 2),
        "Vz_kN": round(fz / 1e3, 2), "Mxx_kNm": round(mxx / 1e3, 3),
        "My_kNm": round(myy / 1e3, 3), "Mz_kNm": round(mzz / 1e3, 3),
    }
    if d["critere"] == "combine" and fy_Pa:
        # sigma = taux x fy : le taux combine EST max(|C1|,|C2|)/fy
        bloc["sigma_MPa"] = round(taux * fy_Pa / 1e6, 2)
    if "St_Pa" in d:
        bloc["St_MPa"] = round(d["St_Pa"] / 1e6, 2)
        bloc["SEy_MPa"] = round(d["SEy_Pa"] / 1e6, 2)
        bloc["SEz_MPa"] = round(d["SEz_Pa"] / 1e6, 2)
        bloc["VM_MPa"] = round(d["VM_Pa"] / 1e6, 2)
    if "axe" in d:
        bloc["axe"] = d["axe"]
    if "signe" in d:
        bloc["signe"] = d["signe"]
    return bloc


# ============================================================================
#  STABILITE EC3 §6.3 — resolution du profil
#
#  Le CALCUL, lui, est dans `commun/stabilite_ec3` (cf. `_session_stabilite`).
#  La traduction « profil GSA -> (famille, designation) » (`_profil_predim`,
#  `_nom_catalogue_par_dimensions`, `_FAMILLES_CLASSEUR`, `_ONGLET_PREDIM`,
#  importees plus haut) vit desormais dans
#  `commun/stabilite_ec3/section_catalogue.py` : elle sert a la fois a choisir
#  le CATALOGUE ou lire les caracteristiques de section, a l'ONGLET du classeur
#  Predim quand on ouvre celui-ci a la main, et — depuis le 01/09/2026 — a la
#  classification EC3 §5.5 du critere ELU « combine » (`commun/criteres.py`),
#  qui a besoin de la meme geometrie catalogue que la stabilite.
# ============================================================================


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
    et non une densite unique appliquee a tout le modele (cf. app_old/server.py,
    meme logique : un modele mixte acier/bois... aurait sinon des masses
    fausses sur le materiau minoritaire).

    Repli (materiau non resolu) : densite acier du modele, sinon 7850.
    """
    par_cle = {(m["type"], m["id"]): m["densite_kg_m3"] for m in mats
               if m["densite_kg_m3"]}
    secours = next((m["densite_kg_m3"] for m in mats
                    if m["type"] == "acier" and m["densite_kg_m3"]),
                   next((m["densite_kg_m3"] for m in mats if m["densite_kg_m3"]), 7850.0))
    return {s["section"]: par_cle.get(
                (_TYPE_GSA_VERS_FR.get(s["materiau"]), s.get("materiau_grade")), secours)
            for s in sections}


def _poids_total_kg(elements: list[dict], sections: list[dict], mats: list[dict]) -> float:
    """Poids total de la structure : Sigma L.A.rho sur les elements REELS
    (les elements factices n'ont pas de matiere), avec la densite reelle du
    materiau de CHAQUE section (cf. _densites_sections)."""
    aires = {s["section"]: s["aire_m2"] for s in sections}
    densites = _densites_sections(mats, sections)
    total = sum(e["longueur_m"] * aires.get(e["propriete"], 0.0)
                * densites.get(e["propriete"], 7850.0)
                for e in elements if not e["factice"])
    return round(total, 1)


def valider_coefs(params: dict) -> tuple[dict, bool]:
    """Coefficients k/kw/C1/C2/repartition + longueurs de flambement/
    deversement de la requete -> entrees io_map (vide si absents), plus le
    drapeau « longueur = longueur de l'element » (bool) : quand actif, il
    ECRASE Lfy/Lfz/Ldev PAR BARRE une fois sa longueur reelle connue (cf.
    `_entrees_classeur`), independamment des trois valeurs uniformes ci-dessus.

    Accepte aussi bien un dict facon parse_qs (valeurs en listes) qu'un objet
    JSON plat (k/kw/C1/C2/Lfy/Lfz/Ldev -> nombre, repartition -> chaine)."""
    coefs = {}
    for cle, cle_io in COEFS_STABILITE.items():
        v = params.get(cle)
        if v not in (None, "", []):
            coefs[cle_io] = float(v[0] if isinstance(v, list) else v)
    rep = params.get("repartition")
    if isinstance(rep, list):
        rep = rep[0] if rep else None
    if rep in REPARTITIONS_STABILITE:
        coefs["repartition_charge"] = rep
    return coefs, bool(params.get("longueur_par_element"))


def _entrees_classeur(b: dict, nuance: str, coefs: dict,
                      longueur_par_element: bool,
                      profil_force: tuple[str, str] | None = None) -> tuple[dict, str | None]:
    """Dict d'entrees io_map pour la verification d'UNE barre isolee, + la
    note de repli catalogue de `_profil_predim` (None pour un profil
    catalogue normal).

    `b` : {"profil_gsa", "longueur_m", "torseur", "my_debut_milieu_fin",
    "mz_debut_milieu_fin"} — meme forme que `dimensionner._torseur_barre` (+
    profil_gsa/longueur_m). `coefs` : sortie de `valider_coefs` (k/kw/C1/C2/
    repartition, et Lfy/Lfz/Ldev si saisis a la main). `longueur_par_element`
    (bool) : si vrai, Lfy/Lfz/Ldev sont EGALES A LA LONGUEUR DE CETTE BARRE,
    quelle que soit la valeur manuelle de `coefs` — la longueur reelle de
    chaque element est connue barre par barre, pas une valeur unique.
    `profil_force` : (famille, nom) deja resolus, court-circuite
    `_profil_predim` — utilise par l'onglet Optimisation, qui teste une
    section CATALOGUE choisie par la page (donc deja connue), pas celle
    reellement affectee a la barre dans GSA.

    `b["combinaison_gouvernante"]`/`b["position_gouvernante_pct"]` : notent
    dans le classeur (cellules C2/C3, prevues a cet effet a cote des libelles
    'Combi'/'Pos', SANS EFFET sur le calcul) quelle combinaison et quelle
    position ont fourni le torseur saisi ci-dessus — fournis par LES TROIS
    appelants (Performances, Optimisation, verification manuelle d'une barre
    isolee), qui identifient tous une combinaison dimensionnante unique
    (`_critere_retenu`) depuis que `ouvrir_excel_barre` ne s'appuie plus sur
    une enveloppe.

    `b["my_debut_milieu_fin"]`/`b["mz_debut_milieu_fin"]` sont OPTIONNELS
    (None) : `_torseur_dimensionnant` les calcule TOUJOURS en meme temps que le
    torseur (meme case, meme appel), donc `ouvrir_excel_barre` et
    `ouvrir_excel_candidat` les fournissent tous les deux depuis le 02/09/2026
    (ce dernier via `job.stab[nom]`/l'essai, qui les gardent desormais). None
    ne reste possible que si la stabilite n'a pas ete verifiee pour ce candidat
    (case decochee) : les cellules D31:D33/D35:D37 restent alors VIDES plutot
    que de recevoir un faux plat (le torseur repete trois fois), et le classeur
    retombe sur ses Cmy/Cmz manuels (1,0) — degrade mais honnete, cf. `Torseur`
    dans `commun/stabilite_ec3/_commun.py`. Sans effet sur C1/C2/k/kw, qui sont
    recopiees telles quelles par l'appelant (cf. son docstring)."""
    if profil_force is not None:
        famille, nom_profil, note = profil_force[0], profil_force[1], None
    else:
        famille, nom_profil, note = _profil_predim(b["profil_gsa"])
    t = b["torseur"]
    entree = {
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
        **coefs,
    }
    # distribution de moments -> facteurs Cm du §6.3.3, cf. docstring
    if b.get("my_debut_milieu_fin") is not None:
        entree["my_debut_kNm"], entree["my_milieu_kNm"], entree["my_fin_kNm"] = \
            b["my_debut_milieu_fin"]
    if b.get("mz_debut_milieu_fin") is not None:
        entree["mz_debut_kNm"], entree["mz_milieu_kNm"], entree["mz_fin_kNm"] = \
            b["mz_debut_milieu_fin"]
    if longueur_par_element:
        entree["longueur_flambement_y_m"] = b["longueur_m"]
        entree["longueur_flambement_z_m"] = b["longueur_m"]
        entree["longueur_deversement_m"] = b["longueur_m"]
    if b.get("combinaison_gouvernante") is not None:
        entree["combinaison_dimensionnante"] = b["combinaison_gouvernante"]
    if b.get("position_gouvernante_pct") is not None:
        entree["position_dimensionnante"] = f"{b['position_gouvernante_pct']:.0f} %"
    return entree, note


def _donnees_torseur_barre(nom: str, elu: str, element: int, fy_Pa: float | None,
                           criteres_actifs: list[str]) -> tuple[dict, str]:
    """Torseur ELU d'UNE SEULE barre (mode Excel visible), sur SA combinaison
    dimensionnante — EXACTEMENT la meme methode que le calcul en flux
    (`_critere_retenu`/`_torseur_dimensionnant`), pas une enveloppe qui
    melangerait, composante par composante, des permutations differentes
    (ancien comportement, source du desaccord constate entre la combinaison
    affichee dans le tableau et le torseur transmis a Excel : `_torseur_barre`
    prenait le pire Vy, le pire Vz et le pire Mz chacun sur SA PROPRE
    combinaison, independamment de N/My). + nuance du modele, pour
    `ouvrir_excel_barre`. L'ELS n'est pas utilise ici (torseur ELU seul : les
    criteres de service portent sur des noeuds, pas sur une barre isolee). `criteres_actifs` : memes criteres coches que le tableau affiche
    a la page (cf. `app.js::criteresActifs`), pour que la combinaison retenue
    ici soit CELLE MONTREE dans la colonne « Combinaison ELU dimensionnante »."""
    chemin = MODEL_DIR / Path(nom).name
    if not chemin.exists():
        raise FileNotFoundError(f"Modèle introuvable : {chemin.name}")
    with GsaModel(chemin) as m:
        m.check_analysis_setup()
        refs = refs_elu_els(m, elu)
        timings = m.analyse()
        if not all(t["ok"] for t in timings):
            raise DimensionnementError("Analyse GSA en échec sur le modèle actuel.")
        e = next((x for x in m.elements() if x["element"] == element), None)
        if e is None:
            raise DimensionnementError(f"Barre {element} introuvable dans le modèle.")
        sections = sections_acier(m, fy_Pa=fy_Pa, source_av="gsa")
        sec = sections.get(e["propriete"], {})
        nuance = _nuance_acier(m.materials())

        resultat = m._result(refs["ELU"])
        eff = efforts_par_permutation(resultat, str(element), POSITIONS).get(element)
        if eff is None:
            raise DimensionnementError(
                f"La combinaison {refs['ELU']} n'a pas de résultats sur la barre {element}.")
        try:
            der = contraintes_derivees_par_permutation(resultat, str(element), POSITIONS).get(element)
        except Exception:                                        # noqa: BLE001
            der = None                     # von Mises indisponible, le reste tient

        blocs = criteres_dimensionnants(eff, der, sec)
        retenu = _critere_retenu(blocs, criteres_actifs)
        if retenu is None:
            raise DimensionnementError(
                f"Aucun critère ELU actif calculable sur la barre {element} : "
                "combinaison dimensionnante indéterminée.")
        _, bloc_gouv = retenu
        perm_g, pos_g = bloc_gouv["perm"], bloc_gouv["position"]

        etiq = libelles_permutations(m, int(refs["ELU"][1:]), element, eff.shape[0], POSITIONS)
        libelles = etiq["libelles"]
        lib_gouv = libelles[perm_g] if perm_g < len(libelles) else f"perm{perm_g + 1:03d}"

        torseur, my_dmf, mz_dmf = _torseur_dimensionnant(eff, perm_g, pos_g)
        b = {"element": element, "profil_gsa": sec.get("profil", ""),
             "longueur_m": round(e["longueur_m"], 3), "torseur": torseur,
             "my_debut_milieu_fin": my_dmf, "mz_debut_milieu_fin": mz_dmf,
             "combinaison_gouvernante": lib_gouv,
             "position_gouvernante_pct": positions_pct(eff.shape[1])[pos_g]}
        return b, nuance


def ouvrir_excel_barre(params: dict) -> dict:
    """Ouvre le classeur Predim VISIBLE, pre-rempli avec le torseur d'une barre
    sur SA combinaison dimensionnante (mode barre isolee, sans chargement),
    pour refaire le calcul a la main.

    C'est le SEUL usage du classeur depuis que la stabilite est calculee par
    `commun/stabilite_ec3` (cf. `_session_stabilite`) — et il n'a de sens que
    si les deux partent des memes hypotheses. Le classeur recoit donc, en plus
    du torseur, les COEFFICIENTS QUE LE MODULE VIENT DE CALCULER pour cette
    barre : C1 et C2 (§3.5 de l'Annexe MCR, deduits de son diagramme de moment)
    et k = kw = 1. Sans ce report, le classeur retomberait sur ses valeurs
    d'abaque par defaut (1,13 / 0,46 et k = 0,5) et afficherait un taux de
    deversement different de celui du tableau — ce qui est precisement ce qu'on
    vient a verifier.

    La reponse porte `stabilite`, le resultat complet du module (les quatre
    taux, le cas dimensionnant, la classe, C1/C2, Mcr) : la page l'affiche a
    cote du torseur, pour que la comparaison avec l'ecran d'Excel soit
    immediate."""
    nom = params.get("modele") or ""
    element = int(params.get("element") or 0)
    coefs, longueur_par_element = valider_coefs(params.get("coefs") or {})
    crit = params.get("criteres") or {}
    cfg = lire_config()
    fy_Pa = float(crit["fy_Pa"]) if crit.get("fy_Pa") else cfg["critere_contrainte"]["fy_Pa"]
    criteres_actifs = [c for c in (params.get("criteres_actifs") or []) if c in CRITERES]
    if CRITERE_BASE not in criteres_actifs:
        criteres_actifs.insert(0, CRITERE_BASE)
    b, nuance = GSA.executer(_donnees_torseur_barre, nom, params.get("elu") or "",
                             element, fy_Pa, criteres_actifs)
    donnees, note = _entrees_classeur(b, nuance, coefs, longueur_par_element)

    # 1) on calcule d'abord la stabilite comme le fait le tableau…
    stabilite = _session_stabilite().verifier({"element": element, **donnees})
    if note and not stabilite.get("erreur") and not stabilite.get("profil_substitue"):
        stabilite["profil_substitue"] = note
    # 2) …puis on recopie DANS LE CLASSEUR les coefficients qui en sortent, pour
    #    qu'il reparte des memes hypotheses (cf. docstring)
    if not stabilite.get("erreur"):
        donnees["facteur_C1_deversement"] = stabilite["C1"]
        donnees["facteur_C2_deversement"] = stabilite["C2"]
        donnees["facteur_k_deversement"] = stabilite["k"]
        donnees["facteur_kw_deversement"] = stabilite["kw"]

    etiquette = f"stabilite_appv2_{Path(nom).stem}_barre{element}".replace(" ", "_")
    with EXCEL:
        chemin, profil_substitue = ouvrir_predim(donnees, etiquette)
    r = {"ok": True, "fichier": chemin.name, "chemin": str(chemin),
         "element": element, "torseur": b["torseur"],
         "combinaison": b["combinaison_gouvernante"],
         "position_pct": b["position_gouvernante_pct"],
         "stabilite": stabilite,
         "my_debut_milieu_fin": b["my_debut_milieu_fin"],
         "mz_debut_milieu_fin": b["mz_debut_milieu_fin"],
         # profil saisi a la main (note non nulle) : on montre le profil GSA
         # d'origine plutot que la designation catalogue approchee (dans
         # `donnees["profil_nom"]`), donnee ci-dessous comme substitution —
         # meme convention que le repli catalogue normal (cf. _profil_predim)
         "profil": b["profil_gsa"] if note else donnees["profil_nom"],
         "nuance": donnees["nuance_acier"],
         "longueur_m": b["longueur_m"]}
    substitution = profil_substitue or (donnees["profil_nom"] if note else None)
    if substitution:
        r["profil_substitue"] = substitution
    return r


def _ouvrir_excel_connu(*, profil_gsa: str, element: int, longueur_m: float,
                        combinaison: str | None, torseur: dict,
                        C1: float | None, C2: float | None,
                        k: float | None, kw: float | None,
                        nuance: str, coefs: dict, longueur_par_element: bool,
                        etiquette: str,
                        my_debut_milieu_fin: list[float] | None = None,
                        mz_debut_milieu_fin: list[float] | None = None) -> dict:
    """Ouvre le classeur Predim VISIBLE, pre-rempli avec un torseur et des
    COEFFICIENTS DEJA CONNUS — sans rouvrir GSA, contrairement a
    `ouvrir_excel_barre`.

    C'est le coeur de `ouvrir_excel_candidat` (bouton Excel du detail
    Optimisation/Opt. globale, cf. son docstring) : la source de verite y est
    le CANDIDAT deja calcule (`job.stab[nom]` ou l'essai retenu), qui porte
    deja tout ce qu'il faut — torseur gouvernant, C1/C2/k/kw, classe — puisque
    c'est exactement ce que le tableau affiche. Reinterroger GSA recalculerait
    la MEME chose, plus lentement, avec un risque reel de diverger si le
    modele a bouge depuis (autre optimisation lancee, GSA ferme...).

    `torseur` : {"N_kN", "Vy_kN", "Vz_kN", "Mxx_kNm", "My_kNm", "Mz_kNm"} —
    memes cles que `_valeurs_torseur`/`_prefixer` (prefixe deja retire par
    l'appelant). `C1`/`C2`/`k`/`kw` : None si la stabilite n'a pas ete
    verifiee pour ce candidat (case « prendre en compte » decochee) — dans ce
    cas, le classeur retombe sur ses valeurs d'abaque par defaut (1,13/0,46 et
    k=0,5) plutot que d'ecrire des cellules vides à la place de nombres.

    `my_debut_milieu_fin`/`mz_debut_milieu_fin` : diagramme des moments a 0/50/
    100 % DEJA CALCULE par `_torseur_dimensionnant` au moment ou la stabilite du
    candidat a ete verifiee (cf. `_extraire_optim`/`_CtxGlobal._stabilite`, qui
    le gardent desormais dans `job.stab[nom]`/l'essai) — None seulement si la
    stabilite n'a pas ete verifiee pour ce candidat (case decochee), auquel cas
    le classeur retombe sur ses Cmy/Cmz manuels par defaut (1,0), cf. la note
    dans `_entrees_classeur`."""
    b = {"element": element, "profil_gsa": profil_gsa, "longueur_m": longueur_m,
         "torseur": {
             "N":  {"enveloppe": torseur["N_kN"]},
             "Vy": {"enveloppe": torseur["Vy_kN"]},
             "Vz": {"enveloppe": torseur["Vz_kN"]},
             "My": {"enveloppe": torseur["My_kNm"]},
             "Mz": {"enveloppe": torseur["Mz_kNm"]},
         },
         "my_debut_milieu_fin": my_debut_milieu_fin,
         "mz_debut_milieu_fin": mz_debut_milieu_fin,
         "combinaison_gouvernante": combinaison,
         "position_gouvernante_pct": torseur.get("lieu_pct")}
    donnees, note = _entrees_classeur(b, nuance, coefs, longueur_par_element)
    if C1 is not None and C2 is not None and k is not None and kw is not None:
        donnees["facteur_C1_deversement"] = C1
        donnees["facteur_C2_deversement"] = C2
        donnees["facteur_k_deversement"] = k
        donnees["facteur_kw_deversement"] = kw
    with EXCEL:
        chemin, profil_substitue = ouvrir_predim(donnees, etiquette)
    r = {"ok": True, "fichier": chemin.name, "chemin": str(chemin),
         "element": element, "torseur": torseur, "combinaison": combinaison,
         "profil": profil_gsa if note else donnees["profil_nom"],
         "nuance": donnees["nuance_acier"], "longueur_m": longueur_m}
    substitution = profil_substitue or (donnees["profil_nom"] if note else None)
    if substitution:
        r["profil_substitue"] = substitution
    return r


def ouvrir_excel_candidat(params: dict) -> dict:
    """Ouvre le classeur Predim pour LA LIGNE SELECTIONNEE du detail
    Optimisation (« un groupe » ou « globale ») — bouton a cote de « Charger
    dans le modele ».

    Contrairement a `ouvrir_excel_barre` (barre isolee, Performances), la
    source ici n'est PAS une barre a reinterroger dans GSA : c'est un candidat
    DEJA CALCULE par `_extraire_optim`/`_optimiser_global`, dont le job garde
    tout ce qu'il faut en memoire (cf. `JobOptim.stab`/`JobOptim.longueurs` et
    `JobGlobal.essais`/`JobGlobal.longueurs_par_famille`) — pas la peine de
    rouvrir une copie du modele, changer une section et relancer une analyse
    pour un simple export vers Excel.

    `params` : {"contexte": "optim"|"global", "job": id du job, "nom": nom du
    candidat (onglet Optimisation) ou "famille"+"nom" (Opt. globale, un meme
    nom de candidat existant dans plusieurs familles)}.

    Les coefficients de stabilite (Lfy/Lfz/Ldev, repartition) NE VIENNENT PAS
    de la requete : ils sont relus sur le JOB (`job.coefs_stabilite`, et pour
    Opt. globale, ecrases par le repli par famille de `_CtxGlobal._coefs`) —
    exactement ceux qui ont servi au calcul DEJA AFFICHE. Les prendre dans
    l'encadre Instabilite tel qu'il est AU MOMENT DU CLIC serait fragile : rien
    n'empeche l'utilisateur de l'avoir modifie entre la fin du calcul et ce
    clic, ce qui ouvrirait un classeur incoherent avec le taux montre a l'ecran."""
    contexte = params.get("contexte")
    jid = params.get("job") or ""
    nom = params.get("nom") or ""

    if contexte == "optim":
        with OPTIM_JOBS_LOCK:
            job = OPTIM_JOBS.get(jid)
        if job is None:
            raise DimensionnementError("Calcul d'optimisation inconnu ou expiré.")
        with job.lock:
            candidat = next((c for c in job.candidats if c["nom"] == nom), None)
            stab = job.stab.get(nom)
            nuance = job.meta.get("nuance")
            coefs, longueur_par_element = dict(job.coefs_stabilite), job.longueur_par_element
        if candidat is None:
            raise DimensionnementError(f"Candidat introuvable : {nom!r}.")
        if not stab or stab.get("erreur") or stab.get("element_gouvernant") is None:
            raise DimensionnementError(
                "Stabilité EC3 non disponible pour ce candidat — coche « prendre "
                "en compte » et relance l'optimisation, ou ouvre-le depuis "
                "Performances une fois chargé dans le modèle.")
        element = stab["element_gouvernant"]
        etiquette = f"stabilite_appv2_optim_{Path(job.nom).stem}_{nom}".replace(" ", "_")
        torseur = {cle: stab.get(f"stab_{cle}") for cle in
                  ("N_kN", "Vy_kN", "Vz_kN", "Mxx_kNm", "My_kNm", "Mz_kNm", "lieu_pct")}
        return _ouvrir_excel_connu(
            profil_gsa=candidat["profil_gsa"], element=element,
            longueur_m=job.longueurs.get(element, 0.0),
            combinaison=stab.get("combinaison"), torseur=torseur,
            C1=stab.get("C1"), C2=stab.get("C2"), k=stab.get("k"), kw=stab.get("kw"),
            nuance=nuance or NUANCE_DEFAUT, coefs=coefs,
            longueur_par_element=longueur_par_element, etiquette=etiquette,
            my_debut_milieu_fin=stab.get("my_debut_milieu_fin"),
            mz_debut_milieu_fin=stab.get("mz_debut_milieu_fin"))

    if contexte == "global":
        famille = int(params.get("famille") or 0)
        with GLOBAL_JOBS_LOCK:
            job = GLOBAL_JOBS.get(jid)
        if job is None:
            raise DimensionnementError("Calcul d'optimisation globale inconnu ou expiré.")
        with job.lock:
            essai = next((e for e in job.essais
                         if e["famille"] == famille and e["nom"] == nom), None)
            longueurs = job.longueurs_par_famille.get(famille, {})
            nuance = job.meta.get("nuance")
            # meme repli famille que `_CtxGlobal._coefs` : les valeurs saisies
            # sur SA ligne (page Opt. globale) ecrasent celles de l'encadre
            # Instabilite, un champ laisse vide cote page n'etant pas transmis
            entree_famille = next((f for f in job.familles if f.get("section") == famille), {})
            coefs = {**job.coefs_stabilite, **(entree_famille.get("coefs") or {})}
            longueur_par_element = bool(
                entree_famille.get("longueur_par_element", job.longueur_par_element))
        if essai is None:
            raise DimensionnementError(f"Essai introuvable : famille {famille}, {nom!r}.")
        element = essai.get("element_stab")
        if not element or essai.get("erreur_stab") or essai.get("taux_stabilite") is None:
            raise DimensionnementError(
                "Stabilité EC3 non disponible pour cet essai — coche « prendre "
                "en compte » l'instabilité et relance l'optimisation globale.")
        etiquette = f"stabilite_appv2_global_{Path(job.nom).stem}_{nom}".replace(" ", "_")
        torseur = {cle: essai.get(f"stab_{cle}") for cle in
                  ("N_kN", "Vy_kN", "Vz_kN", "Mxx_kNm", "My_kNm", "Mz_kNm", "lieu_pct")}
        return _ouvrir_excel_connu(
            profil_gsa=essai["profil_gsa"], element=element,
            longueur_m=longueurs.get(element, 0.0),
            combinaison=essai.get("combinaison_stab"), torseur=torseur,
            C1=essai.get("C1_stab"), C2=essai.get("C2_stab"),
            k=essai.get("k_stab"), kw=essai.get("kw_stab"),
            nuance=nuance or NUANCE_DEFAUT, coefs=coefs,
            longueur_par_element=longueur_par_element, etiquette=etiquette,
            my_debut_milieu_fin=essai.get("my_debut_milieu_fin"),
            mz_debut_milieu_fin=essai.get("mz_debut_milieu_fin"))

    raise DimensionnementError(f"Contexte inconnu : {contexte!r} (attendu 'optim' ou 'global').")


# ============================================================================
#  CALCUL EN FLUX — un groupe de barres, quatre criteres, toutes permutations
# ============================================================================
class JobElu:
    """Etat partage entre le thread GSA (extraction) et les polls de la page.
    Tout acces a lignes/meta/etat passe par `lock`."""

    def __init__(self, nom: str, elu: str, els: str,
                 sections: list[int] | None,
                 fy_Pa: float | None, coefficient: float,
                 reglages_els: dict | None, nuance_modele: bool,
                 coefs_stabilite: dict | None = None,
                 longueur_par_element: bool = False,
                 criteres_actifs: list[str] | None = None,
                 coefficient_els: float = 1.0,
                 coefficient_stabilite: float = 1.0):
        self.nom = nom
        self.elu = elu
        self.els = els
        self.sections = sections            # None = toutes les sections acier
        self.fy_Pa = fy_Pa
        self.coefficient = coefficient
        self.coefficient_els = coefficient_els
        self.coefficient_stabilite = coefficient_stabilite
        # {nom de critere: {direction, limite_mm, actif}} saisis dans l'encadre
        # ELS de la page ; les criteres eux-memes viennent du MODELE
        self.reglages_els = reglages_els or {}
        self.nuance_modele = nuance_modele
        # criteres COCHES cote page au lancement (toujours "combine" au moins) —
        # decide QUELLE combinaison sert de torseur a la stabilite EC3, cf.
        # _critere_retenu/_torseur_dimensionnant
        actifs = [c for c in (criteres_actifs or []) if c in CRITERES]
        if CRITERE_BASE not in actifs:
            actifs.insert(0, CRITERE_BASE)
        self.criteres_actifs = actifs
        self.coefs_stabilite = coefs_stabilite or {}
        self.longueur_par_element = longueur_par_element
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.lignes: list[dict] = []        # une ligne par barre retenue, en ordre
        self.calculables: dict[str, bool] = {c: False for c in CRITERES}
        self.meta: dict = {}
        self.etat = "en_cours"              # en_cours | fini | arrete | erreur
        self.erreur: str | None = None
        # stabilite EC3, thread separe alimente EN PARALLELE de l'extraction GSA
        # par une file de torseurs. Le decoupage date de l'epoque ou chaque
        # barre coutait ~0,6 s de classeur Excel ; il ne coute plus rien
        # (~30 us) mais on le garde tel quel : c'est le contrat de `poll`
        # (`stab`, `stab_fini`) que la page consomme, et le producteur/
        # consommateur reste juste — il finit simplement tout de suite.
        self.stab: dict[int, dict] = {}     # element -> resultat de stabilite EC3
        self.torseurs: queue.Queue = queue.Queue()  # (eid, entree|None, erreur|None) ; None = fin
        self.stab_fini = False
        self.stab_erreur: str | None = None


ELU_JOBS: dict[str, JobElu] = {}
ELU_JOBS_LOCK = threading.Lock()


def _extraire(job: JobElu) -> None:
    """Thread GSA : ouvre + analyse une fois, puis extrait le groupe par paquets
    de barres — efforts et contraintes derivees sur TOUTES les permutations de
    l'enveloppe ELU.

    Le bilan ELS (criteres nodaux du modele) est calcule UNE FOIS, hors de la
    boucle par paquets : il porte sur des noeuds nommes, pas sur les barres du
    groupe — il ne depend donc pas du groupe etudie et n'a pas de colonne dans
    le tableau par barre. Il est rendu dans `meta["els"]`.

    Ne leve jamais : les echecs sont stockes dans job.erreur."""
    try:
        chemin = MODEL_DIR / Path(job.nom).name
        if not chemin.exists():
            raise FileNotFoundError(f"Modèle introuvable : {chemin.name}")
        progres("elu", "copie et ouverture du modèle (GsaAPI)…")
        with GsaModel(chemin) as m:
            m.check_analysis_setup()
            refs = refs_elu_els(m, job.elu, job.els)
            progres("elu", "analyse GSA du modèle…")
            timings = m.analyse()
            if not all(t["ok"] for t in timings):
                raise DimensionnementError("Analyse GSA en échec sur le modèle actuel.")

            try:
                portee_m = portee(m)        # information du resume, plus un critere
            except DimensionnementError:
                portee_m = None

            criteres_service = _criteres_els(m, job.reglages_els)

            sections = sections_acier(
                m, fy_Pa=None if job.nuance_modele else job.fy_Pa, source_av="gsa")
            voulues = set(job.sections or [])
            elements = sorted(
                (e for e in m.elements()
                 if not e["factice"] and e["propriete"] in sections
                 and e["type"] in TYPES_1D
                 and (not voulues or e["propriete"] in voulues)),
                key=lambda e: e["element"])
            if not elements:
                raise DimensionnementError(
                    "Aucune barre acier dans ce groupe (sections non aciers, "
                    "éléments factices ou type d'élément sans torseur).")
            nuances_MPa = sorted({round(s["fy_Pa"] / 1e6) for s in sections.values()
                                  if s.get("fy_Pa")})
            nuance = _nuance_acier(m.materials())   # pour la stabilite EC3 (Predim)

            resultat = m._result(refs["ELU"])

            # etiquetage des permutations sur une barre temoin : la meme
            # combinaison ELU s'applique a tout le modele, donc le meme
            # decoupage en sous-combinaisons vaut pour toutes les barres
            progres("elu", "étiquetage des permutations de l'enveloppe…")
            temoin = elements[0]["element"]
            efforts0 = efforts_par_permutation(resultat, str(temoin), POSITIONS) \
                .get(temoin)
            if efforts0 is None:
                raise DimensionnementError(
                    f"La combinaison {refs['ELU']} n'a pas de résultats sur ce modèle.")
            nperm = efforts0.shape[0]
            etiq = libelles_permutations(m, int(refs["ELU"][1:]), temoin,
                                         nperm, POSITIONS)
            libelles = etiq["libelles"]

            # bilan ELS : UNE FOIS pour tout le modele (criteres nodaux,
            # independants du groupe etudie et des barres extraites plus bas)
            progres("elu", "vérification des critères ELS (nœuds nommés)…")
            els = _bilan_els(m, refs.get("ELS"), criteres_service,
                             _libelles_els(m, refs.get("ELS"), temoin, POSITIONS),
                             job.coefficient_els)

            with job.lock:
                job.meta = {
                    "total": len(elements), "elu": refs["ELU"],
                    "els": els,
                    "nb_perm": nperm, "libelles": libelles,
                    "libelles_valides": etiq["valide"],
                    "nuance_modele": job.nuance_modele,
                    "fy_MPa": round(job.fy_Pa / 1e6, 1) if job.fy_Pa else None,
                    "coefficient": job.coefficient,
                    "coefficient_els": job.coefficient_els,
                    "coefficient_stabilite": job.coefficient_stabilite,
                    "nuances_MPa": nuances_MPa,
                    "criteres": list(CRITERES), "critere_base": CRITERE_BASE,
                    "criteres_actifs": list(job.criteres_actifs),
                    "libelles_criteres": LIBELLES,
                    "portee_m": portee_m,
                }

            for paquet in _paquets(elements):
                if job.stop.is_set():
                    break
                sel = " ".join(str(e["element"]) for e in paquet)
                efforts = efforts_par_permutation(resultat, sel, POSITIONS)
                # contraintes derivees : source du von Mises (cf. commun/criteres.py)
                try:
                    derivees = contraintes_derivees_par_permutation(
                        resultat, sel, POSITIONS)
                except Exception:                               # noqa: BLE001
                    derivees = {}          # von Mises indisponible, le reste tient

                lignes = []
                for e in paquet:
                    eid = e["element"]
                    eff = efforts.get(eid)
                    if eff is None or eff.shape[0] != nperm:
                        continue          # barre sans resultat exploitable : ecartee
                    sec = sections[e["propriete"]]
                    der = derivees.get(eid)
                    blocs = criteres_dimensionnants(eff, der, sec)

                    ligne = {
                        "element": eid,
                        "section": e["propriete"],
                        "profil": sec.get("profil", ""),
                        "nom_section": sec.get("nom", ""),
                        "longueur_m": round(e["longueur_m"], 3),
                        "fy_MPa": round(sec["fy_Pa"] / 1e6, 1)
                                  if sec.get("fy_Pa") else None,
                        "criteres": {
                            c: _bloc_critere(blocs[c], libelles, etiq["combinaisons"],
                                             eff.shape[1], sec.get("fy_Pa"),
                                             job.coefficient)
                            for c in CRITERES},
                    }
                    lignes.append(ligne)

                    # torseur -> entree de stabilite -> file consommee par
                    # `_stabilite` : UNIQUEMENT la combinaison dimensionnante du
                    # critere ELU RETENU (parmi job.criteres_actifs), pas une
                    # enveloppe qui melangerait des permutations differentes
                    # composante par composante (cf. _torseur_dimensionnant)
                    retenu = _critere_retenu(blocs, job.criteres_actifs)
                    if retenu is not None:
                        _, bloc_gouv = retenu
                        perm_g, pos_g = bloc_gouv["perm"], bloc_gouv["position"]
                        torseur, my_dmf, mz_dmf = _torseur_dimensionnant(eff, perm_g, pos_g)
                        lib_gouv = libelles[perm_g] if perm_g < len(libelles) else f"perm{perm_g + 1:03d}"
                        bt = {"element": eid, "profil_gsa": sec.get("profil", ""),
                              "longueur_m": ligne["longueur_m"], "torseur": torseur,
                              "my_debut_milieu_fin": my_dmf, "mz_debut_milieu_fin": mz_dmf,
                              "combinaison_gouvernante": lib_gouv,
                              "position_gouvernante_pct": positions_pct(eff.shape[1])[pos_g]}
                        try:
                            entree_dict, note = _entrees_classeur(
                                bt, nuance, job.coefs_stabilite, job.longueur_par_element)
                            entree = {"element": eid, **entree_dict}
                            job.torseurs.put((eid, entree, None, note))
                        except DimensionnementError as ex:
                            job.torseurs.put((eid, None, str(ex), None))
                    else:
                        job.torseurs.put((eid, None,
                            "Aucun critère ELU actif calculable sur cette barre : "
                            "combinaison dimensionnante indéterminée.", None))

                with job.lock:
                    job.lignes.extend(lignes)
                    for ligne in lignes:
                        for c, bloc in ligne["criteres"].items():
                            if bloc is not None:
                                job.calculables[c] = True
                    fait = len(job.lignes)
                progres("elu", "extraction des permutations…", fait, len(elements))

        with job.lock:
            job.meta["criteres_calculables"] = dict(job.calculables)
            job.etat = "arrete" if job.stop.is_set() else "fini"
        progres("elu", "terminé")
    except BaseException as e:                                  # noqa: BLE001
        with job.lock:
            job.etat = "erreur"
            job.erreur = str(e)
        progres("elu", "terminé")
        if not isinstance(e, (DimensionnementError, ConfigurationAnalyseError,
                              FileNotFoundError, ValueError, KeyError)):
            traceback.print_exc()
    finally:
        job.torseurs.put(None)                 # sentinelle : fin pour la stabilite


def _stabilite(job: JobElu) -> None:
    """Thread de stabilite : consomme les torseurs produits par l'extraction et
    calcule les quatre taux EC3 §6.3 barre par barre (`_session_stabilite`,
    aujourd'hui `commun/stabilite_ec3`).

    Tourne en parallele de l'extraction GSA. Le decoupage en thread + file
    vient de l'epoque du classeur Excel, ou chaque barre coutait ~0,6 s ; il ne
    coute plus rien mais reste la structure la plus simple qui respecte le
    contrat de `poll` (les stabilites arrivent dans `stab`, `stab_fini` clot le
    suivi). Aucun verrou `EXCEL` : plus aucun classeur n'est ouvert ici."""
    session = None
    try:
        while True:
            item = job.torseurs.get()
            if item is None or job.stop.is_set():
                break
            eid, entree, erreur, note = item
            if erreur is not None:
                with job.lock:
                    job.stab[eid] = {"element": eid, "erreur": erreur}
                continue
            if session is None:
                session = _session_stabilite()
                session.open()
            r = session.verifier(entree)
            # profil saisi a la main (note non nulle, cf. _profil_predim) :
            # signale la designation catalogue de repli utilisee — la seule
            # substitution qui subsiste, celle du classeur (section absente de
            # son onglet) n'ayant plus lieu d'etre
            if note and not r.get("erreur") and not r.get("profil_substitue"):
                r["profil_substitue"] = note
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


def elu_demarrer(params: dict) -> dict:
    """Demarre le calcul d'un groupe en flux et renvoie son identifiant."""
    nom = params.get("modele") or ""
    chemin = MODEL_DIR / Path(nom).name
    if not chemin.exists():
        raise FileNotFoundError(f"Modèle introuvable : {chemin.name}")
    crit = params.get("criteres") or {}
    cfg = lire_config()
    fy_Pa = float(crit["fy_Pa"]) if crit.get("fy_Pa") else \
        cfg["critere_contrainte"]["fy_Pa"]
    coefficient = float(crit["coefficient"]) if crit.get("coefficient") else \
        cfg["critere_contrainte"]["coefficient"]
    coefficient_els = float(crit["coefficient_els"]) if crit.get("coefficient_els") else \
        cfg["critere_els"]["coefficient"]
    coefficient_stabilite = float(crit["coefficient_stabilite"]) if crit.get("coefficient_stabilite") else \
        cfg["critere_stabilite"]["coefficient"]
    sections = [int(s) for s in (params.get("sections") or [])] or None
    coefs_stabilite, longueur_par_element = valider_coefs(params.get("coefs") or {})
    criteres_actifs = [str(c) for c in (params.get("criteres_actifs") or [])]
    job = JobElu(nom, params.get("elu") or "", params.get("els") or "",
                 sections, fy_Pa, coefficient,
                 params.get("criteres_els") or {},
                 bool(params.get("nuance_modele")),
                 coefs_stabilite, longueur_par_element, criteres_actifs,
                 coefficient_els, coefficient_stabilite)
    jid = uuid.uuid4().hex
    with ELU_JOBS_LOCK:
        for k in [k for k, j in ELU_JOBS.items() if j.etat != "en_cours"]:
            del ELU_JOBS[k]
        ELU_JOBS[jid] = job
    GSA.soumettre(_extraire, job)
    threading.Thread(target=_stabilite, args=(job,),
                     daemon=True, name=f"stab-{jid[:8]}").start()
    return {"job": jid, "modele": chemin.name}


def elu_etat(jid: str, depuis: int) -> dict:
    """Etat d'un job : nouvelles lignes depuis `depuis`, stabilites connues,
    meta et statut. N'utilise PAS le thread GSA (lecture d'etat partage)."""
    with ELU_JOBS_LOCK:
        job = ELU_JOBS.get(jid)
    if job is None:
        raise DimensionnementError("Calcul inconnu ou expiré.")
    with job.lock:
        return {"lignes": job.lignes[depuis:], "recus": len(job.lignes),
                "stab": {str(k): v for k, v in job.stab.items()},
                "meta": job.meta, "etat": job.etat, "erreur": job.erreur,
                "stab_fini": job.stab_fini, "stab_erreur": job.stab_erreur}


def elu_arreter(jid: str) -> dict:
    """Demande l'arret d'un job (coupe entre deux paquets de barres)."""
    with ELU_JOBS_LOCK:
        job = ELU_JOBS.get(jid)
    if job is not None:
        job.stop.set()
    return {"ok": True}


# ============================================================================
#  OPTIMISATION — reduire la section d'UN groupe (catalogue, meme categorie)
# ============================================================================
def _famille_catalogue(profil_gsa: str) -> tuple[str | None, str | None]:
    """Profil GSA du groupe -> (feuille catalogue, forme) pour l'onglet
    Optimisation.

    `feuille` : nom de fichier catalogue (`commun/catalogues.py::charger_catalogue`)
    a explorer pour des sections plus legeres — None si aucun catalogue de la
    meme categorie n'existe pour ce profil (formes ouvertes saisies a la main :
    I, cornieres... — memes limites que `ec3.geometrie`).
    `forme` : 'CHS'/'RHS' quand les caracteristiques de cisaillement/torsion
    des CANDIDATS peuvent etre reconstruites depuis leur geometrie catalogue
    (memes formules que `ec3.caracteristiques`, cf. `_sect_candidat`), None
    sinon (IPE/IPN/HE/HD : catalogue disponible, mais seul le critere combine
    — contrainte normale — est teste sur les candidats, l'aire de cisaillement
    d'un profil en I n'etant pas reconstructible depuis les seules cotes
    catalogue, cf. `ec3.geometrie`)."""
    parts = (profil_gsa or "").split()
    if len(parts) >= 3 and parts[0] == "CAT":
        nom = parts[2]
        famille = next((f for f in _FAMILLES_CLASSEUR if nom.upper().startswith(f)), None)
        if famille is None:
            return None, None
        feuille = _ONGLET_PREDIM.get(famille, famille)
        return feuille, (feuille if feuille in ("CHS", "RHS") else None)
    g = geometrie(profil_gsa)
    if g is None or g["forme"] not in ("CHS", "RHS"):
        return None, None
    return g["forme"], g["forme"]


def _nom_predim_depuis_catalogue(feuille: str, nom: str) -> tuple[str, str]:
    """Designation catalogue -> (onglet, designation) du classeur Predim.

    La designation ne change JAMAIS : le classeur est rempli depuis ce meme
    catalogue et en garde les noms (un tube carre y est 'SHS70x70x8' dans
    l'onglet RHS). Seul l'onglet peut differer du prefixe du nom, ce dont
    `feuille` tient deja compte (cf. `_famille_catalogue`/`_ONGLET_PREDIM` et
    la note de `_profil_predim` sur le renommage SHS -> RHS retire)."""
    return feuille, nom


class JobOptim:
    """Etat partage entre le thread GSA (evaluation ELU/ELS, PUIS stabilite
    EC3 en ligne pour les candidats qui passent — tout dans `_extraire_optim`,
    pas de thread Excel separe contrairement a `JobElu`) et les polls de la
    page. `stab`/`lock`/`stop`/`stab_fini`/`stab_erreur` gardent les memes
    noms que `JobElu` pour que la page les lise de la meme maniere."""

    def __init__(self, nom: str, elu: str, els: str,
                 section_id: int,
                 fy_Pa: float | None, coefficient: float,
                 reglages_els: dict | None, nuance_modele: bool,
                 coefs_stabilite: dict | None = None,
                 longueur_par_element: bool = False,
                 stabilite_approfondie: bool = False,
                 avec_stabilite: bool = True,
                 coefficient_els: float = 1.0,
                 coefficient_stabilite: float = 1.0):
        self.nom = nom
        self.elu = elu
        self.els = els
        self.section_id = section_id        # UNE section GSA : le groupe optimise
        self.fy_Pa = fy_Pa
        self.coefficient = coefficient
        self.coefficient_els = coefficient_els
        self.coefficient_stabilite = coefficient_stabilite
        self.reglages_els = reglages_els or {}
        self.nuance_modele = nuance_modele
        self.coefs_stabilite = coefs_stabilite or {}
        self.longueur_par_element = longueur_par_element
        # case « prendre en compte » de l'encadre Instabilite : False = aucune
        # verification EC3 6.3 (aucun classeur Excel ouvert), le verdict d'un
        # candidat se limite alors a ELU + ELS. Seuls les criteres de STABILITE
        # sont concernes : ELU et ELS restent verifies dans tous les cas.
        self.avec_stabilite = avec_stabilite
        # stabilite EC3 : False (defaut) = seulement la barre gouvernant l'ELU
        # du groupe, a SA case dimensionnante (rapide, 1 verification/candidat) ;
        # True = TOUTES les barres du groupe, sur TOUTES leurs permutations ET
        # TOUTES leurs positions -- exhaustif (cf. _extraire_optim)
        self.stabilite_approfondie = stabilite_approfondie
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.candidats: list[dict] = []     # une ligne par section catalogue plus legere
        self.meta: dict = {}
        self.etat = "en_cours"
        self.erreur: str | None = None
        self.stab: dict[str, dict] = {}     # nom candidat -> resultat stabilite EC3 (pire barre)
        self.stab_fini = False
        self.stab_erreur: str | None = None
        # message si la boucle s'est arretee d'elle-meme (SEUIL_KO_CONSECUTIFS
        # atteint) plutot que d'avoir epuise tous les candidats ou avoir ete
        # arretee par l'utilisateur (job.stop) — cf. _extraire_optim
        self.arret_auto: str | None = None
        # {element: longueur_m} de TOUTES les barres du groupe — rempli une
        # fois par `_extraire_optim` (la longueur ne depend pas du candidat),
        # sert UNIQUEMENT a `ouvrir_excel_candidat` (bouton Excel du detail
        # optimisation) pour reconstruire les entrees du classeur SANS rouvrir
        # GSA. `nuance`, meme role, ajoutee a `job.meta` (cf. _extraire_optim).
        self.longueurs: dict[int, float] = {}


OPTIM_JOBS: dict[str, JobOptim] = {}
OPTIM_JOBS_LOCK = threading.Lock()


def _extraire_optim(job: JobOptim) -> None:
    """Thread GSA : pour CHAQUE section catalogue plus legere que la section
    actuelle, MODIFIE REELLEMENT la propriete de section du groupe dans la
    copie de travail GSA (`GsaModel.set_section_profile`, meme mecanique que
    `commun/algo_opti`), RELANCE L'ANALYSE, puis reextrait les efforts (ELU)
    de ce groupe pour determiner, PAR BARRE, la combinaison dimensionnante de
    chaque critere — EXACTEMENT la meme methode que l'onglet Performances
    (`_critere_retenu`) — et reevalue les criteres ELS du modele sur les
    deplacements frais des noeuds nommes (`_bilan_els`, GLOBAL : ils portent
    sur la structure entiere, pas sur le groupe optimise, mais changent bien
    avec la section testee puisque la raideur change),
    plutot que de recalculer des taux sur les efforts de la section actuelle
    (ancienne approche, sans reanalyse — abandonnee sur demande explicite :
    dans une structure hyperstatique, changer la raideur d'un groupe
    redistribue reellement les efforts, ce qu'une simple recombinaison de
    caracteristiques de section ne peut pas reproduire).

    L'instabilite (EC3 6.3) n'entre dans le verdict que si la case « prendre
    en compte » de l'encadre Instabilite est cochee (`job.avec_stabilite`) :
    decochee, aucun classeur Excel n'est ouvert et un candidat est retenu sur
    ELU + ELS seuls — beaucoup plus rapide, mais le flambement et le
    deversement ne sont alors PAS verifies.

    Les candidats qui passent ELU ET ELS voient leur stabilite EC3 verifiee
    (demande explicite) pour TOUTES les barres du groupe, pas seulement la
    plus sollicitee en ELU : le taux de stabilite depend de N, de la
    distribution My/Mz et des longueurs de flambement/deversement, pas
    seulement du taux de contrainte — la barre gouvernante peut differer de
    celle qui gouverne l'ELU. Fait de maniere SYNCHRONE, en ligne dans cette
    meme boucle (pas de thread separe comme pour l'onglet Performances
    `_stabilite`) : plus simple a raisonner, et le cout supplementaire n'est
    paye que pour les candidats qui passent deja ELU/ELS (peu nombreux en
    pratique, cf. arret sur `SEUIL_KO_CONSECUTIFS`). Une seule session de
    stabilite pour tout le job (`session`, ouverte au premier besoin, fermee
    dans le `finally`) — depuis la bascule vers `commun/stabilite_ec3` elle
    n'ouvre plus rien et ne prend plus de verrou.

    BEAUCOUP plus couteux que l'ancienne version : une analyse GSA complete
    est relancee PAR CANDIDAT (pas seulement une fois pour la section de
    depart). Le bouton Arreter (`job.stop`) reste verifie entre deux
    candidats et entre deux barres de la verification de stabilite."""
    session = None
    try:
        chemin = MODEL_DIR / Path(job.nom).name
        if not chemin.exists():
            raise FileNotFoundError(f"Modèle introuvable : {chemin.name}")
        progres("optim", "copie et ouverture du modèle (GsaAPI)…")
        with GsaModel(chemin) as m:
            m.check_analysis_setup()
            refs = refs_elu_els(m, job.elu, job.els)
            progres("optim", "analyse GSA du modèle (section actuelle)…")
            timings = m.analyse()
            if not all(t["ok"] for t in timings):
                raise DimensionnementError("Analyse GSA en échec sur le modèle actuel.")

            criteres_service = _criteres_els(m, job.reglages_els)

            sections = sections_acier(
                m, fy_Pa=None if job.nuance_modele else job.fy_Pa, source_av="gsa")
            sec_actuelle = sections.get(job.section_id)
            if sec_actuelle is None:
                raise DimensionnementError(
                    "Section du groupe introuvable ou non acier — choisir un "
                    "groupe acier avant de lancer l'optimisation.")
            elements = sorted(
                (e for e in m.elements()
                 if not e["factice"] and e["propriete"] == job.section_id
                 and e["type"] in TYPES_1D),
                key=lambda e: e["element"])
            if not elements:
                raise DimensionnementError("Aucune barre acier dans ce groupe.")
            ids = [e["element"] for e in elements]
            sel = " ".join(str(i) for i in ids)
            longueurs = {e["element"]: round(e["longueur_m"], 3) for e in elements}
            job.longueurs = longueurs
            temoin = elements[0]["element"]

            feuille, forme = _famille_catalogue(sec_actuelle.get("profil", ""))
            if feuille is None:
                raise DimensionnementError(
                    "Optimisation indisponible pour ce profil : "
                    f"{sec_actuelle.get('profil', '')!r} — aucun catalogue de "
                    "sections comparables (formes ouvertes saisies à la main : "
                    "I, cornières... non transposables).")

            nuance = _nuance_acier(m.materials())
            fy_force = None if job.nuance_modele else job.fy_Pa

            # etiquetage sur la section ACTUELLE, avant toute modification —
            # le nombre de permutations et leur decoupage en sous-combinaisons
            # ne dependent QUE de la structure de l'enveloppe (definition de la
            # combinaison), jamais de la raideur des barres : valable pour
            # tous les candidats, pas la peine de le refaire a chaque tour.
            # Sert aussi a noter, dans le classeur Predim (C2/C3), la
            # combinaison et la position dont proviennent les efforts saisis
            # (cf. _entrees_classeur).
            resultat0 = m._result(refs["ELU"])
            efforts0 = efforts_par_permutation(resultat0, str(temoin), POSITIONS).get(temoin)
            nb_perm = efforts0.shape[0] if efforts0 is not None else 0
            libelles_elu = libelles_permutations(
                m, int(refs["ELU"][1:]), temoin, nb_perm, POSITIONS)["libelles"]
            # meme argument pour l'ELS : l'expansion d'une enveloppe ne depend
            # que de sa definition, jamais de la raideur des barres
            libelles_els = _libelles_els(m, refs.get("ELS"), temoin, POSITIONS)

            # propriete DEDIEE au groupe : on la mute a chaque candidat sans
            # jamais toucher aux autres groupes du modele — meme garde-fou que
            # `commun/algo_opti` (le groupe appv2 = une propriete de section,
            # deja exclusive par construction, mais section_dediee reste le
            # point d'entree standard du projet pour muter une section).
            prop_id = m.section_dediee(ids, nom=f"Optim {sec_actuelle.get('nom', '')}")

            aire_actuelle = sec_actuelle.get("aire_m2") or 0.0
            catalogue = charger_catalogue(feuille)
            candidats_rows = sorted(
                (r for r in catalogue if float(r["aire_m2"] or 0) < aire_actuelle),
                key=lambda r: -float(r["masse_kg_m"]))       # plus proche de l'actuelle d'abord

            # masse actuelle EQUIVALENTE (aire x densite acier) : la section
            # affectee dans GSA n'a pas forcement de masse catalogue (profil
            # 'STD ...' saisi a la main) — l'aire, elle, vient toujours de GSA.
            # Sert de reference pour le poids gagne par candidat et sur tout
            # le groupe (barre x longueur totale des elements du groupe).
            masse_actuelle_kg_m = aire_actuelle * DENSITE_ACIER_KG_M3
            longueur_totale_m = sum(longueurs.values())

            with job.lock:
                job.meta = {
                    "section_actuelle": sec_actuelle.get("profil"),
                    "nom_actuel": sec_actuelle.get("nom"),
                    "aire_actuelle_m2": aire_actuelle,
                    "masse_actuelle_kg_m": round(masse_actuelle_kg_m, 2),
                    "longueur_totale_m": round(longueur_totale_m, 2),
                    "feuille_catalogue": feuille, "forme": forme,
                    "nb_candidats": len(candidats_rows),
                    "nb_barres": len(elements), "nb_perm": nb_perm,
                    "coefficient": job.coefficient,
                    "coefficient_els": job.coefficient_els,
                    "coefficient_stabilite": job.coefficient_stabilite,
                    "els_combinaison": refs.get("ELS"),
                    "criteres_els": criteres_service,
                    "fy_MPa": round(sec_actuelle.get("fy_Pa") / 1e6, 1)
                              if sec_actuelle.get("fy_Pa") else None,
                    "avec_stabilite": job.avec_stabilite,
                    "stabilite_approfondie": job.stabilite_approfondie,
                    # nuance du modele (lue une fois, valable pour tous les
                    # candidats) : sert a `ouvrir_excel_candidat`, qui pre-remplit
                    # le classeur SANS rouvrir GSA — cf. son docstring
                    "nuance": nuance,
                }

            ko_consecutifs = 0
            for i_r, row in enumerate(candidats_rows):
                if job.stop.is_set():
                    break
                nom_gsa = row.get("profil_gsa") or row["nom"]
                progres("optim", f"{row['nom']} : modification du modèle + analyse GSA…",
                        i_r, len(candidats_rows))

                m.set_section_profile(prop_id, nom_gsa)
                timings = m.analyse()
                masse_gagnee_kg_m = masse_actuelle_kg_m - float(row["masse_kg_m"])
                base_ligne = {
                    "nom": row["nom"], "profil_gsa": nom_gsa,
                    "masse_kg_m": float(row["masse_kg_m"]),
                    # aire de la section essayee : colonne du tableau detaille
                    # (cote sortie), a cote de la reduction en pourcentage
                    "aire_m2": float(row["aire_m2"] or 0.0),
                    "reduction_pct": round(100.0 * (1.0 - float(row["aire_m2"]) / aire_actuelle), 1)
                                     if aire_actuelle else None,
                    "masse_gagnee_kg_m": round(masse_gagnee_kg_m, 2),
                    "masse_gagnee_kg_total": round(masse_gagnee_kg_m * longueur_totale_m, 1),
                }
                if not all(t["ok"] for t in timings):
                    with job.lock:
                        job.candidats.append({**base_ligne, "taux_elu": None,
                            "critere_elu": None, "signe_elu": None,
                            "combinaison_elu": None, "element_gouvernant": None,
                            **_prefixer("elu", _EFFORT_VIDE),
                            "taux_els": None, "critere_els": None,
                            "combinaison_els": None, "noeud_gouvernant_els": None,
                            "verdict_elu_els": False,
                            "erreur": "Analyse GSA en échec avec cette section."})
                    ko_consecutifs += 1
                    if ko_consecutifs >= SEUIL_KO_CONSECUTIFS:
                        with job.lock:
                            job.arret_auto = (
                                f"{SEUIL_KO_CONSECUTIFS} sections consécutives en échec — "
                                "arrêt automatique (les plus légères ne feraient "
                                "vraisemblablement pas mieux).")
                        break
                    continue

                sections_c = sections_acier(m, fy_Pa=fy_force, source_av="gsa")
                sec_c = sections_c.get(prop_id)
                if sec_c is None:
                    with job.lock:
                        job.candidats.append({**base_ligne, "taux_elu": None,
                            "critere_elu": None, "signe_elu": None,
                            "combinaison_elu": None, "element_gouvernant": None,
                            **_prefixer("elu", _EFFORT_VIDE),
                            "taux_els": None, "critere_els": None,
                            "combinaison_els": None, "noeud_gouvernant_els": None,
                            "verdict_elu_els": False,
                            "erreur": "Section candidate introuvable après modification du modèle."})
                    ko_consecutifs += 1
                    if ko_consecutifs >= SEUIL_KO_CONSECUTIFS:
                        with job.lock:
                            job.arret_auto = (
                                f"{SEUIL_KO_CONSECUTIFS} sections consécutives en échec — "
                                "arrêt automatique (les plus légères ne feraient "
                                "vraisemblablement pas mieux).")
                        break
                    continue

                # meme sequence que _extraire, restreinte a ce groupe : efforts
                # ELU non reduits, sur l'analyse FRAICHE de cette section
                # candidate
                resultat = m._result(refs["ELU"])
                efforts = efforts_par_permutation(resultat, sel, POSITIONS)
                efforts = {eid: e for eid, e in efforts.items() if e.size}
                nperm = next(iter(efforts.values())).shape[0] if efforts else 0

                # criteres de service, sur les deplacements FRAIS des noeuds
                # nommes : globaux (toute la structure), donc hors de la boucle
                # par barre ci-dessous
                els_candidat = _bilan_els(m, refs.get("ELS"), criteres_service,
                                          libelles_els, job.coefficient_els)

                # combinaison dimensionnante ELU (combine/torsion/cisaillement —
                # jamais von Mises : indisponible sans derivees GSA, non
                # extraites ici par economie, cf. contraintes_derivees_par_permutation),
                # MAX sur les barres du groupe.
                # `elu_par_barre` garde le detail de CHAQUE barre (pas
                # seulement la gouvernante) : necessaire plus bas pour
                # verifier la stabilite de TOUTES les barres, pas seulement
                # celle qui gouverne l'ELU (cf. docstring de la fonction).
                elu_par_barre: dict[int, dict] = {}
                taux_elu_max, elem_gouv, critere_gouv, signe_gouv = 0.0, None, None, None
                perm_gouv = pos_gouv = None
                for e in elements:
                    eid = e["element"]
                    eff = efforts.get(eid)
                    if eff is not None and eff.shape[0] == nperm:
                        blocs = criteres_dimensionnants(eff, None, sec_c)
                        retenu = _critere_retenu(blocs, CRITERES_OPTIM)
                        if retenu is not None:
                            c, b = retenu
                            elu_par_barre[eid] = {"critere": c, "perm": b["perm"],
                                "position": b["position"], "eff": eff, "signe": b.get("signe"),
                                "taux": b["taux"]}
                            if b["taux"] > taux_elu_max:
                                taux_elu_max, elem_gouv, critere_gouv = b["taux"], eid, c
                                perm_gouv, pos_gouv, signe_gouv = b["perm"], b["position"], b.get("signe")

                taux_els_candidat = els_candidat["taux"]
                els_gouv = els_candidat["gouvernant"]

                combinaison_elu = None
                if perm_gouv is not None:
                    combinaison_elu = libelles_elu[perm_gouv] if perm_gouv < len(libelles_elu) \
                        else f"perm{perm_gouv + 1:03d}"
                # torseur (N, Vy, Vz, Mxx, My, Mz) de LA case dimensionnante —
                # colonnes d'efforts du tableau detaille, a cote de la
                # combinaison et de la barre gouvernantes deja affichees
                effort_elu = (_valeurs_torseur(elu_par_barre[elem_gouv]["eff"],
                                               perm_gouv, pos_gouv)
                             if elem_gouv is not None else _EFFORT_VIDE)

                ok_elu = taux_elu_max <= job.coefficient
                # aucun critere de service verifiable (modele sans noeud nomme
                # ELS_*) : le candidat n'est pas recale pour autant
                ok_els = taux_els_candidat is None or taux_els_candidat <= job.coefficient_els
                ligne = {
                    **base_ligne,
                    "taux_elu": round(taux_elu_max, 4), "critere_elu": critere_gouv,
                    "signe_elu": signe_gouv, "combinaison_elu": combinaison_elu,
                    "element_gouvernant": elem_gouv,
                    **_prefixer("elu", effort_elu),
                    "taux_els": taux_els_candidat,
                    "critere_els": els_gouv["nom"] if els_gouv else None,
                    "combinaison_els": els_gouv["libelle"] if els_gouv else None,
                    "noeud_gouvernant_els": els_gouv["noeud"] if els_gouv else None,
                    "criteres_els": els_candidat["criteres"],
                    "verdict_elu_els": bool(ok_elu and ok_els),
                }
                with job.lock:
                    job.candidats.append(ligne)
                progres("optim", "évaluation des sections candidates (GSA réel : ELU/ELS)…",
                        i_r + 1, len(candidats_rows))

                if ligne["verdict_elu_els"]:
                    ko_consecutifs = 0
                else:
                    ko_consecutifs += 1
                    if ko_consecutifs >= SEUIL_KO_CONSECUTIFS:
                        with job.lock:
                            job.arret_auto = (
                                f"{SEUIL_KO_CONSECUTIFS} sections consécutives qui ne "
                                "vérifient pas ELU/ELS — arrêt automatique (les plus "
                                "légères ne feraient vraisemblablement pas mieux).")
                        break

                # stabilite EC3 : seulement pour les candidats qui passent ELU
                # ET ELS (demande explicite). Deux modes (case a cocher cote
                # page, `job.stabilite_approfondie`) :
                #   - defaut (False) : UNE seule verification, sur la barre qui
                #     gouverne l'ELU du groupe (`elem_gouv`), a SA case
                #     dimensionnante — rapide.
                #   - approfondi (True) : TOUTES les barres du groupe, sur
                #     TOUTES leurs permutations ET TOUTES leurs positions (0/25/
                #     50/75/100 %) — chaque case donnant deja le MAX des 4 taux
                #     EC3 §6.3 (flambement, deversement, flechie+comprimee yy,
                #     flechie+comprimee zz, cf. verification.py::verifier_stabilite),
                #     le pire de TOUTES ces cases est le maximum absolu sur le
                #     perimetre complet — exhaustif, pas une heuristique. Couvre
                #     a la fois le cas ou une AUTRE barre que la gouvernante ELU
                #     gouverne la stabilite, et celui ou c'est une AUTRE
                #     permutation/position de la MEME barre qui la gouverne (les
                #     deux constates separement, cf. etudes P2_bracons et P1_sup
                #     des 05-06/08/2026 : la case gouvernant la stabilite d'une
                #     barre ne coincide pas TOUJOURS avec celle qui gouverne son
                #     ELU).
                # Dans les deux cas, le pire taux (et sa barre/permutation) est
                # retenu comme resultat du candidat. Depuis la bascule vers
                # `commun/stabilite_ec3`, la verification ne coute plus que
                # ~30 us : verifier TOUT le perimetre (barres x permutations x
                # positions) reste de l'ordre de quelques dizaines de ms par
                # candidat (autrefois ~80 s/candidat avec l'ancien classeur Excel).
                if ligne["verdict_elu_els"] and elu_par_barre and job.avec_stabilite:
                    try:
                        if session is None:
                            session = _session_stabilite()
                            session.open()
                        famille_predim, nom_predim = _nom_predim_depuis_catalogue(
                            feuille, row["nom"])

                        cases: list[tuple[int, int, int]] = []     # (element, perm, position)
                        if job.stabilite_approfondie:
                            for eid, info in elu_par_barre.items():
                                nperm_b, npos_b = info["eff"].shape[0], info["eff"].shape[1]
                                for ip in range(nperm_b):
                                    for pos in range(npos_b):
                                        cases.append((eid, ip, pos))
                        elif elem_gouv is not None and elem_gouv in elu_par_barre:
                            info = elu_par_barre[elem_gouv]
                            cases.append((elem_gouv, info["perm"], info["position"]))

                        pire = None
                        for eid, perm, position in cases:
                            if job.stop.is_set():
                                break
                            eff = elu_par_barre[eid]["eff"]
                            torseur, my_dmf, mz_dmf = _torseur_dimensionnant(eff, perm, position)
                            lib = libelles_elu[perm] if perm < len(libelles_elu) \
                                else f"perm{perm + 1:03d}"
                            bt = {"element": eid, "profil_gsa": nom_gsa,
                                  "longueur_m": longueurs.get(eid, 0.0), "torseur": torseur,
                                  "my_debut_milieu_fin": my_dmf, "mz_debut_milieu_fin": mz_dmf,
                                  "combinaison_gouvernante": lib,
                                  "position_gouvernante_pct": positions_pct(eff.shape[1])[position]}
                            try:
                                entree_dict, _ = _entrees_classeur(
                                    bt, nuance, job.coefs_stabilite, job.longueur_par_element,
                                    profil_force=(famille_predim, nom_predim))
                                entree = {"element": eid, **entree_dict}
                                r = session.verifier(entree)
                            except DimensionnementError as ex:
                                r = {"element": eid, "erreur": str(ex)}
                            if not r.get("erreur") and (
                                    pire is None or r["taux_stabilite"] > pire["taux_stabilite"]):
                                # torseur de LA case qui gouverne desormais la
                                # stabilite du candidat — colonnes d'efforts du
                                # tableau detaille, a cote de sa barre/combinaison
                                pire = {**r, "element_gouvernant": eid, "combinaison": lib,
                                        "my_debut_milieu_fin": my_dmf, "mz_debut_milieu_fin": mz_dmf,
                                        **_prefixer("stab", _valeurs_torseur(eff, perm, position))}
                        if pire is None:
                            pire = {"erreur": "aucun taux de stabilité lisible sur les "
                                              "barres de ce candidat"}
                        with job.lock:
                            job.stab[row["nom"]] = pire
                        progres("optim",
                                f"{row['nom']} : stabilité EC3 ({len(cases)} case(s))…",
                                i_r + 1, len(candidats_rows))
                    except BaseException as exc:                      # noqa: BLE001
                        with job.lock:
                            job.stab_erreur = str(exc)
                        traceback.print_exc()

        with job.lock:
            job.etat = "arrete" if job.stop.is_set() else "fini"
        progres("optim", "terminé")
    except BaseException as e:                                    # noqa: BLE001
        with job.lock:
            job.etat = "erreur"
            job.erreur = str(e)
        progres("optim", "terminé")
        if not isinstance(e, (DimensionnementError, ConfigurationAnalyseError,
                              FileNotFoundError, ValueError, KeyError)):
            traceback.print_exc()
    finally:
        if session is not None:
            session.close()
        with job.lock:
            job.stab_fini = True


def optim_demarrer(params: dict) -> dict:
    """Demarre l'optimisation d'un groupe (une section) et renvoie son
    identifiant."""
    nom = params.get("modele") or ""
    chemin = MODEL_DIR / Path(nom).name
    if not chemin.exists():
        raise FileNotFoundError(f"Modèle introuvable : {chemin.name}")
    section_id = int(params.get("section") or 0)
    if not section_id:
        raise DimensionnementError(
            "Choisir un groupe (une section) avant de lancer l'optimisation — "
            "« toutes les barres acier » n'est pas transposable à un catalogue unique.")
    crit = params.get("criteres") or {}
    cfg = lire_config()
    fy_Pa = float(crit["fy_Pa"]) if crit.get("fy_Pa") else \
        cfg["critere_contrainte"]["fy_Pa"]
    coefficient = float(crit["coefficient"]) if crit.get("coefficient") else \
        cfg["critere_contrainte"]["coefficient"]
    coefficient_els = float(crit["coefficient_els"]) if crit.get("coefficient_els") else \
        cfg["critere_els"]["coefficient"]
    coefficient_stabilite = float(crit["coefficient_stabilite"]) if crit.get("coefficient_stabilite") else \
        cfg["critere_stabilite"]["coefficient"]
    coefs_stabilite, longueur_par_element = valider_coefs(params.get("coefs") or {})
    job = JobOptim(nom, params.get("elu") or "", params.get("els") or "",
                   section_id, fy_Pa, coefficient,
                   params.get("criteres_els") or {},
                   bool(params.get("nuance_modele")),
                   coefs_stabilite, longueur_par_element,
                   bool(params.get("stabilite_approfondie")),
                   params.get("avec_stabilite", True) is not False,
                   coefficient_els, coefficient_stabilite)
    jid = uuid.uuid4().hex
    with OPTIM_JOBS_LOCK:
        for k in [k for k, j in OPTIM_JOBS.items() if j.etat != "en_cours"]:
            del OPTIM_JOBS[k]
        OPTIM_JOBS[jid] = job
    # stabilite EC3 verifiee EN LIGNE dans _extraire_optim (pas de thread
    # Excel separe pour Optimisation, cf. docstring de _extraire_optim)
    GSA.soumettre(_extraire_optim, job)
    return {"job": jid, "modele": chemin.name}


def optim_etat(jid: str, depuis: int) -> dict:
    """Etat d'un job d'optimisation : nouveaux candidats depuis `depuis`,
    stabilites connues, meta et statut."""
    with OPTIM_JOBS_LOCK:
        job = OPTIM_JOBS.get(jid)
    if job is None:
        raise DimensionnementError("Calcul inconnu ou expiré.")
    with job.lock:
        return {"candidats": job.candidats[depuis:], "recus": len(job.candidats),
                "stab": {str(k): v for k, v in job.stab.items()},
                "meta": job.meta, "etat": job.etat, "erreur": job.erreur,
                "stab_fini": job.stab_fini, "stab_erreur": job.stab_erreur,
                "arret_auto": job.arret_auto}


def optim_arreter(jid: str) -> dict:
    """Demande l'arret d'un job d'optimisation (coupe entre deux candidats)."""
    with OPTIM_JOBS_LOCK:
        job = OPTIM_JOBS.get(jid)
    if job is not None:
        job.stop.set()
    return {"ok": True}


def charger_section_optim(params: dict) -> dict:
    """Enregistre une COPIE du modele — `<modele>_opti.gwb`, a cote du modele
    source dans GSA_model/, ECRASEE a chaque appel (pas d'historique) — avec,
    pour le groupe optimise, la section du candidat choisi dans le tableau
    Optimisation, puis l'ouvre dans l'application GSA (association Windows du
    .gwb) pour inspection manuelle. Le fichier source n'est jamais modifie."""
    nom = params.get("modele") or ""
    chemin = MODEL_DIR / Path(nom).name
    if not chemin.exists():
        raise FileNotFoundError(f"Modèle introuvable : {chemin.name}")
    section_id = int(params.get("section") or 0)
    if not section_id:
        raise DimensionnementError(
            "Section du groupe manquante — choisir un groupe avant de charger "
            "une section candidate dans le modèle.")
    profil_gsa = str(params.get("profil_gsa") or "").strip()
    if not profil_gsa:
        raise DimensionnementError("Profil de la section candidate manquant.")
    elements = [int(e) for e in (params.get("elements") or [])]
    destination = MODEL_DIR / f"{chemin.stem}_opti.gwb"

    with GsaModel(chemin) as m:
        # propriete DEDIEE au groupe (meme garde-fou que _extraire_optim) :
        # ne touche jamais a la section d'une autre famille de barres
        prop_id = m.section_dediee(elements, nom="Optim") if elements else section_id
        m.set_section_profile(prop_id, profil_gsa)
        m.save_to(destination)

    reponse = {"ok": True, "modele": destination.name, "modeles": liste_modeles()}
    try:
        os.startfile(destination)                  # ouvre avec GSA (association Windows)
    except OSError as ex:
        reponse["avertissement"] = f"Fichier enregistré mais l'ouverture a échoué : {ex}"
    return reponse


# ============================================================================
#  OPTIMISATION GLOBALE — plusieurs familles, dans un ORDRE choisi
# ============================================================================
#  L'onglet Optimisation reduit UNE famille en laissant tout le reste du modele
#  fige. « Opt. globale » en enchaine PLUSIEURS : la page choisit lesquelles,
#  dans quel ordre, et par quel algorithme.
#
#  Un algorithme est une fonction `f(ctx)` enregistree dans ALGOS_GLOBAUX. Il ne
#  voit que les operations elementaires de `_CtxGlobal` (candidats d'une
#  famille, essayer une section, figer une famille) : il n'ouvre ni GSA ni
#  Excel, et n'a pas a savoir comment un taux est calcule — meme principe que
#  `commun/algo_opti`, mais sur la maille « propriete de section » d'appv2
#  plutot que sur les familles de config/familles.json.
#
#  CE QUI EST VERIFIE A CHAQUE ESSAI (une analyse GSA reelle par candidat,
#  comme l'onglet Optimisation) :
#    - ELU sur TOUTES les barres du PERIMETRE, pas seulement la famille qu'on
#      allege : alleger une famille redistribue les efforts sur les autres, et
#      une famille deja optimisee peut redevenir insuffisante ;
#    - ELS sur les criteres nodaux du modele — GLOBAUX par nature (le taux
#      retenu est le MAX des criteres declares, cf. els_noeuds.taux_max) ;
#    - stabilite EC3 (`commun/stabilite_ec3`) seulement si la case « prendre en
#      compte » de l'encadre Instabilite est cochee, et alors seulement pour
#      les candidats qui passent deja ELU et ELS.
# ============================================================================

def _familles_acier(m, sections: dict[int, dict]) -> dict[int, dict]:
    """Familles acier du modele : {id de section: fiche}.

    Une famille = toutes les barres 1D reelles qui portent la MEME propriete de
    section — exactement le « groupe » du reste d'appv2 (cf. `app.js::groupes`),
    de sorte que l'onglet Opt. globale parle des memes objets que les deux
    autres. Aucune analyse requise : tables Elements/Sections seules."""
    par: dict[int, dict] = {}
    for e in m.elements():
        if e["factice"] or e["type"] not in TYPES_1D:
            continue
        sec = sections.get(e["propriete"])
        if sec is None:                    # section non acier : hors sujet EC3
            continue
        f = par.setdefault(e["propriete"], {
            "section": e["propriete"],
            "nom": sec.get("nom") or f"section {e['propriete']}",
            "profil_initial": sec.get("profil", ""),
            "aire_initiale_m2": sec.get("aire_m2") or 0.0,
            "elements": [], "longueurs": {}})
        f["elements"].append(e["element"])
        f["longueurs"][e["element"]] = round(e["longueur_m"], 3)
    for f in par.values():
        f["elements"].sort()
        f["sel"] = " ".join(str(i) for i in f["elements"])
        f["longueur_totale_m"] = round(sum(f["longueurs"].values()), 2)
        f["masse_initiale_kg_m"] = round(f["aire_initiale_m2"] * DENSITE_ACIER_KG_M3, 2)
        f["prop_id"] = f["section"]        # ecrase par section_dediee si optimisee
        # masse lineique de la section que la famille porte A CET INSTANT :
        # suivie par `_CtxGlobal.essayer` et `figer_famille` pour donner, essai
        # par essai, le poids du modele (`poids_modele_kg`) — l'ordonnee du
        # graphique de l'onglet Opt. globale
        f["_masse_courante_kg_m"] = f["masse_initiale_kg_m"]
    return par


class _CtxGlobal:
    """Contexte de travail d'une optimisation globale : le modele GSA ouvert, le
    perimetre de familles, et les operations qu'un algorithme enchaine.

    Deux listes de familles, volontairement distinctes :
      `familles`  — celles que l'algorithme a le droit de MODIFIER, dans
                    l'ordre choisi par la page ;
      `perimetre` — celles dont l'ELU est VERIFIE a chaque essai (les
                    precedentes, plus, si la page le demande, toutes les autres
                    familles acier du modele : elles subissent la
                    redistribution sans etre touchees).
    """

    def __init__(self, job: "JobGlobal", m, refs: dict, nuance: str,
                 familles: list[dict], perimetre: list[dict],
                 criteres_service: list[dict], nb_perm: int,
                 libelles_elu: list[str], libelles_els: list[str] | None):
        self.job = job
        self.m = m
        self.refs = refs
        self.nuance = nuance
        self.familles = familles
        self.perimetre = perimetre
        self.criteres_service = criteres_service
        self.nb_perm = nb_perm
        self.libelles_elu = libelles_elu
        self.libelles_els = libelles_els
        self.fy_force = None if job.nuance_modele else job.fy_Pa
        self.session = None                # stabilite EC3, ouverte au 1er besoin

    # ---------------------------------------------------------------- outils
    def stop(self) -> bool:
        return self.job.stop.is_set()

    def poids_perimetre_kg(self) -> float:
        """Poids des familles A OPTIMISER dans l'etat courant du modele :
        somme de (masse lineique de la section qu'elles portent) x (longueur
        totale de leurs barres). Meme perimetre que `meta["poids_initial_kg"]`,
        pour que les deux soient comparables — donc les familles seulement
        VERIFIEES (perimetre ELU etendu) n'y comptent pas : elles ne changent
        jamais de section, elles n'ajouteraient qu'une constante."""
        return round(sum(f["_masse_courante_kg_m"] * f["longueur_totale_m"]
                         for f in self.familles), 1)

    def _libelle_elu(self, perm: int) -> str:
        return self.libelles_elu[perm] if perm < len(self.libelles_elu) \
            else f"perm{perm + 1:03d}"

    def _coefs(self, f: dict) -> tuple[dict, bool]:
        """Coefficients de stabilite applicables a UNE famille : ceux de
        l'encadre Instabilite, ecrases par les valeurs saisies sur sa ligne
        (longueurs de flambement/deversement notamment). Un champ laisse vide
        cote page n'est pas transmis : la valeur globale reste en place."""
        return ({**self.job.coefs_stabilite, **(f.get("coefs") or {})},
                bool(f.get("longueur_par_element", self.job.longueur_par_element)))

    # ------------------------------------------------------- evaluation ELU
    def _elu(self) -> tuple[dict, dict]:
        """(resume, detail) de l'ELU sur tout le perimetre, dans l'etat COURANT
        du modele (deja analyse).

        `resume` : le pire taux et ce qui le gouverne (famille, barre, critere,
        combinaison). `detail` : par famille, sa section et, barre par barre, sa
        case dimensionnante — necessaire pour la stabilite EC3, qui a besoin du
        torseur exact de la combinaison retenue (`_torseur_dimensionnant`)."""
        secs = sections_acier(self.m, fy_Pa=self.fy_force, source_av="gsa")
        resultat = self.m._result(self.refs["ELU"])
        detail: dict[int, dict] = {}
        pire = {"taux": 0.0, "famille": None, "element": None, "critere": None,
                "signe": None, "combinaison": None}
        par_famille: dict[int, dict] = {}
        for f in self.perimetre:
            sec = secs.get(f["prop_id"])
            if sec is None:
                continue
            efforts = efforts_par_permutation(resultat, f["sel"], POSITIONS)
            barres: dict[int, dict] = {}
            meilleur = None
            for eid in f["elements"]:
                eff = efforts.get(eid)
                if eff is None or eff.size == 0 or eff.shape[0] != self.nb_perm:
                    continue           # barre sans resultat exploitable : ecartee
                retenu = _critere_retenu(criteres_dimensionnants(eff, None, sec),
                                         CRITERES_OPTIM)
                if retenu is None:
                    continue
                critere, b = retenu
                barres[eid] = {"critere": critere, "perm": b["perm"],
                               "position": b["position"], "taux": b["taux"],
                               "signe": b.get("signe"), "eff": eff}
                if meilleur is None or b["taux"] > barres[meilleur]["taux"]:
                    meilleur = eid
            if not barres:
                continue
            detail[f["section"]] = {"famille": f, "sec": sec, "barres": barres}
            g = barres[meilleur]
            par_famille[f["section"]] = {
                "taux": round(g["taux"], 4), "element": meilleur,
                "critere": g["critere"], "signe": g["signe"],
                "combinaison": self._libelle_elu(g["perm"])}
            if g["taux"] > pire["taux"]:
                pire = {"taux": round(g["taux"], 4), "famille": f["section"],
                        "element": meilleur, "critere": g["critere"],
                        "signe": g["signe"], "combinaison": self._libelle_elu(g["perm"]),
                        # torseur de la case gouvernante : colonnes d'efforts
                        # de l'essai (cf. etat_courant) — jamais serialise tel
                        # quel, `eff` est un tableau numpy
                        "perm": g["perm"], "position": g["position"], "eff": g["eff"]}
        pire["par_famille"] = par_famille
        return pire, detail

    # ------------------------------------------------------- stabilite EC3
    def _session(self):
        """Session de stabilite EC3, ouverte au premier besoin
        (`_session_stabilite`). Ne prend plus aucun verrou : le module Python
        n'ouvre ni processus ni fichier."""
        if self.session is None:
            self.session = _session_stabilite()
            self.session.open()
        return self.session

    def fermer(self) -> None:
        """Libere la session de stabilite. Toujours appelee, meme en cas
        d'echec — la contrainte date du classeur Excel (un classeur non ferme
        laissait un EXCEL.EXE orphelin qui verrouillait le maitre) ; on la
        garde parce que le contrat de session, lui, n'a pas change."""
        if self.session is not None:
            self.session.close()
            self.session = None

    def _cases_stabilite(self, detail: dict) -> list[tuple[dict, int, int, int]]:
        """Cases (famille, barre, permutation, position) a verifier en
        stabilite. Rapide : la barre qui gouverne l'ELU de CHAQUE famille du
        perimetre, a sa case dimensionnante. Approfondi : TOUTES les barres de
        chaque famille, sur TOUTES leurs permutations ET TOUTES leurs positions
        (0/25/50/75/100 %) — exhaustif, pas une heuristique sur les barres les
        plus sollicitees en ELU (la case qui gouverne la stabilite d'une barre
        n'est pas toujours celle qui gouverne son ELU, cf. l'etude P1_sup)."""
        cases: list[tuple[dict, int, int, int]] = []
        for d in detail.values():
            barres = d["barres"]
            if not barres:
                continue
            if self.job.stabilite_approfondie:
                for eid, info in barres.items():
                    nperm_b, npos_b = info["eff"].shape[0], info["eff"].shape[1]
                    for ip in range(nperm_b):
                        for pos in range(npos_b):
                            cases.append((d["famille"], eid, ip, pos))
            else:
                eid = max(barres, key=lambda k: barres[k]["taux"])
                cases.append((d["famille"], eid, barres[eid]["perm"],
                              barres[eid]["position"]))
        return cases

    def _stabilite(self, detail: dict, profils_predim: dict) -> dict:
        """Pire taux de stabilite EC3 du perimetre, dans l'etat courant.

        `profils_predim` : {id de famille: (famille Predim, nom)} pour les
        familles dont la designation catalogue est deja connue (celle qu'on est
        en train d'essayer) ; les autres sont resolues depuis leur profil GSA
        par `_entrees_classeur`/`_profil_predim`, avec son repli catalogue."""
        cases = self._cases_stabilite(detail)
        if not cases:
            return {"erreur": "aucune barre exploitable pour la stabilité"}
        pire, erreurs = None, []
        for i, (f, eid, perm, position) in enumerate(cases):
            if self.stop():
                break
            progres("global", f"stabilité EC3 — barre {eid} ({f['nom']})…",
                    i, len(cases))
            d = detail[f["section"]]
            eff = d["barres"][eid]["eff"]
            torseur, my_dmf, mz_dmf = _torseur_dimensionnant(eff, perm, position)
            lib = self._libelle_elu(perm)
            bt = {"element": eid, "profil_gsa": d["sec"].get("profil", ""),
                  "longueur_m": f["longueurs"].get(eid, 0.0), "torseur": torseur,
                  "my_debut_milieu_fin": my_dmf, "mz_debut_milieu_fin": mz_dmf,
                  "combinaison_gouvernante": lib,
                  "position_gouvernante_pct": positions_pct(eff.shape[1])[position]}
            coefs, longueur_par_element = self._coefs(f)
            try:
                entree_dict, note = _entrees_classeur(
                    bt, self.nuance, coefs, longueur_par_element,
                    profil_force=profils_predim.get(f["section"]))
                r = self._session().verifier({"element": eid, **entree_dict})
                if note and not r.get("erreur") and not r.get("profil_substitue"):
                    r["profil_substitue"] = note
            except DimensionnementError as ex:
                r = {"element": eid, "erreur": str(ex)}
            if r.get("erreur"):
                # la cause REELLE (profil absent du classeur, Excel muet...) est
                # remontee telle quelle si aucune barre ne repond : sans elle,
                # un « aucun taux lisible » generique masquerait le diagnostic
                erreurs.append(f"barre {eid} : {r['erreur']}")
            elif pire is None or r["taux_stabilite"] > pire["taux_stabilite"]:
                # torseur de LA case qui gouverne desormais la stabilite du
                # perimetre — colonnes d'efforts de l'essai (cf. etat_courant)
                pire = {**r, "element_gouvernant": eid, "famille": f["section"],
                        "famille_nom": f["nom"], "combinaison": lib,
                        "my_debut_milieu_fin": my_dmf, "mz_debut_milieu_fin": mz_dmf,
                        **_valeurs_torseur(eff, perm, position)}
        if pire is None:
            return {"erreur": erreurs[0] if erreurs
                    else "aucun taux de stabilité lisible sur ces barres"}
        return pire

    # ------------------------------------------- etat courant du modele
    def etat_courant(self, profils_predim: dict | None = None) -> dict:
        """Verdict de l'etat COURANT du modele (deja analyse) : ELU sur tout le
        perimetre, ELS global, et stabilite si elle est prise en compte — dans
        ce cas seulement quand ELU et ELS passent deja (meme economie que
        l'onglet Optimisation : inutile de payer Excel pour un etat deja
        recale)."""
        resume, detail = self._elu()
        els = _bilan_els(self.m, self.refs.get("ELS"), self.criteres_service,
                         self.libelles_els, self.job.coefficient_els)
        gouv_els = els["gouvernant"]
        ok_elu = bool(resume["taux"] <= self.job.coefficient)
        ok_els = els["taux"] is None or els["taux"] <= self.job.coefficient_els
        # torseur (N, Vy, Vz, Mxx, My, Mz) de LA barre qui gouverne l'ELU du
        # perimetre — colonnes d'efforts du tableau detaille, a cote de la
        # combinaison et de la barre deja affichees
        effort_elu = (_valeurs_torseur(resume["eff"], resume["perm"], resume["position"])
                     if resume.get("element") is not None else _EFFORT_VIDE)
        etat = {
            "taux_elu": resume["taux"], "critere_elu": resume["critere"],
            "signe_elu": resume["signe"], "combinaison_elu": resume["combinaison"],
            "element_gouvernant": resume["element"],
            "famille_gouvernante": resume["famille"],
            "taux_elu_par_famille": resume["par_famille"],
            **_prefixer("elu", effort_elu),
            "taux_els": els["taux"],
            "critere_els": gouv_els["nom"] if gouv_els else None,
            "combinaison_els": gouv_els["libelle"] if gouv_els else None,
            "noeud_gouvernant_els": gouv_els["noeud"] if gouv_els else None,
            "ok_elu": ok_elu, "ok_els": ok_els,
            "taux_stabilite": None, "combinaison_stab": None,
            "element_stab": None, "famille_stab": None, "cas_stab": None,
            "erreur_stab": None, "profil_substitue": None,
            # coefficients EFFECTIVEMENT utilises par la stabilite EC3 de CET
            # essai (§3.5 Annexe MCR + classe §5.5) : sans objet tant qu'elle
            # n'a pas ete verifiee. Sert UNIQUEMENT a `ouvrir_excel_candidat`
            # (bouton Excel du detail Opt. globale), pour pre-remplir le
            # classeur sans rouvrir GSA — meme role que `job.stab[nom]["C1"]`
            # etc. cote onglet Optimisation (`_extraire_optim`).
            "C1_stab": None, "C2_stab": None, "k_stab": None, "kw_stab": None,
            "classe_stab": None,
            "my_debut_milieu_fin": None, "mz_debut_milieu_fin": None,
            **_prefixer("stab", _EFFORT_VIDE),
        }
        if ok_elu and ok_els and self.job.avec_stabilite:
            stab = self._stabilite(detail, profils_predim or {})
            if stab.get("erreur"):
                etat["erreur_stab"] = stab["erreur"]
            else:
                etat.update(
                    taux_stabilite=stab["taux_stabilite"],
                    combinaison_stab=stab.get("combinaison"),
                    element_stab=stab.get("element_gouvernant"),
                    famille_stab=stab.get("famille"),
                    cas_stab=stab.get("cas"),
                    profil_substitue=stab.get("profil_substitue"),
                    C1_stab=stab.get("C1"), C2_stab=stab.get("C2"),
                    k_stab=stab.get("k"), kw_stab=stab.get("kw"),
                    classe_stab=stab.get("classe"),
                    my_debut_milieu_fin=stab.get("my_debut_milieu_fin"),
                    mz_debut_milieu_fin=stab.get("mz_debut_milieu_fin"),
                    **_prefixer("stab", {cle: stab.get(cle) for cle in
                                         ("N_kN", "Vy_kN", "Vz_kN", "Mxx_kNm",
                                          "My_kNm", "Mz_kNm", "lieu_pct")}))
        # verdict : la stabilite ne recale un etat que si elle a pu etre lue —
        # une erreur Excel laisse le verdict indetermine (None), jamais un OK
        # silencieux
        if not (ok_elu and ok_els):
            etat["ok"] = False
        elif not self.job.avec_stabilite:
            etat["ok"] = True
        elif etat["taux_stabilite"] is not None:
            etat["ok"] = etat["taux_stabilite"] <= self.job.coefficient_stabilite
        else:
            etat["ok"] = None
        return etat

    # ------------------------------------------ operations des algorithmes
    def candidats(self, f: dict) -> list[dict]:
        """Sections catalogue plus LEGERES que celle que porte actuellement la
        famille, de la plus lourde a la plus legere (la plus proche de
        l'actuelle d'abord)."""
        feuille = f.get("feuille_catalogue")
        if not feuille:
            return []
        aire = f["aire_initiale_m2"]
        return sorted((r for r in charger_catalogue(feuille)
                       if float(r["aire_m2"] or 0) < aire),
                      key=lambda r: -float(r["masse_kg_m"]))

    def essayer(self, f: dict, row: dict) -> dict:
        """Ecrit la section `row` sur la famille `f`, RELANCE L'ANALYSE et rend
        la ligne de journal du candidat (verdict compris)."""
        profil = row.get("profil_gsa") or row["nom"]
        self.m.set_section_profile(f["prop_id"], profil)
        f["_dernier_profil"] = profil
        f["_masse_courante_kg_m"] = float(row["masse_kg_m"])
        timings = self.m.analyse()
        masse_gagnee = f["masse_initiale_kg_m"] - float(row["masse_kg_m"])
        ligne = {
            "famille": f["section"], "famille_nom": f["nom"], "ordre": f["ordre"],
            "nom": row["nom"], "profil_gsa": profil,
            "masse_kg_m": float(row["masse_kg_m"]),
            "aire_m2": float(row["aire_m2"] or 0.0),
            "poids_modele_kg": self.poids_perimetre_kg(),
            "reduction_pct": round(100.0 * (1.0 - float(row["aire_m2"])
                                            / f["aire_initiale_m2"]), 1)
                             if f["aire_initiale_m2"] else None,
            "masse_gagnee_kg_m": round(masse_gagnee, 2),
            "masse_gagnee_kg_total": round(masse_gagnee * f["longueur_totale_m"], 1),
        }
        if not all(t["ok"] for t in timings):
            return {**ligne, "ok": False,
                    "erreur": "Analyse GSA en échec avec cette section."}
        predim = {f["section"]: _nom_predim_depuis_catalogue(
            f["feuille_catalogue"], row["nom"])}
        return {**ligne, **self.etat_courant(predim)}

    def figer_famille(self, f: dict, retenue: dict | None) -> dict:
        """Remet la famille sur la section RETENUE (ou sur sa section d'origine
        si aucune n'a passe) et relance l'analyse : les familles optimisees
        ensuite travaillent sur la structure DEJA allegee, et l'etat final du
        modele est celui du dernier candidat accepte — jamais celui du dernier
        candidat essaye, qui vient d'echouer."""
        profil = (retenue.get("profil_gsa") or retenue["nom"]) if retenue \
            else f["profil_initial"]
        if f.get("_dernier_profil") != profil:
            self.m.set_section_profile(f["prop_id"], profil)
            f["_dernier_profil"] = profil
            self.m.analyse()
        masse = float(retenue["masse_kg_m"]) if retenue else f["masse_initiale_kg_m"]
        f["_masse_courante_kg_m"] = masse
        gain = f["masse_initiale_kg_m"] - masse
        maj = {
            "etat": "terminée",
            "nom_retenu": retenue["nom"] if retenue else None,
            "profil_retenu": profil,
            "masse_retenue_kg_m": round(masse, 2),
            "reduction_pct": round(100.0 * (1.0 - float(retenue["aire_m2"])
                                            / f["aire_initiale_m2"]), 1)
                             if retenue and f["aire_initiale_m2"] else None,
            "masse_gagnee_kg_m": round(gain, 2),
            "masse_gagnee_kg_total": round(gain * f["longueur_totale_m"], 1),
        }
        self.job.majer_famille(f["section"], maj)
        return maj

    def journaliser(self, ligne: dict) -> None:
        self.job.ajouter_essai(ligne)


# ------------------------------------------------------------- algorithmes
def _algo_escalier(ctx: _CtxGlobal) -> None:
    """Famille par famille, dans l'ordre choisi : on descend le catalogue de la
    famille courante (des sections les plus lourdes vers les plus legeres) tant
    que la STRUCTURE ENTIERE verifie ELU + ELS (+ stabilite si elle est prise en
    compte), et on passe a la suivante apres `profondeur` echecs consecutifs.

    La section retenue reste en place pour l'optimisation des familles
    suivantes : chacune est donc optimisee sur la structure DEJA allegee par
    celles qui la precedent — c'est ce qui rend l'ORDRE decisif (l'etude de
    sensibilite de `comparaison_modele/` mesure un facteur 3,4 entre deux
    ordres sur le meme treillis).

    Une famille est descendue en entier (pas arretee au premier echec) : les
    catalogues melangent hauteur et epaisseur, une section plus legere d'une
    autre serie peut passer la ou la precedente a echoue. `profondeur` (10 par
    defaut, comme l'onglet Optimisation) borne cette obstination."""
    for f in ctx.familles:
        if ctx.stop():
            return
        if not f.get("feuille_catalogue"):
            ctx.job.majer_famille(f["section"], {
                "etat": "non optimisable",
                "message": f"aucun catalogue comparable pour {f['profil_initial']!r}"})
            continue
        ctx.job.majer_famille(f["section"], {"etat": "en cours"})
        candidats = ctx.candidats(f)
        ctx.job.majer_famille(f["section"], {"nb_candidats": len(candidats)})
        retenue, ko = None, 0
        for i, row in enumerate(candidats):
            if ctx.stop():
                break
            progres("global", f"{f['nom']} — {row['nom']} : analyse GSA + ELU/ELS…",
                    i, len(candidats))
            ligne = ctx.essayer(f, row)
            ctx.journaliser(ligne)
            if ligne.get("ok"):
                retenue, ko = row, 0
            else:
                ko += 1
                if ko >= ctx.job.profondeur:
                    ctx.job.majer_famille(f["section"], {
                        "message": f"{ko} sections consécutives en échec — "
                                   "arrêt de cette famille"})
                    break
        ctx.figer_famille(f, retenue)


ALGOS_GLOBAUX: dict[str, dict] = {
    "escalier": {
        "libelle": "Escalier (famille par famille)",
        "description": ("Dans l'ordre choisi, chaque famille est réduite tant "
                        "que la structure entière vérifie ELU, ELS (et la "
                        "stabilité si elle est prise en compte) ; on passe à la "
                        "suivante après 10 échecs consécutifs. La section "
                        "retenue reste en place pour les familles suivantes : "
                        "l'ordre change le résultat."),
        "fonction": _algo_escalier,
    },
}


class JobGlobal:
    """Etat partage entre le thread GSA (qui deroule l'algorithme) et les polls
    de la page — memes conventions que `JobOptim` (lock/stop/etat/erreur)."""

    def __init__(self, nom: str, elu: str, els: str, familles: list[dict],
                 algo: str, profondeur: int,
                 fy_Pa: float | None, coefficient: float,
                 reglages_els: dict | None, nuance_modele: bool,
                 coefs_stabilite: dict | None, longueur_par_element: bool,
                 avec_stabilite: bool, stabilite_approfondie: bool,
                 elu_perimetre_complet: bool,
                 coefficient_els: float = 1.0,
                 coefficient_stabilite: float = 1.0):
        self.nom = nom
        self.elu = elu
        self.els = els
        # familles A OPTIMISER, DANS L'ORDRE de la page : [{section, coefs,
        # longueur_par_element}] — l'ordre est le parametre principal de
        # l'algorithme escalier, pas un detail d'affichage
        self.familles = familles
        self.algo = algo
        self.profondeur = profondeur
        self.fy_Pa = fy_Pa
        self.coefficient = coefficient
        self.coefficient_els = coefficient_els
        self.coefficient_stabilite = coefficient_stabilite
        self.reglages_els = reglages_els or {}
        self.nuance_modele = nuance_modele
        self.coefs_stabilite = coefs_stabilite or {}
        self.longueur_par_element = longueur_par_element
        self.avec_stabilite = avec_stabilite
        self.stabilite_approfondie = stabilite_approfondie
        # True : l'ELU est verifie sur TOUTES les familles acier du modele, pas
        # seulement celles qu'on optimise (plus lent, mais couvre les familles
        # figees qui subissent la redistribution)
        self.elu_perimetre_complet = elu_perimetre_complet
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.essais: list[dict] = []       # journal : une ligne par candidat essaye
        self.bilan: list[dict] = []        # une ligne par famille, mise a jour en continu
        self.meta: dict = {}
        self.etat = "en_cours"
        self.erreur: str | None = None
        # {section de famille: {element: longueur_m}} de tout le PERIMETRE —
        # rempli une fois par `_optimiser_global` (la longueur ne depend pas de
        # l'essai), sert UNIQUEMENT a `ouvrir_excel_candidat` pour reconstruire
        # les entrees du classeur SANS rouvrir GSA (meme role que
        # `JobOptim.longueurs`, par famille plutot que par groupe unique ici).
        self.longueurs_par_famille: dict[int, dict[int, float]] = {}

    def ajouter_essai(self, ligne: dict) -> None:
        with self.lock:
            self.essais.append(ligne)

    def majer_famille(self, section: int, maj: dict) -> None:
        with self.lock:
            for b in self.bilan:
                if b["section"] == section:
                    b.update(maj)
                    return


GLOBAL_JOBS: dict[str, JobGlobal] = {}
GLOBAL_JOBS_LOCK = threading.Lock()


def _optimiser_global(job: JobGlobal) -> None:
    """Thread GSA : prepare le perimetre, evalue l'etat initial, deroule
    l'algorithme choisi, puis reevalue l'etat final. Ne leve jamais : les
    echecs partent dans `job.erreur`."""
    ctx = None
    try:
        chemin = MODEL_DIR / Path(job.nom).name
        if not chemin.exists():
            raise FileNotFoundError(f"Modèle introuvable : {chemin.name}")
        algo = ALGOS_GLOBAUX.get(job.algo)
        if algo is None:
            raise DimensionnementError(f"Algorithme inconnu : {job.algo!r}.")
        progres("global", "copie et ouverture du modèle (GsaAPI)…")
        with GsaModel(chemin) as m:
            m.check_analysis_setup()
            refs = refs_elu_els(m, job.elu, job.els)
            criteres_service = _criteres_els(m, job.reglages_els)
            nuance = _nuance_acier(m.materials())
            fy_force = None if job.nuance_modele else job.fy_Pa

            # tables seules (aucune analyse necessaire a ce stade) : on decoupe
            # les familles AVANT d'analyser, pour que les proprietes dediees
            # soient en place des la premiere analyse
            fiches = _familles_acier(
                m, sections_acier(m, fy_Pa=fy_force, source_av="gsa"))
            choisies = []
            for i, entree in enumerate(job.familles):
                fiche = fiches.get(entree["section"])
                if fiche is None:
                    continue
                fiche.update(entree)
                fiche["ordre"] = i + 1
                fiche["feuille_catalogue"] = _famille_catalogue(
                    fiche["profil_initial"])[0]
                choisies.append(fiche)
            if not choisies:
                raise DimensionnementError(
                    "Aucune famille à optimiser : cocher au moins une famille "
                    "acier dans le tableau.")

            perimetre = ([fiches[k] for k in sorted(fiches)]
                         if job.elu_perimetre_complet else list(choisies))

            with job.lock:
                job.bilan = [{
                    "section": f["section"], "ordre": f["ordre"], "nom": f["nom"],
                    "profil_initial": f["profil_initial"],
                    "masse_initiale_kg_m": f["masse_initiale_kg_m"],
                    "longueur_totale_m": f["longueur_totale_m"],
                    "nb_barres": len(f["elements"]),
                    "feuille_catalogue": f["feuille_catalogue"],
                    "elements": f["elements"],
                    "etat": "en attente" if f["feuille_catalogue"] else "non optimisable",
                    "message": None if f["feuille_catalogue"] else
                               f"aucun catalogue comparable pour {f['profil_initial']!r}",
                    "nb_candidats": None, "nom_retenu": None, "profil_retenu": None,
                    "masse_retenue_kg_m": None, "reduction_pct": None,
                    "masse_gagnee_kg_m": None, "masse_gagnee_kg_total": None,
                } for f in choisies]

            # propriete DEDIEE a chaque famille optimisee : on la mute sans
            # jamais toucher aux autres (meme garde-fou que _extraire_optim)
            for f in choisies:
                f["prop_id"] = m.section_dediee(f["elements"],
                                                nom=f"Optim {f['nom']}")

            progres("global", "analyse GSA du modèle (état initial)…")
            timings = m.analyse()
            if not all(t["ok"] for t in timings):
                raise DimensionnementError("Analyse GSA en échec sur le modèle actuel.")

            # etiquetage des permutations sur une barre temoin : l'expansion
            # d'une enveloppe ne depend que de sa definition, jamais de la
            # raideur des barres — valable pour tous les candidats
            temoin = perimetre[0]["elements"][0]
            efforts0 = efforts_par_permutation(
                m._result(refs["ELU"]), str(temoin), POSITIONS).get(temoin)
            if efforts0 is None:
                raise DimensionnementError(
                    f"La combinaison {refs['ELU']} n'a pas de résultats sur ce modèle.")
            nb_perm = efforts0.shape[0]
            libelles_elu = libelles_permutations(
                m, int(refs["ELU"][1:]), temoin, nb_perm, POSITIONS)["libelles"]
            libelles_els = _libelles_els(m, refs.get("ELS"), temoin, POSITIONS)

            ctx = _CtxGlobal(job, m, refs, nuance, choisies, perimetre,
                             criteres_service, nb_perm, libelles_elu, libelles_els)
            job.longueurs_par_famille = {f["section"]: f["longueurs"] for f in perimetre}

            progres("global", "état initial : ELU + ELS"
                    + (" + stabilité EC3" if job.avec_stabilite else "") + "…")
            initial = ctx.etat_courant()
            if initial["famille_gouvernante"] is None:
                raise DimensionnementError(
                    "Aucune barre exploitable à l'ELU dans le périmètre : "
                    "vérifier la combinaison ELU et le choix des familles.")
            poids_initial = sum(f["masse_initiale_kg_m"] * f["longueur_totale_m"]
                                for f in choisies)
            with job.lock:
                job.meta = {
                    "algo": job.algo, "libelle_algo": algo["libelle"],
                    "profondeur": job.profondeur, "coefficient": job.coefficient,
                    "coefficient_els": job.coefficient_els,
                    "coefficient_stabilite": job.coefficient_stabilite,
                    "elu": refs["ELU"], "els_combinaison": refs.get("ELS"),
                    "criteres_els": criteres_service, "nb_perm": nb_perm,
                    "avec_stabilite": job.avec_stabilite,
                    "stabilite_approfondie": job.stabilite_approfondie,
                    "elu_perimetre_complet": job.elu_perimetre_complet,
                    "nb_familles": len(choisies),
                    "nb_familles_perimetre": len(perimetre),
                    "nb_barres_perimetre": sum(len(f["elements"]) for f in perimetre),
                    "poids_initial_kg": round(poids_initial, 1),
                    "initial": initial,
                    "nuance": nuance,
                }

            algo["fonction"](ctx)

            progres("global", "état final : vérification du modèle optimisé…")
            with job.lock:
                gain = sum(b["masse_gagnee_kg_total"] or 0.0 for b in job.bilan)
            final = ctx.etat_courant()
            with job.lock:
                job.meta["final"] = final
                job.meta["gain_kg_total"] = round(gain, 1)
                job.meta["gain_pct"] = round(100.0 * gain / poids_initial, 1) \
                    if poids_initial else None
                job.etat = "arrete" if job.stop.is_set() else "fini"
        progres("global", "terminé")
    except BaseException as e:                                    # noqa: BLE001
        with job.lock:
            job.etat = "erreur"
            job.erreur = str(e)
        progres("global", "terminé")
        if not isinstance(e, (DimensionnementError, ConfigurationAnalyseError,
                              FileNotFoundError, ValueError, KeyError)):
            traceback.print_exc()
    finally:
        if ctx is not None:
            ctx.fermer()


def global_demarrer(params: dict) -> dict:
    """Demarre une optimisation globale et renvoie son identifiant."""
    nom = params.get("modele") or ""
    chemin = MODEL_DIR / Path(nom).name
    if not chemin.exists():
        raise FileNotFoundError(f"Modèle introuvable : {chemin.name}")
    familles = []
    for f in params.get("familles") or []:
        try:
            sid = int(f.get("section") or 0)
        except (TypeError, ValueError):
            continue
        if not sid:
            continue
        coefs, longueur_par_element = valider_coefs(f.get("coefs") or {})
        familles.append({"section": sid, "coefs": coefs,
                         "longueur_par_element": longueur_par_element})
    if not familles:
        raise DimensionnementError(
            "Aucune famille sélectionnée : cocher au moins une famille acier.")
    algo = str(params.get("algo") or "escalier")
    if algo not in ALGOS_GLOBAUX:
        raise DimensionnementError(f"Algorithme inconnu : {algo!r}.")
    crit = params.get("criteres") or {}
    cfg = lire_config()
    fy_Pa = float(crit["fy_Pa"]) if crit.get("fy_Pa") else \
        cfg["critere_contrainte"]["fy_Pa"]
    coefficient = float(crit["coefficient"]) if crit.get("coefficient") else \
        cfg["critere_contrainte"]["coefficient"]
    coefficient_els = float(crit["coefficient_els"]) if crit.get("coefficient_els") else \
        cfg["critere_els"]["coefficient"]
    coefficient_stabilite = float(crit["coefficient_stabilite"]) if crit.get("coefficient_stabilite") else \
        cfg["critere_stabilite"]["coefficient"]
    profondeur = int(params.get("profondeur") or SEUIL_KO_CONSECUTIFS)
    coefs_stabilite, longueur_par_element = valider_coefs(params.get("coefs") or {})
    job = JobGlobal(nom, params.get("elu") or "", params.get("els") or "",
                    familles, algo, max(1, profondeur),
                    fy_Pa, coefficient, params.get("criteres_els") or {},
                    bool(params.get("nuance_modele")),
                    coefs_stabilite, longueur_par_element,
                    params.get("avec_stabilite", True) is not False,
                    bool(params.get("stabilite_approfondie")),
                    bool(params.get("elu_perimetre_complet")),
                    coefficient_els, coefficient_stabilite)
    jid = uuid.uuid4().hex
    with GLOBAL_JOBS_LOCK:
        for k in [k for k, j in GLOBAL_JOBS.items() if j.etat != "en_cours"]:
            del GLOBAL_JOBS[k]
        GLOBAL_JOBS[jid] = job
    GSA.soumettre(_optimiser_global, job)
    return {"job": jid, "modele": chemin.name}


def global_etat(jid: str, depuis: int) -> dict:
    """Etat d'une optimisation globale : nouveaux essais depuis `depuis`, bilan
    par famille (reenvoye en entier : il est court et change en place), meta et
    statut."""
    with GLOBAL_JOBS_LOCK:
        job = GLOBAL_JOBS.get(jid)
    if job is None:
        raise DimensionnementError("Calcul inconnu ou expiré.")
    with job.lock:
        return {"essais": job.essais[depuis:], "recus": len(job.essais),
                "bilan": job.bilan, "meta": job.meta,
                "etat": job.etat, "erreur": job.erreur}


def global_arreter(jid: str) -> dict:
    """Demande l'arret d'une optimisation globale (coupe entre deux essais)."""
    with GLOBAL_JOBS_LOCK:
        job = GLOBAL_JOBS.get(jid)
    if job is not None:
        job.stop.set()
    return {"ok": True}


def charger_global(params: dict) -> dict:
    """Enregistre `<modele>_opti.gwb` avec la section retenue de CHAQUE famille
    optimisee, puis l'ouvre dans GSA. Meme convention que
    `charger_section_optim` (copie ecrasee a chaque appel, source jamais
    modifiee), mais pour plusieurs familles d'un coup."""
    nom = params.get("modele") or ""
    chemin = MODEL_DIR / Path(nom).name
    if not chemin.exists():
        raise FileNotFoundError(f"Modèle introuvable : {chemin.name}")
    familles = params.get("familles") or []
    if not familles:
        raise DimensionnementError("Aucune section retenue à charger.")
    destination = MODEL_DIR / f"{chemin.stem}_opti.gwb"
    appliquees = []
    with GsaModel(chemin) as m:
        for f in familles:
            profil = str(f.get("profil_gsa") or "").strip()
            if not profil:
                continue
            elements = [int(e) for e in (f.get("elements") or [])]
            prop_id = m.section_dediee(elements, nom="Optim") if elements \
                else int(f.get("section") or 0)
            if not prop_id:
                continue
            m.set_section_profile(prop_id, profil)
            appliquees.append(profil)
        if not appliquees:
            raise DimensionnementError("Aucune section retenue à charger.")
        m.save_to(destination)

    reponse = {"ok": True, "modele": destination.name, "sections": appliquees,
               "modeles": liste_modeles()}
    try:
        os.startfile(destination)                  # ouvre avec GSA (association Windows)
    except OSError as ex:
        reponse["avertissement"] = f"Fichier enregistré mais l'ouverture a échoué : {ex}"
    return reponse


# ------------------------------------------------------------------ serveur
class Handler(BaseHTTPRequestHandler):

    timeout = 30        # une connexion muette (preconnexion navigateur) est lachee

    def log_message(self, fmt, *args):          # journal compact
        print(f"  [{self.log_date_time_string()}] {fmt % args}")

    def _json(self, data, code=200):
        corps = json.dumps(data, ensure_ascii=False,
                           default=_json_defaut).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def _erreur(self, e: Exception, code=400):
        if not isinstance(e, (DimensionnementError, ConfigurationAnalyseError,
                              FileNotFoundError, ValueError, KeyError)):
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
                    "criteres": {
                        "fy_MPa": cfg["critere_contrainte"]["fy_Pa"] / 1e6,
                        "coefficient": cfg["critere_contrainte"]["coefficient"],
                        "coefficient_els": cfg["critere_els"]["coefficient"],
                        "coefficient_stabilite": cfg["critere_stabilite"]["coefficient"],
                    },
                    "criteres_elu": list(CRITERES),
                    "critere_base": CRITERE_BASE,
                    "libelles_criteres": LIBELLES,
                    # algorithmes de l'onglet Opt. globale : la page remplit son
                    # menu deroulant avec ce que le serveur declare, un
                    # algorithme ajoute a ALGOS_GLOBAUX y apparait sans toucher
                    # au HTML (meme principe que commun/algo_opti::ALGOS)
                    "algos_globaux": [
                        {"cle": k, "libelle": a["libelle"],
                         "description": a["description"]}
                        for k, a in ALGOS_GLOBAUX.items()],
                    "profondeur_defaut": SEUIL_KO_CONSECUTIFS,
                })
            elif url.path == "/api/wiki":
                self._json({"pages": liste_wiki()})
            elif url.path == "/api/progression":
                self._json(etat_progression())
            elif url.path == "/api/resume":
                nom = parse_qs(url.query).get("modele", [""])[0]
                self._json(GSA.executer(resume_modele, nom))
            elif url.path == "/api/vue-sections":
                nom = parse_qs(url.query).get("modele", [""])[0]
                self._json(GSA.executer(vue_sections_modele, nom))
            elif url.path == "/api/elu/poll":
                q = parse_qs(url.query)
                jid = q.get("job", [""])[0]
                depuis = int(q.get("depuis", ["0"])[0] or 0)
                self._json(elu_etat(jid, depuis))
            elif url.path == "/api/optim/poll":
                q = parse_qs(url.query)
                jid = q.get("job", [""])[0]
                depuis = int(q.get("depuis", ["0"])[0] or 0)
                self._json(optim_etat(jid, depuis))
            elif url.path == "/api/global/poll":
                q = parse_qs(url.query)
                jid = q.get("job", [""])[0]
                depuis = int(q.get("depuis", ["0"])[0] or 0)
                self._json(global_etat(jid, depuis))
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
                    raise ValueError("Seuls les fichiers .gwb sont acceptés.")
                if not corps:
                    raise ValueError("Fichier vide.")
                (MODEL_DIR / nom).write_bytes(corps)
                self._json({"ok": True, "modele": nom, "modeles": liste_modeles()})
            elif url.path == "/api/elu/start":
                self._json(elu_demarrer(json.loads(corps or b"{}")))
            elif url.path == "/api/elu/stop":
                params = json.loads(corps or b"{}")
                self._json(elu_arreter(params.get("job") or ""))
            elif url.path == "/api/optim/start":
                self._json(optim_demarrer(json.loads(corps or b"{}")))
            elif url.path == "/api/optim/stop":
                params = json.loads(corps or b"{}")
                self._json(optim_arreter(params.get("job") or ""))
            elif url.path == "/api/optim/charger-section":
                self._json(charger_section_optim(json.loads(corps or b"{}")))
            elif url.path == "/api/global/start":
                self._json(global_demarrer(json.loads(corps or b"{}")))
            elif url.path == "/api/global/stop":
                params = json.loads(corps or b"{}")
                self._json(global_arreter(params.get("job") or ""))
            elif url.path == "/api/global/charger":
                self._json(charger_global(json.loads(corps or b"{}")))
            elif url.path == "/api/excel-barre":
                self._json(ouvrir_excel_barre(json.loads(corps or b"{}")))
            elif url.path == "/api/excel-candidat":
                self._json(ouvrir_excel_candidat(json.loads(corps or b"{}")))
            else:
                self.send_error(404)
        except Exception as e:                                  # noqa: BLE001
            self._erreur(e)


def _json_defaut(o):
    """Sauve-qui-peut du serialiseur. Les scalaires numpy sont convertis en
    nombres Python (les stringifier — ce que fait `default=str` — donnerait des
    chaines la ou la page attend des nombres) ; tout le reste retombe sur str,
    comme dans `app_old/server.py`."""
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        v = float(o)
        return None if math.isnan(v) or math.isinf(v) else v
    return str(o)


def main() -> None:
    parser = argparse.ArgumentParser(description="Interface web appv2 du dimensionneur GSA")
    parser.add_argument("--port", type=int, default=8767)
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
        serveur = Serveur(("127.0.0.1", args.port), Handler)
    except OSError:
        sys.exit(f"Le port {args.port} est deja pris : appv2 est probablement "
                 "deja lance (verifier les processus python), ou choisir un "
                 "autre port avec --port.")
    print(f"appv2 -> {adresse}   (Ctrl+C pour arreter)")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(adresse)).start()
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        print("\nArret.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
