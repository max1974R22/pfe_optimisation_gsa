# -*- coding: utf-8 -*-
"""Permutations d'une combinaison enveloppe, SANS reduction.

`GsaModel.beam_forces` (via `bridge._table_1d`) replie une combinaison
enveloppe en DEUX lignes par position : le max signe de chaque composante sur
toutes les permutations, et le min. C'est pratique pour majorer, mais le max
de N, celui de Myy et celui de Mzz peuvent venir de permutations
DIFFERENTES — les additionner (contrainte combinee C1/C2) n'a alors plus de
sens physique et surestime la contrainte.

Ce module donne l'autre lecture : CHAQUE permutation separement, pour pouvoir
designer celle qui dimensionne reellement une barre et n'additionner que des
efforts qui coexistent. Il sert :

  - aux scripts d'etude `tests/scripts/canopee_elu_*.py` (via `tests/scripts/_elu_commun.py`) ;
  - a l'onglet Performances v2 de l'app (`app_old/server.py`) ;
  - a l'onglet Performances d'appv2 (`appv2/server.py`, via `commun/criteres.py`),
    qui lit en plus les contraintes DERIVEES par permutation
    (`contraintes_derivees_par_permutation`) pour le critere von Mises.

Aucune dependance a `bridge.py` (c'est l'inverse : `bridge._permutations`
delegue ici) — les fonctions recoivent l'objet resultat GSA deja obtenu.
"""
from __future__ import annotations

import numpy as np

# colonnes de sortie -> attribut .NET du Double6. Unites SI du modele : N pour
# les efforts, N.m pour les moments. L'ORDRE fait foi : c'est celui des 6
# colonnes des tableaux produits ici, et celui de `ec3.INDEX_COMPOSANTE`.
CHAMPS = (("Fx", "X"), ("Fy", "Y"), ("Fz", "Z"),
          ("Mxx", "XX"), ("Myy", "YY"), ("Mzz", "ZZ"))
COMPOSANTES = tuple(nom for nom, _ in CHAMPS)

# marqueur present sur une valeur unitaire mais absent d'une collection de
# permutations : "YY" pour un Double6 (efforts/deplacements), "AxialStressA"
# pour une contrainte, "VonMisesStress" pour une contrainte derivee.
MARQUEUR_DOUBLE6 = "YY"


def permutations_collection(coll, marqueur: str = MARQUEUR_DOUBLE6) -> list[list]:
    """Toutes les permutations d'un resultat le long d'un element.

    Un cas d'analyse renvoie une collection PLATE de valeurs (traitee comme
    une permutation unique) ; une combinaison renvoie une collection de
    permutations, chacune une collection de valeurs le long de l'element —
    pour une enveloppe (type ENVELOPPE ELU), il peut y en avoir plusieurs
    centaines. On distingue les deux via un attribut-marqueur present sur la
    valeur unitaire mais absent d'une collection.

    SEULE implementation de cette distinction : `bridge._permutations` delegue
    ici (l'inverse creerait un import circulaire).
    """
    if coll.Count == 0:
        return []
    if hasattr(coll[0], marqueur):
        return [list(coll)]
    return [list(p) for p in coll]


def efforts_par_permutation(resultat, selecteur: str,
                            positions: int = 5) -> dict[int, np.ndarray]:
    """{element: tableau (permutation, position, composante)} — AUCUNE reduction.

    `resultat` : CombinationCaseResult (ou AnalysisCaseResult) GSA, obtenu par
    `GsaModel._result("C47")`. `selecteur` : definition d'entites GSA ("all",
    "12", "1 2 3"...) — extraire par PAQUETS de barres amortit le cout de
    l'appel .NET (cf. `tests/canopee_elu_permutations.py`, ~0,05 s/barre sur la
    Canopee par paquets de 20).

    Les 6 composantes sont dans l'ordre de `COMPOSANTES` (Fx, Fy, Fz, Mxx,
    Myy, Mzz). Les valeurs illisibles restent NaN — a filtrer en aval.
    """
    data = resultat.Element1dForce(selecteur, positions, None)
    sortie: dict[int, np.ndarray] = {}
    for eid in data.Keys:
        perms = permutations_collection(data[eid])
        if not perms:
            continue
        npos = len(perms[0])
        a = np.empty((len(perms), npos, 6), dtype=np.float64)
        # acces direct aux attributs .NET (pas getattr par chaine) : c'est la
        # boucle chaude de l'extraction — permutations x positions x 6
        for ip, perm in enumerate(perms):
            for i in range(npos):
                v = perm[i]
                a[ip, i, 0] = v.X
                a[ip, i, 1] = v.Y
                a[ip, i, 2] = v.Z
                a[ip, i, 3] = v.XX
                a[ip, i, 4] = v.YY
                a[ip, i, 5] = v.ZZ
        sortie[eid] = a
    return sortie


