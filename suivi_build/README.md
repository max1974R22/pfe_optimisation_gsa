# Suivi de build — Comparateur GSA / Excel (PFE V0)

Journal des travaux d'automatisation. Chaque session est documentée : ce qui a
été fait, pourquoi, ce qui a été découvert, comment vérifier.

---

## Session du 2026-07-17 — Dossier `algo_opti/`, menu déroulant d'algo, stabilité dans les résultats

### Nouveau dossier `algo_opti/` (algorithmes d'optimisation globale)

Les algorithmes d'optimisation de la STRUCTURE GLOBALE quittent
`scripts/dimensionner.py` pour un package dédié, pensé pour en accueillir
d'autres :

- `algo_opti/brut_force.py` : l'ancien `optimiser_global` déplacé tel quel
  (force brute par famille + passes / descente par coordonnées, continuité).
  Chaque module expose `LIBELLE`, `DESCRIPTION`, `optimiser(modele, cfg, log)`.
- `algo_opti/__init__.py` : registre `ALGOS` + `ALGO_DEFAUT` ("brut_force").
  Ajouter un algorithme = créer le module et l'enregistrer là : la page le
  propose automatiquement.
- Serveur : `/api/etat` renvoie `algos`/`algo_defaut` ; `/api/global` accepte
  `algo` (validé, écho `res["algo"]`).
- Page : **menu déroulant** de l'algorithme en mode Globale (masqué sinon),
  libellé repris dans le texte d'info et le rappel des critères.

### Stabilité EC3 dans les résultats d'optimisation Barre / Groupe

`dimensionner()` capture désormais, pour CHAQUE section essayée, le torseur
ELU de la barre gouvernante (`barre_gouvernante` par ligne, enveloppe
0/25/50/75/100 % — l'état analysé porte bien la section essayée sur la cible).
Nouvel endpoint `POST /api/stabilite-lignes` {nuance, barres} : une passe
Excel invisible (classeur Predim, mode torseur) pour toutes les lignes,
AUCUN appel GSA (torseurs déjà capturés). La table de résultats gagne
**« Taux stabilité »** et **« Cas dimensionnant »**, remplis en différé après
l'affichage (jeton anti-écrasement si on relance pendant la passe) ; « — »
avec motif en infobulle si le profil n'existe pas dans le classeur (ex.
IPE550 absent de l'onglet IPE). La nuance vient du modèle (matériaux renvoyés
par `dimensionner`, retirés de la réponse par le serveur).

### Critère ELU : enveloppe SIGNÉE min/max de TOUTES les contraintes GSA

Réponse au problème documenté le 16/07 (« le critère ELU par défaut ne lit
que la fibre C1 et rate la compression C2 ») : le critère et les affichages
prennent désormais le **max signé et le min signé de toutes les contraintes
GSA** (C1, C2, A, By, Bz, von Mises, cisaillements, torsion), la plus grande
amplitude gouvernant le taux ELU. La mesure manuelle **My_Wel est supprimée**
(elle ne valait que pour la flexion pure de la poutre ISO).

- `scripts/dimensionner.py` : My_Wel retiré de `MESURES_ELU`,
  `MESURES_DEFAUT` = toutes les mesures ; nouveaux helpers
  **`extremes_mesures`** (max/min signés par mesure, avec la barre) et
  **`bilan_extremes`** (max global, min global, gouvernant = amplitude max) ;
  chaque ligne porte `sigma_max_MPa`/`mesure_max`, `sigma_min_MPa`/
  `mesure_min`, et `sigma_MPa`/`mesure` = le gouvernant du taux ELU. La clé
  `mesures` de config/dimensionnement.json est retirée (restriction toujours
  possible en la remettant).
- `algo_opti/brut_force.py` : `evaluer()` renvoie le bilan complet ; les
  lignes par famille portent les mêmes colonnes max/min.
- `app/server.py` (`/api/performance`) : par barre, max et min signés de
  toutes les colonnes des DEUX tables de contraintes (`_COLS_MESURE`), avec
  la mesure gouvernante ; tuiles extrêmes renommées `sigma_max`/`sigma_min`
  (+ mesure).
- Page : tableau Performances → colonnes « σ max ELU / Stress max / σ min
  ELU / Stress min » ; tableaux d'optimisation (barre/groupe ET global) →
  mêmes colonnes, valeur gouvernante en gras, infobulle « gouverné par X »
  sur le taux ELU ; les **chips de sélection des mesures sont supprimées**
  (tout est toujours évalué).

Vérifié (Pratt_1) : perfs → σ max 27,3 MPa (barre 1, VM), σ min −24,9 MPa
(barre 7, C2) ; optim barre n°1 → taux ELU 0,129 = 27,3/211,5 gouverné par
VM ; global → 8 familles avec max/min et mesures ; aucune erreur console.

### Export Predim : mode torseur PARTOUT (fin de la transposition des chargements)

L'ancien bouton « Ouvrir \<section\> dans Excel » des modes Barre/Groupe
transposait les CHARGEMENTS extérieurs du modèle (portée, appuis, G/Q
répartis) — un chemin qui ne valait que pour la Poutre ISO (poutre
isostatique chargée en travée) : sur tout autre modèle, les charges
partaient en avertissements et le classeur ne recevait rien d'utile.

Désormais le classeur Predim est TOUJOURS alimenté en **mode torseur** :
enveloppe ELU des efforts de la barre gouvernante à 0/25/50/75/100 %
(max/min/enveloppe signée par composante), comme l'onglet Performances.

- `app/server.py` : `donnees_predim`, `ouvrir_excel_predim` et la route
  `POST /api/excel` SUPPRIMÉS. Le bouton des modes Barre/Groupe passe par
  `/api/excel-famille` avec la `barre_gouvernante` de la section retenue —
  torseur capturé pendant la boucle, donc dans l'état analysé AVEC la
  section retenue, même sans « Charger dans le modèle ».
- Page : bouton « Ouvrir la barre n°X (\<section\>) dans Excel », récap du
  torseur transmis (helper `recapTorseur` commun aux trois boutons Excel),
  note du bloc réécrite ; masqué si la ligne retenue n'a pas de torseur.

Vérifié (Pratt_1, barre n°1, IPE80 retenu) : classeur ouvert avec
N = −3,13 kN / Vz = −0,44 / My = 0,23 kNm (efforts GSA, pas de chargement),
`/api/excel` → 404, aucune erreur console.

### Nettoyages demandés

- **Graphique d'optimisation supprimé** (SVG masse/marge σ/flèche) : fonction
  `dessinerGraphe`, div `#graphe-optim` et bloc CSS retirés (la colonne
  `masse_totale_kg` du backend reste, inoffensive et utile en CSV).
- Texte « critère ELU sur cette barre ; flèche vérifiée sur toute la
  structure » retiré (mode Barre : plus d'info-cible).

Vérifié dans le navigateur (Pratt_1) : barre n°1 × série IPE → 18 sections en
0,6 s, stabilités remplies en 15,3 s (Déversement, IPE550 en « — » motivé) ;
mode Globale → menu « Force brute (passes) », 440 analyses / 3 passes / 6,8 s,
8 familles avec taux de stabilité ; aucune erreur console ; aucun `.gwb`
modifié.

---

## Session du 2026-07-16 — Restauration du bridge + section « Performances du modèle actuel »

### Restauration de `gsa_bridge/bridge.py` (régression)

Une ancienne version du bridge avait écrasé la courante : 7 méthodes
appelées par l'app et les scripts manquaient. Restaurées et re-vérifiées sur
le Pratt : `node_loads()`, `lists()`, `beam_stresses()`,
`beam_derived_stresses()`, `section_dediee()`, `set_section_profile()`,
`save_to()`, plus `longueur_m` dans `elements()` et `Zy_m3`/`Zz_m3` dans
`sections()`. `_along()` prend un attribut-marqueur (résultat plat vs
permutations, quel que soit le type de valeur).

### Contraintes dans l'export CSV

`scripts/export_gsa.py` : `RESULT_TABLES` gagne **Beam Stresses.csv**
(`Element1dStress` : A, Sy/Sz, By±z, Bz±y, C1/C2) et **Beam Derived
Stresses.csv** (`Element1dDerivedStress` : SEy/SEz, St, von Mises), Pa,
tous cas empilés comme les autres tables.

### Section « 03 — Performances du modèle actuel » (page)

Volet `<details>` entre Résumé et Dimensionnement : à l'ouverture,
`GET /api/performance` analyse le modèle **tel quel** (résultats du fichier
réutilisés si les combinaisons ELU/ELS y sont déjà) et affiche en tête
**poids d'acier** (Σ L·A·ρ, ρ du matériau acier du modèle), **traction max**
(fibre C1, ELU), **compression max** (fibre C2, ELU) et **déplacement max**
(|Uz|, ELS) avec la barre concernée ; puis un sous-volet **barre par barre**
(profil, L, masse, C1 max, C2 min, |Uz| max — extrêmes surlignés magenta) et,
sur case à cocher, les **efforts aux extrémités par membre** (`Member1dForce`,
la sortie « 1D member results » de GSA : N, Vz, My aux deux bouts, ELU).
Nouvelle méthode bridge : `member_forces(cas, positions)`. Les sections
Dimensionnement/Résultats passent en 04/05. Le volet se referme et se vide à
chaque (re)chargement de résumé — donc aussi après « Charger dans le modèle ».

Vérifié dans le navigateur (Pratt) : 205,0 kg, +164,2 MPa barre 14,
−272,3 MPa barre 7, 5,97 mm barre 3 ; 21 lignes, bascule des colonnes membre,
valeurs identiques au calcul direct par script.

### Refonte de la page en 3 onglets + graphique d'optimisation

- **Trois onglets principaux** en tête de colonne gauche : « Modèle &
  hypothèses » (dépôt + résumé), « Performances » (l'analyse se lance à
  l'ouverture de l'onglet — plus de volet), « Optimisation » (dimensionnement
  + résultats). Performances/Optimisation verrouillés tant qu'aucun résumé
  n'est chargé ; changement de modèle → retour à l'onglet Modèle, onglets
  reverrouillés.
- **Nettoyage** : badge « serveur connecté » (échec signalé dans le message du
  bloc Modèle), aide 3D (« glisser : rotation… »), et indications entre
  parenthèses des libellés supprimés.
- **Vue 3D** : numéros de BARRES au milieu de chaque élément (magenta si
  surlignée) au lieu des numéros de nœuds ; seuil 120 éléments.
- **Graphique d'optimisation** (cible barre/groupe ; masqué en mode global) :
  SVG maison sans dépendance, x = **masse totale de la configuration**
  (nouvelle colonne `masse_totale_kg` par ligne dans
  `scripts/dimensionner.py` : base fixe hors cible + L·A·ρ de la section
  essayée), y gauche = **marge de contrainte** (σ limite − σ max de la pire
  barre, pointillé « marge σ = 0 »), y droite = **flèche ELS** (pointillé
  « flèche limite »). Étiquettes de sections inclinées, décimées à 26 px ;
  infobulles par point.

Vérifié dans le navigateur (Pratt) : onglets + verrouillage OK, perfs
auto au clic d'onglet (205 kg / ±… identiques), run barre n°1 (18 sections,
graphe 205→322 kg) et groupe Diagonale (17 sections, 108→1 234 kg,
seuils tracés), aucune erreur console.

