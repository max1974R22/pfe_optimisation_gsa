# tests — scripts de vérification et de benchmark

Scripts autonomes de contrôle : chronométrage des appels GSA, comparaison de
stratégies d'extraction, et trace pas-à-pas du calcul manuel. Ce ne sont **pas**
des tests unitaires (pas de `pytest`) : chacun se lance directement et écrit ses
sorties dans `tests/resultats/`. Tous travaillent sur une **copie** du modèle
(`gsa_bridge/runtime/`) — les `.gwb` maîtres ne sont jamais modifiés.

| Script | Ce qu'il fait |
|---|---|
| `test_canopee.py` | Chrono détaillé d'un `Element1dStress` sur l'enveloppe ELU de la Canopée, pour **une seule barre**. Écrit `resultats/test_canopee_stress.csv` et affiche le temps de chaque étape (connexion, analyse, appel .NET, marshalling, écriture). |
| `test_comparaison.py` | Compare le coût de **3 appels `Element1dStress` séparés** (barres 1, 2, 3) contre **un seul appel groupé** (`"1 2 3"`), modèle ouvert/analysé une seule fois. Écrit `resultats/stress_barre*.csv`. |
| `analyser_stress.py` | Post-traitement (aucun appel GSA) : max/min de chaque colonne de contrainte de `resultats/test_canopee_stress.csv` (sortie de `test_canopee.py`). |
| `test_IPE80.py` | Trace pas-à-pas du calcul manuel d'une section (formules pL²/8, pL/2, 5pL⁴/384EI) et écart vs GSA. Réutilise `scripts/calcul_manuel.py`. Argument optionnel : la section (ex. `IPE200`). |
| `canopee_elu_libelles.py` | **Identifie et valide** les 668 permutations de la combinaison `ENVELOPPE ELU`. Sur une seule barre : lit les permutations de l'enveloppe, puis celles de chaque combinaison enveloppée (C9…C46), et **prouve** que la concaténation dans l'ordre de définition redonne l'enveloppe valeur par valeur. Écrit `resultats/canopee_elu_libelles.csv` (perm → combinaison, nom, définition). |
| `canopee_elu_permutations.py` | **Extraction principale** : efforts de **chaque** permutation de l'`ENVELOPPE ELU`, pour **chaque barre acier**. Écrit `resultats/canopee_elu_permutations.csv` — 1 ligne par (barre, position 0/25/50/75/100 %), 1 colonne par (permutation × composante). |
| `canopee_elu_synthese.py` | Dépouillement (aucun appel GSA) : à partir du grand tableau, **une ligne par barre** donnant, pour chacun des 6 efforts, l'amplitude maximale, la permutation et la position qui l'atteignent. Écrit `resultats/canopee_elu_synthese.csv`. |
| `canopee_elu_ec3.py` | **Taux d'utilisation EC3** (EN 1993-1-1 §6.2, résistance de section) : une ligne par barre, 7 critères (compression, traction, flexion yy/zz, torsion, cisaillement y/z), chacun avec son taux, l'effort, la permutation et la position gouvernantes. Écrit `resultats/canopee_elu_ec3.csv`. |
| `canopee_elu_matrice.py` | **Carte 2D** barres × permutations : un pixel par case, teinte = critère EC3 gouvernant, intensité = taux (blanc 0 → teinte pleine 1), noir au-delà de 1. Écrit `resultats/canopee_elu_matrice.png` (1 px/case) et `…_annotee.png` (axes + légende). |
| `_elu_commun.py` | Briques partagées par les scripts ci‑dessus (ouverture/analyse, repérage de l'enveloppe, sélection des barres acier, lecture **brute** des permutations). **Pas un script à lancer.** |

## Lancer

```bash
venv/Scripts/python.exe tests/test_canopee.py
venv/Scripts/python.exe tests/test_comparaison.py
venv/Scripts/python.exe tests/analyser_stress.py        # après test_canopee.py
venv/Scripts/python.exe tests/test_IPE80.py             # ou : tests/test_IPE80.py IPE200
venv/Scripts/python.exe tests/canopee_elu_libelles.py       # à lancer en premier
venv/Scripts/python.exe tests/canopee_elu_permutations.py   # puis l'extraction
```

`resultats/` contient les dernières sorties (CSV) de ces scripts.

## Étude des 668 combinaisons ELU (Canopée)

`canopee_elu_permutations.py` répond à la question « quelle combinaison
dimensionne quelle barre ». Sa sortie est volontairement **non réduite** :
là où `GsaModel.beam_forces` replie une combinaison enveloppe en deux lignes
max/min par position (`bridge._table_1d`), chaque permutation garde ici ses
propres colonnes.

| | |
|---|---|
| **Lignes** | 657 barres acier × 5 positions = **3 285** (0 / 25 / 50 / 75 / 100 % de la longueur). Sont retenues les barres 1D dont la **section** est en acier (`materiau == STEEL`) — 22 sections sur 34, le reste étant du bois. |
| **Colonnes** | 7 colonnes d'identité (`element`, `type`, `section`, `nom_section`, `profil`, `longueur_m`, `pos_pct`) puis **668 × 6 = 4 008** valeurs, nommées `permNNN_<libellé>_<composante>` (ex. `perm038_C11p01_Myy`). |
| **Composantes** | `Fx` (axial), `Fy`/`Fz` (efforts tranchants), `Mxx` (torsion), `Myy`/`Mzz` (moments fléchissants) — les 6 du torseur `Element1dForce`. |
| **Unités** | SI du modèle : **N** et **N·m**. |
| **Volume / durée** | ≈ 79 Mo ; **47 s** au total sur la Canopée (16 s d'analyse GSA, 30 s d'extraction — 0,05 s/barre). |

Le libellé de colonne vient de `canopee_elu_libelles.csv` : `C9` pour une
combinaison à permutation unique, `C10p03` pour la 3ᵉ permutation de C10.
Sans ce fichier (ou s'il est marqué non valide), les colonnes retombent sur
`permNNN_<composante>`.

**Pourquoi 668 ?** `C47 = ENVELOPPE ELU = "C9 to C46"`, soit 38 combinaisons
ELU. 18 d'entre elles référencent une enveloppe de vent (`C2`/`C3` =
env. min/max TIC, 36 permutations chacune) → 18 × 36 = 648, plus 20
combinaisons à permutation unique = **668**.

Options utiles : `--limite N` (n'extraire que N barres, pour un essai),
`--paquet N` (barres par appel GSA, défaut 20), `--positions N`,
`--precision N` (chiffres significatifs, défaut 6), `--modele`, `--sortie`.

### Taux d'utilisation EC3 (`canopee_elu_ec3.py`)

Relit le **grand tableau** (et non la synthèse : distinguer compression et
traction exige le **signe**, que la synthèse perd en ne gardant que des
amplitudes) et produit une ligne par barre × 7 critères, chacun avec
`taux_<critère>`, `<critère>_valeur`, `<critère>_perm`, `<critère>_pos_pct`,
plus `taux_max` / `critere_max`. Durée : ~4 s, aucun recalcul GSA (le modèle
n'est ouvert que pour les tables Sections / Materials).

| Critère | EC3-1-1 | Formule |
|---|---|---|
| `compression` | 6.2.4 | \|N\|/(A·fy/γM0), sur l'extrême **négatif** de Fx |
| `traction` | 6.2.3 | N/(A·fy/γM0), sur l'extrême **positif** de Fx |
| `flexion_yy` / `flexion_zz` | 6.2.5 | \|M\|/(W·fy/γM0) |
| `torsion` | 6.2.7 | (\|T\|/Wt)/(fy/√3/γM0) |
| `cisaillement_y` / `_z` | 6.2.6 | \|V\|/(Av·(fy/√3)/γM0) |

`fy` est résolu **par section** depuis la nuance du modèle (S355 → 355 MPa,
S450 → 450 MPa ; `--fy-mpa` force une valeur unique). Le moment résistant est
**élastique** (Wel) par défaut — valable et conservatif de la classe 1 à 3 ;
`--plastique` bascule sur Wpl.

**Caractéristiques de section — ce que GSA donne, et ce qu'il ne donne pas.**
`Section.Properties()` (exposé par `gsa_bridge`) fournit A, Iyy/Izz, J, les
modules de flexion Zy/Zz (élastiques) et Zpy/Zpz (plastiques), **et le module
de torsion `C`** (τ = Mt/C). `C` est utilisé tel quel : vérifié sur les 22
sections acier de la Canopée, il égale à 0,5 % près la reconstruction de Bredt
(2·Am·t) pour les RHS et J/(d/2) pour les CHS et ronds pleins — le résidu
n'étant que l'arrondi des cotes catalogue.

En revanche GSA **n'expose pas** l'aire de cisaillement Av de l'EC3. Ce qu'il
donne, `Kyy`/`Kzz`, ce sont les facteurs de cisaillement de **Timoshenko**
(aire réduite de *déformation*, pour la flèche) — une autre grandeur :

| | K (GSA) | Av/A (EC3 6.2.6) |
|---|---|---|
| rond plein | 0,857 (6/7) | 0,750 |
| tube mince CHS | 0,500 | 0,637 (2/π) |
| RHS 200×120×10, sens z | 0,573 | 0,625 (h/(b+h)) |

Av suit donc les **formules de l'EC3**, à partir des cotes lues dans la chaîne
de profil (`STD RHS h b t t`, `STD C d`, `CAT EN-CHS CHSdxt`, en mm) ; un
garde-fou compare l'aire recalculée à celle de GSA et signale tout écart > 5 %.
`--av gsa` bascule sur K×A si l'on veut malgré tout la valeur GSA — ce n'est
alors plus la vérification de l'EC3 (sur la Canopée : taux de cisaillement
+27 %, mais ils restent négligeables dans les deux cas, ≤ 0,085).

**Limites, à lire avant d'exploiter les taux :**
- **aucun flambement (6.3.1) ni déversement (6.3.2)** — vérifications
  d'*élément*, qui exigent des longueurs de flambement absentes du modèle.
  Le taux de compression est donc une **borne inférieure** ; la stabilité
  passe par le classeur Predim (`excel_bridge/`) ;
- **aucune interaction** entre efforts (6.2.9 M+N, 6.2.10 M+V…) : les 7 taux
  sont indépendants et gouvernés en général par des permutations
  *différentes*, donc `taux_max` n'est pas un taux d'ensemble ;
- **aucune classification** de section, ni réduction de fy pour les fortes
  épaisseurs (tableau 3.1).

### Carte 2D (`canopee_elu_matrice.py`)

Une image de **657 × 668 pixels** : une ligne par barre, une colonne par
permutation ELU. Le taux d'une case est le maximum des 7 taux EC3 de cette
barre sous **cette seule** permutation (efforts réduits sur les 5 positions).

| | |
|---|---|
| **Teinte** | le critère le plus sollicité — compression **bleu**, traction **rouge**, flexion yy **jaune**, flexion zz **violet**, torsion **cyan**, cisaillement y **vert**, cisaillement z **orange** |
| **Intensité** | blanc à taux 0, teinte pleine à taux 1 |
| **Noir** | taux > 1 |

Les résistances sont importées de `canopee_elu_ec3.py`
(`charger_sections` / `resistances`) : **un seul endroit définit les formules
EC3**, la carte et le tableau de taux ne peuvent pas diverger. Les limites du
§6.2 s'appliquent donc à l'identique (pas de flambement, pas d'interaction).

`--tri section` regroupe les lignes par section — bien plus lisible que l'ordre
des id d'élément. `--tri taux` classe par taux max décroissant. `--echelle N`
agrandit l'image brute à l'identique (N pixels par case). Durée : ~5 s.

Sur la Canopée : 438 876 cases, **71,4 % gouvernées par la flexion yy**,
14,7 % traction, 13,3 % compression ; torsion et cisaillements ne gouvernent
que 11 cases sur 438 876. Les 26,6 % de cases noires sont concentrées sur les
sections 16 (`ROND 10`, 276 barres) et 21 (`ROND 14`, 50 barres) — cf. la
mise en garde ci‑dessous.

> **Lecture** : les dépassements sont *tous* le fait de tirants ronds pleins
> Ø10 et Ø14, en flexion yy, sous la seule combinaison `C9` (1.35PP + 1.35CP).
> C'est la flèche sous poids propre de tiges élancées modélisées en éléments
> fléchissants — un artefact de modélisation, pas une action de calcul. Aucune
> des 189 barres RHS/CHS ne dépasse 1,0 en résistance de section.