def deplacements_par_permutation(resultat, selecteur: str,
                                 positions: int = 5) -> dict[int, np.ndarray]:
    """{element: tableau (permutation, position)} de Uz (fleche verticale, m,
    signee) — AUCUNE reduction. Pendant de `efforts_par_permutation` pour
    `Element1dDisplacement` : meme decoupage en permutations, donc la
    permutation `p` designe la meme sous-combinaison que dans un tableau
    d'efforts de la MEME combinaison GSA (les etiquettes de
    `libelles_permutations` valent pour les deux).

    Seul Uz est lu (flexion verticale, la fleche que compare le critere ELS
    du projet) : les 5 autres composantes du Double6 ne servent a personne
    ici, inutile de les extraire."""
    data = resultat.Element1dDisplacement(selecteur, positions, None)
    sortie: dict[int, np.ndarray] = {}
    for eid in data.Keys:
        perms = permutations_collection(data[eid])
        if not perms:
            continue
        npos = len(perms[0])
        a = np.empty((len(perms), npos), dtype=np.float64)
        for ip, perm in enumerate(perms):
            for i in range(npos):
                a[ip, i] = perm[i].Z
        sortie[eid] = a
    return sortie



def deplacements_noeuds_par_permutation(resultat, selecteur: str = "all"
                                        ) -> dict[int, np.ndarray]:
    """{noeud: tableau (permutation, 3)} de (Ux, Uy, Uz) en m — AUCUNE reduction.

    Pendant nodal de `deplacements_par_permutation` : `GsaModel.node_displacements`
    (via `bridge._table_noeud`) replie une combinaison enveloppe en deux lignes
    max/min par composante, ce qui melange des permutations differentes — sans
    objet pour un critere ELS qui compare TROIS noeuds entre eux (cf.
    `commun/els_noeuds.py`, criteres ELS_3pts_X), ou l'ecart n'a de sens que si
    les trois deplacements viennent de la MEME sous-combinaison.

    Un resultat nodal expose directement la valeur (Double6) pour un cas
    d'analyse ou une permutation unique, et une collection de Double6 (une par
    permutation) pour une enveloppe — pas d'echelon « le long de l'element »
    contrairement aux resultats 1D, d'ou la distinction faite ici plutot que
    par `permutations_collection`.

    L'indice de permutation designe la MEME sous-combinaison que dans un
    tableau d'efforts de la meme combinaison GSA (meme ordre d'expansion) : les
    etiquettes de `libelles_permutations` valent aussi pour ces tableaux.

    Les trois translations sont lues (les rotations ne servent a aucun critere
    ELS du projet) ; la direction comparee est choisie en aval.
    """
    data = resultat.NodeDisplacement(selecteur, None)
    sortie: dict[int, np.ndarray] = {}
    for nid in data.Keys:
        val = data[nid]
        perms = [val] if hasattr(val, MARQUEUR_DOUBLE6) else list(val)
        if not perms:
            continue
        a = np.empty((len(perms), 3), dtype=np.float64)
        for ip, v in enumerate(perms):
            a[ip, 0] = v.X
            a[ip, 1] = v.Y
            a[ip, 2] = v.Z
        sortie[nid] = a
    return sortie


