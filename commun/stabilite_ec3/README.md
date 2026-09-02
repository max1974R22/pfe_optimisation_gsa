# `commun/stabilite_ec3` — la stabilité EC3 §6.3 sans Excel

Réécriture Python des quatre taux que le classeur Predim calcule dans son
onglet `Calcul` (cellules `X35:X38`) : flambement §6.3.1, déversement §6.3.2,
barre fléchie et comprimée [6.61] et [6.62]. Même entrée, même sortie que
`commun/excel_bridge/stabilite.py::SessionStabilite.verifier`, mais en Python
pur — sans COM, sans classeur ouvert, sans verrou `EXCEL`.

> **C'est le moteur de stabilité d'`appv2` depuis le 01/09/2026.** Les trois
> onglets qui vérifient l'EC3 §6.3 passent par ici ; le classeur ne sert plus
> qu'au bouton « Ouvrir dans Excel » d'une barre, où il reçoit les C1/C2 que ce
> module vient de calculer. Le point de bascule tient en une fonction :
> `appv2/server.py::_session_stabilite()`.

| fichier | clause | cellule du classeur |
|---|---|---|
| `flambement.py` | §6.3.1 | `X35` (= `P67`) |
| `deversement.py` | §6.3.2, M<sub>cr</sub> par l'Annexe MCR | `X36` (= `Q86`), `W73` |
| `flexion_compression_yy.py` | [6.61] | `X37` (= `V96`) |
| `flexion_compression_zz.py` | [6.62] | `X38` (= `V100`) |
| `coefficients_c1_c2.py` | C1/C2 de M<sub>cr</sub>, §3.5 de l'Annexe MCR | *(rien : le classeur ne les calcule pas)* |
| `coefficients_cm_b3.py` | C<sub>my</sub>/C<sub>mz</sub>, Tableau B.3 | `AL51`, `AL64` |
| `_commun.py` | χ [6.49], α (Tableau 6.1), k<sub>zz</sub>, k<sub>zy</sub> | `P62/P63`, `AB42:AC46`, `AE80/AF80`, `AH80/AH81` |
| `classe_section.py` | classe de section §5.5, Tableau 5.2 | onglet `Calcul classe` entier |
| `section_catalogue.py` | géométrie, I<sub>w</sub>, courbes de flambement | `AC12:AC34` — mais lus **au catalogue** |
| `session.py` | `SessionStabilitePython` : même API que la session Excel | — |
| `verification.py` | assemble, retient le MAX | `L4` |

Les trois derniers sont ce qu'il a fallu ajouter pour **se passer du classeur**,
et non plus seulement le doubler : sans eux le module réclamait en entrée deux
choses que seul le classeur savait produire — les caractéristiques de section
qu'il résolvait par `VLOOKUP`, et la classe de section.

Chaque fonction cite la clause **et** la cellule dont elle est la traduction.
Ces correspondances ont été relues une à une sur le classeur courant
(`reference/excels/Predim_poutre acier_v3_GSA.xlsm`) à l'openpyxl, **formules
et non valeurs** : en cas de doute, c'est cette lecture qui fait foi, pas ce
fichier.

## Comment vérifier tout ça

```bash
venv\Scripts\python.exe tests\scripts\comparaison_stabilite_excel_python.py --annexe
```

```bash
venv\Scripts\python.exe tests\scripts\comparaison_stabilite_excel_python.py --modele 10_story_frame.gwb --max-barres 40
```

```bash
venv\Scripts\python.exe tests\scripts\comparaison_stabilite_excel_python.py --debit
```

