# -*- coding: utf-8 -*-
"""
Algorithme « force brute » (avec passes) — premier algorithme du dossier
algo_opti/ :

    force brute par famille (toutes les sections de la serie essayees, une
    analyse GSA par essai) + descente par coordonnees (on repasse sur les
    familles jusqu'a stabilite des affectations), contrainte de continuite
    optionnelle entre familles adjacentes, et — optionnellement — contrainte
    de stabilite EC3 (§6.3) verifiee via le classeur Predim.

STRATEGIE STABILITE (cfg["stabilite"]) : les appels au classeur Excel sont
lents, on ne les met donc PAS dans la boucle interne d'essais de sections. A
la place, une BOUCLE EXTERNE :
    1. descente par coordonnees sur les seuls efforts (contrainte GSA +
       fleche) — rapide, aucun appel Excel ;
    2. verification de la stabilite EC3 de la barre gouvernante de chaque
       famille a l'etat converge (une passe Excel, une barre par famille) ;
    3. pour chaque famille qui ne passe pas, on interdit sa section courante et
       toutes les plus legeres (plafond d'indice abaisse -> section au moins
       d'un cran plus grosse), puis on relance la descente sur les efforts. On
       repete jusqu'a satisfaction (ou plafond a la plus grosse section).
Le verificateur Excel est injecte par l'appelant via cfg["stab_verifier"].

Les briques d'evaluation et de mise en forme sont mutualisees dans
algo_opti/_commun.py (memes sorties que l'algorithme genetique).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from gsa_bridge.bridge import GsaModel
from dimensionner import DimensionnementError, serie_sections
from . import _commun

LIBELLE = "Force brute"
DESCRIPTION = ("Toutes les sections de la série essayées famille par famille "
               "(une analyse GSA par essai), passes répétées jusqu'à "
               "stabilité des affectations (descente par coordonnées). "
               "Option stabilité EC3 : boucle externe efforts → vérification "
               "Predim → sections plus grosses si besoin.")


def _index_serie(serie: list[dict], profil_modele: str) -> int | None:
    """Indice, dans la serie, de la section correspondant a un profil GSA du
    modele (ex. 'CAT IPE-AM IPE240 20170912' -> section 'IPE240'), ou None si
    la section existante n'appartient pas a la serie optimisee."""
    parts = (profil_modele or "").split()
    nom = parts[2] if len(parts) >= 3 and parts[0] == "CAT" else (parts[-1] if parts else "")
    for idx, s in enumerate(serie):
        if s["nom"] == nom:
            return idx
    return None