#  contraintes DERIVEES (SEy, SEz, St, von Mises) — memes permutations, mais
#  lues telles que GSA les calcule, pas reconstruites depuis le torseur.
#  Utilisees par appv2 pour le critere von Mises : la contrainte equivalente
#  de GSA tient compte de la geometrie reelle de la section (fibres, cisaillement
#  de flexion), ce qu'un calcul depuis les seuls efforts ne peut pas reproduire.
CHAMPS_DERIVES = (("SEy", "ElasticShearStressSEy"),
                  ("SEz", "ElasticShearStressSEz"),
                  ("St", "TorsionalStressSt"),
                  ("VM", "VonMisesStress"))
COMPOSANTES_DERIVEES = tuple(nom for nom, _ in CHAMPS_DERIVES)

# marqueur de la valeur unitaire d'une contrainte derivee (cf. MARQUEUR_DOUBLE6)
MARQUEUR_DERIVE = "VonMisesStress"


def contraintes_derivees_par_permutation(resultat, selecteur: str,
                                        positions: int = 5) -> dict[int, np.ndarray]:
    """{element: tableau (permutation, position, composante)} — AUCUNE reduction.

    Pendant de `efforts_par_permutation` pour `Element1dDerivedStress` : les 4
    composantes sont dans l'ordre de `COMPOSANTES_DERIVEES` (SEy, SEz, St, VM),
    en Pa. Meme decoupage en permutations, donc meme indexation que les
    efforts : la permutation `p` designe la meme sous-combinaison dans les deux
    tableaux, et les etiquettes de `libelles_permutations` valent pour les deux.

    Les valeurs illisibles restent NaN — a filtrer en aval.
    """
    data = resultat.Element1dDerivedStress(selecteur, positions, None)
    sortie: dict[int, np.ndarray] = {}
    for eid in data.Keys:
        perms = permutations_collection(data[eid], MARQUEUR_DERIVE)
        if not perms:
            continue
        npos = len(perms[0])
        a = np.empty((len(perms), npos, 4), dtype=np.float64)
        for ip, perm in enumerate(perms):
            for i in range(npos):
                v = perm[i]
                a[ip, i, 0] = v.ElasticShearStressSEy
                a[ip, i, 1] = v.ElasticShearStressSEz
                a[ip, i, 2] = v.TorsionalStressSt
                a[ip, i, 3] = v.VonMisesStress
        sortie[eid] = a
    return sortie


def positions_pct(npos: int) -> list[float]:
    """[0, 25, 50, 75, 100] pour npos = 5 — positions le long de la barre, en %."""
    if npos <= 1:
        return [0.0]
    return [round(100.0 * i / (npos - 1), 1) for i in range(npos)]


# --------------------------------------------------------------------------
#  Etiquetage des permutations : quelle combinaison se cache derriere perm N ?
#
#  L'API ne le dit PAS. On le retrouve en decomposant la definition de
#  l'enveloppe ("C9 to C46"), en lisant separement chaque combinaison
#  enveloppee sur UNE barre temoin, et en verifiant que la concatenation dans
#  l'ordre de definition redonne, valeur par valeur, les permutations de
#  l'enveloppe. Prouve sur la Canopee (668 permutations, cf. tests/README.md).
# --------------------------------------------------------------------------
def _cid(jeton: str) -> int | None:
    """'C12' -> 12 ; tout le reste -> None."""
    jeton = jeton.strip().upper()
    if len(jeton) > 1 and jeton[0] == "C" and jeton[1:].isdigit():
        return int(jeton[1:])
    return None


def refs_enveloppe(definition: str) -> list[int]:
    """Combinaisons enveloppees par une definition du type 'C9 to C46'.

    Renvoie [] si la definition n'est PAS une simple liste de combinaisons
    (une expression avec coefficients ou 'or' n'est pas decomposable ainsi).
    """
    jetons = definition.replace(",", " ").split()
    ids: list[int] = []
    i = 0
    while i < len(jetons):
        if jetons[i].lower() == "to" and ids and i + 1 < len(jetons):
            fin = _cid(jetons[i + 1])
            if fin is None:
                return []
            ids.extend(range(ids[-1] + 1, fin + 1))
            i += 2
            continue
        c = _cid(jetons[i])
        if c is None:
            return []
        ids.append(c)
        i += 1
    return ids


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