Le script extrait de GSA les mêmes torseurs que l'onglet Performances d'appv2
(combinaison dimensionnante de chaque barre, toutes les permutations de
l'enveloppe ELU × 5 positions), les envoie au classeur, **relit dans le
classeur les caractéristiques de section qu'il a lui-même résolues**
(`AC12:AC34`, `W13:W17`, `P30:P36`, `G15:G17`, la classe) et fait tourner le
module Python **sur ces chiffres-là**. Une différence de résultat ne peut donc
venir que d'une différence de **formule**, jamais d'une donnée d'entrée.

Trois colonnes sont produites par barre : `excel`, `python` (C1/C2 calculés) et
`python_c1c2` (C1/C2 forcés aux valeurs du classeur, via
`ParametresBarre.c1_c2_manuels`). La troisième est le test de non-régression :
à coefficients égaux, elle **doit** coller à `excel`.

Les sorties des trois passages ci-dessous sont conservées dans
`tests/resultats/` : `comparaison_stabilite_<modèle>_<groupe>.csv` (une ligne
par barre, toutes les colonnes) et `…_synthese.txt` (la synthèse à l'écran).

## Résultat 1 — à coefficients égaux, les deux implémentations sont identiques

| modèle | sections | barres | combinaison | écart max sur le taux retenu |
|---|---|---|---|---|
| `10_story_frame.gwb` | `HE1000M` (profil en I) | 30 | `C6`, 7 permutations | **0,0000 %** |
| `Pratt_1_ELS_test.gwb` | `RHS`/`SHS` (tubes) | 21 | `C1` | **0,0000 %** |
| `240320_gymnase_v27_CG.gwb`, `P1_sup` | `CHS324x5.6` | 12 | `C281`, 26 permutations | **0,0000 %** |

63 barres, trois familles de sections, aucun écart mesurable — les quatre taux
pris séparément comme le taux retenu.

**La chaîne autonome donne exactement la même chose.** La colonne `python_cat`
du harnais refait le calcul sans rien lire dans le classeur : géométrie reprise
du **catalogue** (`section_catalogue`, avec I<sub>w</sub> et courbes de
flambement reconstruits) et **classe calculée** (`classe_section`). Sur les
mêmes 63 barres : **0,0000 %** d'écart, et la **classe de section est
63/63 identique** à celle que calculait le classeur. C'est ce résultat qui a
permis la bascule.

La réécriture est donc fidèle, y compris
sur les deux particularités de section creuse du classeur, longtemps absentes
du module Python et **corrigées le 01/09/2026** grâce à cette comparaison :

- **k<sub>zz</sub> et k<sub>yz</sub>, ligne « Creux » du Tableau B.1.** Le
  classeur choisit la formule par `AB81 = IF(AH76="h i", AE80, AF80)`, où
  `AH76 = IF(OR(AB2=1..4), "H I", "Creux")` : « H I » pour les onglets
  IPE/IPN/HE/HD **seulement**, « Creux » pour CHS, RHS/SHS et Custom. Le module
  appelait `facteur_kzz_I_H` pour tout le monde. `facteur_kzz_creux` existait
  bien, mais n'était appelé nulle part et portait le commentaire « non utilisé
  par le projet actuel (profils IPE uniquement) » — dans un projet dont les
  modèles sont des treillis tubulaires. Ordre de grandeur de l'erreur : à
  λ̄<sub>z</sub> = 1 et n = 0,3, le coefficient passe de 1,42 (I/H) à 1,24
  (creux), soit **15 % sur le terme M<sub>z</sub>** de [6.61]/[6.62].
- **χ<sub>LT</sub> = 1 pour un CHS.** `S80 = IF(AB2=5, 1, ...)` : un tube
  circulaire a la même inertie de flexion dans toutes les directions, il n'a
  pas d'axe faible et ne déverse pas. Le module calculait un χ<sub>LT</sub> < 1
  — et n'aurait de toute façon pas pu aboutir : l'onglet CHS du classeur laisse
  la colonne `b` **vide**, donc `courbe_deversement` (h/b) divisait par zéro.
  Excel ne rencontre pas le problème parce que son `IF` paresseux
  court-circuite `Q71` avant de l'évaluer.

## Résultat 2 — la vraie différence : C1 et C2

C'est la seule divergence **voulue**. Le classeur lit C1 et C2 dans deux
cellules saisies à la main (`P32`/`P33`, valeurs d'abaque) : appv2 y envoie ce
que porte l'encadré Instabilité, **1,13 et 0,46 par défaut, les mêmes pour
toutes les barres du modèle**. Le module Python les calcule barre par barre à
partir du diagramme de moment (§3.5 de l'Annexe MCR).

Sur `10_story_frame` (30 barres, profils en I de 10 m — le déversement y pèse
vraiment) :

| | classeur | calculé |
|---|---|---|
| C1 | 1,130 (fixe) | 1,342 … 3,148 — médiane **2,621** |
| C2 | 0,460 (fixe) | 0,000 … 1,247 — médiane **0,000** |

| taux | min | médiane | max |
|---|---|---|---|
| déversement | −21,3 % | **−9,9 %** | +25,0 % |
| fléchi + comprimé yy | −21,0 % | −1,9 % | +22,1 % |
| fléchi + comprimé zz | −21,0 % | −3,0 % | +18,9 % |
| **taux retenu** | −21,0 % | **−3,5 %** | +18,9 % |

Python est plus permissif sur 26 barres, plus sévère sur 3, identique sur 1 —
et **aucune des 30 barres ne change de verdict** (taux ≤ 1). Le sens de
l'écart n'est pas systématique : un C1 calculé plus grand relève M<sub>cr</sub>
donc abaisse le taux, mais un C2 calculé quasi nul supprime le terme
−C2·z<sub>g</sub> qui, dans le classeur, **augmentait** M<sub>cr</sub> ; les
deux effets se compensent différemment selon la forme du diagramme.

**Sur les modèles tubulaires, l'écart est exactement nul** (Pratt et gymnase,
33 barres) : leurs barres sont courtes, λ̄<sub>LT</sub> ≈ 0 et χ<sub>LT</sub>
vaut déjà 1 — sur un CHS, par exemption. C1 et C2 n'ont alors plus aucune
influence. **Calculer C1/C2 ne change rien tant que le déversement n'est pas
actif** : le gain porte sur les poutres élancées en profil ouvert.

### « Ouvrir dans Excel » : les coefficients suivent la barre

Le bouton de vérification manuelle d'une barre garde tout son sens, mais il
serait trompeur si le classeur repartait de ses valeurs d'abaque : il
afficherait un autre taux que le tableau de l'app. `ouvrir_excel_barre`
**recopie donc dans le classeur les C1/C2 calculés pour cette barre**, et
k = k<sub>w</sub> = 1 avec eux. Le mode `--report` du harnais le vérifie :

```bash
venv\Scripts\python.exe tests\scripts\comparaison_stabilite_excel_python.py --modele 10_story_frame.gwb --report
```

| modèle | sans report | avec report | écart au module |
|---|---|---|---|
| `10_story_frame` (8 `HE1000M`) | le classeur donne un autre taux sur **8/8** barres (barre 1 : 0,650 contre 0,556, soit **17 %**) | il retrouve le taux du module | **0,0000 %** |
| `Pratt_1_ELS_test` (8 tubes) | identique sur **8/8** — leur déversement n'est pas actif | inchangé | **0,0000 %** |

La page affiche à côté du torseur les coefficients reportés, la classe de
section et les quatre taux à retrouver dans le classeur.

### Le calcul de C1/C2 est-il conforme à l'annexe ?

`--annexe` rejoue les Tableaux 1 et 2 de l'Annexe MCR
(`reference/Eurocode/NF EN 1993-1-1_NA.pdf`, p. 17-18) :

| Tableau 1 (moments d'extrémité seuls, μ = 0) | écart |
|---|---|
| ψ = +1,00 → norme 1,00 | **0,00 %** (exactement 1,0000 — le moment uniforme est la définition de C1) |
| ψ = +0,50 → 1,31 | +0,14 % |
| ψ = 0,00 → 1,77 | +0,36 % |
| ψ = −0,50 → 2,33 | +1,41 % (le pire des 9 points) |
| ψ = −1,00 → 2,55 | −0,20 % |

| Tableau 2, lignes couvertes par le §3.5 | C1 | C2 |
|---|---|---|
| appuyé-appuyé + charge répartie (M = 0) | 1,1270 vs 1,13 (−0,27 %) | 0,4540 vs 0,45 (+0,89 %) |
| encastré-encastré + charge répartie (ψ = +1, μ = −1,5) | 2,6132 vs 2,57 (+1,68 %) | 1,5601 vs 1,55 (+0,65 %) |

Les deux lignes à **charge ponctuelle** du Tableau 2 (C1 = 1,35 et 1,69) ne
sont pas reproductibles : le §3.5 ne traite que la charge uniformément
répartie, et le module ne prétend pas les couvrir. Le paragraphe est lui-même
qualifié d'**approché** par la norme ; des écarts de l'ordre du pour cent sont
attendus.

## Résultat 3 — le temps

| | par barre | 1 000 barres |
|---|---|---|
| classeur Predim (COM) | **≈ 0,60 s** (médiane 0,57 s ; min 0,52 s, max 1,9 s au premier appel) | **≈ 10 min** |
| module Python, mesuré dans le même harnais | **≈ 32 µs** | ≈ 32 ms |
| module Python, débit pur (`--debit`, 20 000 appels) | **≈ 15 µs** — 68 000 barres/s | ≈ 15 ms |

*(le débit pur était de 7,5 µs avant que `verifier_stabilite` ne renvoie
aussi son `detail` — les résultats intermédiaires dont `ouvrir_excel_barre`
a besoin pour recopier C1/C2 dans le classeur. Le doublement du coût d'un
calcul à 10<sup>-5</sup> s est sans conséquence.)*

**Rapport ≈ 2 × 10<sup>4</sup>** à conditions égales. Le temps Excel mesuré est
celui qu'appv2 paie réellement par barre : `set_inputs` (dont la résolution du
profil, qui relit toute la colonne B de l'onglet de famille), `recalc`, lecture
des sorties. L'ouverture du classeur (3 à 5 s) est amortie sur la session et
n'y figure pas.

Ce que ça a changé pour l'app, mesuré après la bascule :

- l'onglet **Performances** ne montre plus jamais l'état « … » d'attente de
  stabilité : les taux arrivent avec les barres ;
- l'onglet **Optimisation** en mode « stabilité approfondie » (5 barres × toutes
  les permutations, à **chaque** candidat) était le calcul le plus long du
  projet — sur une enveloppe à 26 permutations, 130 vérifications Excel par
  candidat, soit ~80 s **par section essayée**. Il ne coûte plus rien ;
- **Opt. globale** sur `Pratt_1_ELS_test`, deux familles, stabilité approfondie :
  **39 s pour 16 essais**, et ces 39 s sont désormais entièrement de la
  réanalyse GSA. Résultat identique à celui d'avant la bascule (`RHS100x50x7.1`
  retenue, ELU final 0,8993, stabilité 0,972).

Le verrou `EXCEL` ne protège plus que le bouton « Ouvrir dans Excel », avec les
pannes qu'il traîne : erreur RPC transitoire à l'activation d'Excel, classeur
orphelin qui verrouille le maître (cf. `commun/excel_bridge/bridge.py`). Les
calculs, eux, n'ouvrent plus rien.

## Classe de section — quel module de flexion, et la classe 4 refusée

Les contraintes liées au moment (déversement, [6.61], [6.62]) utilisent le
module de flexion **plastique** (W<sub>pl</sub>) en classe 1 et 2, **élastique**
(W<sub>el</sub>) en classe 3 — `classe3 = parametres.classe_section == 3` dans
`deversement.py`/`flexion_compression_yy.py`/`flexion_compression_zz.py`.

**Une section de classe 4 n'est pas vérifiée du tout** :
`verifier_stabilite` (point d'entrée unique du module) lève `SectionClasse4`
avant le moindre calcul dès que `classe_section == 4`, et `session.py`
transforme ça en `{"erreur": "..."}` — la barre affiche « — » dans les
tableaux d'appv2 au lieu d'un taux, comme n'importe quelle autre erreur de
stabilité. Une classe 4 exige des caractéristiques **efficaces** (aire et
module efficaces, décalage du centre de gravité, EN 1993-1-5) pour **toutes**
les formules de résistance en jeu ici, pas seulement le choix W<sub>el</sub>/
W<sub>pl</sub> — ce module ne les calcule pas, et se rabattre sur W<sub>pl</sub>
(ce qu'il faisait implicitement avant, en traitant toute classe "≠ 3" comme
1/2) **surestimait** la résistance d'une classe 4, côté dangereux. **Le
classeur Predim, lui, ne fait pas ce refus** : il continue avec W<sub>pl</sub>
quelle que soit la classe — ce module s'en écarte délibérément sur ce point
(cf. `tests/scripts/comparaison_stabilite_excel_python.py`, colonne
`classe_calculee`, pour repérer une éventuelle classe 4 sur un modèle réel).

Vérifié directement (sans GSA, `commun/stabilite_ec3/_commun.py` + la même
section IPE400 que `test_stabilite.py`, même torseur, seule la classe varie) :

| classe | module | taux retenu |
|---|---|---|
| 1 | W<sub>pl</sub> | 2,503 |
| 2 | W<sub>pl</sub> (identique à la classe 1) | 2,503 |
| 3 | W<sub>el</sub> | 2,626 (plus sévère : W<sub>el</sub> < W<sub>pl</sub>) |
| 4 | — | **refusée** (`SectionClasse4`) |

Et sur un cas réel rencontré en pratique : `10_story_frame.gwb`, barre 20 avec
la section candidate `UB1100x400x343` — classe 4 (âme), auparavant vérifiée
avec W<sub>pl</sub> (taux affiché 0,983) et **désormais refusée**. Ce candidat
ne peut donc plus être retenu par une optimisation tant que sa stabilité n'est
pas vérifiée autrement (à la main, ou en implémentant les modules efficaces).

**Le même choix W<sub>pl</sub>/W<sub>el</sub>/refus vaut aussi pour le critère
ELU « combine »** (contrainte normale combinée, `commun/criteres.py` —
critère de RÉSISTANCE DE SECTION, pas de stabilité, mais qui devait la même
cohérence : cf. son en-tête et `_classe_combine`). Deux différences avec la
stabilité, propres à ce second usage :

  - la classe y est déterminée par la case (permutation, position) qui
    gouverne le critère avec W<sub>pl</sub> (1ère passe), pas par une seule
    combinaison ELU déjà choisie en amont — le torseur qui décide de la classe
    n'est donc connu qu'après ce premier calcul (cf. `taux_par_permutation`) ;
  - la géométrie catalogue (`section_catalogue`) n'y sert QUE pour classer :
    les modules W<sub>pl</sub>/W<sub>el</sub> réellement utilisés dans le
    critère restent ceux lus dans GSA (`Zpy_m3`/`Zy_m3`...), pas ceux du CSV,
    pour ne jamais avoir deux sources de la même grandeur.

La résolution profil GSA -> (feuille, désignation) catalogue (`profil_predim`,
`nom_catalogue_par_dimensions`, `FAMILLES_CLASSEUR`, `ONGLET_PREDIM`) vit
d'ailleurs ici, dans `section_catalogue.py` — déplacée depuis `appv2/server.py`
le 01/09/2026 quand `commun/criteres.py` en a eu besoin à son tour ;
`appv2/server.py` les importe désormais sous leurs anciens noms privés.

## Conformité à l'Eurocode — ce qui est exact, ce qui ne l'est pas

Les deux implémentations partagent les mêmes hypothèses (le Python est une
traduction du classeur) : les points ci-dessous valent donc pour les **deux**,
sauf mention contraire.

**Conforme**

- M<sub>cr</sub> : formule (1) de l'Annexe MCR sans le terme C<sub>3</sub>·z<sub>j</sub>
  — correct pour une section doublement symétrique, qui est le domaine
  d'application déclaré de l'annexe.
- χ et χ<sub>LT</sub> : formule [6.49] avec α du Tableau 6.1, plafonnés à 1.
  Méthode **générale** du §6.3.2.2, pas la méthode alternative des profils
  laminés du §6.3.2.3.
- Facteurs d'interaction : Annexe B, méthode 2 (Tableaux B.1 à B.3), avec la
  ligne « Creux » pour les tubes.
- χ<sub>LT</sub> = 1 pour un CHS : un profil circulaire ne déverse pas.
- W<sub>y</sub> = W<sub>el</sub> en classe 3, W<sub>pl</sub> sinon.

**À savoir avant d'exploiter un taux**

1. **C1/C2 calculés supposent k<sub>z</sub> = k<sub>w</sub> = 1** — la norme
   l'écrit noir sur blanc : « Les valeurs de C1 et C2 ont été déterminées pour
   kz = 1 et kw = 1 ». **Tranché à la bascule : k = k<sub>w</sub> = 1 est
   imposé** (`session.py::K_DEVERSEMENT`), et les champs k / k<sub>w</sub> ont
   disparu de l'encadré Instabilité — comme C1 et C2, qui sont calculés.
   Rien n'est perdu en expressivité : k·L et L<sub>dév</sub> jouent le même rôle
   dans M<sub>cr</sub>, et L<sub>dév</sub> reste saisissable, par famille dans
   l'Opt. globale. **Attention à la reprise d'anciens calculs** : le défaut
   proposé jusque-là était k = 0,5, qui multipliait M<sub>cr</sub> par 4 ; les
   taux de déversement d'avant la bascule ne sont donc pas comparables tels
   quels, sauf sur les barres où χ<sub>LT</sub> valait déjà 1 (tous les tubes
   courts, tous les CHS).
2. **Courbe de déversement des tubes.** `Q71 = IF(h/b<=2, "a", "b")` applique à
   **toutes** les sections la règle que le Tableau 6.4 réserve aux sections en I
   **laminées** ; la norme range « autres sections » en courbe d. Pour un RHS/SHS
   la courbe retenue est donc a ou b au lieu de d : **non conservatif**. Sans
   effet sur un CHS (χ<sub>LT</sub> = 1) et sans effet non plus quand
   λ̄<sub>LT</sub> ≈ 0, ce qui est le cas de tous les tubes courts des modèles
   du projet — mais l'écart s'ouvrirait sur un tube élancé.
3. **z<sub>g</sub> = h/2 systématiquement** (`P34 = Q2/2`), c'est-à-dire charge
   appliquée au niveau de la semelle supérieure — l'hypothèse défavorable. En
   mode torseur, il n'y a pourtant **aucune charge transversale** : les efforts
   viennent de GSA. Le C2 calculé règle le problème de lui-même (μ ≈ 0 ⇒ C2 ≈ 0
   ⇒ le terme C2·z<sub>g</sub> disparaît) ; le C2 = 0,46 saisi à la main du
   classeur, lui, continue de peser.
4. **C<sub>mLT</sub> figé à 1.** Le classeur calcule la vraie valeur en `AI47`
   mais utilise toujours `AI48 = 1` dans `AH80/AH81`. Les valeurs du
   Tableau B.3 étant ≤ 1, forcer 1 agrandit le dénominateur (C<sub>mLT</sub> −
   0,25) et donc k<sub>zy</sub> : **conservatif**. Ça évite aussi la divergence
   numérique quand C<sub>mLT</sub> approche 0,25.
5. **Tableau B.2 appliqué à tout le monde.** `P36 = "oui"` par défaut
   (« sensible aux déformations par torsion »), y compris pour les tubes
   fermés, qui ne le sont pas et relèveraient du Tableau B.1. B.2 donne un
   k<sub>zy</sub> plus proche de 1, donc plus sévère : sûr, mais pas littéral.
   Le module expose le choix (`ParametresBarre.sensible_torsion`) ; appv2 ne
   l'expose pas (absent de `COEFS_STABILITE`), donc le comportement reste celui
   du classeur.
6. **Aucune des deux exemptions de la norme n'est appliquée** :
   λ̄ ≤ 0,2 (§6.3.1.2(4), flambement ignoré) et λ̄<sub>LT</sub> ≤ λ̄<sub>LT,0</sub>
   (§6.3.2.2(4), déversement ignoré). Conservatif, sans conséquence sur le
   verdict puisque χ ≈ 1 dans ce domaine.
7. **γ<sub>M0</sub> et γ<sub>M1</sub>.** Le classeur divise certaines
   résistances par γ<sub>M0</sub> **puis** par γ<sub>M1</sub> (`W6/W14`,
   `W12/W14`) ; le module Python ne divise que par γ<sub>M1</sub>. Identique
   tant que γ<sub>M0</sub> = 1 — la valeur du classeur, jamais modifiée par
   appv2. Le harnais de comparaison le vérifie implicitement (écart nul).
8. **Curiosité inoffensive du classeur.** `AB78` (k<sub>yy</sub>, classe 1/2)
   teste `Cmy(1+(λ̄y−0,2)n) ≤ Cmy(1+0,8·λ̄y·n)` mais renvoie `Cmy(1+0,8n)` dans
   la branche `sinon` — le test porte un λ̄y que la valeur n'a pas. Sans
   conséquence : la bascule a lieu exactement en λ̄y = 1, où les deux
   expressions coïncident avec le `min()` du Tableau B.1. Le module Python
   écrit le `min()` littéral de la norme.

## Les trois questions qui bloquaient la bascule, et comment elles ont été tranchées

1. **k et C1/C2** → k = k<sub>w</sub> = 1 imposé, C1/C2 calculés (cf. point 1
   ci-dessus). Les quatre champs ont disparu de l'interface.
2. **La classe de section**, que le classeur fournissait → calculée par
   `classe_section.py`, port intégral de l'onglet `Calcul classe`.
   **63/63 identiques** au classeur sur les trois modèles de référence. Elle
   n'est pas cosmétique : c'est elle qui décide entre W<sub>el</sub> (classe 3)
   et W<sub>pl</sub> (classes 1, 2 et — dans ce classeur — 4).
3. **Le repli « section absente de l'onglet Predim »**
   (`BeamWorkbook._section_au_dessus`, qui substituait la section supérieure la
   plus proche) → **il disparaît**, et c'est une simplification, pas une perte :
   il n'existait que pour rattraper un désaccord entre le catalogue et sa copie
   dans le classeur. Le catalogue étant désormais la seule source, le désaccord
   n'est plus possible. L'autre repli, celui de
   `section_catalogue.py::profil_predim` pour les profils **saisis à la main**
   (`STD CHS 323,9 5,4` → plus petite section catalogue qui les couvre), reste
   en place : lui répond à un vrai manque, une section sans désignation
   catalogue n'a aucune ligne où lire ses caractéristiques.

## Où le module est utilisé

| appelant | usage |
|---|---|
| `appv2/server.py::_session_stabilite` | **le moteur de l'app** — onglets Performances, Optimisation et Opt. globale (stabilité EC3 §6.3) |
| `commun/criteres.py::_classe_combine` | classe de section pour le critère ELU « combine » (résistance de section §6.2, pas §6.3) — mêmes `classe_section`/`section_catalogue`, cf. plus haut |
| `appv2/server.py::ouvrir_excel_barre` | calcule C1/C2 puis les **recopie** dans le classeur ouvert pour la vérification manuelle |
| `tests/scripts/comparaison_stabilite_excel_python.py` | le compare au classeur (qui reste l'oracle du test, donc pas du code mort) |
| `visualisation/*.py` | courbes et cartes de taux, sans Excel |
