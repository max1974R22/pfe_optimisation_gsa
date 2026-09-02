# -*- coding: utf-8 -*-
"""Types et briques partagees par flambement.py / deversement.py /
flexion_compression_yy.py / flexion_compression_zz.py.

Deux choses seulement :
  - les structures de donnees d'entree (`CaracteristiquesSection`,
    `ParametresBarre`, `Torseur`) ;
  - les formules qui servent a PLUSIEURS clauses du §6.3, pour qu'elles ne
    puissent pas diverger d'un fichier a l'autre : le coefficient de
    reduction chi [6.49] (flambement ET deversement), le tableau des facteurs
    d'imperfection alpha, le MAX du diagramme de moment ([6.61] ET [6.62]),
    et les facteurs kzz / kzy du Tableau B.1-B.2 (utilises par
    `flexion_compression_yy.facteur_kyz` ET `flexion_compression_zz`).

Toute formule propre a UNE clause reste dans le fichier de cette clause.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


# Onglets du classeur Predim ranges « H I » par Calcul!AH76
# (= IF(OR(AB2=1,AB2=2,AB2=3,AB2=4),"H I","Creux"), AB2 etant l'index de
# l'onglet de famille : 1=IPE, 2=IPN, 3=HE, 4=HD, 5=CHS, 6=RHS, 7=Custom).
# Tout le reste — CHS, RHS/SHS, Custom — est traite en section CREUSE pour le
# Tableau B.1 (cf. `facteur_kzz_creux`).
# W (AISC, catalogue W-AM) n'a pas d'onglet Predim (pas de traduction via
# ONGLET_PREDIM comme UB/UC -> HE/HD : catalogue dedie, cf. catalogues/W.csv)
# mais reste un profil en I/H lamine ordinaire — memes formules que HE/HD.
FAMILLES_I_H = ("IPE", "IPN", "HE", "HD", "W")


def drapeaux_famille(famille_predim: str) -> dict[str, bool]:
    """Les deux drapeaux de `CaracteristiquesSection` qui ne dependent que de
    l'ONGLET Predim de la section (`_ONGLET_PREDIM` d'appv2 : 'IPE', 'HE',
    'CHS', 'RHS'...), tels que le classeur les etablit :

      est_section_I_H         Calcul!AH76 — choisit la ligne « H I » ou
                              « Creux » du Tableau B.1 pour kzz
      deversement_sans_objet  Calcul!S80 = IF(AB2=5, 1, ...) — chi_LT force a 1
                              pour un CHS : un tube circulaire ne deverse pas
                              (inertie de flexion identique dans toutes les
                              directions, il n'y a pas d'axe faible)

    A passer tel quel a `CaracteristiquesSection(**drapeaux_famille(f), ...)`.
    """
    famille = (famille_predim or "").upper()
    return {"est_section_I_H": famille in FAMILLES_I_H,
            "deversement_sans_objet": famille == "CHS"}


@dataclass
class CaracteristiquesSection:
    """Geometrie et inerties d'un profil (mm / mm2 / mm3 / mm4 / mm6).

    Correspond aux colonnes du catalogue (`catalogues/IPE.csv` etc., en m —
    convertir en mm) ou aux cellules nommees du classeur (`Calcul!AC12:AC31`).
    """
    nom: str
    h: float             # hauteur, mm                    (Excel: h = AC12)
    b: float              # largeur, mm                    (Excel: b = AC13)
    tw: float             # epaisseur d'ame, mm             (Excel: tw = AC14)
    tf: float             # epaisseur de semelle, mm        (Excel: tf = AC15)
    A: float              # aire, mm2                       (Excel: A = AC16)
    Iy: float             # inertie flexion y-y, mm4         (Excel: Iy = AC17)
    Iz: float             # inertie flexion z-z, mm4         (Excel: Iz = AC22)
    Wyel: float           # module elastique y-y, mm3        (Excel: Wyel = AC18)
    Wypl: float           # module plastique y-y, mm3        (Excel: Wypl = AC19)
    Wzel: float           # module elastique z-z, mm3        (Excel: Wzel = AC23)
    Wzpl: float           # module plastique z-z, mm3        (Excel: Wzpl = AC24)
    iy: float             # rayon de giration y-y, mm         (Excel: AC20)
    iz: float             # rayon de giration z-z, mm         (Excel: AC25)
    It: float             # constante de torsion, mm4         (Excel: It = AC29)
    Iw: float             # constante de gauchissement, mm6    (Excel: Iw = AC30)
    courbe_flambement_y: str   # courbe EC3 tableau 6.2, axe y-y (Excel: AC33)
    courbe_flambement_z: str   # courbe EC3 tableau 6.2, axe z-z (Excel: AC34)
    # Tableau B.1 : ligne « H I » (True) ou « Creux » (False) pour kzz/kyz —
    # LU par `flexion_compression_zz.facteur_kzz` et `..._yy.facteur_kyz`.
    # (Excel: AH76, via AB81 = IF(AH76="h i", AE80, AF80).) Se deduit de
    # l'onglet Predim, cf. `drapeaux_famille`.
    # rayon de raccordement ame/semelle, mm (Excel: _r = AC32). Sert
    # UNIQUEMENT a la classification (§5.5) : c'est lui qui fixe la hauteur
    # droite de l'ame (c = h - 2r - 2tf) et la console de semelle
    # (c = 0.5b - 0.5tw - r). Nul pour un tube (le classeur y met la colonne
    # « r,internal » a vide) et sans effet : la classification des sections
    # creuses utilise c = h - 3t, sans rayon.
    r: float = 0.0
    est_section_I_H: bool = True
    # CHS : chi_LT force a 1, le deversement est sans objet (Excel: S80 =
    # IF(AB2=5, 1, ...)). Aussi le seul cas ou `b` peut etre nul — l'onglet
    # CHS du classeur laisse la colonne « b » vide —, ce qui rendrait
    # `courbe_deversement` indefini : cf. sa garde.
    deversement_sans_objet: bool = False

    @property
    def zg(self) -> float:
        """Distance point d'application de charge / centre de cisaillement,
        mm, utilisee dans Mcr (Annexe F). Defaut classeur = h/2 (Excel: P34
        = Q2/2, Q2 = AC12 = h) : charge appliquee au niveau de la semelle
        superieure."""
        return self.h / 2.0

    @property
    def courbe_deversement(self) -> str:
        """Courbe de deversement EC3 tableau 6.4 (methode generale),
        deduite de h/b (Excel: Q71 = IF(h/b<=2,"a","b")).

        `b` nul (onglet CHS du classeur, dont la colonne « b » est vide) :
        on renvoie "b" plutot que de diviser par zero — sans consequence, un
        CHS ayant `deversement_sans_objet` et donc chi_LT = 1 quoi qu'il
        arrive. Excel ne rencontre pas le probleme parce que S80 court-circuite
        Q71 avant de l'evaluer (IF paresseux).

        LIMITE PARTAGEE AVEC LE CLASSEUR : le Tableau 6.4 ne donne les courbes
        a/b (h/b <= 2 ou non) que pour les sections en I LAMINEES ; il range
        « autres sections » en courbe d. Le classeur applique quand meme la
        regle des I lamines aux tubes RHS/SHS — non conservatif pour eux. On
        le reproduit ici a l'identique pour rester comparable au classeur
        (cf. README.md, « Conformite a l'Eurocode »).
        """
        if not self.b:
            return "b"
        return "a" if self.h / self.b <= 2.0 else "b"


@dataclass
class ParametresBarre:
    """Conditions aux limites / materiau, propres a la barre verifiee."""
    fy: float              # limite elastique, MPa                (Excel: fy = AH2)
    E: float = 210_000.0   # module d'Young, MPa                   (Excel: E = W16)
    G: float = 80_769.0    # module de cisaillement, MPa           (Excel: G = W17)
    gamma_M0: float = 1.0  # (Excel: gM0 = W13)
    gamma_M1: float = 1.0  # (Excel: W14)
    Lcr_y_m: float = 0.0   # longueur de flambement y-y, m         (Excel: G15)
    Lcr_z_m: float = 0.0   # longueur de flambement z-z, m         (Excel: G16)
    L_deversement_m: float = 0.0   # longueur de deversement, m    (Excel: G17)
    k: float = 1.0         # facteur de longueur effective (Annexe F) (Excel: k = P30)
    kw: float = 1.0        # facteur de gauchissement (Annexe F)      (Excel: kw = P31)
    C1: float = 1.0        # facteur de moment (Annexe MCR)            (Excel: P32)
    C2: float = 0.0        # facteur de moment (Annexe MCR)            (Excel: P33)
    # True : utiliser les C1/C2 ci-dessus MEME quand le diagramme de moment
    # est fourni — c'est-a-dire se comporter EXACTEMENT comme le classeur
    # Predim, qui lit deux cellules saisies a la main (P32/P33) et n'a aucun
    # automatisme. Sert a isoler l'effet du calcul analytique de C1/C2 dans
    # `tests/scripts/comparaison_stabilite_excel_python.py` : a C1/C2 egaux,
    # tout ecart restant vient d'une AUTRE formule.
    # False (defaut) : C1/C2 calcules par `coefficients_c1_c2` des que le
    # diagramme est la (cf. `deversement.taux_deversement`).
    c1_c2_manuels: bool = False
    classe_section: int = 1    # 1 a 4 (Excel: classe = W3)
    # Choisit la formule de kzy (§6.3.3, Annexe B) : True -> Tableau B.2
    # (`facteur_kzy_torsion_sensible`), False -> Tableau B.1 (`flexion_
    # compression_zz.facteur_kzy`). Defaut True car c'est la configuration
    # REELLE et FIGEE du classeur Predim (Excel: P36 = "oui", jamais
    # decoche par appv2 -- absent de `COEFS_STABILITE`) : utiliser False
    # ici sans changer aussi la lecture du classeur produirait une
    # comparaison Python/Excel qui ne porte plus sur la meme formule.
    sensible_torsion: bool = True   # (Excel: P36)
    # Cmy/Cmz : valeurs de REPLI, utilisees SEULEMENT si le diagramme
    # correspondant (`Torseur.My_debut_kNm.../Mz_debut_kNm...`) n'est pas
    # fourni -- sinon `flexion_compression_yy/zz.py` les recalcule depuis le
    # diagramme via `coefficients_cm_b3.cm_tableau_b3` (Tableau B.3, meme
    # logique que le classeur, cf. `repartition_charge` ci-dessous).
    Cmy: float = 1.0       # facteur de moment equivalent, plan yy (tableau B.3)
    Cmz: float = 1.0       # facteur de moment equivalent, plan zz (tableau B.3)
    CmLT: float = 1.0      # facteur de moment equivalent pour deversement --
                            # UNIQUEMENT utilise par `facteur_kzy_torsion_sensible`
                            # (tableau B.2, cf. ci-dessous). Le classeur CALCULE
                            # une "vraie valeur" (Excel: AI47) mais s'en sert
                            # JAMAIS : la cellule reellement utilisee (AI48,
                            # "valeur fixe, utilise dans calcul") est figee a 1 --
                            # ne pas recalculer CmLT depuis un diagramme.
    # "uniforme" (defaut), "concentree" ou "noeuds_deplacables" -- categorie
    # de charge transversale, Tableau B.3 (Excel: P35, case a cocher
    # "Charge"). Determine la formule de Cmy/Cmz utilisee quand le diagramme
    # est fourni ; sans effet sinon (Cmy/Cmz manuels ci-dessus).
    repartition_charge: str = "uniforme"


@dataclass
class Torseur:
    """Sollicitations de calcul (convention classeur : N > 0 = traction)."""
    N_Ed_kN: float          # (Excel: P22)
    My_Ed_kNm: float        # (Excel: P25)
    Mz_Ed_kNm: float        # (Excel: P26)

    # Diagramme de My le long de la barre (debut/milieu/fin), optionnel.
    # (Excel: D31/D32/D33). Fourni -> `deversement.taux_deversement` calcule
    # C1/C2 via `coefficients_c1_c2.py` (§3.5 Annexe MCR) au lieu de lire
    # `ParametresBarre.C1`/`C2` (saisie manuelle par defaut). Egalement
    # utilise par `flexion_compression_yy/zz.py` : le terme My du [6.61]/
    # [6.62] est MAX(|My,debut|,|My,milieu|,|My,fin|), PAS My_Ed_kNm seul
    # (Excel : Q86/V96/V100 = MAXA(ABS(D31),ABS(D32),ABS(D33))/... — verifie
    # par lecture directe des formules du classeur).
    My_debut_kNm: float | None = None
    My_milieu_kNm: float | None = None
    My_fin_kNm: float | None = None

    # Diagramme de Mz le long de la barre (Excel: D35/D36/D37) — MEME role
    # que My_debut/milieu/fin pour le plan zz : terme Mz du [6.61]/[6.62] =
    # MAX(|Mz,debut|,|Mz,milieu|,|Mz,fin|) (Excel : V96/V100, meme MAXA),
    # ET source de Cmz (`coefficients_cm_b3.cm_tableau_b3`, Tableau B.3,
    # Excel : AL64 — bloc identique a celui de Cmy/AL51, applique a D35:D37
    # au lieu de D31:D33). Sans ce diagramme, Cmz reste la valeur manuelle
    # `ParametresBarre.Cmz` (defaut 1.0) et le terme Mz retombe sur
    # Mz_Ed_kNm seul — comportement degrade, pas celui du classeur.
    Mz_debut_kNm: float | None = None
    Mz_milieu_kNm: float | None = None
    Mz_fin_kNm: float | None = None


def lambda_1(E: float, fy: float) -> float:
    """Elancement de reference §6.3.1.3(1), lambda_1 = pi*sqrt(E/fy).
    (Excel: P58 = PI()*SQRT(E/fy))"""
    return math.pi * math.sqrt(E / fy)


def coefficient_reduction_chi(lambda_bar: float, alpha: float) -> float:
    """Coefficient de reduction chi, formule [6.49], commun au flambement
    (§6.3.1.2) et au deversement (§6.3.2.2) :
    Phi = 0.5*(1+alpha*(lambda_bar-0.2)+lambda_bar^2)
    chi = min(1/(Phi+sqrt(Phi^2-lambda_bar^2)), 1)
    (Excel : P62/P63 pour le flambement y-y, U62/U63 pour z-z,
    S78/S80 pour le deversement)"""
    phi = 0.5 * (1 + alpha * (lambda_bar - 0.2) + lambda_bar ** 2)
    # max(...,0) : garde-fou numerique (Phi^2-lambda_bar^2 peut friser 0 par
    # arrondi flottant a lambda_bar tres faible ; le classeur ne s'en soucie
    # pas car Excel tolere les erreurs #NUM! silencieusement dans ce cas)
    chi = 1.0 / (phi + math.sqrt(max(phi ** 2 - lambda_bar ** 2, 0.0)))
    return min(chi, 1.0)


# Tableau 6.1 EC3 — facteur d'imperfection alpha par courbe de flambement.
# (Excel : plage AB42:AC46)
ALPHA_COURBES: dict[str, float] = {"a0": 0.13, "a": 0.21, "b": 0.34, "c": 0.49, "d": 0.76}


def moment_max_diagramme(M_debut: float | None, M_milieu: float | None,
                         M_fin: float | None, M_repli: float) -> float:
    """MAX(|M_debut|,|M_milieu|,|M_fin|) si le diagramme 3 points est
    fourni (cas normal), sinon |M_repli| (valeur ponctuelle seule -- mode
    degrade, cf. `Torseur.My_debut_kNm`/`Mz_debut_kNm`). Partagee par
    `flexion_compression_yy.py` et `flexion_compression_zz.py` (meme calcul
    pour le terme My et pour le terme Mz du [6.61]/[6.62]).

    (Excel : MAXA(ABS(D31),ABS(D32),ABS(D33)) pour My, MAXA(ABS(D35),
    ABS(D36),ABS(D37)) pour Mz -- V96/V100/Q86)"""
    if M_debut is not None and M_milieu is not None and M_fin is not None:
        return max(abs(M_debut), abs(M_milieu), abs(M_fin))
    return abs(M_repli)


def facteur_kzz_I_H(Cmz: float, lambda_bar_z: float, n_z: float, classe3: bool) -> float:
    """kzz — Tableau B.1, Annexe B, membre non sensible aux deformations de
    torsion, SECTION EN I OU H (AH76 = "H I"). Partagee par
    `flexion_compression_yy.facteur_kyz` (kyz = 0.6*kzz ou kzz selon la
    classe) et `flexion_compression_zz.facteur_kzz` (= kzz directement),
    pour eviter de dupliquer la formule dans les deux fichiers.

    classe 1/2 : Cmz*[1+(2*lambda_bar_z-0.6)*nZ] <= Cmz*[1+1.4*nZ]  (Excel: AE80)
    classe 3/4 : Cmz*[1+0.6*lambda_bar_z*nZ] <= Cmz*[1+0.6*nZ]      (Excel: AC81)
    """
    if classe3:
        return min(Cmz * (1 + 0.6 * lambda_bar_z * n_z), Cmz * (1 + 0.6 * n_z))
    return min(Cmz * (1 + (2 * lambda_bar_z - 0.6) * n_z), Cmz * (1 + 1.4 * n_z))


def facteur_kzy_torsion_sensible(CmLT: float, lambda_bar_z: float, N_Ed_kN: float,
                                 Nb_Rd_z_kN: float, classe3: bool) -> float:
    """kzy — Tableau B.2, Annexe B, membre SENSIBLE aux deformations de
    torsion (AH76 = section ouverte I/H). C'est la configuration REELLE du
    classeur Predim : `P36` ("sensible aux deformations par torsion") vaut
    "oui" par defaut (jamais decoche par appv2, absent de `COEFS_STABILITE`)
    -- verifie par lecture directe des formules (AH80/AH81, choisies par
    AB80/AC80 = IF(P36="non", <tableau B.1>, <ceci>)). Le Tableau B.1
    (`facteur_kzy` de `flexion_compression_yy.py`) n'est utilise QUE si P36
    est explicitement mis a "non", ce qu'aucun appelant ne fait aujourd'hui.

    `CmLT` : facteur de moment equivalent pour le deversement -- le classeur
    le calcule (AI47, "vraie valeur") mais utilise TOUJOURS une valeur FIXE
    de 1.0 dans le calcul (AI48, "valeur fixe, utilise dans calcul" : Excel
    ne branche jamais sur AI47) ; `ParametresBarre.CmLT` vaut 1.0 par defaut
    pour la meme raison -- ne PAS le recalculer depuis un diagramme.

    classe 1/2 (Excel : AH80) :
      bornes = 1 - (0.1*lambda_bar_z*|N_Ed|) / [(CmLT-0.25)*Nb,Rd,z]   (AM78)
             et 1 - (0.1*|N_Ed|) / [(CmLT-0.25)*Nb,Rd,z]                (AM80)
      lambda_bar_z<0.4 : kzy = MIN(0.6+lambda_bar_z, AM78)
      sinon            : kzy = MAX(AM78, AM80)

    classe 3/4 (Excel : AH81, coefficient 0.05 au lieu de 0.1) :
      kzy = MAX(1 - (0.05*lambda_bar_z*|N_Ed|)/[(CmLT-0.25)*Nb,Rd,z],
                1 - (0.05*|N_Ed|)/[(CmLT-0.25)*Nb,Rd,z])                (AQ78/AQ80)
    """
    base = (CmLT - 0.25) * Nb_Rd_z_kN
    if classe3:
        borne_lambda = 1 - 0.05 * lambda_bar_z * abs(N_Ed_kN) / base   # AQ78
        borne_fixe = 1 - 0.05 * abs(N_Ed_kN) / base                    # AQ80
        return max(borne_lambda, borne_fixe)
    borne_lambda = 1 - 0.1 * lambda_bar_z * abs(N_Ed_kN) / base        # AM78
    borne_fixe = 1 - 0.1 * abs(N_Ed_kN) / base                         # AM80
    if lambda_bar_z < 0.4:
        return min(0.6 + lambda_bar_z, borne_lambda)                   # AH80
    return max(borne_lambda, borne_fixe)                               # AH80


def facteur_kzz_creux(Cmz: float, lambda_bar_z: float, n_z: float, classe3: bool) -> float:
    """kzz — Tableau B.1, section CREUSE (RHS/SHS/CHS, AH76 = "Creux").

    Utilise pour TOUTE section qui n'est pas dans un onglet IPE/IPN/HE/HD du
    classeur (cf. `drapeaux_famille`) — c'est-a-dire la majorite des barres
    des modeles du projet, qui sont des treillis tubulaires. Excel: AF80
    (classe 1/2 seulement — la branche classe 3/4 est identique a
    `facteur_kzz_I_H` : AC81 ne distingue pas section I/H vs creuse).

    Ce module a longtemps appele `facteur_kzz_I_H` pour tout le monde, ce qui
    surestimait kzz (donc le taux [6.61]/[6.62]) sur les tubes : a
    lambda_bar_z = 1 et n = 0,3, le coefficient passe de 1+(2*1-0.6)*0.3 =
    1,42 (I/H) a 1+(1-0.2)*0.3 = 1,24 (creux), soit 15 % d'ecart sur le seul
    terme Mz. Corrige le 01/09/2026.

    classe 1/2 : Cmz*[1+(lambda_bar_z-0.2)*nZ] <= Cmz*[1+0.8*nZ]  (Excel: AF80)
    """
    if classe3:
        return facteur_kzz_I_H(Cmz, lambda_bar_z, n_z, classe3=True)
    return min(Cmz * (1 + (lambda_bar_z - 0.2) * n_z), Cmz * (1 + 0.8 * n_z))
