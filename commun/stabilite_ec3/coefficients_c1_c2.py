# -*- coding: utf-8 -*-
"""Calcul analytique des coefficients C1 et C2 du moment critique de
deversement Mcr (§2 de l'Annexe MCR, NF EN 1993-1-1/NA), via les formules
du §3.5 "Formulations analytiques des coefficients C1 et C2 (alternative aux
Figures 3 et 4)" — evite la lecture d'abaque (jusqu'ici saisie manuelle dans
`ParametresBarre.C1`/`C2`, cf. `deversement.py`).

Domaine de validite (§3.4/3.5 de l'annexe) : barre soumise a une
COMBINAISON de moments d'extremite (M, psi*M) et d'une charge UNIFORMEMENT
REPARTIE q (Figure 2 de l'annexe) — kz = kw = 1. Ne couvre PAS les charges
ponctuelles (le Tableau 2 de l'annexe donne des valeurs figees pour ces cas,
non deductibles de ce paragraphe).

Parametres du diagramme de moment (§3.4) :
  psi = rapport des moments d'extremite, -1 <= psi <= +1 (+1 = moment uniforme)
  mu  = qL²/(8M), rapport du moment "isostatique" du a q au moment d'extremite M
        (M = valeur ABSOLUE du moment d'extremite maximal)
  mu > 0 si M et q flechissent la barre dans le meme sens (convention Figure 2)

Formules validees numeriquement (cf. conversation) contre :
  - Tableau 1 (moments d'extremite seuls, mu=0) : 9 points, ecart < 1.5 %
  - Tableau 2, ligne "encastre-encastre + charge uniforme" (psi=+1, mu=-1.5) :
    C1 calcule 2.61 vs tableau 2.57 (+1.7 %), C2 calcule 1.56 vs tableau 1.55
    (+0.6 %) — coherent avec le caractere APPROCHE de la formule (le §3.2
    donne deja une formule "approchee" alternative pour le cas plus simple
    mu=0, memes ordres de grandeur d'ecart).
"""
from __future__ import annotations

import math

# valeurs figees si pas de moment d'extremite (charge q seule) ou si le
# moment d'extremite est negligeable devant l'effet de la charge repartie
# (Notes du §3.5, apres les encadres C1 = m*C10 et C2 = 0,398 r2 |mu| C10)
C1_CHARGE_SEULE = 1.127
C2_CHARGE_SEULE = 0.454
MU_SEUIL_CHARGE_PREPONDERANTE = 20.0


def parametres_diagramme(M_debut_kNm: float, M_milieu_kNm: float,
                         M_fin_kNm: float) -> tuple[float | None, float, float]:
    """Deduit (psi, mu, M) d'un diagramme de moment a 3 points (debut/milieu/
    fin, meme convention de signe que `Calcul!D31:D33` du classeur — moment
    le long de la barre, PAS un moment relatif a chaque extremite), en
    supposant que ce diagramme resulte d'une combinaison moments d'extremite
    + charge uniformement repartie (parabole, Figure 2) :

      M(x) = M_debut + (M_fin-M_debut)*(x/L) + 4*(M_milieu-M_lineaire_milieu)*(x/L)*(1-x/L)

    M_ref = l'extremite de plus grand moment (en valeur absolue) ; M = |M_ref|
    (definition du §3.4). psi et mu sont normalises par le signe de M_ref,
    pour que M soit bien positif comme l'exige la definition du paragraphe.

    Renvoie (None, 0.0, 0.0) si M_debut = M_fin = 0 (pas de moment
    d'extremite : charge q seule, hors du domaine — cf. `C1_C2_depuis_diagramme`).
    """
    if abs(M_debut_kNm) >= abs(M_fin_kNm):
        M_ref, M_autre = M_debut_kNm, M_fin_kNm
    else:
        M_ref, M_autre = M_fin_kNm, M_debut_kNm

    if M_ref == 0.0:
        return None, 0.0, 0.0

    signe = 1.0 if M_ref > 0 else -1.0
    M = abs(M_ref)
    psi = M_autre * signe / M
    M_udl_milieu = M_milieu_kNm - (M_debut_kNm + M_fin_kNm) / 2.0   # = qL²/8, signe global
    mu = M_udl_milieu * signe / M
    return psi, mu, M


def coefficients_C1_C2(psi: float, mu: float) -> tuple[float, float]:
    """C1, C2 — §3.5 de l'Annexe MCR, formule generale (mu != 0, |mu| <= 20).

    Ne pas appeler directement avec mu=0 issu d'une charge q seule (M=0) :
    dans ce cas M est indetermine, utiliser `C1_C2_depuis_diagramme` qui gere
    l'aiguillage. mu=0 avec M != 0 (moments d'extremite seuls, pas de charge
    repartie) EST valide ici (cf. Tableau 1, ecart < 1.5 % verifie).
    """
    beta = psi + 4 * mu - 1
    gamma = beta ** 2 - 8 * mu

    a = 0.5 * (1 + beta) + 0.1413364 * gamma - 0.6960364 * beta * mu + 0.9126223 * mu ** 2
    b = 0.5 * (1 + beta) + 0.1603341 * gamma - 0.9240091 * beta * mu + 1.4281556 * mu ** 2
    c = -0.1801266 * beta - 0.0900633 * gamma + 0.5940757 * beta * mu - 0.9352904 * mu ** 2
    A = a * b - c ** 2
    B = 2 * a + b / 2

    d1, e1 = abs(mu + 0.52 * (1 + psi)), 0.3
    f1 = 0.88 - 0.04 * psi
    r1 = 1.0 if d1 > e1 else f1 + d1 * (1 - f1) / e1

    if mu == 0.0:
        # limite mu->0 : le diagramme est lineaire (pas de charge repartie),
        # le moment maximal le long de la barre est M lui-meme -> m = 1
        m = 1.0
    else:
        xi = 0.5 - (1 - psi) / (8 * mu)
        xi = min(max(xi, 0.0), 1.0)
        m = max(abs(1 - xi * (1 - psi) + 4 * mu * xi * (1 - xi)), 1.0)

    C10 = r1 * math.sqrt((B - math.sqrt(B ** 2 - 4 * A)) / (2 * A))
    C1 = m * C10

    d2, e2 = abs(0.425 + mu + 0.675 * psi), 0.65 - 0.35 * psi
    f2 = 0.81 + 0.05 * psi
    r2 = 1.0 if d2 > e2 else f2 + d2 * (1 - f2) / e2
    C2 = 0.398 * r2 * abs(mu) * C10

    return C1, C2


def C1_C2_depuis_diagramme(M_debut_kNm: float, M_milieu_kNm: float,
                           M_fin_kNm: float) -> tuple[float, float]:
    """C1, C2 directement depuis le diagramme de moment a 3 points (fonction
    a utiliser depuis `deversement.taux_deversement`) : aiguille vers le cas
    "charge q seule" (C1=1,127 / C2=0,454) si les deux extremites sont a
    moment nul ou si |mu| > 20, sinon applique la formule generale."""
    psi, mu, _M = parametres_diagramme(M_debut_kNm, M_milieu_kNm, M_fin_kNm)
    if psi is None or abs(mu) > MU_SEUIL_CHARGE_PREPONDERANTE:
        return C1_CHARGE_SEULE, C2_CHARGE_SEULE
    return coefficients_C1_C2(psi, mu)
