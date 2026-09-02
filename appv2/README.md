# appv2 — dimensionneur GSA par groupes de barres

Deuxième version de l'interface web. La première, **archivée dans `app_old/`**,
reste utilisable telle quelle sur un autre port : les deux applications sont
indépendantes et peuvent servir en même temps.

```bash
venv\Scripts\python.exe appv2\server.py
```

→ http://localhost:8767 (`--port` pour en changer, `--no-browser` pour ne pas
ouvrir le navigateur). Configuration `dimensionneur-v2` dans
`.claude/launch.json`.

## La page : entrées à gauche, sorties à droite

```
┌──────────────────────────────────────────────────────────────────────────┐
│  elioth · PFE                        [modèle ▾] [Charger] [déposer .gwb]  │  ← bandeau
├───────────────────────────────────────┬──────────────────────────────────┤
│  GROUPE ÉTUDIÉ  [ Membrure haute ▾ ]  │  ┌ Vue 3D ┬ Détail optimisation ┐ │
│  ┌Résumé┬Critères┬Perf.┬Optim┬Glob.┐  │  │                              │ │
│  │                                 │  │  │      (la structure, ou       │ │
│  │   ENTRÉES : ce qu'on décide     │  │  │   le tableau complet des     │ │
│  │   + le RÉSUMÉ des résultats     │  │  │   sections essayées)         │ │
│  └─────────────────────────────────┘  │  └──────────────────────────────┘ │
└───────────────────────────────────────┴──────────────────────────────────┘
```

**Le chargement du modèle est dans le bandeau**, en haut à droite : il n'est
dans aucune des deux colonnes, parce que les deux en dépendent.

**Le groupe étudié** est épinglé au-dessus des onglets d'entrée, et non dans
l'un d'eux : c'est la maille de tout le raisonnement (Performances et
Optimisation en dépendent), il doit rester visible au moment où l'on lit ses
propres résultats. Sur le gymnase (2406 barres acier, enveloppe ELU à 26
permutations) : ~8 s pour un groupe de 181 barres, ~55 s pour le modèle entier.

**Cinq onglets d'entrée** (colonne de gauche) :

| onglet | ce qu'on y fait |
|---|---|
| **Résumé** | tables du modèle (nœuds, éléments, groupes, sections, matériaux, cas de charge, combinaisons) et drapeaux de contrôle |
| **Critères** | tout ce qu'on impose au calcul : combinaisons ELU/ELS, taux limite et f<sub>y</sub>, critères ELU comparés, limites ELS par nœud nommé, coefficients et longueurs d'instabilité |
| **Performances** | mesure du groupe actuel : 4 critères ELU, stabilité EC3, bilan ELS |
| **Optimisation** | réduction d'**un** groupe — commandes + **résumé** (cartes de statistiques) |
| **Opt. globale** | réduction de **plusieurs familles** — commandes, **résumé**, **graphique** poids/essai, bilan par famille |

**Deux onglets de sortie** (colonne de droite, façon navigateur) :

| onglet | contenu |
|---|---|
| **Vue 3D** *(par défaut)* | la structure, groupe surligné, sections extrudées à la demande, capture PNG |
| **Détail optimisation** | le tableau **complet** de la dernière optimisation — une ligne par section essayée, ~39 colonnes pour un groupe (~38 pour la globale), exportable en CSV (« Exporter (Excel) ») ; c'est là qu'on **sélectionne la section à charger dans le modèle**. Quatorze de ces colonnes portent sur les deux cases dimensionnantes — celle de l'ELU et celle de la stabilité, souvent différentes — à côté de leur combinaison et de leur barre déjà affichées : le **torseur** (N, V<sub>y</sub>, V<sub>z</sub>, M<sub>xx</sub>, M<sub>y</sub>, M<sub>z</sub>) et le **lieu** le long de la barre (0/25/50/75/100 %) où cette case a été lue. Une bascule *Un groupe / Globale* choisit laquelle des deux optimisations est montrée ; elle passe automatiquement sur celle qu'on vient de lancer |

Le détail n'est jamais recalculé à droite : les deux colonnes lisent les
**mêmes** objets (`dernierOptim`, `dernierGlobal`). La droite en montre plus de
colonnes, pas d'autres chiffres — elles ne peuvent donc pas diverger.

La colonne de sortie est **collante** et défile dans son propre cadre : la 3D
ou le tableau restent sous les yeux pendant qu'on fait défiler les entrées. En
dessous de 1180 px de large, la page repasse sur une seule colonne, les sorties
au-dessus.

## Ce qui change par rapport à `app_old/`

| | `app_old/` | `appv2/` |
|---|---|---|
| Maille de raisonnement | modèle entier | **un groupe** de barres à la fois |
| Groupes | listes GSA (optimisation) | **propriété de section** : un groupe = toutes les barres qui portent la même section |
| Résultats lus | éléments **et** membres | **éléments seulement** |
| Critère ELU | contrainte combinée seule (onglet Performances v2) | **4 critères comparables** : combiné, torsion, cisaillement, von Mises |
| Stabilité EC3 §6.3 | absente | **calculée** (classeur Predim), colonne du tableau et condition de retenue des optimisations |
| Disposition | une colonne + panneau 3D | **entrées / sorties**, 5 onglets + 2 onglets |

## Les quatre critères

Pour chaque élément, la combinaison dimensionnante est cherchée sur **toutes les
permutations** de l'enveloppe ELU × **5 positions** (0/25/50/75/100 %) — aucune
réduction max/min, donc des efforts qui coexistent physiquement (raison d'être
de `commun/gsa_bridge/permutations.py`, cf. la note « l'enveloppe réduite n'est
pas une borne »).

