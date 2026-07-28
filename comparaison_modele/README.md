# Comparaison modèle — algorithme escalade sur le treillis Pratt

Étude de sensibilité de l'algorithme d'optimisation globale **escalade**
(`algo_opti/escalade.py`) sur `GSA_model/Pratt_1.gwb`, famille **RHS** (tubes
rectangulaires/carrés). Le pilotage reproduit exactement ce que fait la page web
(mêmes familles, même contrat `cfg`), pour mesurer l'influence des **données
d'entrée** sur la masse d'acier obtenue.

> Stabilité EC3 (classeur Excel) **désactivée** : l'étude porte sur ELU/ELS pur
> (GSA seul), reproductible et rapide. L'activer ne changerait pas la mécanique
> comparée, mais rendrait chaque run lent et dépendant d'Excel.

## Organisation

Un script Python **par comparaison** ; chacun calcule (CSV dans `result/`) **et**
trace (PNG dans `result/`) en une seule exécution. `_commun.py` factorise le
pilotage de l'algorithme et les fonctions de traçage (pas un script à lancer).
Chaque script affiche en tête de fichier les valeurs par défaut des AUTRES
paramètres (ceux qu'il ne fait pas varier).

| Script | Paramètre balayé | Les autres restent... |
|---|---|---|
| `A1_hauteur_max.py` | `hauteur_max_m` | au défaut (epaisseur_max_mm=10, ratio_hauteur_depart=20, ratio_largeur_depart=3) |
| `A2_epaisseur_max.py` | `epaisseur_max_mm` | au défaut |
| `A3_ratio_hauteur_depart.py` | `ratio_hauteur_depart` (point de départ h₀=L/ratio) | au défaut |
| `A4_ratio_largeur_depart.py` | `ratio_largeur_depart` (point de départ b₀=h₀/ratio) | au défaut |
| `B1_ordres_choisis.py` | ordre de départ des familles — **8 ordres choisis à la main** | tous fixés au défaut |
| `B2_ordres_aleatoires.py` | ordre de départ des familles — **N permutations aléatoires** (`argv[1]`, défaut 100) | tous fixés au défaut |

## Lancer

```bash
venv/Scripts/python.exe comparaison_modele/A1_hauteur_max.py
venv/Scripts/python.exe comparaison_modele/A2_epaisseur_max.py
venv/Scripts/python.exe comparaison_modele/A3_ratio_hauteur_depart.py
venv/Scripts/python.exe comparaison_modele/A4_ratio_largeur_depart.py
venv/Scripts/python.exe comparaison_modele/B1_ordres_choisis.py
venv/Scripts/python.exe comparaison_modele/B2_ordres_aleatoires.py 100
```

## Les 8 familles du treillis (listes GSA du modèle)

| Famille | Membres | Rôle |
|---|---|---|
| Membrure haute | 12, 13, 15, 17 | **dimensionnante** |
| Diag ext | 7, 11 | **dimensionnante** |
| Diag int | 19, 20 | |
| Diag mid | 18, 21 | |
| Membrure basse | 1, 2, 3, 4, 5, 6 | **la plus lourde** (6 barres) |
| Mont ext | 14, 16 | |
| Mont int | 8, 10 | |
| Mont mid | 9 | |

## Partie A — un paramètre à la fois

Défauts : `hauteur_max = 0.5 m`, `epaisseur_max = 10 mm`,
`ratio_hauteur_depart = 20` (h₀ = L/20), `ratio_largeur_depart = 3` (b₀ = h₀/3).

| Balayage | Fichier | Observation |
|---|---|---|
| Hauteur max de section | `A1_hauteur_max` | **sans effet** au-dessus de 0,08 m (167,5 kg) : les RHS retenues restent petites. En dessous (0,05 m) la structure ne convient plus (non convergent, ×). |
| Épaisseur de paroi max | `A2_epaisseur_max` | **effet en dessous de 8 mm** : 4 mm → 194,9 kg, 6,3 mm → 174,3 kg, ≥ 8 mm → 167,5 kg (plafond non contraignant). Brider la paroi force des sections plus hautes/larges donc plus lourdes. |
| Ratio hauteur de départ (L/ratio) | `A3_ratio_hauteur_depart` | **paramètre le plus influent du départ** : partir trop trapu (L/10 → 253 kg) coûte cher ; l'optimum est vers **L/25 (163,1 kg)** ; au-delà (L/30, L/40) la masse se stabilise mais le **nombre d'analyses GSA explose** (16 → 112) car on part de plus loin. Bon compromis masse/coût : L/20–L/25. |
| Ratio largeur de départ (h/ratio) | `A4_ratio_largeur_depart` | **sans effet** (167,5 kg) : la phase d'allègement ré-optimise la largeur quel que soit le point de départ. |

Chaque graphe A trace la **masse** (axe gauche, rose) et le **nombre d'analyses
GSA** (axe droit, bleu) ; une croix noire signale un point non convergent.

## Partie B — ordre de départ des familles (paramètres fixés au défaut)

8 familles = 8! = 40 320 ordres possibles.

**B1 (8 ordres choisis à la main)**, en déplaçant surtout les familles
**dimensionnantes** (Membrure haute, Diag ext) et la **plus lourde** (Membrure
basse) — résultat net et binaire :

| Groupe | Ordres | Masse |
|---|---|---|
| Familles dimensionnantes escaladées **avant** la membrure basse | `1-naturel`, `2-dim_d_abord`, `4-dim_puis_lourd`, `7-lourd_en_dernier` | **167,5 kg** |
| Membrure basse (lourde) escaladée **avant** les dimensionnantes | `3-lourd_d_abord`, `5-lourd_puis_dim`, `6-dim_en_dernier`, `8-inverse` | **561,4 kg** (×3,4) |

**B2 (100 permutations aléatoires)** confirme la structure multimodale de la
distribution : la masse totale se concentre presque exclusivement sur 4 valeurs
discrètes (~167, ~217, ~348, ~561 kg), correspondant chacune à un ordre relatif
particulier entre la membrure basse et les familles dimensionnantes — pas un
continuum.

**Conclusion** : l'ordre de départ est **décisif** pour l'escalade. Si la
membrure basse (lourde, mais peu sollicitée) est grossie en premier, elle rigidifie
la structure et l'escalade fige un optimum local très lourd ; en laissant d'abord
les familles réellement dimensionnantes trouver leur taille, la structure converge
vers un optimum jusqu'à 3,4× plus léger. **Règle pratique : escalader les
familles dimensionnantes en premier, la membrure basse en dernier.**

## Contenu de `result/`

- `A1..A4_*.csv` / `.png` — un balayage par paramètre (masse, analyses, convergence, taux ELS, sections retenues).
- `B1_ordres_choisis.csv` / `.png` — masse par ordre choisi + séquence détaillée.
- `B2_ordres_aleatoires.csv` / `.png` — masse par permutation aléatoire (histogramme de distribution) + séquence détaillée.
