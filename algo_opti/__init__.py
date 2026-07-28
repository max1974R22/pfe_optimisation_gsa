# -*- coding: utf-8 -*-
"""
Algorithmes d'optimisation de la STRUCTURE GLOBALE (une section par famille
de barres). Chaque algorithme est un module de ce dossier qui expose :

    LIBELLE     : nom court affiche dans le menu deroulant de la page ;
    DESCRIPTION : une phrase (infobulle) ;
    optimiser(modele: Path, cfg: dict, log=...) -> dict
                  meme contrat que l'ancien optimiser_global de
                  scripts/dimensionner.py (cfg["groupes"], cfg["continuite"],
                  criteres...) ; renvoie {"groupes": [...], "masse_totale_kg",
                  "passes", "analyses", "converge", ...}.

Pour ajouter un algorithme : creer le module (ex. recuit_simule.py), puis
l'enregistrer dans ALGOS ci-dessous. La page le proposera automatiquement
(menu deroulant alimente par /api/etat).
"""
from . import brut_force
from . import genetique
from . import escalade

ALGOS = {
    "escalade": {
        "libelle": escalade.LIBELLE,
        "description": escalade.DESCRIPTION,
        "optimiser": escalade.optimiser,
    },
    "brut_force": {
        "libelle": brut_force.LIBELLE,
        "description": brut_force.DESCRIPTION,
        "optimiser": brut_force.optimiser,
    },
    "genetique": {
        "libelle": genetique.LIBELLE,
        "description": genetique.DESCRIPTION,
        "optimiser": genetique.optimiser,
    },
}

ALGO_DEFAUT = "escalade"