### Stabilité EC3 par barre (classeur Predim en « mode torseur »)

Le classeur Predim possède un bloc **« Torseur de sollicitations »**
(P22:P26 ELU / Q22:Q26 ELS : N, Vz, Vy, My, Mz) et un bloc **« Distribution
de moments pour la vérification de la stabilité »** (D31:D33 My
début/milieu/fin, D35:D37 Mz) — tous deux des FORMULES calculées depuis le
chargement. Les écraser par des constantes (copie de travail uniquement)
donne un mode « barre isolée » : torseur saisi, aucun chargement. Sorties
§6.3 : X35 Flambement, X36 Déversement, X37 [6.61] yy, X38 [6.62] zz,
L4 = max. Convention du classeur : N > 0 = traction (flambement ignoré) —
cohérent avec Fx GSA.

- `excel_bridge/config/io_map.json` : + 10 entrées torseur, 6 entrées
  distribution, 4 sorties de taux §6.3.
- **`excel_bridge/stabilite.py`** (nouveau) : `verifier_stabilites(barres)` —
  UN classeur Excel invisible pour toute la liste, par barre : profil +
  nuance + portée (= longueur de barre, appuyé-appuyé, poids propre non) +
  torseur + distribution → recalc → 4 taux, cas dimensionnant = taux max.
  Barre en échec (profil hors classeur) signalée sans bloquer les autres.
- `app/server.py` : `donnees_torseur()` (thread GSA — enveloppe ELU max/min
  par composante sur `beam_forces` à 0/25/50/75/100 %, kN/kNm),
  `GET /api/stabilite` (passe Excel sur le thread HTTP sous verrou EXCEL),
  `POST /api/excel-barre` (ouvre le classeur VISIBLE pré-rempli pour une
  barre : vérification manuelle).
- Page : le tableau des performances gagne **« Taux stabilité »** et **« Cas
  dimensionnant »**, remplis en différé après l'analyse GSA (message
  d'attente ; « — » avec le motif en infobulle si Excel indisponible ou
  profil non transposable ; infobulle = détail des 4 taux). Les lignes sont
  **cliquables** : la barre choisie est surlignée (tableau + vue 3D) et un
  bloc « Vérification EC3 » apparaît avec le bouton « Ouvrir la barre n°X
  dans Excel » + récapitulatif du torseur transmis (max / min / saisi).

Vérifié (Pratt, 21 barres en ~15-20 s) : barres tendues → flambement 0 et
cas « Déversement » ; comprimées → « Fléchi + comprimé zz » ; **diagonales
7 et 11 : taux 1,042 → dépassement en stabilité alors que la contrainte
C1 passait** (0,148) — la stabilité gouverne, comme attendu sur ce treillis.

### Diagnostic écart export GSA ↔ app (demande utilisateur)

Les écarts constatés (flèche 11,37 vs 5,97 mm ; −296 MPa non vus) ont DEUX
causes, aucune dans l'extraction : (1) l'export portait sur le modèle
d'origine tout-IPE80 (= `.avant-optim`) alors que le master actuel a des
sections mélangées après « Charger dans le modèle » ; (2) le critère ELU par
défaut ne lit que la fibre **C1** (`mesures: ["C1"]`) et rate la fibre C2
(compression), gouvernante en treillis. Correction en attente de décision.

---

## Session du 2026-07-15 (4) — Optimisation globale (onglets Barre / Groupe / Globale, continuité)

Le bloc « Cible de l'optimisation » passe de la case à cocher à **trois
onglets** : Barre, Groupe, **Globale**.

### Mode Globale (`optimiser_global` dans `scripts/dimensionner.py`)

Une section optimale **par famille de barres** (les listes GSA), par **force
brute + descente par coordonnées** :

- chaque famille reçoit sa propriété de section dédiée ; départ uniforme sur
  la plus grosse section de la série ;
- famille par famille, TOUTES les sections de la série sont essayées (une
  analyse GSA par essai, les autres familles restant à leur affectation
  courante) ; critères : ELU sur la **barre la plus sollicitée de la famille**
  + flèche globale ; on retient la plus légère qui passe ;
- les familles interagissant (raideur, poids propre), on repasse jusqu'à
  stabilité des affectations (max 8 passes, 40 avec continuité) ; drapeau
  `converge` renvoyé ;
- famille sans solution → repli sur la plus grosse admissible + verdict
  DEPASSE (les autres familles continuent) ;
- mesure manuelle `My_Wel` refusée en global (un Wel par famille) ;
- vérification finale à l'état retenu → table : famille, section retenue,
  **barre dimensionnante**, σ, taux ELU, masse (kg = masse/m × Σ longueurs),
  verdict + bilan global (masse totale, flèche/taux ELS, passes, analyses).

### Contrainte « continuité »

Case à cocher du mode Globale : deux barres MITOYENNES (nœud partagé) ne
peuvent avoir qu'**une section d'écart** dans la série — les sections étant
uniformes par famille, la contrainte s'applique entre **familles adjacentes**
(adjacence calculée par les topologies). Fenêtre admissible d'une famille =
`[max(voisines)−1, min(voisines)+1]`, jamais vide grâce au départ uniforme
(invariant maintenu de proche en proche).