| critère | formule | source |
|---|---|---|
| `combine` | max(\|C1\|, \|C2\|) / f_y, avec A = N/aire, B = \|My\|/W_y + \|Mz\|/W_z | efforts, module **plastique ou élastique selon la classe** |
| `torsion` | (\|Mxx\|/Wt) / (f_y/√3) — EC3 §6.2.7 | efforts |
| `cisaillement` | max(\|Vy\|/Avy, \|Vz\|/Avz) / (f_y/√3) — EC3 §6.2.6 | efforts (la ligne dit l'axe qui gouverne) |
| `von_mises` | VM / f_y | contrainte équivalente **lue dans GSA** (`Element1dDerivedStress`) |

`combine` est toujours pris en compte (c'est la référence) ; les trois autres
sont des cases à cocher. Cocher un critère **recalcule la combinaison
dimensionnante** de chaque barre — celle qui maximise le plus élevé des taux
cochés — mais **sans aucun appel GSA** : le serveur envoie les quatre d'un coup,
et le maximum d'un ensemble de critères est le maximum des maxima
(cf. `commun/criteres.py`).

**`combine` suit la classe de section EC3 §5.5, depuis le 01/09/2026** —
module **plastique** (W<sub>pl</sub>) en classe 1 et 2, **élastique**
(W<sub>el</sub>) en classe 3 ; une section de **classe 4 est rejetée** (le
critère devient indisponible, « n/a » dans le tableau, comme un profil dont
l'aire de cisaillement est inconnue) plutôt que d'être évaluée avec une
hypothèse fausse. La classe est déterminée à la case (permutation, position)
qui gouverne le critère calculé une 1<sup>ère</sup> fois avec W<sub>pl</sub> ;
si elle vaut 3, le critère est **recalculé en entier avec W<sub>el</sub>**
(la case gouvernante peut changer — A et B ne changent pas dans les mêmes
proportions). Même géométrie catalogue que la stabilité EC3 §6.3
(`commun/stabilite_ec3/section_catalogue.py`, cf. plus bas), utilisée
UNIQUEMENT pour classer : les modules W<sub>pl</sub>/W<sub>el</sub>
effectivement employés restent ceux lus dans GSA. Un profil non transposable
vers une désignation catalogue (forme en I/H saisie à la main — cas rare,
inexistant en pratique) rend aussi le critère indisponible, faute de
géométrie pour le classer.

**À savoir avant d'interpréter l'écart von Mises / combiné.** Le von Mises de
GSA est élastique et local (contrainte en un point de la section) ; le critère
combiné est une résistance de section au module plastique. Sur un CHS le facteur
de forme Wpl/Wel vaut ~1,3 : le von Mises peut donc dépasser le taux combiné de
~30 % en flexion pure, sans qu'aucun cisaillement n'intervienne. Sur les profils
ouverts (`STD CH`, `STD I`) l'écart est encore plus marqué. Ce n'est pas une
incohérence de calcul — c'est ce que la comparaison est là pour montrer.

**Ces quatre critères sont des résistances de SECTION** (EC3 §6.2 seulement,
comme `commun/ec3.py`) : ni flambement, ni déversement, ni interaction entre
efforts. La stabilité d'ÉLÉMENT (§6.3) est bien calculée, mais c'est un
critère à part — sa propre colonne dans le tableau, son propre encadré de
réglages, et elle est vérifiée par le classeur Predim (Excel), pas ici.
Voir « Stabilité EC3 » plus bas.

## Critères ELS : des nœuds nommés dans le modèle

L'ELS n'est plus une flèche de barre comparée à `L/dénominateur`. Les critères
de service sont **déclarés dans le modèle GSA en nommant des nœuds**, et la
page ne renseigne, par critère trouvé, que la **direction comparée** (axe
global x, y ou z) et la **limite en millimètres** :

| Nom des nœuds | Ce qui est comparé à la limite |
|---|---|
| `ELS_glob_X` | le **déplacement** de chaque nœud portant ce nom, dans la direction choisie. Ex. « tous les nœuds `ELS_glob_3` se déplacent de moins de 6 mm suivant z ». |
| `ELS_3pts_X` | pour les **trois** nœuds portant ce nom : la distance du point du milieu **déplacé** à sa projection sur la droite formée par les deux extrémités — la flèche **relative à la corde**. Une descente d'ensemble de 30 mm sans déformation ne consomme rien ; un ventre de 6 mm entre deux appuis eux-mêmes descendus le consomme entièrement. |

`X` est un indice libre (un chiffre en pratique) : plusieurs critères de la
même famille coexistent. Pour un critère 3 points, le milieu et les extrémités
sont identifiés par la **géométrie** (les deux nœuds les plus éloignés l'un de
l'autre sont les extrémités), pas par l'ordre de numérotation ; l'écart est pris
à l'abscisse du milieu sur la corde **non déformée** (cf. `commun/els_noeuds.py`).

Les déplacements sont lus **par permutation**, jamais sur l'enveloppe repliée
max/min : pour un critère 3 points, l'écart n'a de sens que si les trois
déplacements viennent de la **même** sous-combinaison.

Conséquence sur l'affichage : l'ELS a **son propre tableau** (une ligne par
critère : déplacement, limite, nœud gouvernant, sous-combinaison, taux,
verdict), et non des colonnes du tableau par barre — il qualifie la structure
entière, pas un groupe de barres. Le verdict d'une barre ne porte donc plus que
sur l'ELU et la stabilité EC3.

Une **seule** combinaison ELS sert à lire ces déplacements ; elle reste
**facultative** : sans elle le tableau ELU est complet, seul le bilan de service
est vide (des modèles réels n'ont aucune combinaison ELS). Un modèle sans nœud
nommé `ELS_*` n'a simplement aucune exigence de service — ce n'est pas un
échec, et le taux ELS vaut alors `null`, pas zéro.

## Stabilité EC3 §6.3 — calculée en Python, vérifiable dans Excel

La colonne « Taux stabilité » de l'onglet Performances et la condition de
retenue des deux optimisations viennent de **`commun/stabilite_ec3`** (Python
pur) depuis le 01/09/2026. Avant, c'était le classeur Predim piloté par COM.
La bascule tient dans une fonction, `server.py::_session_stabilite()` : les
deux moteurs ont la même interface, revenir en arrière est une ligne.

Pourquoi basculer :

- **≈ 2 × 10<sup>4</sup> fois plus rapide** : 0,60 s par barre pour le
  classeur, ~30 µs pour le module. Le mode « stabilité approfondie »
  (5 barres × toutes les permutations, à chaque candidat) coûtait ~80 s par
  section essayée sur une enveloppe à 26 permutations ; il ne coûte plus rien ;
- **même résultat** : à coefficients égaux, écart nul (0,0000 %) sur 63 barres
  et 3 modèles, profils en I comme tubes CHS/RHS/SHS — et la **classe de
  section**, que le classeur calculait, est retrouvée 63/63 ;
- plus de verrou Excel sur les calculs, plus de classeur à ouvrir, plus
  d'erreur COM transitoire à encaisser.

**Ce qui change dans l'interface.** C1, C2, k et k<sub>w</sub> ont disparu de
l'encadré Instabilité : C1 et C2 sont **calculés barre par barre** depuis son
diagramme de moment (§3.5 de l'Annexe MCR), et k = k<sub>w</sub> = 1 est imposé
— c'est le domaine de validité de ces formules. Restent à saisir les longueurs
L<sub>fy</sub>, L<sub>fz</sub>, L<sub>dév</sub> (ou « longueur de la barre ») et
le type de répartition de charge. Une longueur de déversement différente de la
portée se dit avec L<sub>dév</sub>, qui joue le même rôle que k·L dans
M<sub>cr</sub>.

> **Comparer avec un calcul d'avant la bascule** demande de la prudence : le
> défaut proposé était k = 0,5, qui multiplie M<sub>cr</sub> par 4. Les taux de
> déversement ne sont pas comparables tels quels — sauf sur les barres où
> χ<sub>LT</sub> valait déjà 1, c'est-à-dire tous les tubes courts et tous les
> CHS, où les valeurs sont rigoureusement inchangées.

**Le bouton « Ouvrir dans Excel » reste, et devient cohérent.** Sélectionner une
barre dans le tableau Performances ouvre toujours le classeur Predim pré-rempli
avec son torseur — mais il reçoit désormais **les C1/C2 qui viennent d'être
calculés pour elle** (et k = k<sub>w</sub> = 1). Sans ce report il repartirait
de ses valeurs d'abaque et afficherait un autre taux que le tableau : mesuré
sur `10_story_frame`, 17 % d'écart sur la première barre. Avec le report, le
classeur retrouve le taux du module à 0,0000 % (vérifié par
`comparaison_stabilite_excel_python.py --report`). Le panneau affiche à côté du
torseur les coefficients reportés, la classe de section et les quatre taux à
retrouver dans le classeur.

Le détail, les points de conformité à l'Eurocode et les trois questions
tranchées à la bascule : **`commun/stabilite_ec3/README.md`**.

**Le même bouton existe dans le détail Optimisation (« un groupe » et
« globale »), depuis le 01/09/2026.** Sélectionner une ligne (clic, comme pour
« Charger dans le modèle ») fait apparaître « Ouvrir dans Excel » à côté du
bouton de chargement. Contrairement au bouton de Performances, **aucun rappel
GSA** : la ligne sélectionnée porte déjà tout ce qu'il faut — torseur
gouvernant la stabilité, C1/C2/k/k<sub>w</sub>, classe — puisque c'est
exactement ce que le tableau affiche (`JobOptim.stab`/`JobGlobal.essais`,
remplis pendant le calcul). Rouvrir GSA recalculerait la même chose plus
lentement, avec un risque réel de diverger si le modèle a bougé depuis. Seule
différence avec le bouton de Performances : pas de diagramme de moment à 3
points (une seule case connue, pas les trois) — les cellules D31:D33/D35:D37
restent VIDES plutôt que de recevoir un faux plat, et le classeur retombe sur
ses C<sub>m,y</sub>/C<sub>m,z</sub> manuels (1,0), sans toucher à C1/C2/k/k<sub>w</sub>,
recopiés tels quels. Le bouton reste désactivé, avec le motif affiché, tant
que la stabilité n'a pas été vérifiée pour la ligne sélectionnée (case
« prise en compte » décochée, ou candidat déjà en échec ELU/ELS).

## Ce qu'une optimisation vérifie — et l'instabilité, au choix

Les deux onglets d'optimisation (un groupe, ou plusieurs familles) reposent sur
la même mécanique : pour **chaque** section candidate, la propriété de section
est réellement modifiée dans la copie GSA, **l'analyse est relancée**, et le
candidat n'est retenu que s'il passe :

| critère | portée | source |
|---|---|---|
| **ELU** | toutes les barres du périmètre, sur toutes les permutations | `commun/criteres.py` (combiné, torsion, cisaillement — jamais von Mises : il demanderait les contraintes dérivées de GSA, non extraites ici) |
| **ELS** | la structure entière — le taux affiché est le **maximum des critères ELS déclarés** (nœuds nommés) | `commun/els_noeuds.py::taux_max` |
| **stabilité EC3** | **seulement si la case « prise en compte » de l'encadré Instabilité est cochée** | `commun/stabilite_ec3` (Python) |

La case « prise en compte » (onglet **Critères**, encadré Instabilité) est le
commutateur : **décochée, aucun classeur Excel n'est ouvert** et une section
est retenue sur ELU + ELS seuls (bien plus rapide, mais ni flambement ni
déversement ne sont vérifiés — la colonne de stabilité affiche « non prise en
compte », pas un tiret ambigu). L'onglet Performances n'est pas concerné : il
*mesure*, il ne décide pas, et sa colonne de stabilité reste calculée dans tous
les cas.

## Onglet « Opt. globale » — plusieurs familles, dans un ordre choisi

L'onglet Optimisation réduit **une** famille en laissant tout le reste figé.
Celui-ci en enchaîne **plusieurs** :

- un tableau liste les familles acier du modèle. Une case pour l'inclure, une
  colonne ↑/↓ pour **changer leur ordre** ;
- un menu choisit l'**algorithme** (rempli par le serveur depuis
  `ALGOS_GLOBAUX` : en ajouter un ne touche pas au HTML) ;
- quand l'instabilité est prise en compte, chaque ligne porte ses propres
  **longueurs de flambement/déversement** (L<sub>fy</sub>, L<sub>fz</sub>,
  L<sub>dév</sub>, ou « L = longueur de la barre ») — vide = la valeur de
  l'encadré Instabilité. Les coefficients k, k<sub>w</sub>, C1, C2 et le type de
  charge restent communs.

**Algorithme « escalier »** (`server.py::_algo_escalier`) : dans l'ordre choisi,
on descend le catalogue de la famille courante (des sections les plus lourdes
vers les plus légères) tant que la structure vérifie tout, et on passe à la
suivante après `profondeur` échecs consécutifs (10 par défaut, comme l'onglet
Optimisation). Une famille est descendue **en entier**, pas arrêtée au premier
échec : les catalogues mélangent hauteur et épaisseur, une section plus légère
d'une autre série peut passer là où la précédente a échoué.

Deux points qui font la justesse du résultat :

1. **L'ELU est vérifié sur tout le périmètre, pas sur la seule famille qu'on
   allège.** Alléger une famille redistribue les efforts sur les autres, et une
   famille déjà optimisée peut redevenir insuffisante. Par défaut le périmètre
   est celui des familles cochées ; une case l'étend à **toutes** les familles
   acier du modèle (celles qu'on n'optimise pas subissent quand même la
   redistribution).
2. **La section retenue reste en place pour les familles suivantes** : chacune
   est optimisée sur la structure déjà allégée. C'est ce qui rend **l'ordre
   décisif** — l'étude de sensibilité de `comparaison_modele/` mesure un facteur
   3,4 entre deux ordres sur le même treillis.

À gauche, la page affiche l'**état initial** (et prévient si le modèle de
départ ne vérifie déjà pas tout : aucune section plus légère ne pourrait alors
être retenue), un **bilan par famille** mis à jour en continu, l'**état final**
revérifié sur le modèle optimisé, et un **graphique** : un point par essai —
en abscisse l'ordre des essais, en ordonnée le poids du périmètre optimisé dans
l'état où l'essai a laissé le modèle, en couleur le verdict (vert = retenu,
rouge = refusé). Le trait suit le meilleur poids valide atteint, c'est-à-dire
la descente réelle par opposition au nuage des essais refusés ; le tiret
horizontal marque le poids de départ. Survoler un point donne la famille, la
section, les trois taux et le verdict.

À droite, dans l'onglet **Détail optimisation**, le **journal complet des
essais** : une ligne par section testée, celle finalement retenue marquée ★,
avec pour chaque essai les trois taux, leurs combinaisons gouvernantes, la
barre gouvernante — et la **famille** qui gouverne l'ELU, mise en avant quand
ce n'est pas celle qu'on allège (c'est le signe visible de la redistribution).
« Charger le résultat dans le modèle » écrit `<modèle>_opti.gwb` avec **toutes**
les sections retenues et l'ouvre dans GSA (le fichier source n'est jamais
modifié).

## Organisation

```
appv2/
  server.py            serveur stdlib, thread GSA unique (même architecture qu'app_old/)
  static/
    index.html         bandeau + 5 onglets d'entrée + 2 onglets de sortie
    app.js             critère retenu décidé CÔTÉ PAGE (cf. son en-tête)
    style.css          charte d'app_old/ reprise telle quelle, étendue en fin de fichier
    viewer3d.js        copie d'app_old/ + Vue3D.surligner / redessiner
```

Modules de calcul **partagés** avec `app_old/` (une seule implémentation par
formule, principe du dépôt) :

- `commun/criteres.py` — **nouveau** : les 4 critères, leurs tableaux
  (permutation × position) et l'argmax de chacun ; depuis le 01/09/2026,
  `combine` classe la section (EC3 §5.5) via `commun/stabilite_ec3` pour
  choisir W<sub>pl</sub>/W<sub>el</sub> ou rejeter une classe 4 ;
- `commun/gsa_bridge/permutations.py` — `contraintes_derivees_par_permutation`
  **ajoutée** (SEy, SEz, St, VM par permutation, marqueur `VonMisesStress`) ;
- `commun/dimensionnant.py`, `commun/ec3.py`, `commun/dimensionner.py` —
  **inchangés au calcul** (`contraintes_c1_c2` acceptait déjà n'importe quel
  module de flexion — seul son docstring a été généralisé) ;
- `commun/stabilite_ec3/` — **stabilité EC3 §6.3**, le moteur de l'app
  (`SessionStabilitePython`), avec le calcul de C1/C2 et de la classe de
  section — `section_catalogue.py` y porte aussi, depuis le 01/09/2026, la
  résolution profil GSA → désignation catalogue (`profil_predim`, déplacée
  depuis `appv2/server.py` : `commun/criteres.py` en a besoin lui aussi) ;
- `commun/excel_bridge/stabilite.py` — la même chose par le classeur Predim
  (`SessionStabilite`) : plus branchée dans l'app, mais toujours l'**oracle**
  du test de comparaison ;
- `commun/els_noeuds.py` — critères de service par nœuds nommés.

## API

| route | rôle |
|---|---|
| `GET /api/etat` | modèles `.gwb`, critères par défaut, libellés des critères, **algorithmes de l'Opt. globale** (`ALGOS_GLOBAUX`) et profondeur par défaut |
| `GET /api/progression` | avancement des calculs longs, par canal |
| `GET /api/resume?modele=` | résumé complet — la page en déduit elle-même les groupes |
| `GET /api/vue-sections?modele=` | géométrie 3D réelle (sections extrudées) |
| `POST /api/elu/start` | `{modele, sections?: [id], criteres?, nuance_modele?, elu?, els?, criteres_els?}` → `{job}` |
| `GET /api/elu/poll?job=&depuis=` | nouvelles lignes, meta, état |
| `POST /api/elu/stop` | coupe le calcul entre deux paquets de barres |
| `POST /api/optim/start` · `poll` · `stop` · `charger-section` | optimisation d'**un** groupe ; chaque candidat porte `aire_m2`, les trois taux et leurs gouvernants |
| `POST /api/excel-barre` | ouvre le classeur Predim **visible**, pré-rempli avec le torseur d'une barre sur sa combinaison dimensionnante |
| `POST /api/excel-candidat` | `{contexte: "optim"\|"global", job, nom, famille? (global)}` → ouvre le classeur Predim pour la ligne sélectionnée du détail Optimisation, **sans rouvrir GSA** (torseur, C1/C2/k/kw et classe déjà connus du job) |
| `POST /api/global/start` | `{modele, familles: [{section, coefs?}] DANS L'ORDRE, algo, profondeur?, avec_stabilite?, elu_perimetre_complet?, …}` → `{job}` |
| `GET /api/global/poll?job=&depuis=` | nouveaux essais, bilan par famille, meta (états initial/final, gain), état ; chaque essai porte `poids_modele_kg` (l'ordonnée du graphique) |
| `POST /api/global/stop` | coupe entre deux essais |
| `POST /api/global/charger` | écrit `<modèle>_opti.gwb` avec toutes les sections retenues et l'ouvre dans GSA |
| `POST /api/upload?nom=` | dépose un `.gwb` dans `GSA_model/` |

## Vérifications faites

- **Élément 2169 du gymnase** (`P1_sup`, `STD CHS 323,9 5,4`, ELU `C181`) :
  permutation `C165` (1,35G_avant+1,5S+0,9V180(+)), position 100 %,
  N = −190,2 kN, My = −5,83 kNm, **taux combiné 0,197** — identique au cas de
  référence établi avec `tests/scripts/elu2_diagnostic_barre.py`. Le von Mises
  de GSA y vaut 49,1 MPa, cohérent avec la contrainte combinée **élastique**
  (49,59 MPa) du calcul à la main.
- Les 4 critères recalculés à la main sur une section fictive : écart nul.
- `Pratt_1` : résultats symétriques sur la membrure basse (barres 1↔6, 2↔5,
  3↔4), comme la structure.
- Modèle entier du gymnase (2406 barres, 18 profils dont `STD I`, `STD CH`,
  `STD A`) : aucun critère perdu, aucune erreur.
- `10_story_frame` (2 groupes en `UB-AM`, `BEAM 1-3S`/`BEAM 7-9S`) : la
  stabilité EC3 échouait ("Le classeur Predim n'a pas d'onglet pour le
  profil") — `_FAMILLES_CLASSEUR`/`_profil_predim`/`_famille_catalogue` ne
  reconnaissaient que les 7 onglets natifs du classeur (`IPE IPN CHS RHS SHS
  HD HE`), pas les préfixes `UB`/`UC` des profils ajoutés à la main aux
  feuilles HE/HD du catalogue (cf. `catalogues/README.md`). Corrigé par
  `_ONGLET_PREDIM` (`UB`→`HE`, `UC`→`HD`, même mécanisme que `SHS`→onglet `RHS`) :
  stabilité lisible 3/3 sur les deux groupes, et l'onglet Optimisation
  explore bien le catalogue `HE` (candidats `HE...` et `UB...` mélangés) pour
  un groupe en `UB`.
- `10_story_frame`, groupe entier (30 barres) : la stabilité EC3 est tombée
  une fois à « 0/30 » avec `(-2147023174, 'Le serveur RPC n'est pas
  disponible.', None, None)` — erreur COM **transitoire** à l'activation
  d'Excel (`BeamWorkbook.open`, `commun/excel_bridge/bridge.py`), observée
  après plusieurs sessions Excel démarrées coup sur coup (Performances ×2 +
  Optimisation dans la même minute). Comme `session.open()` était hors du
  `try/except` par barre, le premier échec faisait tomber TOUT le calcul
  (0 barre lue) au lieu d'une seule. Corrigé par un retry (3 essais, 1,5 s de
  pause, nettoyage de l'App/Book partiels entre deux essais) dans
  `BeamWorkbook.open()` — bénéficie aussi à `predim.py::ouvrir_predim` et aux
  scripts CLI de `commun/excel_bridge/scripts/`. Reproduit et revérifié
  ensuite sur le même groupe : « stabilités EC3 : 30/30 ».
- **Tubes carrés (SHS) : la stabilité EC3 n'était JAMAIS calculée** (31/08).
  `_profil_predim` et `_nom_predim_depuis_catalogue` renommaient la
  désignation `SHS…` en `RHS…` avant de la chercher dans le classeur. Or le
  classeur Predim **régénéré** garde les noms du catalogue : ses 251 tubes
  carrés sont rangés dans l'onglet RHS sous `SHS70x70x8`, `SHS100x100x5`…,
  aucun `RHS<c>x<c>x…`. D'où « Designation de profil introuvable dans l'onglet
  'RHS' : 'RHS70x70x8' », **sans même le repli conservatif** de
  `BeamWorkbook._section_au_dessus` (qui cherche la désignation demandée dans
  le catalogue partagé, où `RHS70x70x8` n'existe pas davantage). Le renommage
  datait d'un classeur antérieur ; seul l'ONGLET change désormais
  (`_ONGLET_PREDIM`, exactement comme `UB`/`UC`), jamais le nom. Vérifié sur
  `Pratt_1_ELS_test`, groupe `Membrure haute` (`SHS70x70x8`) : « stabilités
  EC3 : 4/4 » (0/4 avant), taux 0,886 « Fléchi + comprimé yy ».
- **Opt. globale, `Pratt_1_ELS_test`** (31/08) : familles `Membrure haute`
  puis `Membrure basse`, algorithme escalier, profondeur 10, **sans**
  stabilité — 16 sections essayées, `Membrure haute` passe de `SHS70x70x8` à
  `RHS100x50x7.1` (− 2,6 %, 1,5 kg), `Membrure basse` reste inchangée (ses
  2 candidats plus légers dépassent l'ELU). État final revérifié :
  ELU 0,899 ≤ 0,9 — **exactement celui du candidat retenu**, ce qui prouve que
  la section retenue est bien remise en place après les 10 échecs qui ont clos
  la famille. L'ELU de `Membrure basse` passe de 0,832 à 0,829 sous l'effet de
  l'allègement de l'autre famille : la redistribution est bien prise en compte.
  Même modèle, même famille, **avec** stabilité : `SHS70x70x8` 0,886,
  `RHS100x50x7.1` 0,972 → retenue. Avec L<sub>fy</sub> = L<sub>fz</sub> = 2 m
  et L<sub>dév</sub> = 1,5 m saisis **sur la ligne de la famille**,
  `RHS90x50x8` passe de 0,941 à 1,436 : les paramètres par famille agissent.
- Onglet Optimisation, même groupe, case « prise en compte » **décochée** :
  aucun classeur Excel ouvert, verdict sur ELU + ELS seuls, colonne de
  stabilité « non prise en compte » — section recommandée `RHS100x50x7.1`,
  la même que celle retenue par l'onglet Opt. globale (deux chemins de calcul
  indépendants, même résultat).
- **Réorganisation entrées/sorties** (01/09), vérifiée dans l'app en marche sur
  `Pratt_1_ELS_test` : deux colonnes de 745 px à 1600 px de large, les cinq
  onglets d'entrée sur une seule ligne, le canvas 3D à 744 × 674 px avec une
  taille de rendu correcte (1116 × 1011 à dpr 1,5). La page **ne défile jamais
  horizontalement** ; ce sont les tableaux détaillés qui défilent dans leur
  cadre. Optimisation du groupe `Membrure haute` : 14 candidats, en-tête et
  lignes à **25 colonnes** exactement, ligne recommandée `RHS100x50x7.1`
  surlignée, clic → panneau « Charger dans le modèle ». Opt. globale sur les
  deux membrures : 16 essais, **24 colonnes**, graphique à 16 points (3 validés,
  13 refusés) dont la ligne du meilleur poids est bien monotone décroissante
  (81 → 79 kg), et les deux exports CSV cohérents (26 et 28 colonnes, toutes les
  lignes de la bonne longueur). Onglet Performances inchangé : 4 barres, 4/4
  stabilités EC3, bilan ELS à 2 critères.
- **Redessin de la vue 3D** : le canvas remplit maintenant une demi-page souple
  au lieu d'une hauteur fixe. Sans `ResizeObserver`, sa taille de rendu restait
  celle du dernier dessin (mesuré : backing 376 × 480 pour un affichage
  744 × 674, soit une image étirée) — `Vue3D.redessiner()` est appelée au retour
  sur l'onglet, et un `ResizeObserver` couvre le redimensionnement de la fenêtre.
- **Stabilité EC3, Excel contre Python** (01/09,
  `tests/scripts/comparaison_stabilite_excel_python.py`) : à coefficients
  égaux, **0,0000 %** d'écart sur 63 barres et 3 modèles — `10_story_frame`
  (30 `HE1000M`, `C6`), `Pratt_1_ELS_test` (21 `RHS`/`SHS`, `C1`), gymnase
  `P1_sup` (12 `CHS324x5.6`, `C281`). Le classeur reste ~2 × 10⁴ fois plus
  lent (0,60 s/barre contre 32 µs). Détail : `commun/stabilite_ec3/README.md`.
- **Bascule de la stabilité vers `commun/stabilite_ec3`** (01/09), vérifiée
  dans l'app en marche sur `Pratt_1_ELS_test`. Onglet Performances, groupe
  `Membrure haute` : 4/4 stabilités, `SHS70x70x8` à **0,886 « Fléchi + comprimé
  yy »** — *exactement* la valeur que donnait le classeur avant la bascule
  (C1/C2 et k n'ont aucune influence sur ce tube, dont le déversement vaut
  0,091 et le χ<sub>LT</sub> 1). La réponse porte désormais C1, C2, M<sub>cr</sub>,
  la classe (âme et semelle) et f<sub>y</sub>. Onglet Optimisation, même groupe,
  **stabilité approfondie** : mêmes 3 sections retenues qu'avant, mêmes taux
  (0,886 / 0,941 / 0,972). Opt. globale, deux familles, **stabilité
  approfondie** : **39 s pour 16 essais** — le mode qui coûtait ~80 s par
  section essayée —, `RHS100x50x7.1` retenue, état final ELU 0,8993 · ELS
  0,3312 · stabilité 0,972, identique au résultat d'avant la bascule.
- **Report des coefficients vers Excel** : bouton « Ouvrir dans Excel » sur la
  barre 12 → le classeur s'ouvre avec le torseur, les diagrammes de moment
  **et** C1 = 1,151 / C2 = 0,012 / k = k<sub>w</sub> = 1 calculés pour elle ; le
  panneau récapitule les quatre taux à y retrouver. Vérifié par
  `comparaison_stabilite_excel_python.py --report` : sur `10_story_frame`
  (profils en I) le report change le taux du classeur sur **8/8** barres — 0,650
  → 0,556 sur la première, soit 17 % — et l'aligne sur le module à
  **0,0000 %** ; sur `Pratt_1_ELS_test` (tubes) il ne change rien sur 8/8,
  leur déversement n'étant pas actif.
- **12 colonnes d'efforts dans le tableau détaillé** (01/09), vérifiées dans
  l'app en marche sur `Pratt_1_ELS_test`. Onglet Optimisation, groupe
  `Membrure haute`, stabilité approfondie : la section retenue
  `RHS100x50x7.1` montre le même torseur (N = −336,56 kN, M<sub>y</sub> =
  −1,765 kNm) pour l'ELU et pour la stabilité — cohérent, c'est la même barre
  (12) et la même combinaison (C1) qui gouvernent les deux, ce que le modèle
  d'essai (une seule permutation) rend visible. Un candidat qui échoue déjà
  ELU/ELS (`RHS150x100x4`) affiche bien ses efforts ELU (N = −334,34 kN,
  M<sub>y</sub> = −4,698 kNm) et six « — » sur les colonnes de stabilité,
  jamais calculée pour lui. Même vérification sur l'Opt. globale (essais et
  bilan) : 36 colonnes par ligne, cohérentes avec l'en-tête, mêmes efforts
  retrouvés sur `RHS100x50x7.1`. Les deux exports CSV (« Exporter (Excel) »)
  portent les mêmes 12 colonnes (`elu_N_kN`… `stab_Mz_kNm`), toutes les
  lignes de la longueur de l'en-tête.
- **Critère `combine` classé par section (01/09)**, vérifié sans GSA sur le
  catalogue réel : `HE600M` à N = −500 kN / M<sub>y</sub> = 100 kNm reste
  classe 1 (taux identique, au chiffre près, au calcul Wpl d'avant) ;
  `UB1100x400x343` (le candidat classe 4 déjà repéré côté stabilité, cf.
  `commun/stabilite_ec3/README.md`) est classe 1 en flexion pure, classe 3 dès
  N = −200 kN, classe 4 dès N = −2000 kN — dégradation progressive avec la
  compression, cohérente avec le §5.5. Confirmé **en marche** sur
  `10_story_frame`, groupe `COLUMN 1-2S` : parmi 57 candidats testés (analyse
  GSA réelle par candidat), `UB1100x400x343` est retenu classe 4 par la
  stabilité EC3 (« aucun taux de stabilité lisible » — refus déjà en place,
  cf. plus haut) tandis que `UB1000x400x296` (candidat recommandé) et
  `UB1000x400x321` sont classés 3 par le module, chacun avec son propre
  C1/C2/k/k<sub>w</sub>.
- **Bouton « Ouvrir dans Excel » du détail Optimisation (01/09)**, vérifié
  **en marche**, Excel réellement ouvert et relu par COM (`xlwings`), sans
  passer par le bouton de Performances : sur `UB1000x400x296` (onglet « un
  groupe »), le classeur reçoit N = −5148,45 kN, M<sub>y</sub> = 789,953 kNm,
  C1 = 2,6308, C2 = 0, k = k<sub>w</sub> = 1, nuance S235, combinaison
  `C3p01`, position 0 % — identiques au candidat affiché, et les cellules du
  diagramme de moment (D31:D33) restent aux formules du classeur (aucun faux
  plat écrit). Sur `UB1000x400x321` (onglet « globale », famille `COLUMN
  1-2S`, après une optimisation à 9 familles/408 essais) : mêmes valeurs
  retrouvées (N = −5146,63 kN, C1 = 2,6298…) depuis `JobGlobal.essais`, sans
  aucun second appel GSA. Les deux boutons affichent bien leur motif de
  désactivation (« stabilité EC3 non disponible… ») sur un candidat dont la
  stabilité a échoué (`UB1100x400x343`, classe 4, cf. ci-dessus).
- **Stabilité approfondie devenue exhaustive, et diagramme de moment relié au
  bouton Excel du détail Optimisation (02/09)** : la case « stabilité
  approfondie » vérifiait jusqu'ici les 5 barres les plus sollicitées en ELU
  d'un groupe/famille, chacune à la position qui maximise son critère
  « combiné » — une heuristique. Elle vérifie désormais **toutes** les barres,
  sur **toutes** leurs permutations ET **toutes** leurs positions (0/25/50/75/
  100 %) : chaque case donne déjà le max des 4 taux §6.3
  (`verification.py::verifier_stabilite`), donc le max de toutes ces cases est
  le maximum absolu sur le périmètre — exhaustif, pas approché (`_extraire_optim`,
  `_CtxGlobal._cases_stabilite`). Coût mesuré : toujours de l'ordre de
  quelques dizaines de ms/candidat (`commun/stabilite_ec3` reste à ~30 µs/case).
  Le mode par défaut (décoché) est inchangé : barre gouvernant l'ELU du
  groupe, à sa case dimensionnante. — Corrigé en même temps : le diagramme de
  moment (D31:D33/D35:D37, facteurs Cmy/Cmz de §6.3.3) était laissé vide par
  le bouton Excel du détail Optimisation (cf. juste au-dessus, « aucun faux
  plat écrit ») alors que `_torseur_dimensionnant` le calcule TOUJOURS en même
  temps que le torseur retenu — il n'était simplement jamais conservé au-delà
  du calcul de stabilité. `job.stab[nom]` (un groupe) et l'essai
  (`JobGlobal.essais`, globale) gardent maintenant `my_debut_milieu_fin`/
  `mz_debut_milieu_fin`, transmis à `_ouvrir_excel_connu` qui les passe à
  `_entrees_classeur` — mêmes cellules que `ouvrir_excel_barre`, sans second
  appel GSA. Revérifié à la main que `_entrees_classeur` produit bien
  `my_debut_kNm`/`my_milieu_kNm`/`my_fin_kNm` corrects depuis un
  `my_debut_milieu_fin` réel sorti d'un job (`[-626,05, 80,49, 787,02]` sur
  `UB914x305x345`, `10_story_frame`, groupe `COLUMN 1-2S`) ; la relecture par
  COM des cellules D31:D33 elles-mêmes n'a pas pu être refaite dans cette
  session (classeur ouvert par le serveur de prévisualisation, hors de portée
  du process qui a servi à la vérification COM du 01/09 ci-dessus).
- **Tableau détaillé de l'onglet Performances, aligné sur celui du détail
  Optimisation (02/09)** : `table-perf` n'affichait, par barre, que la
  combinaison/le critère/le taux ELU retenus et le taux de stabilité global —
  le torseur (N/Vy/Vz/Mxx/My/Mz) et les quatre taux §6.3 séparés n'étaient
  visibles qu'en infobulle. Il porte désormais les mêmes colonnes que
  `table-optim`/`table-global` : 6 colonnes d'efforts ELU (déjà connues de
  `_bloc_critere`, aucun changement serveur) + cas/combinaison/6 efforts/lieu
  de la case qui gouverne la stabilité + les 4 taux §6.3 séparés
  (Flambement/Déversement/Fléchi+comprimé yy/zz), en plus du taux global et de
  la classe déjà affichés — colonnes « Barre ELU »/« Barre stab. » omises
  (redondantes : la ligne EST déjà une barre). Contrairement aux onglets
  d'optimisation, la combinaison de stabilité coïncide TOUJOURS avec la
  combinaison ELU dimensionnante (`_extraire` ne vérifie la stabilité qu'à la
  case ELU retenue, pas d'« approfondie » ici) — documenté en infobulle sur
  l'en-tête plutôt que masqué. Côté serveur (`JobElu._extraire`/`_stabilite`),
  `job.stab[eid]` porte maintenant aussi `combinaison`/`stab_N_kN`… (mêmes clés
  que `_prefixer`/`_valeurs_torseur`, réutilisées telles quelles par
  `celulesEfforts`/`celluleLieu` côté page). `appliquerStabilite` (patch
  incrémental des cellules quand la stabilité arrive après l'ELU) a été
  simplifié : il régénère la ligne entière (`ligneHTML`) au lieu de patcher
  deux cellules — nécessaire puisque la stabilité alimente désormais une
  dizaine de cellules, pas deux. Export CSV (« Exporter (Excel) ») étendu aux
  mêmes colonnes. Vérifié **en marche** dans le navigateur de prévisualisation
  (pas seulement lu) : `Poutre ISO.gwb` (1 barre) — taux stabilité 6,261 =
  max(0 / 3,283 / 4,905 / 6,261), cas affiché « Fléchi + comprimé zz »,
  cohérent ; `Pratt_1.gwb`, groupe « toutes les barres acier » (21 barres,
  streaming par paquets + stabilité en parallèle) — 21/21 lignes cohérentes
  (ex. barre 7 : taux 0,914 = max(0,808/0,103/0,914/0,904), cas « Fléchi +
  comprimé yy »), sélection de ligne et panneau Excel toujours fonctionnels,
  export CSV sans erreur, aucune erreur console dans les deux cas.