def optimiser(modele: Path, cfg: dict, log=lambda s: None) -> dict:
    """Optimisation GLOBALE : une section optimale PAR FAMILLE de barres.

    cfg["groupes"] = [{"elements": [ids], "libelle": str}, ...] (les familles),
    DANS L'ORDRE d'optimisation voulu (l'ordre change les resultats : la
    descente parcourt les familles dans cet ordre). Force brute par famille :
    chaque famille recoit une propriete de section dediee, puis, famille par
    famille, TOUTES les sections de la serie sont essayees — analyse GSA a
    chaque essai, les autres familles restant a leur affectation courante — et
    la plus legere qui passe (ELU sur la barre la plus sollicitee de la famille
    + fleche globale) est retenue. On repasse sur toutes les familles jusqu'a
    stabilite des affectations (descente par coordonnees).

    cfg["continuite"] (bool) : deux familles MITOYENNES ne peuvent avoir qu'UNE
    section d'ecart dans la serie. cfg["stabilite"] (bool) + cfg["stab_verifier"]
    (callable) : contrainte de stabilite EC3 en boucle externe (cf. module).

    Renvoie {"groupes": [ligne par famille], "masse_totale_kg", "passes",
    "analyses", "converge", "stabilite", "boucles_stabilite", "historique", ...}.
    `historique` = [{"masse", "ok"}] par configuration essayee (pour le graphe
    de progression cote interface).
    """
    serie = serie_sections(cfg)                 # triee par masse DECROISSANTE
    n = len(serie)
    groupes = cfg.get("groupes") or []
    if not groupes:
        raise DimensionnementError("Optimisation globale : aucune famille de barres.")
    continuite = bool(cfg.get("continuite"))
    max_passes = int(cfg.get("max_passes", 40 if continuite else 8))

    stabilite = bool(cfg.get("stabilite")) and callable(cfg.get("stab_verifier"))
    stab_verifier = cfg.get("stab_verifier")
    taux_stab_max = float(cfg.get("critere_stabilite", {}).get("coefficient", 1.0))
    max_boucles = int(cfg.get("max_boucles_stabilite", 6))

    analyses = 0
    historique: list[dict] = []
    with GsaModel(modele) as m:
        m.check_analysis_setup()
        ctx = _commun.preparer_contexte(m, cfg)
        _commun.verifier_familles(groupes, ctx["infos_elem"])
        refs = ctx["refs"]
        sigma_lim, fleche_lim = ctx["sigma_lim"], ctx["fleche_lim"]
        infos_elem = ctx["infos_elem"]
        adjacentes = _commun.adjacence(groupes, infos_elem)

        props = [m.section_dediee(g["elements"], nom=f"Optim {g['libelle']}")
                 for g in groupes]

        # --- configuration de depart. Par defaut « maxee » : toutes les familles
        # sur la plus grosse section (serie[0]) — depart faisable, robuste. Si
        # depart_max est faux, chaque famille demarre de sa section EXISTANTE
        # dans le modele (situee dans la serie) ; une section existante hors
        # serie retombe sur la plus grosse.
        depart_max = bool(cfg.get("depart_max", True))
        secs_modele = ({} if depart_max
                       else {s["section"]: s for s in m.sections()})
        affect = []
        for gi, p in enumerate(props):
            idx = 0
            if not depart_max:
                trouve = _index_serie(serie, secs_modele.get(p, {}).get("profil", ""))
                if trouve is None:
                    log(f"{groupes[gi]['libelle']} : section existante hors série "
                        f"{serie[0]['nom']}… → départ sur la plus grosse")
                else:
                    idx = trouve
            affect.append(idx)
            m.set_section_profile(p, serie[idx]["profil_gsa"])
        # plafond d'indice par famille (contrainte de stabilite) : une famille
        # ne peut pas descendre PLUS LEGER que plafond[gi] (indice croissant =
        # section plus legere). n-1 = aucune contrainte.
        plafond = [n - 1] * len(groupes)

        def evaluer_essai(gi: int, idx: int) -> list[dict]:
            """Details PAR FAMILLE (C1/C2, taux ELU/ELS) apres analyse, la
            famille gi etant a l'indice idx et les autres a leur affectation
            courante — UNE analyse GSA, TOUTES les familles evaluees d'un
            coup (cf. _commun.evaluer_etat, rapide : C1/C2 depuis les seuls
            efforts, pas les tables de contraintes GSA). Necessaire pour que
            « faisable » (cf. plus bas) reflete l'etat REEL de la structure
            ENTIERE a cet instant, pas seulement de la famille en cours
            d'essai (sinon le graphe de progression peut afficher un point
            « faisable » alors qu'une autre famille est toujours en defaut)."""
            nonlocal analyses
            sections_tmp = [serie[affect[j]] for j in range(len(groupes))]
            sections_tmp[gi] = serie[idx]
            details, _ = _commun.evaluer_etat(m, groupes, ctx, sections_tmp)
            analyses += 1
            return details

        def masse_essai(gi: int, idx: int) -> float:
            """Masse totale de la structure avec la famille gi placee a idx."""
            tmp = list(affect)
            tmp[gi] = idx
            return _commun.masse_totale(tmp, groupes, serie, infos_elem)

        def config_essai(gi: int, idx: int) -> dict[str, str]:
            """{libelle famille -> section} avec gi placee a idx, les autres a
            leur affectation courante — snapshot pour le graphe de progression
            (survol d'un point, cf. app.js::afficherProgression)."""
            tmp = list(affect)
            tmp[gi] = idx
            return {groupes[j]["libelle"]: serie[tmp[j]]["nom"] for j in range(len(groupes))}

        def descente(numero_boucle: int) -> tuple[bool, int, set[int]]:
            """Descente par coordonnees sur les EFFORTS seuls (contrainte +
            fleche), en respectant continuite et plafonds de stabilite. Mute
            `affect` et l'etat du modele ; renvoie (converge, passes, echecs)."""
            for gi in range(len(groupes)):
                if affect[gi] > plafond[gi]:
                    affect[gi] = plafond[gi]
                    m.set_section_profile(props[gi], serie[affect[gi]]["profil_gsa"])
            echecs: set[int] = set()
            converge = False
            passe = 0
            for passe in range(1, max_passes + 1):
                avant = list(affect)
                for gi, g in enumerate(groupes):
                    lo, hi = 0, plafond[gi]
                    if continuite and adjacentes[gi]:
                        vois = [affect[j] for j in adjacentes[gi]]
                        lo = max(0, max(vois) - 1)
                        hi = min(hi, min(vois) + 1)
                    lo = min(lo, hi)   # stabilite prime sur continuite si conflit
                    meilleure = None   # indice le plus leger qui passe
                    for idx in range(lo, hi + 1):
                        m.set_section_profile(props[gi], serie[idx]["profil_gsa"])
                        log(f"boucle {numero_boucle} · passe {passe} · {g['libelle']} : "
                            f"essai {serie[idx]['nom']} ({idx - lo + 1}/{hi - lo + 1})")
                        details_essai = evaluer_essai(gi, idx)
                        d = details_essai[gi]
                        faisable = d["sigma"] <= sigma_lim and d["uz_famille"] <= fleche_lim
                        toutes_ok = all(dd["sigma"] <= sigma_lim and dd["uz_famille"] <= fleche_lim
                                       for dd in details_essai)
                        historique.append({"masse": round(masse_essai(gi, idx), 1),
                                           "ok": toutes_ok, "config": config_essai(gi, idx)})
                        if faisable:
                            meilleure = idx  # serie decroissante : le dernier OK = le plus leger
                    if meilleure is None:
                        echecs.add(gi)
                        meilleure = lo       # repli : la plus grosse admissible
                    else:
                        echecs.discard(gi)
                    affect[gi] = meilleure
                    m.set_section_profile(props[gi], serie[meilleure]["profil_gsa"])
                log(f"boucle {numero_boucle} · passe {passe} : " + ", ".join(
                    f"{g['libelle']}={serie[affect[i]]['nom']}" for i, g in enumerate(groupes)))
                if affect == avant:
                    converge = True
                    break
            return converge, passe, echecs

        log(f"Optimisation globale [force brute] : {len(groupes)} famille(s), "
            f"serie {serie[0]['nom']} -> {serie[-1]['nom']} ({n} sections), "
            f"depart {'sections max' if depart_max else 'config existante'}, "
            f"continuite {'ON' if continuite else 'OFF'}, "
            f"stabilite {'ON' if stabilite else 'OFF'}")

        # --- boucle externe : efforts, puis stabilite, puis efforts a nouveau
        converge = False
        passe = 0
        echecs: set[int] = set()
        details: list[dict] = []
        uz_f = 0.0
        stab_par_famille: dict[int, dict] = {}
        boucle = 0
        for boucle in range(1, (max_boucles if stabilite else 1) + 1):
            converge, passe, echecs = descente(boucle)
            details, uz_f = _commun.evaluer_etat(
                m, groupes, ctx, [serie[affect[gi]] for gi in range(len(groupes))])
            analyses += 1
            if not stabilite:
                break

            barres = [{"cle": d["gi"], **d["barre_gouvernante"]}
                      for d in details if d["barre_gouvernante"]]
            log(f"boucle {boucle} : verification stabilite EC3 de "
                f"{len(barres)} barre(s) gouvernante(s) (classeur Predim)…")
            stab_par_famille = stab_verifier(barres, m.materials()) if barres else {}

            change = False
            for gi in range(len(groupes)):
                r = stab_par_famille.get(gi)
                taux = r.get("taux_stabilite") if r else None
                if taux is not None and taux > taux_stab_max and plafond[gi] > 0:
                    if affect[gi] <= plafond[gi]:
                        plafond[gi] = min(plafond[gi], affect[gi]) - 1
                        change = True
                        log(f"boucle {boucle} : {groupes[gi]['libelle']} instable "
                            f"(taux {taux}) -> section plus grosse "
                            f"(plafond {serie[plafond[gi]]['nom']})")
            if not change:
                log(f"boucle {boucle} : stabilite satisfaite (ou plafond atteint)")
                break

        # --- mise en forme des resultats (une ligne par famille)
        lignes = [
            _commun.construire_ligne(
                groupes[d["gi"]], serie[affect[d["gi"]]], d, ctx,
                echec=d["gi"] in echecs, stabilite=stabilite,
                stab=stab_par_famille.get(d["gi"]) if stabilite else None,
                taux_stab_max=taux_stab_max)
            for d in details
        ]

    return {
        "groupes": lignes,
        "portee_m": ctx["L"],
        "fleche_ELS_mm": round(uz_f * 1000, 2),
        "fleche_limite_mm": round(fleche_lim * 1000, 2),
        "taux_ELS": round(uz_f / fleche_lim, 3),
        "masse_totale_kg": round(sum(l["masse_kg"] for l in lignes), 1),
        "sigma_limite_Pa": sigma_lim,
        "refs": refs,
        "passes": passe,
        "analyses": analyses,
        "converge": converge,
        "continuite": continuite,
        "depart_max": depart_max,
        "stabilite": stabilite,
        "boucles_stabilite": boucle if stabilite else 0,
        "historique": historique,
    }