Mesuré sur Pratt_1 (charges nodales passées à −50 kN par l'utilisateur) :
sans continuité → haute IPE140 / basse IPE80 / diag IPE120 / montants IPE80,
205,8 kg (3 passes, 220 analyses, 3,7 s) ; avec continuité → montants
remontés à IPE120 et basse à IPE100, 240,4 kg (12 passes — la fenêtre ±1 ne
descend que d'un cran par passe —, 118 analyses, 1,8 s).

### Serveur + page

- `POST /api/global` {modele, famille, criteres?, groupes, continuite?} ;
- `/api/appliquer` accepte désormais `applications: [{elements, libelle,
  section}]` → **toutes les familles appliquées en un clic** (une seule
  sauvegarde, un seul `.avant-optim`) ; forme simple conservée ;
- onglets stylés façon éditoriale (soulignement magenta de l'actif) ; en
  Globale : sélecteur masqué, case continuité, **toutes les barres groupées
  surlignées** dans la vue 3D ; table dédiée `#table-global` (l'autre se
  masque) ; bouton « Charger n famille(s) dans le modèle » ; **export Excel
  masqué en global** (le classeur Predim vérifie UNE configuration de poutre
  — à réintroduire par famille si besoin).

Vérifié de bout en bout dans le navigateur (Pratt_1, continuité cochée) :
table conforme aux valeurs API, application des 4 familles en un clic,
résumé rafraîchi (prop 3 = IPE100 barres 1-6, prop 5/1 = IPE120 diagonales/
montants, prop 4 = IPE140 membrures hautes), aucune erreur console. Modes
Barre/Groupe inchangés (non-régression).

---

## Session du 2026-07-15 (3) — Vue 3D permanente à droite

La vue 3D quitte la carte « Résumé » pour un **panneau permanent à droite**
(`<aside class="panneau-3d">`), les étapes 01-04 défilent à gauche :

- grille `.disposition` (2 colonnes : `minmax(0,1fr)` / `minmax(360px, 42%)`,
  max 1560 px) ; le panneau est **sticky sous l'entête** (top 96 px) et le
  canvas prend la hauteur de la fenêtre (`calc(100vh - 220px)`) ;
- avant chargement : message d'attente (`#vide-3d`) ; après : nom du modèle
  en pastille (`#titre-3d`) ; le surlignage de la cible reste visible en
  permanence pendant qu'on règle les critères ou qu'on lit les résultats ;
- < 1020 px : retour à une colonne, vue 3D en tête (300 px, non sticky) ;
- plus besoin de charger la vue « après affichage de la carte » (le canvas
  n'est plus jamais `hidden`, l'ancien piège du canvas de largeur 0 disparaît).

Vérifié : panneau à droite et épinglé au défilement (top constant à 96 px
après 600 px de scroll), structure + surlignage dessinés, placeholder puis
titre, repli à 900 px, aucune erreur console.

**Correctifs (même jour)** :

- le placeholder « charger un modèle… » restait affiché après chargement :
  le `display: grid` de `.vide3d` **écrasait l'attribut `hidden`** (le
  `[hidden]{display:none}` du navigateur perd contre toute règle auteur) →
  règle globale `[hidden] { display: none !important; }` en tête de feuille ;
- **tuiles repliables** : `tuile()` n'affiche que les 6 premières lignes et
  ajoute un petit `+ n autre(s)` (magenta, dépliage/repliage, un seul
  écouteur délégué sur `#grille-resume`) ; l'ex-tuile « Géométrie » est
  scindée en « Nœuds (n) » et « Éléments 1D (n) » avec une ligne par entité
  (longueur comprise), et les tuiles courtes restent inchangées (pas de
  bouton sous 7 lignes).

---

## Session du 2026-07-15 (2) — Treillis Pratt : optimisation par barre ou par groupe, application au modèle

Le modèle d'essai `GSA_model/Pratt_1.gwb` (treillis Pratt : 12 nœuds, 21
barres toutes en IPE80 **partageant la même propriété de section**, 4 listes
GSA nommées — Membrure haute/basse, Diagonale, Montant —, charges nodales
−5 kN sur les nœuds 2 à 6, combinaisons ELU/ELS) est maintenant entièrement
pris en charge.

### Pont GSA (`gsa_bridge/bridge.py`)

- `node_loads()` : charges nodales (l'API exige un type par appel —
  NODE_LOAD / APPL_DISP / SETTLEMENT agrégés ; GRAVITY lève « Unsupported »).
- `lists()` : listes GSA nommées avec ids développés par `ExpandList`.
- `elements()` : + `longueur_m` (`Model.ElementLength`).
- `section_dediee(element_ids, nom)` : propriété de section commune et
  **exclusive** à une cible — réutilisée si déjà exclusive, sinon **clonée**
  sous un id libre et affectée aux éléments + membres homonymes (maillage
  1 membre = 1 élément). ⚠️ Découverte : les objets Section de l'API sont des
  **références vives** (muter `s.Name` mute la section d'origine) → clonage
  par modification + `SetSection(nouvel id)` puis restauration +
  `SetSection(id d'origine)`. Vérifié : section 1 intacte après clonage.
- `save_to(destination)` : `SaveAs` explicite — seule écriture hors copie de
  travail (le retour de SaveAs n'est pas fiable, on vérifie l'existence).

### Dimensionnement ciblé (`scripts/dimensionner.py`)

`cfg["cible"] = {"elements": [ids], "libelle"}` : la boucle change la section
de la SEULE cible (via `section_dediee`) et le critère ELU est le max sur la
cible — donc à chaque section essayée, c'est la **barre la plus sollicitée**
du groupe qui décide (elle peut changer d'une section à l'autre : sur les
diagonales du Pratt, la gouvernante oscille entre les barres 11 et 21).
Chaque ligne de résultat porte `element_gouvernant`. Le critère ELS reste
**global** (changer une barre modifie la raideur d'ensemble ; c'est la flèche
de la structure qu'on borne à L/300). Sans cible : comportement historique.

### Serveur + page

- `/api/resume` : + `charges_nodales`, `listes`, longueurs d'éléments.
- `/api/dimensionner` : + `cible` (validée par `valider_cible`).
- **`/api/appliquer`** (nouveau) : applique une section du catalogue à la
  cible et **enregistre le modèle** dans GSA_model/ — seule action qui
  modifie un fichier déposé ; l'état d'avant la PREMIÈRE optimisation est
  copié en `<nom>.gwb.avant-optim` (invisible dans la liste, glob `*.gwb`).
- Page : bloc « Cible de l'optimisation » (case **optimiser par groupe** →
  sélecteur de listes GSA ; sinon sélecteur de barres avec longueur et
  profil), la cible est **surlignée en magenta dans la vue 3D**
  (`Vue3D.surligner`, tracé épais par-dessus) ; repli sans listes : pseudo-
  groupes par champ `groupe` des éléments. Résultats : colonne « Barre
  gouvernante », bannière avec cible et barre la plus sollicitée, bouton
  **« Charger dans le modèle »** (recharge le résumé en gardant les
  résultats) + bouton Excel conservé (les charges nodales partent en
  avertissement : le classeur ne connaît que des charges sur travée).

Vérifié de bout en bout dans le navigateur : résumé complet, sélection
Diagonale surlignée (6 barres), IPE80 retenu (gouvernante n°11, taux ELU
0,148), application → propriété n°3 « Diagonale - IPE80 » sur les 6 barres,
les 15 autres restent sur la propriété 1, `.avant-optim` créé, résumé
rafraîchi. Barre seule en HEA : HE100A. Non-régression Poutre ISO : IPE120,
taux 0,237/0,933 inchangés. (Modèle Pratt remis à l'état d'origine après les
tests.)

NB tests PowerShell : `Invoke-RestMethod -Body <string>` envoie du latin-1 →
un « ° » dans le JSON casse le décodage UTF-8 côté serveur ; passer des
octets `[Text.Encoding]::UTF8.GetBytes($json)`. Le navigateur, lui, envoie
bien de l'UTF-8.

---

## Session du 2026-07-15 — Bouton « Ouvrir dans Excel » (Predim pré-rempli) + mise en page façon elioth.com

### Vérification Predim depuis la page (reprise d'`excel_bridge/`)

Après le dimensionnement, un bloc « Vérification EC3 — classeur Predim »
propose d'ouvrir le classeur `Predim_poutre acier_v3.xlsm` **pré-rempli** avec
les données du modèle GSA et la **section retenue** :

- **`excel_bridge/predim.py`** (nouveau) : `ouvrir_predim(donnees, etiquette)`
  copie le maître, remplit via l'io_map existant, recalcule, puis **laisse
  Excel ouvert et visible** (calcul repassé en automatique, alertes réactivées) ;
  en cas d'échec de saisie, Excel est refermé et l'erreur propagée.
  `famille_predim()` : IPE→IPE, IPN→IPN, HEA/HEB/HEM→HE ; **UPE/UPN refusées**
  (pas d'onglet dans le classeur).
- **`app/server.py`** : `POST /api/excel {modele, famille, section}`.
  `donnees_predim()` (thread GSA) transpose le modèle : portée, conditions
  d'appui (encastrement = `res_yy` bloqué), poids propre (= charge gravité
  présente), nuance (nom du matériau acier, ex. `S235`), et surtout le
  **classement G/Q par les facteurs de la combinaison ELU** (`1.35A1 + 1.5A2` ;
  lien An→Ln par la `description` du cas d'analyse ; facteur ≥ 1,45 → Q) — on
  ne se fie PAS au type GSA (les deux cas de la Poutre ISO sont `Dead`).
  Tout ce qui n'est pas transposable (charges ponctuelles, horizontales,
  cas hors combinaison) part en `avertissements[]`, affichés dans la page.
  L'ouverture Excel se fait dans le thread HTTP (CoInitialize) sous verrou
  `EXCEL` ; seuls les accès GSA passent par le thread `TravailGsa`.
- **`excel_bridge/bridge.py`** : résolution de profil **insensible aux
  espaces/casse** (le classeur écrit `IPE 80` mais `IPE100`, et `HE 100 A` là
  où GSA écrit `HE100A`) ; paramètre `visible` sur `BeamWorkbook` ;
  `ignore_read_only_recommended=True` à l'ouverture.
- **UI** : bouton « Ouvrir IPE120 dans Excel » sous le tableau, récapitulatif
  des données transposées + avertissements après ouverture.

Vérifié de bout en bout (Poutre ISO, IPE120) : AB2=1, AB10=3 (=IPE120),
Lo=10 m, S235, appuyé/appuyé, poids propre oui, Q=0,05 kN/m ; le classeur
calcule taux flèche **0,906** (GSA : 0,933 — l'écart est exactement le
E=205 000 codé en dur du classeur vs 200 000 GSA : 0,933×200/205 ≈ 0,910),
taux contrainte 0,185, et **ajoute la stabilité au déversement (0,538)** que
GSA ne vérifie pas.

Découvertes machine (poste EGIS) :

- **Le classeur Predim s'ouvre TOUJOURS en lecture seule** sur ce poste —
  COM comme double-clic, maître comme copie, dans OneDrive comme hors.
  Éliminé : attribut disque, « lecture seule recommandée », « marquer comme
  final », réservation d'écriture, vue protégée, étiquette visible. Les
  `SaveAs` **programmatiques échouent silencieusement** (fichier jamais créé),
  y compris pour un classeur neuf → politique du poste (étiquetage Purview
  obligatoire, vraisemblablement). Sans incidence sur l'usage : l'édition des
  cellules fonctionne (le pont automatisé écrit depuis le début), et
  l'« Enregistrer sous » **interactif** affiche le dialogue d'étiquette et
  aboutit. `ChangeFileAccess(xlReadWrite)` est sans effet (silencieux).
- **OneDrive verrouille en écriture toute copie fraîche** pendant sa
  synchronisation (>8 s, persistant tant qu'Excel la tient) : les copies
  utilisateur vont donc dans **`%LOCALAPPDATA%\PredimGSA\`** (hors OneDrive,
  horodatées, jamais synchronisées ; l'utilisateur « Enregistre sous » s'il
  veut garder).

### Mise en page inspirée d'elioth.com

Le site public (elioth.com — elioth.fr ne répond pas) a été analysé dans le
navigateur (styles calculés ; la capture d'écran du pane était en panne) :
Gilroy partout, noir/blanc, **aucun arrondi**, libellés en petites capitales
espacées, filets fins, esthétique éditoriale aérée. `style.css` refondu et
`index.html` restructuré dans cet esprit, charte Egis conservée :

- plus de « cartes » : des **sections éditoriales** séparées par des filets,
  numérotées `01…04` (numéro magenta, seule touche vive) ;
- `border-radius: 0` partout (boutons, selects, pastilles, tuiles, barres) ;
- boutons rectangulaires en capitales espacées — principal bleu nuit (hover
  magenta), secondaire filet ; chips actives en bleu nuit ;
- entête : logo + sous-titre en capitales avec séparateurs « – » magenta
  (signature de la nav elioth), filet bleu nuit, sticky ;
- tableau : en-têtes en capitales, filet d'en-tête appuyé ; bannières de
  résultat à **liseré gauche** (plus d'encadré arrondi) ;
- footer éditorial à filet.

Les IDs et variables CSS (`--v3d-*` pour la vue 3D) sont inchangés : aucun
impact sur `app.js`/`viewer3d.js`.

Source : `reference/Identité graphique/Elioth_charteGraphique-Nov2020.pdf`
(texte + valeurs CMJN extraites des flux de contenu du PDF, pypdf).

La page passe en **thème clair** conforme à la charte :

- **Magenta identitaire** CMJN 0/100/0/0 → `#E6007E`, « en petites touches »
  comme demandé : pastille du logo (ronde, écho au point final elioth),
  pastille après le h1, boutons principaux, chips actives, focus, et
  **dépassements** (verdict DEPASSE, taux > 1 ; gradation pastel `#EF8FC2`
  entre 0,85 et 1) ;
- **Bleu nuit Egis** 94/77/54/66 → `#0B1F33` : tout le texte ;
- fond blanc dominant, aucun dégradé ni aplat décoratif (exigence charte) ;
- **complémentaires Egis** réservées aux éléments graphiques : barres de taux
  OK en vert egis `#A5C400` (texte en `#6F8500` assombri pour le contraste),
  vue 3D en bleu canard `#0A5E73` / gris acier moyen `#61828A` (variables
  dédiées `--v3d-*` dans style.css) ;
- polices : pile `Gilroy, Segoe UI, ...` (Gilroy si installée — gratuite en
  light/extrabold d'après la charte —, sinon Segoe UI = police bureautique
  officielle, déjà présente sur les postes) ; titres en extrabold (800) ;
- favicon : le « e· » officiel d'elioth (`reference/Identité graphique/
  elioth_LOGO_e_black.png`, recoloré en magenta #E6007E, rogné et mis au
  carré 128×128 → `app/static/favicon_e.png`) ;
- **logo officiel elioth** dans l'entête (remplace le pictogramme poutre ⌶) :
  `reference/Identité graphique/elioth_logo2020_magenta.png`, copié dans
  `app/static/logo_elioth.png` **rogné à son contenu** (1329×687 → 910×287,
  Pillow — installé dans le venv pour l'occasion, usage outillage uniquement) ;
  affiché en 32 px de haut ; type MIME `.png` ajouté au serveur.

Corrigé au passage : `Vue3D.charger()` était appelé pendant que la carte
résumé était encore `hidden` (canvas de largeur 0) ; le tracé dépendait alors
du ResizeObserver, qui ne se déclenche pas si le rendu est occulté (onglet en
arrière-plan). Le chargement 3D se fait désormais après l'affichage de la
carte.

Validation (pane navigateur, styles inspectés au pixel) : fond blanc / texte
`#0B1F33`, pastille et bouton `#E6007E`, bannière retenue pastel `#F2F6DD`,
canvas 3D en `#0A5E73`/`#6F8500`/`#61828A`, parcours complet Poutre ISO →
IPE120 inchangé.

---

## Session du 2026-07-10 (3) — ELU sur contraintes GSA, vue 3D, serveur multi-thread

### Diagnostic préalable : « l'app tourne dans le vide »

Deux causes réelles, reproduites puis corrigées :

1. **Double lancement** : deux instances de `app/server.py` étaient liées au
   même port 8765 (sous Windows, `allow_reuse_address` de `http.server`
   autorise silencieusement la double liaison) ; le navigateur tombait sur
   l'instance qui ne recevait pas les connexions. → `allow_reuse_address =
   False` : une 2ᵉ instance échoue désormais avec un message clair.
2. **Serveur mono-thread + préconnexions navigateur** : les navigateurs
   ouvrent des connexions spéculatives *sans requête* ; `BaseHTTPRequestHandler`
   sans timeout bloquait dessus indéfiniment et la vraie requête attendait dans
   la file. → serveur **ThreadingHTTPServer** + `timeout = 30` sur le handler,
   et la contrainte GsaAPI (un seul thread) est respectée par un **thread
   travailleur unique** (`TravailGsa`, file de fonctions) par lequel passent
   tous les appels GSA (`/api/resume`, `/api/dimensionner`). La page et
   `/api/etat` ne sont plus jamais bloquées par un calcul en cours.

### Critère ELU sur les contraintes calculées par GSA

Avant : σ = |My_max|/Wel,y calculé à la main. Désormais le critère ELU
s'applique aux **contraintes issues de l'analyse GSA**, au choix (une ou
plusieurs, le max gouverne) :

- `gsa_bridge/bridge.py` : nouvelles méthodes **`beam_stresses`**
  (`Element1dStress` : axiale A, cisaillements Sy/Sz, flexion By fibres ±z,
  Bz fibres ±y, combinées C1/C2) et **`beam_derived_stresses`**
  (`Element1dDerivedStress` : SEy/SEz, torsion St, **von Mises**), unités Pa.
  `_along()` prend un attribut-marqueur pour distinguer résultat plat /
  permutations de combinaison quel que soit le type de valeur.
- `scripts/dimensionner.py` : registre **`MESURES_ELU`** (C1, C2, A, By, Bz,
  VM, Sy, Sz, SEy, SEz, St + `My_Wel` qui reproduit l'ancien calcul manuel),
  `valider_mesures()`, config `critere_contrainte.mesures` (défaut `["C1"]`).
  Chaque ligne de résultat porte σ par mesure, le σ max et la **mesure
  gouvernante**. N.B. : comparer un cisaillement à 0,9·fy reste au jugement de
  l'ingénieur (fy/√3 non appliqué).
- API : `/api/etat` expose `mesures_elu` (id, libellé, groupe) ;
  `/api/dimensionner` accepte `criteres.mesures`.
- UI : chips multi-sélection des mesures, colonne « Mesure gouvernante »,
  détail σ par mesure en infobulle.

### Vue 3D du modèle dans la page

**`app/static/viewer3d.js`** : visionneuse filaire **canvas maison, aucune
dépendance ni CDN** (conforme à la philosophie du projet — Rhino/Grasshopper
jugé inutile pour ce besoin). Projection orthographique, caméra orbitale
(glisser = rotation, molette = zoom, clic droit/Maj = translation,
double-clic = recadrage), Z vertical (convention GSA), éléments en polylignes,
appuis en triangles verts, numéros de nœuds si ≤ 60 nœuds, points adaptatifs
selon la densité, trièdre XYZ. Alimentée par les tables déjà renvoyées par
`/api/resume` (nœuds + topologie des éléments) — aucun appel supplémentaire.

### Divers

- Émojis retirés de la page (favicon 🏗️ → pictogramme SVG « I », ancre ⚓ →
  texte « appui », ✓/✗ → pilules colorées seules, ★ → « — retenue »).

### Validation

- Navigateur (pane) : page + `/api/etat` instantanés ; résumé Poutre ISO →
  vue 3D correcte (2 nœuds, appuis, portée 10 m) ; canopée (242 nœuds,
  1258 éléments) → forme fidèle et fluide.
- Dimensionnement UI, mesures C1 + VM : 17 sections en 0,29 s, **IPE120**
  retenue, σ(IPE120) = 50,0 MPa gouverné par C1 — identique à l'ancien calcul
  My/Wel (flexion pure, cohérence attendue).
- CLI `scripts/dimensionner.py` : IPE120, mêmes valeurs, CSV avec colonnes
  par mesure.

---

## Session du 2026-07-10 (2) — Interface web du dimensionneur

### Intention

Une interface moderne (pas tkinter) pour : déposer/choisir un `.gwb`, vérifier
visuellement le modèle, choisir la **famille de sections**, lancer le
dimensionnement et afficher le tableau des taux ELU/ELS.

### Choix technique

**Serveur HTTP en bibliothèque standard** (`http.server`) + page unique
HTML/CSS/JS vanilla (`app/`) : **aucune dépendance nouvelle** (pas de
Flask/Streamlit à installer — environnement d'entreprise), aucun CDN (page
auto-contenue). Contrainte GsaAPI respectée par construction : serveur
volontairement **mono-thread**, tous les appels GSA restent sur le thread
principal (requêtes traitées en série).

### Réalisé

- `scripts/dimensionner.py` **refactoré** : la boucle est maintenant une
  fonction `dimensionner(modele, cfg)` réutilisable (CLI inchangé en
  comportement) ; erreurs via `DimensionnementError` au lieu de `sys.exit`.
- `config/familles.json` : 7 familles (IPE, HEA, HEB, HEM, UPE, UPN, IPN) →
  (catalogue CSV, regex série standard). NB : nomenclature HE du catalogue =
  `HE100A`/`HE100B`/`HE100M`.
- `app/server.py` : API JSON — `/api/etat` (modèles, familles, critères),
  `/api/resume?modele=` (tables du modèle + drapeaux : analysable,
  combinaisons ELU/ELS trouvées par nom, portée), `/api/upload` (dépôt d'un
  `.gwb` dans `GSA_model/`), `/api/dimensionner` (famille + critères
  surchargés depuis l'UI).
- `app/static/` : page sombre moderne — sélecteur/dépôt de fichier
  (drag & drop), tuiles résumé (géométrie avec appuis, section actuelle,
  matériaux, charges, combinaisons), chips de familles, critères éditables
  (coefficient × fy, L/n, avec limite recalculée en direct), tableau de
  résultats avec **barres de taux colorées** (vert/orange/rouge), ligne
  retenue ★, bannière « Section retenue ».
- `.claude/launch.json` : lancement du serveur pour la prévisualisation.

### Validation

- CLI : `scripts/dimensionner.py` → IPE120 (identique à avant refactor).
- API : `/api/resume` (analysable ✓, ELU=C1/ELS=C2 ✓, L=10 m) ;
  `/api/dimensionner` famille HEA → **HE120A** retenue (24 sections, 0,3 s).
- UI vérifiée en navigateur (captures) : résumé complet et fidèle au modèle
  (charge −50 N/m, gravité, E=200 GPa...), tableau 17 lignes IPE avec IPE120
  ★ et IPE100 DEPASSE.
- Bouton « Lancer » désactivé tant que le modèle n'est pas analysable ou que
  les combinaisons ELU/ELS manquent (contrôle visuel par badges ✓/✗).

Lancement : `venv\Scripts\python.exe app\server.py` (ouvre le navigateur sur
http://localhost:8765 ; `--port`, `--no-browser` disponibles).

---

## Session du 2026-07-10 — Réorganisation + dimensionnement automatique ELU/ELS

### Réorganisation du projet

Les scripts étaient éparpillés (`test/`, `test_sections/`, `hand_section/`,
`result_sections/comparer.py` — un script dans un dossier de sorties). Nouvelle
structure : **`scripts/`** (tous les points d'entrée), **`config/`** (critères
modifiables), **`result/`** (toutes les sorties, par catégorie). Un `README.md`
racine sert de carte. Correspondance :

| Avant | Après |
|---|---|
| `test/main.py` | `scripts/export_model.py` |
| `test/export_gsa.py` | `scripts/export_gsa.py` |
| `test_sections/main.py` | `scripts/etude_sections.py` |
| `result_sections/comparer.py` | `scripts/comparer_sections.py` |
| `hand_section/section_calcul_main.py` | `scripts/calcul_manuel.py` |
| `standalone_iso_beam.py` | `scripts/standalone_iso_beam.py` |
| `result/<modèle>/` | `result/export/<modèle>/` |
| `result_sections/` | `result/sections/` |
| `hand_section/_Comparaison.csv` | `result/calcul_manuel/_Comparaison.csv` |

L'ancienne structure est conservée dans `_archive/ancienne_structure/`
(supprimable une fois la nouvelle validée). Tous les scripts ont été relancés
après déplacement : OK (export, étude 10 sections, comparaison, calcul manuel).

### Nouvelle fonctionnalité : `scripts/dimensionner.py`

Dimensionnement de la poutre ISO **par le modèle GSA seul**. Hypothèse : le
modèle possède deux combinaisons **nommées** `ELU` et `ELS` (résolution par
nom via `combination_cases()`, message d'erreur listant les combinaisons
présentes sinon). Critères dans **`config/dimensionnement.json`** (modifiable
sans toucher au code) :

- contrainte ELU : σ = |My_max| / Wel_y ≤ **0,90 × 235 MPa** = 211,5 MPa
  (Wel_y lu dans GSA — propriété `Zy` ajoutée à `sections()` et
  `set_section_profile()` du bridge) ;
- flèche ELS : |Uz_max| ≤ **L/300**, L = distance entre nœuds d'appui lue
  dans le modèle (10 m → 33,3 mm).

Algorithme : parcours de la série IPE standard par taille **décroissante**
(IPE600 → IPE80) ; swap de section + ré-analyse + extraction à chaque pas ;
arrêt à la première section qui dépasse (critères monotones) ; la section
retenue est la plus petite qui passe. Sortie : tableau console + CSV
`result/dimensionnement/Dimensionnement.csv` (section, σ, taux ELU, flèche,
taux ELS, verdict).

### Résultat (Poutre ISO, charges actuelles : poids propre + 50 N/m)

17 sections essayées en 1,2 s. **Section retenue : IPE120** — taux ELS 0,933
(flèche 31,1 mm / 33,3), taux ELU 0,237 (σ 50 MPa / 211,5). L'ELS gouverne
largement ; l'IPE100 dépasse en flèche (taux 1,478). Contrôle croisé : la
flèche ELS d'IPE120 (31,09 mm) est identique à celle de l'étude paramétrique.

---

## Session du 2026-07-09 — Catalogues de sections + étude paramétrique 10 IPE

### Intention

Deux briques nouvelles : (1) extraire les **catalogues de sections** de GSA en
CSV de référence réutilisables ; (2) une **étude paramétrique** qui recalcule
la Poutre ISO avec 10 sections IPE et exporte chaque variante au format des
exports de `test/`.

### Constat préalable

`GSA_model/Poutre ISO.gwb` est **redevenu analysable** : la tâche d'analyse et
les cas A1/A2 ont été recréés dans GSA. La charge répartie L2 vaut désormais
**50 N/m** (et non plus 1 kN/m comme dans les sessions du 07/07) — les valeurs
de référence anciennes (My ELU −19 737 N·m, flèche −861 mm) ne sont plus
comparables telles quelles.

### Nouveau dossier `catalogues/`

`extract_catalogues.py` lit la base SQLite installée avec GSA
(`C:\Program Files\Oasys\GSA 10.2\sectlib.db3`, ouverte en lecture seule) et
produit : `Catalogues.csv` (17 catalogues), `Types.csv` (272 types), et une
CSV par type européen courant — `IPE-AM` (68), `HE-AM` (124), `UPE-AM` (14),
`UPN-AM` (18), `IPN-AM` (21). Colonnes : géométrie, aire, inerties (convention
modèle : Iyy = axe fort = `SECT_I_XX` de la base), modules élastiques/
plastiques, torsion, et surtout **`profil_gsa`** : la désignation exacte à
passer au champ `Profile` d'une section (`CAT IPE-AM IPE200 20170912`).
Contrôle : la ligne IPE80 reproduit exactement la section du modèle (A, Iyy,
J au chiffre près). Voir `catalogues/README.md`.

### `GsaModel.set_section_profile()` (gsa_bridge)

L'utilitaire de swap de section « en attente » depuis le pivot du 07/07 est
ajouté au bridge : `set_section_profile(section_id, profile)` modifie le
profil dans la **copie de travail** uniquement et renvoie la section relue
(profil normalisé par GSA + propriétés) pour contrôle. C'est la seule méthode
d'écriture du bridge, documentée comme telle.

### Nouveau dossier `test_sections/`

`main.py` : pour chacune des sections choisies — par défaut les **10 premières
IPE de la série standard** (IPE80 → IPE270, hors variantes A/AA/O/V), lues
dans `catalogues/IPE-AM.csv` — swap du profil, **ré-analyse** (obligatoire :
le swap invalide les résultats), export complet dans
`result_sections/<SECTION>/` (mêmes 16 fichiers que `result/<modèle>/`, dont
`Analysis Timing.csv`), pour les 4 cas A1/A2/C1/C2. Un récapitulatif
`result_sections/_Comparatif.csv` empile section × cas : masse, aire, Iyy,
My max, Vz max, flèche max, réaction d'appui. Options : `--sections
IPE100,IPE300`, `--nombre N`, `--positions N`.

### `result_sections/comparer.py` — tableau comparatif large

Post-traitement pur (aucun appel GSA) : lit les CSV des sous-dossiers de
sections et produit `_Comparaison.csv` — **une ligne par section**, et pour
chaque cas trouvé (A1/A2/C1/C2) six colonnes : `<cas>_Uz_max_m` / `_x_m`,
`<cas>_My_max_Nm` / `_x_m`, `<cas>_Vz_max_N` / `_x_m` (valeur de plus grande
amplitude, signée, et sa position en mètres calculée depuis `Nodes.csv`).
Contrôle : Uz et My max à mi-travée (x = 5 m), Vz max à l'appui (x = 0 m).

### `hand_section/section_calcul_main.py` — contre-calcul analytique

Mêmes grandeurs par les formules classiques (My = pL²/8, Vz = pL/2,
f = 5pL⁴/384EI), sections et constantes reprises du modèle (E = 200 GPa,
ρ = 7850, g = 9.80665, L2 = 50 N/m, C1 = 1.35·A1 + 1.5·A2). Produit
`hand_section/_Comparaison.csv` au même format que celui de `result_sections/`
et imprime l'écart max par grandeur. Résultat : **My et Vz = GSA à 0,000 %** ;
flèche : écart de 0,076 % (IPE80) à 0,882 % (IPE270), croissant en (h/L)² —
c'est la **déformation d'effort tranchant** incluse par GSA et négligée par
Euler-Bernoulli, pas une erreur.

### Validation

- Étude complète (10 sections × 4 cas, analyse + export) : **1,4 s**.
- Physique vérifiée à la main (IPE80) : flèche A1 = 5wL⁴/384EI avec
  w = 58,8 N/m (poids propre) → 47,8 mm calculé vs 47,6 exporté ✓ ; A2
  (w = 50 N/m) → 40,7 mm ✓ ; C1 = 1.35·A1 + 1.5·A2 et C2 = A1 + A2
  vérifiés au N·m près ✓ ; réactions A1 = 292,5 N = ½ poids propre ✓.
- La flèche ELS passe de 88,3 mm (IPE80) à 4,6 mm (IPE270) : le swap agit.
- Le fichier maître n'est jamais modifié (travail sur `runtime/working.gwb`).

---

## Session du 2026-07-08 (3) — Où passe le temps à l'export ? + sélection des cas

### Question

L'export de la canopée (~380 s) semblait dominé par l'écriture des CSV, alors
qu'un fichier GSA déjà calculé s'ouvre vite. L'écriture rappelle-t-elle l'API à
chaque ligne ?

### Mesures (benchmark, canopée)

Pour 30 cas d'analyse (75 480 lignes) :

| Étape | Temps |
|---|---|
| Rappeler `model.Results()` par cas | 0,038 s (→ 0,001 s si mis en cache) |
| Appels API `Element1dForce("all")` | 0,599 s |
| **Marshalling** (`.X/.YY/…` de chaque `Double6`) | **0,845 s** |
| Écriture CSV disque | 0,143 s |

→ **L'écriture disque n'est PAS le goulot** (0,14 s / 75 k lignes).
Le coût est l'**extraction API + marshalling .NET→Python**. Et surtout :
**les combinaisons** coûtent ~0,7 s chacune (×15 vs un cas d'analyse), voire
bien plus pour les **enveloppes** (env. min/max/tot TIC : nombreuses
permutations recalculées à la volée par GSA). L'analyse (~19 s) n'est faite
qu'une fois ; la remettre en cache/objet ne gagne rien.

Conclusion : la reformulation « analyser → stocker les outputs → écrire les
CSV » n'accélère rien, car « stocker les outputs » = les extraire de GSA, qui
EST l'étape lente. `Element1DResults` (efforts+déplacements en 1 appel) est
encore plus lent (calcule aussi les contraintes).

### Deux leviers retenus

**(a) Ne pas ré-analyser un fichier déjà calculé.** `main.py` ne lance
désormais l'analyse **que si le `.gwb` ne contient pas déjà de résultats**
(`result_cases()` vide) ; sinon il les réutilise. `--reanalyse` force le
recalcul. Gain : sur la canopée déjà calculée, export d'1 combinaison en
**1,8 s** au lieu de 19,7 s.

**(b) Ne pas tout extraire.** Option `--cases` (parseur `parse_cases`) : `C`
(toutes combinaisons), `A` (tous cas d'analyse), `C1-C10` (plage), `C1,C3,A2`
(sélection). Défaut : tous. `--limit` s'applique ensuite.

### Ce qui NE marche pas (mesuré)

- Fusionner les 4 passes (efforts / dépl. / dépl. nodaux / réactions) en **une
  seule passe** réutilisant l'objet-résultat par cas : **45,4 s vs 46,2 s** sur
  5 combinaisons → aucun gain. Pas de recalcul redondant entre passes à
  éliminer ; le coût est le calcul GSA par cas.
- On **ne peut pas** « appeler tous les résultats en une fois » : les résultats
  GSA sont **par cas** (`Results()[i]` / `CombinationCaseResults()[i]`), donc
  une boucle sur les cas est obligatoire. `Element1dForce("all")` batche déjà
  tous les éléments d'**un** cas.
- Les **combinaisons enveloppes** (env. min/max/tot) restent lentes (nombreuses
  permutations recalculées à la volée) — incompressible côté GSA ; seule
  solution : ne pas les extraire si inutiles (`--cases`).

---

## Session du 2026-07-08 (2) — Poutre ISO « ne calcule pas » : diagnostic + réparation non destructive

### Symptôme

Sur `Poutre ISO.gwb`, `main.py` sortait des CSV de résultats vides et un temps
d'analyse de 0 s.

### Cause (confirmée par l'API .NET)

Le fichier a **perdu sa tâche d'analyse et ses cas d'analyse**. Il reste :
2 cas de charge (L1 Poids, L2 Charge permanente), 0 tâche, 0 cas d'analyse, et
2 combinaisons **orphelines** `ELU = 1.35A1 + 1.5A2` / `ELS = A1 + A2` qui
référencent des cas A1/A2 inexistants. Sans tâche, `analyse()` n'a rien à
lancer → 0 s et aucun résultat d'analyse (seuls des résultats de combinaison
nodaux restaient en cache).

### Comportement retenu : lever une erreur (ne rien modifier)

> Une première version reconstruisait automatiquement la config d'analyse (tâche
> Static + cas d'analyse) dans la copie de travail. **Abandonné à la demande de
> l'utilisateur** : le tool ne doit pas « bricoler » le modèle. À la place, il
> **signale l'erreur**.

`GsaModel.check_analysis_setup()` (lève `ConfigurationAnalyseError`, **ne modifie
rien**) : vérifie la présence de cas de charge, d'une tâche d'analyse et de cas
d'analyse ; lève une erreur listant ce qui manque. `main.py` l'appelle juste
après l'ouverture, **avant** de créer le dossier de sortie : un modèle non
analysable produit un message clair et **aucun fichier** (plus de dossier
`result/` trompeur à moitié vide).

Rappel (hiérarchie GSA) : une analyse exige **cas de charge → tâche d'analyse
contenant des cas d'analyse → lancer la tâche**. Les combinaisons (ELU/ELS) ne
font que recombiner des résultats de cas d'analyse déjà calculés ; seules, elles
ne suffisent pas.

### Validation

- Poutre ISO → `ERREUR : Modele non analysable : aucune tache d'analyse ... ;
  aucun cas d'analyse ...` (exit 1, fichier intact, aucun dossier créé).
- Canopée → passe la vérification, analyse ses 6 tâches (~19 s) et exporte
  normalement.

Pour rendre Poutre ISO analysable, il faut recréer dans GSA la tâche d'analyse
et les cas A1/A2 (= L1, L2), puis sauver.

---

## Session du 2026-07-08 — Export CSV façon GSA + modèle canopée

### Intention

Réorganiser `test/` pour **enregistrer** les tables (données du modèle + résultats
d'analyse) dans un dossier de sortie, via un `main.py` qui crée le dossier
`result/` du projet. Comme les cas de charge peuvent être très nombreux, **ne
pas** faire un CSV par cas : produire, comme dans GSA, **un CSV par type de
résultat** avec une colonne `case` (tous les cas empilés).

### Modèle ajouté

`GSA_model/Canopée - Modèle de Vent.gwb` (58 Mo) — charpente bois (1243 BAR +
15 BEAM), 242 nœuds, 34 sections, **83 cas de charge, 203 cas d'analyse, 47
combinaisons, 6 tâches** (statique, flambements modaux, dynamique modale,
spectre). `main.py` **relance systématiquement l'analyse** des 6 tâches
(~19 s au total : statique 5 s, flambements 6,9/2,5/2,9 s, modal 1 s,
spectre 0,7 s) puis lit les résultats fraîchement calculés.

### Renommage `GSA/` → `GSA_model/`

**Fait** (après libération de la session GSA interactive qui verrouillait le
dossier). `main.py` pointe directement sur `GSA_model/`.

> ⚠️ État du fichier `GSA_model/Poutre ISO.gwb` : il a **perdu sa tâche
> d'analyse et ses cas d'analyse** ; il ne reste que les combinaisons ELU/ELS
> (référençant des cas A1/A2 absents) avec seulement des résultats nodaux de
> combinaison en cache. Il exporte donc ses tables de modèle mais quasiment pas
> de résultats. Non causé par les outils (qui travaillent sur copie ; mtime du
> fichier = 7/07 16:22). À corriger dans GSA si l'on veut réexploiter ce
> modèle. Sans incidence sur la canopée.

### Nouvelle structure de `test/`

| Fichier | Rôle |
|---|---|
| `main.py` | Point d'entrée. Sans argument : **menu interactif** listant les `.gwb` de `GSA_model/` (on analyse un seul modèle à la fois). Puis, dans `result/<nom du modèle>/` : (1) lit le fichier, (2) écrit les tables du modèle, (3) **relance l'analyse** en chronométrant chaque tâche (→ console + `Analysis Timing.csv`), (4) écrit les tables de résultats. On peut aussi passer un chemin en argument (automatisation). Options : `--positions N` (défaut 2), `--limit N` (debug, limite les cas de résultats). |
| `export_gsa.py` | Logique d'export : tables du modèle (1 CSV/entité) + tables de résultats **consolidées** (1 CSV/type, colonne `case`, écriture en flux). |

(`etude_sortie_gsa.py` et `prototype_dotnet.py` supprimés — remplacés.)

### Fichiers produits dans `result/<modèle>/`

- **Tables du modèle** : `Nodes.csv`, `Elements.csv`, `Sections.csv`,
  `Materials.csv`, `Load Cases.csv`, `Beam Loads.csv`, `Gravity Loads.csv`,
  `Analysis Tasks.csv`, `Analysis Cases.csv`, `Combinations.csv` (les tables
  vides, ex. `Members` pour la canopée, ne sont pas écrites).
- **Résultats consolidés** (noms des tables GSA) : `Beam and Spring Forces and
  Moments.csv`, `Beam and Spring Displacements.csv`, `Nodal Displacements.csv`,
  `Reactions.csv`. `Reactions` ne liste que les nœuds réellement appuyés (les
  nœuds sans réaction, tout-NaN, sont filtrés — comme la table GSA).

### Validation

Export complet de la canopée (250 cas) : **629 000** lignes d'efforts,
**591 290** de déplacements poutres, **60 500** de déplacements nodaux,
**2 250** réactions (250 cas × 9 appuis). Durée ~380 s (250 cas × 1258
éléments × 2 tables). Contrôle : efforts/réactions cohérents, sections bois
`STD R`, valeurs en unités SI. Encodage UTF-8-BOM (accents OK sous Excel).

> Note perf : ~6 min pour tout exporter. Réductible via `--limit`, ou en
> filtrant les cas (l'export prend `cases=` en paramètre). Pas optimisé
> davantage pour l'instant (extraction séparée efforts / déplacements).

---

## Session du 2026-07-07 (3) — `gsa_bridge` devient un lecteur générique

### Intention

Recentrer `gsa_bridge` : au lieu d'un outil spécifique « poutre ISO + swap de
section », en faire un **lecteur générique** capable d'ouvrir **n'importe quel
fichier `.gwb`** et d'en sortir les **tables brutes** de GSA (nœuds, éléments,
membres, sections, matériaux, charges, efforts, déplacements, réactions), sans
mise en forme métier. But : voir « ce qui sort du modèle » et pouvoir bâtir
dessus.

### Changements

- **`gsa_bridge/bridge.py` réécrit** : classe `GsaModel` (renommée depuis
  `GsaBeamModel`, qui n'a plus de sens puisqu'elle lit tout modèle). Uniquement
  des méthodes d'extraction renvoyant des `list[dict]` (une ligne par entité,
  unités SI brutes) :
  - modèle : `nodes, elements, members, sections, materials, load_cases,
    beam_loads, gravity_loads, analysis_tasks, analysis_cases,
    combination_cases` ;
  - résultats : `analyse`, `result_cases`, `beam_forces, beam_displacements,
    node_displacements, node_reactions` (cas désigné `"A1"`/`"C1"`).
  - Gère la différence de structure entre cas d'analyse (résultats plats,
    `Double6` par position) et combinaison (imbriqués : permutations → 1ʳᵉ prise).
  - Entrée = chemin de fichier libre ; travail toujours sur copie
    `runtime/working.gwb`.
- **Nettoyage du dossier `gsa_bridge/`** : suppression du fallback COM
  (`bridge_com.py`, `com_session.py`) et de la config spécifique
  (`config/gsa_map.json`). Restent : `bridge.py`, `dotnet_runtime.py`,
  `__init__.py`, `runtime/`, + nouveau **`README.md`** détaillant le contenu du
  dossier et le rôle de `dotnet_runtime` (pourquoi `load("netfx")` et
  `add_dll_directory` sont indispensables).
- **`test/etude_sortie_gsa.py` réécrit** : se connecte directement à un modèle
  (n'importe quel `.gwb` en argument, défaut = poutre ISO), analyse, et vide
  toutes les tables en console — option `--csv <dossier>` pour l'export.
  Suppression de `test/prototype_dotnet.py` (fusionné ici).

### Validation

`test/etude_sortie_gsa.py` sur la poutre ISO : toutes les tables sortent
correctement. Contrôles de cohérence : My ELU (C1) = −19 737 N·m à mi-travée,
Vz ELU aux appuis ±7 895 N, flèche ELS (C2) −860,98 mm, réactions 7 895 N par
appui. Les `NaN` en réaction-moment du nœud rotulé sont la sortie fidèle de GSA
(pas de blocage en rotation → composante inexistante). Export CSV vérifié
(UTF-8-BOM, ouvrable Excel).

### ⚠️ Impact sur le comparateur (à traiter)

`app/compare.py` et `app/ui.py` s'appuyaient sur l'ancienne API
(`GsaBeamModel.run(section)` + `config/gsa_map.json`), désormais supprimée. **Le
comparateur GSA↔Excel est donc cassé en l'état.** À rebâtir sur `GsaModel` +
un petit utilitaire de changement de section (l'écriture `SetSection` sort du
périmètre « lecture seule » de `gsa_bridge`). Décision en attente.

---

## Session du 2026-07-07 (suite) — Migration du pont GSA vers l'API .NET

### Déclencheur

À l'usage, chaque calcul faisait apparaître une fenêtre GSA fantôme (le
serveur COM `GSA.exe` externe) à fermer à la main. Décision : migrer le pont
GSA de l'API COM vers l'**API .NET** (`GsaAPI.dll`), qui charge le moteur de
calcul **dans le processus Python** — sans fenêtre ni processus externe.

### Faisabilité validée par prototype ([test/prototype_dotnet.py](../test/prototype_dotnet.py))

- pythonnet 3.1.0 fonctionne avec le Python 3.14 du venv.
- **Piège majeur rencontré** : sans précaution, pythonnet démarre le runtime
  CoreCLR et le moteur natif de GSA plante en `AccessViolationException` au
  premier `Analyse`. Correctif indispensable : `pythonnet.load("netfx")`
  **avant** le premier `import clr` (GsaAPI.dll cible .NET Framework 4.8),
  plus le dossier GSA dans le chemin de recherche des DLL natives
  (`os.add_dll_directory`). Encapsulé dans `gsa_bridge/dotnet_runtime.py`.
- `SetSection` fonctionne directement (même GSA ouvert en interactif — le
  blocage des `SET` COM n'existe pas in-process) : le détour par le patch
  texte GWA devient inutile. GSA normalise même la désignation
  (`CAT IPE-AM IPE300` → `CAT IPE-AM IPE300 20170912`).
- Résultats **identiques au newton près** à ceux du pont COM (IPE300 :
  My −25 739 N·m, Fz −10 295,6 N, Uz −11,14 mm).
- Performance : cycle complet **0,2 s** contre ~15 s en COM (démarrage du
  serveur) — le calcul Excel (~9 s) domine désormais totalement.

### Changements

| Fichier | Changement |
|---|---|
| `gsa_bridge/bridge.py` | Réécrit sur GsaAPI (.NET) : copie du maître → `Model()` → `SetSection` → `Analyse(1)` → `CombinationCaseResults()` → `Element1dForce`/`Element1dDisplacement`. Interface publique inchangée (`GsaBeamModel.run(section)`) : `app/compare.py` et `app/ui.py` n'ont pas bougé. |
| `gsa_bridge/dotnet_runtime.py` | Nouveau : chargement idempotent du runtime netfx + chemins DLL. |
| `gsa_bridge/bridge_com.py` | Ancien pont COM conservé en fallback documenté (avec `com_session.py`). |
| `gsa_bridge/config/gsa_map.json` | Simplifié : plus de motif GWA ni datarefs ; ajout `sectionId`, `catalogue`, `task`. |
| `test/etude_sortie_gsa.py` | Adapté à la nouvelle interface (`extract_profile(combo_id, "Myy"/"Fz"/"Uz")`). |
| `requirements.txt` | + `pythonnet>=3.1`. |
| `gsa_bridge/runtime/` | Purgé des artefacts COM (`template.gwa`, `scenario.gwa`, `master_copy.gwb`) ; ne reste que `working.gwb`. |

### Validation après migration

- `test/etude_sortie_gsa.py IPE80` : diagrammes identiques (My −19 737,3 N·m
  à mi-travée, Fz ∓7 894,9 N aux appuis, flèche −860,98 mm).
- `app/compare.py IPE500` : GSA **0,55 s**, Excel 9,1 s ; écarts cohérents
  (My +0,27 %, Vz +23 % — bug γQ du classeur, flèche +5,4 %).
- Smoke test UI (IPE200) : résultats identiques à la version COM.
- Aucun processus `GSA.exe` créé (vérifié par comptage avant/après) ; plus
  aucune fenêtre parasite.

### Notes

- **Multithreading** : la limitation documentée de l'API .NET (« not suitable
  for use in a multi-threaded application ») est respectée par construction :
  l'UI n'a qu'un seul thread de travail. Pour du parallélisme futur
  (balayage de sections), passer par le multi-processus.
- La licence GSA de la machine est utilisée par le moteur in-process ;
  fonctionne avec la session GSA interactive ouverte en parallèle.
- Le fallback COM (`bridge_com.py`) reste utilisable en remplaçant l'import
  dans `app/compare.py` si un poste posait problème avec pythonnet.

---

## Session du 2026-07-07 — V0 du comparateur GSA vs Excel

### Objectif

Construire une interface permettant de **sélectionner une section IPE** (seul
paramètre variable pour le moment) et d'obtenir, pour la poutre isostatique du
modèle `GSA/Poutre ISO.gwb` :

- les **efforts ELU** (My,Ed et Vz,Ed) et la **flèche ELS**,
- issus d'une part du **modèle Oasys GSA**, d'autre part du **classeur Excel
  EC3** `reference/excels/Predim_poutre acier_v3.xlsm`,
- présentés côte à côte avec l'écart.

### Existant au démarrage

- `excel_bridge/` : pont Excel opérationnel (xlwings/COM, copie de travail,
  `io_map.json` pour les adresses, sorties = 4 taux d'utilisation).
- `GSA/Poutre ISO.gwb` : modèle poutre 10 m sur 2 appuis (rotule + appui
  simple), 1 élément BEAM, section catalogue **IPE-AM IPE80**, acier S235
  (E = 2·10¹¹ Pa dans le modèle), 2 cas de charge (L1 poids propre,
  L2 UDL −1 kN/m en Z global), combinaisons **C1 = ELU = 1.35·A1 + 1.5·A2**
  et **C2 = ELS = A1 + A2**. Unités SI (N, m).
- Aucun pont GSA, aucune interface.

### Documentation GSA lue

Sources :
- [GSA COM API](https://docs.oasys-software.com/structural/gsa/references/comautomation/) (référence des fonctions)
- [COM Output Data Reference](https://docs.oasys-software.com/structural/gsa/references/com-output-data-reference/) (codes `dataref`)
- [PDF de référence COM API](https://arup-group.github.io/oasys-combined/gsa/GSA_COM_API.pdf) (syntaxe GwaCommand, Output_Init)
- [gsapy](https://docs.oasys-software.com/structural/gsapy/version/latest/) — écarté : réservé au personnel Arup (`packages.arup.com`).

Enseignements clés (vérifiés sur machine, GSA 10.2.18.8) :

| Point | Constat |
|---|---|
| Connexion | `win32com.client.Dispatch("Gsa_10_2.ComAuto")` fonctionne (pywin32). |
| Séparateur GwaCommand | **Tabulation obligatoire** sur ce poste : `GET, NODE, 1` (doc) renvoie 0, `GET\tNODE\t1` fonctionne. Cause : le séparateur de liste accepté suit la locale Windows (française ici). |
| Écriture `SET` | **Toutes les commandes SET échouent** (retour 1, données inchangées) tant qu'une fenêtre GSA interactive est ouverte — limitation documentée (« COM APIs may fail if a GSA window is active »). Contournement retenu : passage par le format texte GWA (voir décisions). |
| Lecture/analyse | `Open`, `SaveAs`, `Analyse(-1)`, `Output_*` fonctionnent même GSA ouvert. |
| Datarefs éléments 1D | Uz = 14001003 (`REF_DISP_EL1D_DZ`), Fz = 14002003, Myy = 14002006. Flag `0x20` = points « intéressants » (extrema) en plus des positions régulières. |
| Cycle de vie | Aucune méthode Quit/Exit : chaque Dispatch laisse un processus `GSA.exe` sans fenêtre qui survit au script. |
| Sections catalogue | `sectlib.db3` (SQLite, dossier d'installation) liste les désignations valides. Catalogue `IPE-AM` : 68 profils IPE80→IPE750 (variantes A/AA/O/V incluses), tous datés 2017-09-12. |

### Revue du classeur Excel (nouvelles découvertes)

Le torseur affiché (P/Q 22-26) est **positionnel** : le menu M20
(gauche/milieu/droite) choisit où sont lus les efforts. À mi-travée Vz = 0 :
pour une poutre appuyée-appuyée chargée uniformément, le Vz de calcul se lit à
l'appui, dans la table interne AR29:BD36 (lignes = conditions d'appui,
colonnes = Vz/Vy/My/Mz × gauche/milieu/droite ; lignes 29-32 ELS, 33-36 ELU).

Trois particularités relevées, **importantes pour interpréter les écarts** :

1. **Bug probable — Vz ELU** : la formule des colonnes Vz de la table ELU
   applique des coefficients décalés. Comparer :
   - My (AZ35) : `=AZ14*$I$22+AZ18*$I$22+AZ22*$I$23+AZ26*$I$23` → γG sur les
     deux lignes G, γQ sur les deux lignes Q. Correct.
   - Vz (AS35) : `=AS14*$I$22+AS18*$I$23+AS22*$I$24+AS26*$I$25` → la charge
     variable répartie est pondérée par I24 (= 1.0) au lieu de γQ = 1.5.
   Conséquence : le **Vz,Ed ELU du classeur est sous-estimé** (jusqu'à ~33 %
   pour une charge dominée par Q). L'écart GSA/Excel de ~+39 à +46 % sur Vz
   vient de là, pas de GSA.
2. **E codé en dur dans la flèche** : les formules de flèche (BE12:BE27)
   utilisent `E = 205 000` MPa en littéral (ex. BE22
   `=5*F23*(G14*1000)^4/(384*205000*Q7)`), alors que la cellule nommée `E`
   (W16) vaut 210 000 MPa (valeur EN 1993-1-1). Le modèle GSA utilise lui
   200 000 MPa (matériau du modèle). Écart de flèche attendu ≈ 205/200 = +2.5 %
   côté GSA.
3. **Liste IPE incomplète/hétérogène** : l'onglet IPE écrit `IPE 80` (avec
   espace) mais `IPE100`… sans espace ; **IPE550 est absent** (IPE500 → IPE600).

### Architecture construite

```
PFE_V0/
├── app/                       # NOUVEAU — interface et orchestration
│   ├── ui.py                  # interface Tkinter (liste déroulante + tableau comparatif)
│   ├── compare.py             # orchestrateur + CLI : python app/compare.py IPE200
│   ├── sections.py            # sections proposées = intersection GSA ∩ Excel (17 IPE)
│   └── results/               # un JSON horodaté par comparaison
├── gsa_bridge/                # NOUVEAU — pont GSA (miroir de excel_bridge)
│   ├── bridge.py              # GsaBeamModel : template GWA → patch section → analyse → extraction
│   ├── com_session.py         # session COM unique + nettoyage des processus à la sortie
│   ├── config/gsa_map.json    # chemin maître, motif de section, cas C1/C2, datarefs
│   └── runtime/               # copies de travail (master_copy.gwb, template.gwa, scenario.gwa)
├── excel_bridge/              # EXISTANT — étendu
│   └── config/io_map.json     # + 6 sorties : My/Vz ELU & ELS, flèches totale/nuisible
└── suivi_build/               # NOUVEAU — ce journal
```

Scénario figé côté Excel pour refléter le modèle GSA : portée 10 m,
appuyé-appuyé, poids propre « oui », **Q = 1 kN/m en variable** (cohérent avec
le facteur 1.5 de la combinaison ELU du modèle GSA), G additionnelle nulle.

### Décisions techniques

1. **Changement de section par patch texte GWA, pas par `SET`** : les SET COM
   sont bloqués dès qu'une fenêtre GSA est ouverte (cas fréquent en usage
   réel). Circuit retenu, robuste dans les deux situations :
   copie du maître → export texte `template.gwa` (mis en cache, invalidé sur
   mtime du maître) → remplacement regex de `CAT IPE-AM IPE80 20170912` par la
   section demandée → `Open(scenario.gwa)` → `Analyse(-1)` → `Output_*`.
2. **Patch en binaire** : le GWA exporté par GSA est encodé ANSI (°, accents).
   Un passage par `str` UTF-8 corrompt ces octets et l'ouverture du fichier
   corrompu **bloque indéfiniment** le COM (boîte de dialogue invisible) —
   constaté pendant le build. Le patch se fait donc en `bytes`, seule la
   désignation ASCII change.
3. **Session COM unique + nettoyage** (`com_session.py`) : GSA n'a pas de
   Quit ; sans précaution, chaque calcul laisse un processus ~200 Mo. Une seule
   instance est créée par processus Python (toujours depuis le même thread,
   contrainte STA) ; les PID GSA apparus pendant sa création sont tués à la
   sortie (`atexit`). Les GSA déjà ouverts (session interactive) ne sont
   jamais touchés. Gain annexe : le 1er calcul coûte ~15 s (démarrage GSA), les
   suivants ~2 s.
4. **UI : un seul thread de travail persistant** possède la session COM et
   dépile les demandes ; l'interface Tkinter ne gèle pas et l'objet COM ne
   change jamais de thread.
5. **Vz,Ed Excel lu dans la table interne (AS35/AS31)** et non dans le torseur
   P23 (qui vaut 0 à mi-travée). Adresse valable uniquement pour la ligne
   « 3. Appuyé / Appuyé » — documenté dans `io_map.json`.

### Validation

Vérification manuelle (IPE80, g = 6,0 kg/m ≈ 0,0589 kN/m, q = 1 kN/m, L = 10 m) :

| Grandeur | Calcul manuel | GSA | Excel |
|---|---|---|---|
| My ELU = wL²/8, w = 1.35G+1.5Q = 1.5795 kN/m | 19.74 kN·m | 19.737 | 19.736 |
| Vz ELU = wL/2 | 7.90 kN | 7.895 | **5.395** (bug γQ, cf. ci-dessus) |
| Flèche ELS = 5wL⁴/384EI, w = 1.0589 kN/m | 861 mm (E=200 GPa) / 840 mm (E=205) | 860.98 | 838.90 |

Comparaisons exécutées de bout en bout : IPE80 (CLI), IPE300 (pont GSA seul,
flèche 11.1 mm — le changement de section agit bien), IPE200 (via l'UI, smoke
test automatisé) :

```
=== IPE200 — GSA vs Excel ===
My,Ed ELU [kNm]   22.452   22.427   +0.11 %
Vz,Ed ELU [kN]     8.981    6.471  +38.79 %   <- bug Vz du classeur
Flèche ELS [mm]   41.052   39.814   +3.11 %   <- E 200 vs 205 GPa (+ Iy/poids propre)
```

### Utilisation

```powershell
# Interface graphique (recommandé : la session GSA est réutilisée entre calculs)
venv\Scripts\python.exe app\ui.py

# Ligne de commande (une comparaison, résultat JSON dans app/results/)
venv\Scripts\python.exe app\compare.py IPE200
```

Premier calcul ~25-30 s (démarrage GSA + Excel), calculs suivants ~12 s
(Excel domine ; la session GSA est déjà chaude). GSA et Excel peuvent rester
ouverts pendant l'utilisation : l'outil travaille exclusivement sur copies.

### Limites connues / pistes

- Scénario figé (portée, charges, appuis) : seule la section varie. Étendre =
  patcher d'autres champs du GWA + élargir `SCENARIO_EXCEL`.
- Vz,Ed Excel lu sur la ligne « appuyé/appuyé » uniquement (AS31/AS35).
- Les modules E diffèrent entre les trois référentiels (GSA 200 GPa, flèche
  Excel 205 GPa codé en dur, EC3 210 GPa) : à harmoniser selon la référence
  souhaitée — de préférence en corrigeant le classeur et le matériau du modèle.
- Familles non-IPE (HE, etc.) non exposées dans l'interface (le classeur les
  gère ; le motif GWA vise le catalogue IPE-AM).
- Processus résiduels : deux instances GSA sans fenêtre datant des premiers
  essais de la session (avant le nettoyage automatique) peuvent rester —
  fermables sans risque via le Gestionnaire des tâches (GSA.exe sans fenêtre).