def libelles_permutations(m, cid: int, element: int, nb_perm: int,
                          positions: int = 3, tolerance: float = 1e-6) -> dict:
    """Etiquette les permutations de la combinaison C`cid` ('C10p03', 'C9'...).

    Travaille sur UNE barre temoin (`element`), donc en quelques secondes meme
    sur un gros modele. `nb_perm` est le nombre de permutations deja mesure sur
    cette barre pour l'enveloppe.

    Renvoie {"libelles", "valide", "ecart_max", "combinaisons"} :
      - `libelles`   : une etiquette par permutation, dans l'ordre ;
      - `valide`     : la concatenation des sous-combinaisons redonne bien
                       l'enveloppe valeur par valeur — si faux, les etiquettes
                       sont generiques ('perm001') et ne doivent pas etre
                       affichees comme certaines ;
      - `combinaisons` : {libelle: {"combinaison", "nom", "definition"}}.

    Une combinaison sans permutations multiples (ou dont la definition n'est
    pas decomposable) retombe proprement sur des etiquettes generiques.
    """
    generique = {
        "libelles": [f"perm{p:03d}" for p in range(1, nb_perm + 1)],
        "valide": False, "ecart_max": None, "combinaisons": {},
    }

    combis = {c["combinaison"]: c for c in m.combination_cases()}
    cible = combis.get(cid)
    if cible is None:
        return generique

    # combinaison a permutation unique : son propre nom suffit
    if nb_perm <= 1:
        lib = f"C{cid}"
        return {"libelles": [lib], "valide": True, "ecart_max": 0.0,
                "combinaisons": {lib: {"combinaison": f"C{cid}",
                                       "nom": cible["nom"] or "",
                                       "definition": cible["definition"] or ""}}}

    refs = refs_enveloppe(cible["definition"] or "")
    if not refs:
        return generique

    env = efforts_par_permutation(m._result(f"C{cid}"), str(element), positions)
    env = env.get(element)
    if env is None or env.shape[0] != nb_perm:
        return generique

    libelles: list[str] = []
    infos: dict[str, dict] = {}
    morceaux: list[np.ndarray] = []
    for c in refs:
        sub = efforts_par_permutation(m._result(f"C{c}"), str(element), positions)
        a = sub.get(element)
        if a is None:
            return generique
        n = a.shape[0]
        for k in range(1, n + 1):
            lib = f"C{c}p{k:02d}" if n > 1 else f"C{c}"
            libelles.append(lib)
            infos[lib] = {"combinaison": f"C{c}",
                          "nom": (combis.get(c) or {}).get("nom") or "",
                          "definition": (combis.get(c) or {}).get("definition") or ""}
        morceaux.append(a)

    if len(libelles) != nb_perm:
        return generique

    attendu = np.concatenate(morceaux, axis=0)
    if attendu.shape != env.shape:
        return generique

    # comparaison valeur par valeur, robuste aux NaN et aux zeros
    ech = np.maximum(np.abs(attendu), np.abs(env))
    deux_nan = np.isnan(attendu) & np.isnan(env)
    un_nan = np.isnan(attendu) ^ np.isnan(env)
    with np.errstate(invalid="ignore", divide="ignore"):
        ecart = np.where(ech < 1e-9, 0.0, np.abs(attendu - env) / np.where(ech < 1e-9, 1.0, ech))
    ecart = np.where(deux_nan, 0.0, ecart)
    ecart = np.where(un_nan, np.inf, ecart)
    ecart_max = float(np.nanmax(ecart)) if ecart.size else 0.0
    if not (ecart_max <= tolerance):
        return {**generique, "ecart_max": ecart_max}

    return {"libelles": libelles, "valide": True, "ecart_max": ecart_max,
            "combinaisons": infos}
