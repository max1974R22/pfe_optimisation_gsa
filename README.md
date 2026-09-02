# PFE V0 — Automatisation GSA / Excel (vérification de poutres acier)

Croiser le modèle Oasys GSA et le classeur Excel de prédimensionnement pour
automatiser la vérification de poutres acier (EC3). Le pont GSA travaille
**in-process** (API .NET `GsaAPI.dll` via pythonnet) et **toujours sur une
copie** : les fichiers `.gwb` maîtres ne sont jamais modifiés.

## Arborescence 

| Dossier | Rôle |
|---|---|
| `GSA_model/` | Modèles GSA maîtres (`.gwb`). |
| `appv2/` | **L'interface web du projet** (`venv\Scripts\python.exe appv2\server.py` → http://localhost:8767), par GROUPES de barres. Page en deux colonnes : **entrées à gauche** (5 onglets — Résumé, Critères ELU/ELS/instabilité, Performances, Optimisation, Opt. globale), **sorties à droite** (2 onglets — Vue 3D, Détail optimisation), chargement du modèle dans le bandeau. Sa propre doc : `appv2/README.md`. Son registre d'algorithmes (`ALGOS_GLOBAUX`) est distinct de `commun/algo_opti` ci-dessous : il travaille sur la maille « propriété de section », pas sur `config/familles.json`. |
| `app_old/` | **Première interface web, archivée** (`venv\Scripts\python.exe app_old\server.py` → http://localhost:8765). Onglets : Modèle, Performances, **Performances v2** (combinaison dimensionnante, voir plus bas), Optimisation. Conservée pour l'onglet Performances v2 et ses cartes barres × permutations, qu'`appv2/` n'a pas repris. |
| `commun/` | **Tout ce qui est partagé** entre l'app, les scripts et les tests — voir ci-dessous. |
| `commun/gsa_bridge/` | Pont GSA : `GsaModel` (lecture des tables + résultats, swap de section) + `permutations.py` (permutations d'une enveloppe **non réduites**, et leur étiquetage `C10p03`). |
| `commun/excel_bridge/` | Pont Excel (classeur Predim, xlwings/COM) : `predim.py` (classeur visible, vérification manuelle), `stabilite.py` (stabilité EC3 §6.3 en flux, `SessionStabilite` — **c'est ce qu'utilise appv2**). |
| `commun/stabilite_ec3/` | **La même stabilité EC3 §6.3, en Python pur** — flambement, déversement, [6.61]/[6.62], plus le calcul analytique de C1/C2 (§3.5 de l'Annexe MCR) que le classeur n'a pas. Écart nul avec le classeur à coefficients égaux, ~2·10⁴ fois plus rapide. Pas encore branchée dans l'app : voir `commun/stabilite_ec3/README.md`. |
| `commun/algo_opti/` | **Algorithmes d'optimisation de la structure globale** (une section par famille de barres). Un module par algorithme (`LIBELLE`, `DESCRIPTION`, `optimiser(modele, cfg)`), enregistré dans `ALGOS` (`__init__.py`) et proposé automatiquement dans le menu déroulant de la page. Premier algo : `brut_force.py` (force brute + passes, ex-`optimiser_global`). |
| `commun/ec3.py`, `commun/dimensionnant.py`, `commun/dimensionner.py` | Modules de calcul de l'onglet Performances (v1 et v2) — voir le tableau « Scripts » ci-dessous. |
| `catalogues/` | Catalogues de sections extraits de la base GSA (`sectlib.db3`) + extracteur. |
| `config/` | Critères modifiables (`dimensionnement.json` : 90 % fy, L/300…). |
| `scripts/` | Scripts CLI **autonomes** restants (voir ci-dessous) — les modules partagés en sont partis pour `commun/`. |
| `tests/` | `tests/scripts/` : scripts de vérification et de benchmark (chrono GSA, calcul manuel), **étude des 668 permutations de l'ENVELOPPE ELU** de la Canopée, et **comparaison stabilité Excel / Python** (`comparaison_stabilite_excel_python.py`). `tests/resultats/` : leurs sorties. Voir `tests/README.md`. |
| `comparaison_modele/` | Étude de sensibilité de l'algorithme escalade (treillis Pratt). Voir `comparaison_modele/README.md`. |
| `result/` | Toutes les sorties : `export/<modèle>/`, `sections/`, `calcul_manuel/`, `dimensionnement/`. |
| `optimisations/` | Journaux (`.txt`) des runs d'optimisation (horodatés par modèle et algorithme). |
| `reference/` | Documents de référence (Eurocode, classeur Excel, identité graphique…). |
| `suivi_build/` | Journal des sessions de build (à lire pour l'historique). |

## Scripts (`venv\Scripts\python.exe scripts\<script>.py`)

| Script | Ce qu'il fait |
|---|---|
| `export_model.py` | Exporte un modèle `.gwb` en CSV (tables + résultats) → `result/export/<modèle>/`. Menu interactif sans argument. |
| `etude_sections.py` | Recalcule la Poutre ISO avec N sections IPE → `result/sections/<SECTION>/` + `_Comparatif.csv`. |
| `comparer_sections.py` | Post-traitement : tableau large 1 ligne/section (max et position par cas) → `result/sections/_Comparaison.csv`. |
| `calcul_manuel.py` | Mêmes grandeurs par les formules (pL²/8, pL/2, 5pL⁴/384EI) + écart vs GSA → `result/calcul_manuel/`. |
| `standalone_iso_beam.py` | Démo minimale d'accès direct aux résultats via `GsaModel`. |
| `../catalogues/scripts/extract_catalogues.py` | Regénère `catalogues_sections.xlsx` depuis `sectlib.db3` (puis `exporter_csv.py` pour les CSV lus par le code). |

## Modules partagés (`commun/`)

| Module | Ce qu'il porte |
|---|---|
| `commun/dimensionner.py` | **Dimensionnement**, CLI ET module (`venv\Scripts\python.exe commun\dimensionner.py`) : parcourt la série de sections en décroissant, critère ELU sur les **contraintes calculées par GSA** — enveloppe **signée min/max de toutes les mesures** (combinées C1/C2, axiale A, flexion By/Bz, von Mises, cisaillements…), la plus grande amplitude gouverne ; restriction possible via une clé `mesures` dans `config/dimensionnement.json` —, critères ELS **nodaux** (déplacements des nœuds nommés `ELS_glob_X` / `ELS_3pts_X` dans le modèle, cf. `commun/els_noeuds.py`), suppose des combinaisons nommées `ELU`/`ELS` → tableau des taux (avec mesure gouvernante) + section retenue → `result/dimensionnement/`. Logique réutilisée par les interfaces et par les algorithmes de `commun/algo_opti/`. |
| `commun/ec3.py` | **Module de calcul, pas un point d'entrée** : résistances de section EC3 §6.2 (7 critères), caractéristiques lues dans le profil (Av, Wt). Seule implémentation, partagée par `tests/scripts/canopee_elu_*` et l'onglet Performances v2. |
| `commun/dimensionnant.py` | **Module de calcul, SEUL endroit où C1/C2 est recalculé depuis les efforts** (module de flexion **plastique**, partout) : `contraintes_c1_c2`/`permutation_dimensionnante` sur le tableau non réduit (permutation × position, onglet Performances v2), et `contrainte_combinee`/`amplitude_c1_c2` sur des lignes déjà réduites (`beam_forces` max/min, onglet Performances v1 et optimisation globale) — deux fonctions, deux formes d'entrée, un seul fichier. Plus les 7 taux EC3 par permutation (`taux_ec3_par_permutation`). |
| `commun/criteres.py` | **Les 4 critères ELU d'appv2**, barre par barre et permutation par permutation : combiné (module plastique), torsion, cisaillement, von Mises (lu dans GSA). Renvoie la case dimensionnante de CHACUN, pour que la page puisse changer de critère retenu sans appel serveur. Résistance de SECTION seulement (§6.2), comme `ec3.py`. |
| `commun/els_noeuds.py` | **Critères de service par NŒUDS NOMMÉS** : un modèle déclare ses exigences en nommant ses nœuds `ELS_glob_X` (déplacement) ou `ELS_3pts_X` (écart à la corde de trois points). Découverte des critères, évaluation par permutation, taux retenu = MAX. |
| `commun/stabilite_ec3/` | **Stabilité EC3 §6.3 en Python pur** (paquet) : flambement, déversement, [6.61]/[6.62], C1/C2 analytiques du §3.5 de l'Annexe MCR, C<sub>m</sub> du Tableau B.3. Traduction cellule par cellule du classeur Predim, vérifiée à écart nul. Voir son README. |
| `commun/catalogues.py` | Chargement des catalogues de sections (`catalogues/*.csv`), triés par masse croissante — source unique des sections candidates des optimisations. |

Convention d'imports (inchangée par le déplacement dans `commun/`) : `commun/gsa_bridge`,
`commun/excel_bridge` et `commun/algo_opti` s'importent comme des paquets
(`from commun.gsa_bridge.bridge import GsaModel`) ; `commun/ec3.py`,
`commun/dimensionnant.py` et `commun/dimensionner.py` s'importent par leur nom
seul (`from ec3 import ...`) — chaque appelant ajoute la racine du projet ET
`commun/` à `sys.path`.

## Onglet « Performances v2 » — la combinaison qui dimensionne vraiment

Sur une combinaison **enveloppe**, `bridge._table_1d` réduit les permutations à
deux lignes par position : le max signé de *chaque composante prise séparément*,
et le min. Le N, le M<sub>y</sub> et le M<sub>z</sub> d'une même ligne peuvent
donc venir de permutations différentes, et `contrainte_combinee` les additionne
quand même.

**Cette réduction n'est pas une borne**, ni haute ni basse :

- elle **surestime** quand elle cumule des efforts qui ne coexistent dans aucune
  combinaison ;
- elle **sous-estime** parce que B = |M<sub>y</sub>|/W<sub>y</sub> +
  |M<sub>z</sub>|/W<sub>z</sub> prend une valeur absolue : la ligne « max »
  associe le N maximal au M<sub>y</sub> maximal **signé**, et rate le
  M<sub>y</sub> de signe opposé — souvent bien plus grand — qui accompagne
  réellement ce N.

Mesuré sur 60 barres de la Canopée : réduction trop faible sur 28 barres, trop
forte sur 14, exacte sur 18. Cas type, barre 168 (RHS 300×200×10) à mi-portée :
la réduction voit (N = +1082 kN, M<sub>y</sub> = +3,98 kNm) et (N = −3,3 kN,
M<sub>y</sub> = −30,73 kNm) → 125,3 MPa, alors que la permutation 275 porte
N = +1082 kN **et** M<sub>y</sub> = −30,73 kNm ensemble → 158,5 MPa (+26,5 %).

L'onglet garde donc les permutations séparées et retient, barre par barre, le
couple (permutation, position) qui maximise l'amplitude de C1/C2 — un état de
chargement qui existe vraiment. Une **seule extraction** alimente à la fois le
tableau (une ligne par barre : combinaison dimensionnante, lieu en %, torseur
complet, C1/C2, taux ELU) et **7 cartes** barres × permutations, une par critère
EC3 — elles ne peuvent pas diverger. Coût : ~45 s sur la Canopée (657 barres ×
668 permutations), en tâche de fond avec progression et arrêt.

Les cartes voyagent en **PNG niveaux de gris** dont le pixel porte le taux
quantifié (`app/png_gris.py`, zlib de la stdlib) : la page applique la teinte
elle-même, ce qui évite ~15 Mo de JSON et permet de retrier sans recalcul.

En **vue d'ensemble** (défaut) un pixel regroupe plusieurs barres — et au besoin
plusieurs permutations — et prend le **maximum** du groupe, jamais un
échantillonnage : une case saturée ne peut donc pas disparaître (vérifié sur la
Canopée : 24 124 blocs contiennent une case > 1, 24 124 blocs sont noirs). Les
7 cartes tiennent ainsi dans un écran au lieu de s'étirer sur 657 lignes ; le
sélecteur *Détail* repasse à 1/2/4 px par case, le cadre défilant alors sur
place. Le pic et le nombre de dépassements affichés portent toujours sur les
données complètes, jamais sur l'image réduite.

> **f<sub>y</sub>** : par défaut celui du critère ELU de la page (unique). Sur un
> modèle à plusieurs nuances la page le signale et propose « nuance de chaque
> section » — indispensable sur la Canopée, qui est en S355 sauf ses tirants
> ronds en S450 (leur imposer 355 MPa surestime leurs taux de 27 %).

Mêmes limites que `commun/ec3.py` : résistance de **section** uniquement (§6.2),
sans flambement, sans déversement, sans interaction entre efforts.

## Stabilité EC3 §6.3 — le classeur Excel et sa réécriture Python

Le projet vérifie le flambement, le déversement et la flexion composée
(§6.3.1, §6.3.2, [6.61]/[6.62]) de **deux** manières :

| | `commun/stabilite_ec3/` | `commun/excel_bridge/stabilite.py` |
|---|---|---|
| Moteur | Python pur | classeur Predim piloté par COM (xlwings) |
| Branché dans `appv2/` | **oui**, depuis le 01/09/2026 | non — reste l'**oracle** du test de comparaison, et le classeur qu'ouvre le bouton « Ouvrir dans Excel » |
| C1 et C2 du M<sub>cr</sub> | **calculés** barre par barre, §3.5 de l'Annexe MCR | saisis à la main (abaque), les mêmes pour toutes les barres |
| Coût | **≈ 30 µs par barre** | ≈ 0,60 s — soit ~2·10⁴ fois plus |
| Classe de section | **calculée** (§5.5, Tableau 5.2) | calculée par le classeur |

`tests/scripts/comparaison_stabilite_excel_python.py` les compare sur les mêmes
barres, en relisant dans le classeur les caractéristiques de section qu'il a
lui-même résolues : toute différence est donc une différence de **formule**.
Résultat, sur 63 barres et 3 modèles (profils en I, tubes RHS/SHS, tubes CHS) :
**à C1/C2 égaux, écart nul (0,0000 %)**. La seule divergence est celle qu'on a
voulue — le calcul de C1/C2 —, et elle ne se voit que là où le déversement est
actif : sur des poutres en I élancées le taux bouge de −21 % à +25 % (médiane
−10 %), sur les treillis tubulaires du projet l'écart est exactement nul
(χ<sub>LT</sub> vaut déjà 1).

La chaîne autonome — géométrie reprise du **catalogue** (avec I<sub>w</sub> et
courbes de flambement reconstruits) et **classe de section calculée** — donne
le même résultat : 0,0000 % d'écart, et la classe **63/63 identique** à celle
du classeur. C'est ce qui a permis de basculer l'app sur le module Python.

La comparaison a aussi révélé deux particularités du classeur que la
réécriture ignorait, corrigées depuis : la ligne « Creux » du Tableau B.1 pour
k<sub>zz</sub> (tous les tubes) et χ<sub>LT</sub> = 1 pour un CHS. Analyse
complète, points de conformité à l'Eurocode et les trois questions tranchées à
la bascule (k et C1/C2, la classe de section, le repli catalogue) :
**`commun/stabilite_ec3/README.md`**.

## Prérequis

- GSA 10.2 installé (licence utilisée par le moteur in-process).
- `venv` Python avec `requirements.txt` (pythonnet ≥ 3.1 notamment).
- Un seul script GSA à la fois (copie de travail partagée `commun/gsa_bridge/runtime/`).
